import tempfile
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from Apps.Pedidos.models import Cliente, Pedido, Venta
from Apps.integraciones.models import (
    CompraAgil,
    ConciliacionPago,
    DocumentoTributarioEntrante,
    FiltroCompraAgil,
    MovimientoBancario,
    SaldoBancario,
)
from Apps.integraciones.services.banco_chile import (
    _crear_client_assertion,
    consultar_movimientos,
    guardar_resultado,
    importar_filas,
    normalizar_movimiento,
)
from Apps.integraciones.services.conciliacion import confirmar_conciliacion, proponer_conciliaciones
from Apps.integraciones.services.documentos import guardar_adjunto
from Apps.integraciones.services.mercado_publico import sincronizar_compras_agiles


class BancoChileImportTests(TestCase):
    def test_normaliza_e_importa_sin_duplicar(self):
        fila = {
            "id": "trx-1",
            "fecha": "2026-10-19",
            "monto": "12.345,00",
            "tipo": "ABONO",
            "glosa": "Transferencia recibida",
            "rutContraparte": "76.123.456-7",
        }
        datos = normalizar_movimiento(fila)
        self.assertEqual(datos["monto"], Decimal("12345.00"))
        self.assertEqual(datos["tipo"], MovimientoBancario.TIPO_ABONO)
        self.assertEqual(normalizar_movimiento({**fila, "id": "trx-2", "monto": 12345.67})["monto"], Decimal("12345.67"))
        self.assertEqual(importar_filas([fila]), (1, 0))
        self.assertEqual(importar_filas([fila]), (0, 1))

    def test_normaliza_respuesta_oficial_y_guarda_saldo(self):
        spec_path = Path(__file__).resolve().parent / "specs" / "MovimientosySaldos-1.0.0.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        respuesta = spec["paths"]["/obtener-periodo"]["post"]["responses"]["200"]["content"]["application/json"]["example"]
        creados, existentes, saldo, saldo_creado = guardar_resultado(
            respuesta,
            desde=date(2024, 8, 1),
            hasta=date(2024, 8, 31),
        )
        self.assertEqual((creados, existentes), (3, 0))
        self.assertTrue(saldo_creado)
        self.assertEqual(saldo.saldo_disponible, Decimal("2863902"))
        self.assertTrue(saldo.cuenta_enmascarada.endswith("3456"))
        self.assertNotIn("000005123456", saldo.cuenta_enmascarada)
        self.assertEqual(SaldoBancario.objects.count(), 1)
        abono = MovimientoBancario.objects.get(identificador_externo="00d2fd81-d5a0-410b-9452-69e72e7528bd")
        self.assertEqual(abono.fecha, date(2024, 8, 21))
        self.assertEqual(abono.tipo, MovimientoBancario.TIPO_ABONO)
        self.assertEqual(abono.rut_contraparte, "128123456")
        self.assertIn("TRASPASO", abono.descripcion)
        cargo = MovimientoBancario.objects.get(identificador_externo="29de6ab0-764f-46ae-abac-5e3dc584d6c1")
        self.assertEqual(cargo.tipo, MovimientoBancario.TIPO_CARGO)

    @override_settings(
        BANCO_CHILE_MOVIMIENTOS_URL="https://gw.example/sandbox/v1/movimientos-cuenta",
        BANCO_CHILE_CLIENT_ID="cliente",
        BANCO_CHILE_CLIENT_SECRET="secreto",
        BANCO_CHILE_BEARER_TOKEN="token",
        BANCO_CHILE_RUT_ORIGEN="76123456-7",
        BANCO_CHILE_PRODUCTO_CUENTA="CTD",
        BANCO_CHILE_CUENTA="123456789",
        BANCO_CHILE_RUT_APODERADO="11111111-1",
    )
    def test_consulta_periodo_envia_contrato_oficial(self):
        respuestas = [
            {"codigoRetorno": None, "movimientos": [{"secuencial": "1"}], "indicadorMasPaginas": "Y", "indiceTerminoRespuesta": 100},
            {"codigoRetorno": None, "movimientos": [{"secuencial": "2"}], "indicadorMasPaginas": "N"},
        ]
        requests = []

        class Respuesta:
            def __init__(self, datos):
                self.datos = datos
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(self.datos).encode("utf-8")

        def urlopen_falso(request, timeout, context):
            requests.append(request)
            return Respuesta(respuestas[len(requests) - 1])

        with patch("Apps.integraciones.services.banco_chile.urlopen", side_effect=urlopen_falso):
            resultado = consultar_movimientos(date(2026, 10, 1), date(2026, 10, 19))

        self.assertEqual(len(resultado["movimientos"]), 2)
        self.assertTrue(requests[0].full_url.endswith("/obtener-periodo"))
        cuerpo_1 = json.loads(requests[0].data.decode("utf-8"))
        cuerpo_2 = json.loads(requests[1].data.decode("utf-8"))
        self.assertEqual(cuerpo_1["rutOrigen"], "76123456-7")
        self.assertEqual(cuerpo_1["rutApoderado"], [{"value": "11111111-1"}])
        self.assertEqual(cuerpo_1["fechaDesde"], "2026-10-01")
        self.assertEqual(cuerpo_2["paginacionDesde"], 101)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer token")
        self.assertEqual(requests[0].get_header("User-agent"), "CLIENTE_APISTORE")

    @override_settings(
        BANCO_CHILE_MOVIMIENTOS_URL="https://gw.example/sandbox/v1/movimientos-cuenta",
        BANCO_CHILE_CLIENT_ID="cliente",
        BANCO_CHILE_CLIENT_SECRET="secreto",
        BANCO_CHILE_BEARER_TOKEN="token",
        BANCO_CHILE_RUT_ORIGEN="76123456-7",
        BANCO_CHILE_PRODUCTO_CUENTA="CTD",
        BANCO_CHILE_CUENTA="123456789",
        BANCO_CHILE_RUT_APODERADO="11111111-1",
    )
    def test_cursor_repetido_cierra_paginacion_y_elimina_duplicados(self):
        respuesta = {
            "codigoRetorno": None,
            "movimientos": [{"secuencial": "1"}],
            "indicadorMasPaginas": "Y",
            "indiceTerminoRespuesta": -1,
        }

        with patch(
            "Apps.integraciones.services.banco_chile._solicitar_pagina",
            return_value=respuesta,
        ) as solicitar:
            resultado = consultar_movimientos(date(2026, 10, 1), date(2026, 10, 19))

        self.assertEqual(resultado["movimientos"], [{"secuencial": "1"}])
        self.assertIn("repitió el cursor", resultado["advertenciasPaginacion"][0])
        solicitar.assert_called_once()

    def test_client_assertion_productiva_usa_rs256_y_claims_del_documento(self):
        llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = llave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "banco_chile.pem"
            ruta.write_bytes(pem)
            token = _crear_client_assertion(
                {
                    "client_id": "cliente-productivo",
                    "assertion_audience": "https://apistore.bancochile.auth0app.com/",
                    "private_key_path": str(ruta),
                    "private_key_id": "llave-bch",
                }
            )

        encabezado = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual(encabezado["alg"], "RS256")
        self.assertEqual(encabezado["kid"], "llave-bch")
        self.assertEqual(claims["iss"], "cliente-productivo")
        self.assertEqual(claims["sub"], "cliente-productivo")
        self.assertEqual(claims["aud"], "https://apistore.bancochile.auth0app.com/")
        self.assertLessEqual(claims["exp"] - claims["iat"], 60)
        self.assertTrue(claims["jti"])

    @override_settings(
        BANCO_CHILE_AMBIENTE="production",
        BANCO_CHILE_MOVIMIENTOS_URL="https://api.example/v1/movimientos-cuenta",
        BANCO_CHILE_TOKEN_URL="https://auth.example/oauth/token",
        BANCO_CHILE_CLIENT_ID="cliente-produccion-test",
        BANCO_CHILE_CLIENT_SECRET="no-debe-enviarse",
        BANCO_CHILE_PRIVATE_KEY_ID="",
        BANCO_CHILE_AUTH0_ASSERTION_AUDIENCE="https://auth.example/",
        BANCO_CHILE_API_AUDIENCE="https://openbanking/",
        BANCO_CHILE_TIMEOUT=35,
        BANCO_CHILE_RUT_ORIGEN="76123456-7",
        BANCO_CHILE_PRODUCTO_CUENTA="CTD",
        BANCO_CHILE_CUENTA="123456789",
        BANCO_CHILE_RUT_APODERADO="11111111-1",
    )
    def test_produccion_obtiene_token_auth0_y_lo_inyecta_en_api(self):
        solicitudes = []

        class Respuesta:
            def __init__(self, datos):
                self.datos = datos

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.datos).encode("utf-8")

        respuestas = [
            {"access_token": "token-productivo", "expires_in": 86400, "token_type": "Bearer"},
            {"codigoRetorno": None, "movimientos": [], "indicadorMasPaginas": "N"},
        ]

        def urlopen_falso(request, timeout, context):
            solicitudes.append((request, timeout))
            return Respuesta(respuestas[len(solicitudes) - 1])

        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "banco_chile.pem"
            ruta.write_text("llave-prueba", encoding="utf-8")
            with override_settings(BANCO_CHILE_PRIVATE_KEY_PATH=str(ruta)), patch(
                "Apps.integraciones.services.banco_chile._crear_client_assertion",
                return_value="assertion-firmada",
            ), patch(
                "Apps.integraciones.services.banco_chile.urlopen",
                side_effect=urlopen_falso,
            ):
                consultar_movimientos(date(2026, 10, 1), date(2026, 10, 19))

        solicitud_token, timeout_token = solicitudes[0]
        formulario = parse_qs(solicitud_token.data.decode("utf-8"))
        self.assertEqual(solicitud_token.full_url, "https://auth.example/oauth/token")
        self.assertEqual(formulario["grant_type"], ["client_credentials"])
        self.assertEqual(formulario["client_assertion"], ["assertion-firmada"])
        self.assertEqual(formulario["audience"], ["https://openbanking/"])
        self.assertEqual(timeout_token, 35)

        solicitud_api, timeout_api = solicitudes[1]
        self.assertEqual(solicitud_api.get_header("Authorization"), "Bearer token-productivo")
        self.assertEqual(solicitud_api.get_header("User-agent"), "CLIENTE_APISTORE")
        self.assertIsNone(solicitud_api.get_header("Client-secret"))
        self.assertEqual(timeout_api, 35)


class ConciliacionTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user("contador", password="x", is_staff=True)
        cliente = Cliente.objects.create(
            nombre_cliente="Cliente prueba",
            rut_cliente="76123456-7",
            direccion_cliente="Dirección 1",
            direccion_bodega_cliente="Bodega 1",
            telefono_cliente="123",
            correo_cliente="cliente@example.com",
            categoria="PYME",
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=cliente,
            fecha_pedido=date(2026, 10, 18),
            estado_pedido="Entregado",
        )
        Venta.objects.create(
            pedidoid=self.pedido,
            fecha_venta=date(2026, 10, 18),
            documento_pedido="Factura",
            num_documento=100,
            venta_neto_pedido=Decimal("10000"),
            venta_iva_pedido=Decimal("1900"),
            venta_total_pedido=Decimal("11900"),
        )
        self.movimiento = MovimientoBancario.objects.create(
            identificador_externo="trx-pago",
            fecha=date(2026, 10, 19),
            descripcion="Pago cliente",
            tipo="ABONO",
            monto=Decimal("11900"),
        )

    def test_propuesta_y_confirmacion_marcan_pedido_pagado(self):
        self.assertEqual(proponer_conciliaciones(self.movimiento), 1)
        conciliacion = ConciliacionPago.objects.get()
        confirmar_conciliacion(conciliacion, self.usuario)
        self.pedido.refresh_from_db()
        self.movimiento.refresh_from_db()
        self.assertEqual(self.pedido.estado_pedido, "Pagado")
        self.assertEqual(self.movimiento.estado, MovimientoBancario.ESTADO_CONCILIADO)


