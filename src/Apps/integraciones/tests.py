import tempfile
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from Apps.Pedidos.models import Cliente, Pedido, Venta
from Apps.integraciones.models import (
    ConciliacionPago,
    DocumentoTributarioEntrante,
    MovimientoBancario,
    SaldoBancario,
)
from Apps.integraciones.services.banco_chile import (
    consultar_movimientos,
    guardar_resultado,
    importar_filas,
    normalizar_movimiento,
)
from Apps.integraciones.services.conciliacion import confirmar_conciliacion, proponer_conciliaciones
from Apps.integraciones.services.documentos import guardar_adjunto


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

        def urlopen_falso(request, timeout):
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
        self.assertEqual(cuerpo_2["paginacionDesde"], 100)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer token")


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