class DocumentoEntranteTests(TestCase):
    def test_extrae_datos_dte_xml_y_evitar_duplicado(self):
        xml = b"""<DTE><Documento><Encabezado><IdDoc><TipoDTE>33</TipoDTE><Folio>456</Folio></IdDoc><Emisor><RUTEmisor>76.111.222-3</RUTEmisor></Emisor><Totales><MntTotal>11900</MntTotal></Totales></Encabezado></Documento></DTE>"""
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                documento, creado = guardar_adjunto(
                    message_id="gmail-1",
                    remitente="proveedor@example.com",
                    asunto="Factura 456",
                    recibido_en=None,
                    nombre="factura.xml",
                    contenido=xml,
                )
                self.assertTrue(creado)
                self.assertEqual(documento.folio, "456")
                self.assertEqual(documento.rut_emisor, "76.111.222-3")
                self.assertEqual(documento.monto_total, Decimal("11900"))
                _, creado_otra_vez = guardar_adjunto(
                    message_id="gmail-2",
                    remitente="proveedor@example.com",
                    asunto="Reenvío",
                    recibido_en=None,
                    nombre="factura.xml",
                    contenido=xml,
                )
                self.assertFalse(creado_otra_vez)
                self.assertEqual(DocumentoTributarioEntrante.objects.count(), 1)


class SincronizacionBancoViewTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            "admin_banco", password="x", is_staff=True
        )
        self.client.force_login(self.usuario)

    def test_pantalla_muestra_consulta_y_post_sincroniza(self):
        respuesta = {"movimientos": [], "saldoDisponible": 1000}
        saldo = SimpleNamespace(saldo_disponible=Decimal("1000"))
        with patch(
            "Apps.integraciones.views.consultar_movimientos",
            return_value=respuesta,
        ) as consultar, patch(
            "Apps.integraciones.views.guardar_resultado",
            return_value=(0, 0, saldo, True),
        ) as guardar:
            get_response = self.client.get(reverse("integraciones:conciliacion_bancaria"))
            post_response = self.client.post(
                reverse("integraciones:sincronizar_banco"),
                {"desde": "2026-10-18", "hasta": "2026-10-19"},
                follow=True,
            )

        self.assertContains(get_response, "Consultar Banco de Chile")
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Consulta completada")
        consultar.assert_called_once_with(date(2026, 10, 18), date(2026, 10, 19))
        guardar.assert_called_once()


class CompraAgilSincronizacionTests(TestCase):
    def setUp(self):
        self.filtro = FiltroCompraAgil.objects.create(
            nombre="Garantías RM",
            regiones=[13],
            palabras_clave="garantía\nreactivos",
            estados=["publicada"],
            monto_minimo=Decimal("100000"),
        )
        self.item = {
            "codigo": "1234-10-COT26",
            "nombre": "Servicio con garantía",
            "estado": {"codigo": "publicada", "glosa": "Publicada"},
            "convocatoria": {"estado_convocatoria": 1},
            "fechas": {
                "fecha_publicacion": "2026-10-20T10:00:00Z",
                "fecha_cierre": "2026-10-23T18:00:00Z",
                "fecha_ultimo_cambio": "2026-10-20T12:00:00Z",
            },
            "montos": {"moneda": "CLP", "monto_disponible_clp": 250000},
            "institucion": {
                "organismo_comprador": "Servicio de Salud",
                "rut": "61.000.000-0",
                "unidad_compra": "Abastecimiento Santiago",
                "region": 13,
                "nombre_region": "Metropolitana",
            },
        }
        self.detalle = {
            **self.item,
            "descripcion": "Equipo que requiere garantía de dos años.",
            "convocatoria": {
                "estado_convocatoria": 1,
                "fecha_cierre_primer_llamado": "2026-10-23T18:00:00Z",
            },
            "presupuesto": {"moneda": "CLP", "monto_disponible_clp": 250000},
            "entrega": {"direccion_entrega": "Santiago Centro"},
        }

    def test_sincroniza_listado_detalle_y_asocia_filtro(self):
        class ClienteFalso:
            def __init__(self, item, detalle):
                self.item = item
                self.detalle_data = detalle
                self.consultas = []

            def listar(self, parametros):
                self.consultas.append(parametros)
                items = [self.item] if parametros.get("q") == "garantía" else []
                return {
                    "items": items,
                    "paginacion": {"numero_pagina": 1, "total_paginas": 1},
                }

            def detalle(self, codigo):
                self.codigo_detalle = codigo
                return self.detalle_data

        cliente = ClienteFalso(self.item, self.detalle)
        resultado = sincronizar_compras_agiles(cliente)

        compra = CompraAgil.objects.get(codigo="1234-10-COT26")
        self.assertEqual(resultado, {"creadas": 1, "actualizadas": 0, "coincidentes": 1, "filtros": 1})
        self.assertEqual(compra.descripcion, "Equipo que requiere garantía de dos años.")
        self.assertEqual(compra.fecha_cierre_primer_llamado.date(), date(2026, 10, 23))
        self.assertEqual(compra.monto, Decimal("250000"))
        self.assertEqual(
            compra.enlace_publico,
            "https://buscador.mercadopublico.cl/ficha?code=1234-10-COT26",
        )
        self.assertEqual(compra.filtros.get(), self.filtro)
        self.assertTrue(compra.coincide_filtros)
        self.assertEqual(cliente.codigo_detalle, compra.codigo)
        self.assertEqual({consulta.get("q") for consulta in cliente.consultas}, {"garantía", "reactivos"})
        self.assertTrue(all(consulta["region"] == "13" for consulta in cliente.consultas))

    def test_lugar_que_no_coincide_excluye_resultado(self):
        self.filtro.lugar = "Valparaíso"
        self.filtro.save()

        class ClienteFalso:
            def listar(self, parametros):
                return {
                    "items": [self.item],
                    "paginacion": {"numero_pagina": 1, "total_paginas": 1},
                }

            def detalle(self, codigo):
                return self.detalle_data

        cliente = ClienteFalso()
        cliente.item = self.item
        cliente.detalle_data = self.detalle
        resultado = sincronizar_compras_agiles(cliente)
        self.assertEqual(resultado["coincidentes"], 0)
        self.assertFalse(CompraAgil.objects.get().coincide_filtros)


class CompraAgilViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("admin_mp", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.compra = CompraAgil.objects.create(
            codigo="1234-10-COT26",
            nombre="Compra de equipamiento",
            descripcion="Incluye garantía.",
            organismo_comprador="Servicio de Salud",
            monto=Decimal("250000"),
        )

    def test_tabla_muestra_columnas_y_permite_seguimiento(self):
        respuesta = self.client.get(reverse("integraciones:compras_agiles"))
        self.assertContains(respuesta, "Nombre Compra Ágil")
        self.assertContains(respuesta, "Fecha cierre primer llamado")
        self.assertContains(respuesta, self.compra.nombre)

        respuesta = self.client.post(
            reverse("integraciones:cambiar_estado_compra_agil", args=[self.compra.pk]),
            {"estado": CompraAgil.ESTADO_SEGUIMIENTO},
        )
        self.assertRedirects(respuesta, reverse("integraciones:compras_agiles"))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado_gestion, CompraAgil.ESTADO_SEGUIMIENTO)

    def test_crea_filtro_desde_pantalla(self):
        respuesta = self.client.post(
            reverse("integraciones:filtros_compras_agiles"),
            {
                "nombre": "Garantías",
                "activo": "on",
                "regiones": ["13", "5"],
                "lugar": "Santiago",
                "palabras_clave": "garantía",
                "estados": ["publicada"],
                "monto_minimo": "100000",
                "monto_maximo": "5000000",
            },
        )
        self.assertRedirects(respuesta, reverse("integraciones:filtros_compras_agiles"))
        filtro = FiltroCompraAgil.objects.get(nombre="Garantías")
        self.assertEqual(filtro.regiones, [13, 5])

    def test_dashboard_muestra_cantidad_segun_filtros_y_excluye_descartadas(self):
        CompraAgil.objects.create(
            codigo="1234-11-COT26",
            nombre="Compra descartada",
            estado_gestion=CompraAgil.ESTADO_DESCARTADA,
        )
        respuesta = self.client.get(reverse("home"))
        self.assertEqual(respuesta.context["cantidad_compras_agiles"], 1)
        self.assertContains(respuesta, "Compras Ágiles encontradas (1)")
        self.assertContains(respuesta, self.compra.nombre)
        self.assertNotContains(respuesta, "Compra descartada")
