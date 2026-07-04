import base64
import csv
from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.etree import ElementTree as ET

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from Apps.Pedidos.models import (
    BoletaElectronica,
    Categoria,
    CategoriaEmpaque,
    Cliente,
    ConfiguracionBoletaSii,
    Cotizacion,
    EntregaPedido,
    ListaPrecios,
    ListaPreciosPredItem,
    ListaPreciosPredeterminada,
    PackComponente,
    Pedido,
    PedidoLinea,
    Producto,
    Proveedor,
    Recepcion,
    RecepcionLinea,
    Stock,
    UtilidadProducto,
    Subcategoria,
    Venta,
)
from Apps.Pedidos.templatetags.custom_filters import formatear_miles
from Apps.Pedidos.utils_pdf import _items_pedido_para_pdf, formatear_miles_punto
from Apps.Pedidos.services import sincronizar_lista_predeterminada_a_cliente
from Apps.Pedidos.views.pedido import _detalle_lineas_pedido
from Apps.Pedidos.views.producto import _parse_codigos_proveedor
from Apps.indicadores.services.contabilidad import Periodo, filas_stock_contable


class ClonarDbSqliteCommandTests(SimpleTestCase):
    def test_clonar_db_sqlite_copia_archivo_a_destino(self):
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "origen.db"
            target = Path(tmpdir) / "destino.db"
            source.write_bytes(b"sqlite-data-prueba")

            out = StringIO()
            call_command(
                "clonar_db_sqlite",
                source=str(source),
                target=str(target),
                overwrite=True,
                stdout=out,
            )

            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"sqlite-data-prueba")
            self.assertIn("Base de pruebas clonada correctamente", out.getvalue())

    def test_clonar_db_sqlite_falla_si_destino_existe_sin_overwrite(self):
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "origen.db"
            target = Path(tmpdir) / "destino.db"
            source.write_bytes(b"sqlite-data-prueba")
            target.write_bytes(b"ya-existe")

            with self.assertRaises(CommandError):
                call_command(
                    "clonar_db_sqlite",
                    source=str(source),
                    target=str(target),
                )


class CodigoProveedorParserTests(SimpleTestCase):
    def test_parse_codigos_proveedor_ignora_fila_totalmente_vacia(self):
        codigos, errores = _parse_codigos_proveedor({
            "codigos_proveedor[0][proveedor]": "",
            "codigos_proveedor[0][codigo_proveedor]": "",
        })

        self.assertEqual(codigos, [])
        self.assertEqual(errores, [])

    def test_parse_codigos_proveedor_exige_proveedor_si_hay_codigo(self):
        codigos, errores = _parse_codigos_proveedor({
            "codigos_proveedor[0][proveedor]": "",
            "codigos_proveedor[0][codigo_proveedor]": "EXT-01",
        })

        self.assertEqual(codigos, [])
        self.assertEqual(errores, ["Fila 0: debes seleccionar un proveedor."])


class CrearProductoCodigosProveedorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("producto_crear", password="test123")
        self.client.force_login(self.user)

        self.categoria = Categoria.objects.create(categoria="Categoria Producto")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Producto",
        )
        self.empaque_primario = CategoriaEmpaque.objects.create(nombre="Unidad Producto", nivel="PRIMARIO")
        self.empaque_secundario = CategoriaEmpaque.objects.create(nombre="Caja Producto", nivel="SECUNDARIO")
        self.empaque_terciario = CategoriaEmpaque.objects.create(nombre="Pallet Producto", nivel="TERCIARIO")

    def _producto_payload(self, codigo="PADE01"):
        return {
            "categoria_producto": self.categoria.id,
            "subcategoria_producto": self.subcategoria.id,
            "codigo_producto_interno": codigo,
            "nombre_producto": f"Producto {codigo}",
            "qty_terciario": "1",
            "qty_secundario": "6",
            "qty_primario": "12",
            "qty_unidad": "1",
            "medida": "und",
            "qty_minima": "3",
            "empaque_primario": self.empaque_primario.id,
            "empaque_secundario": self.empaque_secundario.id,
            "empaque_terciario": self.empaque_terciario.id,
        }

    def _crear_producto(self, codigo="PADE01"):
        return Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno=codigo,
            nombre_producto=f"Producto {codigo}",
            qty_terciario=1,
            qty_secundario=6,
            qty_primario=12,
            qty_unidad=1,
            medida="und",
            qty_minima=3,
            empaque_primario=self.empaque_primario,
            empaque_secundario=self.empaque_secundario,
            empaque_terciario=self.empaque_terciario,
        )

    def test_crear_producto_no_renderiza_fila_de_codigo_por_defecto(self):
        resp = self.client.get(reverse("crear_producto"))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="codigos_proveedor[0][codigo_proveedor]"', html=False)

    def test_editar_producto_sin_codigos_no_renderiza_fila_de_codigo_por_defecto(self):
        producto = self._crear_producto(codigo="PADE02")

        resp = self.client.get(reverse("editar_producto", args=[producto.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="codigos_proveedor[0][codigo_proveedor]"', html=False)

    def test_crear_producto_permite_repetidor_opcional_vacio(self):
        resp = self.client.post(
            reverse("crear_producto"),
            data={
                **self._producto_payload(),
                "codigos_proveedor[0][proveedor]": "",
                "codigos_proveedor[0][codigo_proveedor]": "",
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("lista_productos"))

        producto = Producto.objects.get(codigo_producto_interno="PADE01")
        self.assertEqual(producto.nombre_producto, "Producto PADE01")
        self.assertEqual(producto.codigos_proveedor.count(), 0)


class RedondeoSiiFormattingTests(SimpleTestCase):
    def test_formatear_miles_redondea_final_con_regla_sii(self):
        self.assertEqual(formatear_miles(Decimal("10.49")), "10")
        self.assertEqual(formatear_miles(Decimal("10.50")), "11")
        self.assertEqual(formatear_miles(Decimal("1238.50")), "1.239")

    def test_formatear_miles_pdf_redondea_final_con_regla_sii(self):
        self.assertEqual(formatear_miles_punto(Decimal("10.49")), "10")
        self.assertEqual(formatear_miles_punto(Decimal("10.50")), "11")
        self.assertEqual(formatear_miles_punto(Decimal("1238.50")), "1.239")


class SiiSetPruebaBoletaTests(SimpleTestCase):
    def test_parsea_casos_boleta_exento_unidad_y_referencia(self):
        from Apps.Pedidos.services import parse_set_prueba_boleta, totales_boleta_set_case

        text = """
CASO-1
==========
Item                    Cantidad    Precio Unitario con IVA
Cambio de aceite        1           19900
Alineacion y balanceo   1           9900

CASO-4
=========
Item                    Cantidad    Precio Unitario con IVA
item afecto 1           8           1590
item exento 2           2           1000

OBSERVACION: "El item 1 es un servicio afecto. El item 2 es un servicio exento."

CASO-5
=========
Item                    Cantidad    Precio Unitario con IVA
Arroz                   5           700
"""

        cases = parse_set_prueba_boleta(text)

        self.assertEqual([case.codigo for case in cases], ["CASO-1", "CASO-4", "CASO-5"])
        self.assertTrue(cases[1].items[1].exento)
        self.assertEqual(cases[2].items[0].unidad_medida, "Kg")
        self.assertEqual(
            totales_boleta_set_case(cases[1]),
            {
                "monto_neto": Decimal("10689"),
                "iva": Decimal("2031"),
                "monto_exento": Decimal("2000"),
                "monto_total": Decimal("14720"),
            },
        )


class GenerarSetPruebaBoletaCommandTests(TestCase):
    def test_generar_set_prueba_be_crea_xmls_desde_txt_sii(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            acteco_principal="521900",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            resolucion_numero=80,
            resolucion_fecha=datetime(2024, 1, 15).date(),
            ruta_caf_tipo_39="caf/tipo39.xml",
        )
        txt = """
CASO-4
=========
Item                    Cantidad    Precio Unitario con IVA
item afecto 1           8           1590
item exento 2           2           1000
"""
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "set_be.txt"
            output_dir = Path(tmpdir) / "out"
            input_path.write_text(txt, encoding="utf-8")

            out = StringIO()
            call_command(
                "generar_set_prueba_be",
                input=str(input_path),
                output=str(output_dir),
                folio_inicial=10,
                fecha_emision="2026-06-30",
                stdout=out,
            )

            xml_path = output_dir / "boleta_caso-4_folio_10.xml"
            sobre_path = output_dir / "sobre_set_boletas.xml"
            rcof_path = output_dir / "rcof_set_boletas.xml"
            self.assertTrue(xml_path.exists())
            self.assertTrue(sobre_path.exists())
            self.assertTrue(rcof_path.exists())

            root = ET.fromstring(xml_path.read_bytes())
            self.assertEqual(root.findtext("./Documento/Referencia/CodRef"), "SET")
            self.assertEqual(root.findtext("./Documento/Referencia/RazonRef"), "CASO-4")
            self.assertEqual(root.findtext("./Documento/Encabezado/Totales/MntExe"), "2000")
            self.assertEqual(root.findtext("./Documento/Detalle[2]/IndExe"), "1")

            ns = {"sii": "http://www.sii.cl/SiiDte"}
            sobre = ET.fromstring(sobre_path.read_bytes())
            self.assertEqual(sobre.findtext("./sii:SetDTE/sii:Caratula/sii:SubTotDTE/sii:NroDTE", namespaces=ns), "1")
            self.assertEqual(sobre.findtext("./sii:SetDTE/sii:DTE/sii:Documento/sii:Referencia/sii:RazonRef", namespaces=ns), "CASO-4")

            rcof = ET.fromstring(rcof_path.read_bytes())
            self.assertEqual(rcof.findtext("./sii:DocumentoConsumoFolios/sii:Resumen/sii:TipoDocumento", namespaces=ns), "39")
            self.assertEqual(rcof.findtext("./sii:DocumentoConsumoFolios/sii:Resumen/sii:FoliosUtilizados", namespaces=ns), "1")
            self.assertEqual(rcof.findtext("./sii:DocumentoConsumoFolios/sii:Resumen/sii:MntTotal", namespaces=ns), "14720")
            self.assertIn("Sobre unico:", out.getvalue())
            self.assertIn("RCOF/RDV:", out.getvalue())
            self.assertIn("XMLs generados: 1", out.getvalue())


class RecepcionTotalesTests(TestCase):
    def setUp(self):
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor IVA",
            rut_proveedor="76000000-1",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Dir Bodega",
            empresa_activa=True,
            banco_proveedor="Banco IVA",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="123456789",
        )

    def test_actualizar_totales_calcula_iva_aun_si_incluir_iva_es_false(self):
        recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 1, 10).date(),
            estado_recepcion="Pendiente",
            documento_recepcion="Factura",
            num_documento_recepcion=5001,
            total_neto_recepcion=Decimal("1000.00"),
            iva_recepcion=Decimal("0.00"),
            total_recepcion=Decimal("1000.00"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )

        recepcion.actualizar_totales()
        recepcion.refresh_from_db()

        self.assertEqual(recepcion.iva_recepcion, Decimal("190.00"))
        self.assertEqual(recepcion.total_recepcion, Decimal("1190.00"))

    def test_actualizar_totales_calcula_iva_si_incluir_iva_es_true(self):
        recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 1, 11).date(),
            estado_recepcion="Pendiente",
            documento_recepcion="Factura",
            num_documento_recepcion=5002,
            total_neto_recepcion=Decimal("1000.00"),
            iva_recepcion=Decimal("0.00"),
            total_recepcion=Decimal("1000.00"),
            incluir_iva=True,
            moneda_recepcion="CLP",
        )

        recepcion.actualizar_totales()
        recepcion.refresh_from_db()

        self.assertEqual(recepcion.iva_recepcion, Decimal("190.00"))
        self.assertEqual(recepcion.total_recepcion, Decimal("1190.00"))


class RecepcionLineasSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("recepcion_sync", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Sync", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Sync", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Sync", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Sync")
        self.subcategoria = Subcategoria.objects.create(categoria=self.categoria, subcategoria="Sub Sync")
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Sync",
            rut_proveedor="76000000-2",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Dir Bodega",
            empresa_activa=True,
            banco_proveedor="Banco Sync",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="987654321",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="SYNC001",
            nombre_producto="Producto Sync",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 1, 15).date(),
            estado_recepcion="Pendiente",
            documento_recepcion="Factura",
            num_documento_recepcion=6001,
            total_neto_recepcion=Decimal("100.00"),
            iva_recepcion=Decimal("19.00"),
            total_recepcion=Decimal("119.00"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )

    def test_agregar_producto_sincroniza_neto_desde_lineas_y_evita_doble_conteo(self):
        resp = self.client.post(
            reverse("crear_recepcion_productos", args=[self.recepcion.id]),
            data={
                "producto": self.producto.id,
                "qty": "1",
                "empaque": "PRIMARIO",
                "precio_unitario": "100.00",
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.recepcion.refresh_from_db()
        self.assertEqual(self.recepcion.total_neto_recepcion, Decimal("100.00"))
        self.assertEqual(self.recepcion.iva_recepcion, Decimal("19.00"))
        self.assertEqual(self.recepcion.total_recepcion, Decimal("119.00"))

    def test_formulario_recepcion_productos_pide_cantidad_en_enteros(self):
        resp = self.client.get(reverse("crear_recepcion_productos", args=[self.recepcion.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="qty"')
        self.assertContains(resp, 'step="1"')
        self.assertContains(resp, 'inputmode="numeric"')

    def test_recepcion_redirige_a_login_si_no_hay_sesion(self):
        self.client.logout()
        url = reverse("crear_recepcion_productos", args=[self.recepcion.id])

        resp = self.client.post(
            url,
            data={
                "producto": self.producto.id,
                "qty": "1",
                "empaque": "PRIMARIO",
                "precio_unitario": "100.00",
            },
        )

        self.assertRedirects(resp, f"{settings.LOGIN_URL}?next={url}")
        self.assertFalse(RecepcionLinea.objects.filter(recepcion=self.recepcion).exists())

    def test_eliminar_producto_recalcula_neto_desde_lineas_restantes(self):
        RecepcionLinea.objects.create(
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion,
        )
        otra_linea = RecepcionLinea.objects.create(
            producto=self.producto,
            qty=2,
            empaque="PRIMARIO",
            precio_unitario=Decimal("50.00"),
            recepcion=self.recepcion,
        )
        self.recepcion.total_neto_recepcion = Decimal("999.00")
        self.recepcion.save(update_fields=["total_neto_recepcion"])

        resp = self.client.post(reverse("eliminar_recepcion_producto", args=[otra_linea.id]))

        self.assertEqual(resp.status_code, 302)
        self.recepcion.refresh_from_db()
        self.assertEqual(self.recepcion.total_neto_recepcion, Decimal("100.00"))
        self.assertEqual(self.recepcion.iva_recepcion, Decimal("19.00"))
        self.assertEqual(self.recepcion.total_recepcion, Decimal("119.00"))

    def test_finalizar_recepcion_corrige_neto_antes_de_cambiar_estado(self):
        RecepcionLinea.objects.create(
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion,
        )
        self.recepcion.total_neto_recepcion = Decimal("200.00")
        self.recepcion.save(update_fields=["total_neto_recepcion"])

        resp = self.client.post(reverse("finalizar_recepcion", args=[self.recepcion.id]))

        self.assertEqual(resp.status_code, 302)
        self.recepcion.refresh_from_db()
        self.assertEqual(self.recepcion.estado_recepcion, "Finalizado")
        self.assertEqual(self.recepcion.total_neto_recepcion, Decimal("100.00"))
        self.assertEqual(self.recepcion.iva_recepcion, Decimal("19.00"))
        self.assertEqual(self.recepcion.total_recepcion, Decimal("119.00"))


class RecepcionFinalizadaGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("recepcion_cerrada", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Cerrada", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Cerrada", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Cerrada", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Cerrada")
        self.subcategoria = Subcategoria.objects.create(categoria=self.categoria, subcategoria="Sub Cerrada")
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Cerrado",
            rut_proveedor="76000000-3",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Dir Bodega",
            empresa_activa=True,
            banco_proveedor="Banco Cerrado",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="555666777",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="CERR001",
            nombre_producto="Producto Cerrado",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 1, 20).date(),
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=7001,
            total_neto_recepcion=Decimal("100.00"),
            iva_recepcion=Decimal("19.00"),
            total_recepcion=Decimal("119.00"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )
        self.stock = Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion,
        )

    def test_urls_de_edicion_redirigen_a_historico_si_recepcion_esta_finalizada(self):
        resp_editar = self.client.get(reverse("editar_recepcion", args=[self.recepcion.id]))
        resp_productos = self.client.get(reverse("crear_recepcion_productos", args=[self.recepcion.id]))

        self.assertRedirects(
            resp_editar,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )
        self.assertRedirects(
            resp_productos,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )

    def test_post_agregar_producto_no_modifica_recepcion_finalizada(self):
        total_lineas = RecepcionLinea.objects.filter(recepcion=self.recepcion).count()

        resp = self.client.post(
            reverse("crear_recepcion_productos", args=[self.recepcion.id]),
            data={
                "producto": self.producto.id,
                "qty": "2",
                "empaque": "PRIMARIO",
                "precio_unitario": "50.00",
            },
        )

        self.assertRedirects(
            resp,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )
        self.assertEqual(RecepcionLinea.objects.filter(recepcion=self.recepcion).count(), total_lineas)

    def test_post_eliminar_producto_no_modifica_recepcion_finalizada(self):
        self.linea = RecepcionLinea.objects.create(
            recepcion=self.recepcion,
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
        )

        resp = self.client.post(reverse("eliminar_recepcion_producto", args=[self.linea.id]))

        self.assertRedirects(
            resp,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )
        self.assertTrue(RecepcionLinea.objects.filter(id=self.linea.id).exists())

    def test_eliminar_recepcion_finalizada_queda_bloqueada(self):
        resp = self.client.get(reverse("eliminar_recepcion", args=[self.recepcion.id]))

        self.assertRedirects(
            resp,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )
        self.assertTrue(Recepcion.objects.filter(id=self.recepcion.id).exists())


class DashboardHomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dashboard", password="test123")
        self.client.force_login(self.user)

        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Dashboard",
            rut_proveedor="76100000-1",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Bodega Proveedor",
            empresa_activa=True,
            banco_proveedor="Banco Dashboard",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="100200300",
        )

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Dashboard",
            rut_cliente="77100000-2",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Bodega Cliente",
            cliente_activo=True,
            telefono_cliente="+56911111111",
            correo_cliente="dashboard@test.local",
            categoria="PYME",
        )

    def test_home_muestra_todas_las_tareas_pendientes_sin_limite_de_tres(self):
        for idx in range(4):
            Recepcion.objects.create(
                proveedor=self.proveedor,
                fecha_recepcion=datetime(2026, 1, idx + 1).date(),
                estado_recepcion="Pendiente",
                documento_recepcion="Factura",
                num_documento_recepcion=2000 + idx,
                total_neto_recepcion=Decimal("1000.00"),
                iva_recepcion=Decimal("190.00"),
                total_recepcion=Decimal("1190.00"),
                incluir_iva=True,
                moneda_recepcion="CLP",
                comentario_recepcion=f"Recepcion {idx}",
            )

            Pedido.objects.create(
                nombre_cliente=self.cliente,
                fecha_pedido=datetime(2026, 2, idx + 1).date(),
                estado_pedido="Pendiente",
                comentario_pedido=f"Pedido pendiente {idx}",
            )

            Pedido.objects.create(
                nombre_cliente=self.cliente,
                fecha_pedido=datetime(2026, 3, idx + 1).date(),
                estado_pedido="Entregado",
                comentario_pedido=f"Pedido entregado {idx}",
            )

        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["recepciones"]), 4)
        self.assertEqual(len(resp.context["pedidos"]), 4)
        self.assertEqual(len(resp.context["pedidos_no_pagados"]), 4)
        self.assertContains(resp, "Recepciones Pendientes (4)")
        self.assertContains(resp, "Pedidos Pendientes (4)")
        self.assertContains(resp, "Pendientes de Pago (4)")
        self.assertContains(resp, "2000")
        self.assertContains(resp, "2003")

    def test_home_muestra_total_adeudado_en_titulos_de_pedidos(self):
        categoria = Categoria.objects.create(categoria="Abarrotes")
        subcategoria = Subcategoria.objects.create(categoria=categoria, subcategoria="General")
        producto = Producto.objects.create(
            categoria_producto=categoria,
            subcategoria_producto=subcategoria,
            codigo_producto_interno="DASH-001",
            nombre_producto="Producto Dashboard",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )

        pedido_pendiente_1 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 2, 1).date(),
            estado_pedido="Pendiente",
            comentario_pedido="Pendiente 1",
        )
        pedido_pendiente_2 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 2, 2).date(),
            estado_pedido="Pendiente",
            comentario_pedido="Pendiente 2",
        )
        pedido_entregado_1 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 3, 1).date(),
            estado_pedido="Entregado",
            comentario_pedido="Entregado 1",
        )
        pedido_entregado_2 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 3, 2).date(),
            estado_pedido="Entregado",
            comentario_pedido="Entregado 2",
        )

        PedidoLinea.objects.create(
            pedido=pedido_pendiente_1,
            producto=producto,
            descripcion="Pendiente 1",
            empaque="PRIMARIO",
            cantidad=1,
            precio_unitario=Decimal("1000.00"),
        )
        PedidoLinea.objects.create(
            pedido=pedido_pendiente_2,
            producto=producto,
            descripcion="Pendiente 2",
            empaque="PRIMARIO",
            cantidad=2,
            precio_unitario=Decimal("1000.00"),
        )
        PedidoLinea.objects.create(
            pedido=pedido_entregado_1,
            producto=producto,
            descripcion="Entregado 1",
            empaque="PRIMARIO",
            cantidad=1,
            precio_unitario=Decimal("1500.00"),
        )
        PedidoLinea.objects.create(
            pedido=pedido_entregado_2,
            producto=producto,
            descripcion="Entregado 2",
            empaque="PRIMARIO",
            cantidad=1,
            precio_unitario=Decimal("2500.00"),
        )

        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.context["monto_pedidos_pendientes"], Decimal("3570.00"))
        self.assertEqual(resp.context["monto_pedidos_no_pagados"], Decimal("4760.00"))
        self.assertContains(resp, "Total adeudado: $3.570")
        self.assertContains(resp, "Total adeudado: $4.760")

    def test_home_muestra_alerta_por_precios_cliente_bajo_costo(self):
        categoria = Categoria.objects.create(categoria="Bebidas")
        subcategoria = Subcategoria.objects.create(categoria=categoria, subcategoria="Jugos")
        producto = Producto.objects.create(
            categoria_producto=categoria,
            subcategoria_producto=subcategoria,
            codigo_producto_interno="ALR-001",
            nombre_producto="Jugo en Alerta",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 4, 10).date(),
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=9100,
            total_neto_recepcion=Decimal("120.00"),
            iva_recepcion=Decimal("22.80"),
            total_recepcion=Decimal("142.80"),
            incluir_iva=True,
            moneda_recepcion="CLP",
            comentario_recepcion="Compra alerta",
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("120.00"),
            recepcion=recepcion,
        )
        precio = ListaPrecios.objects.create(
            nombre_cliente=self.cliente,
            nombre_producto=producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("100.00"),
            precio_iva=Decimal("19.00"),
            precio_total=Decimal("119.00"),
            vigencia=timezone.localdate(),
        )

        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["cantidad_precios_cliente_bajo_costo"], 1)
        self.assertEqual(len(resp.context["precios_cliente_bajo_costo"]), 1)
        self.assertContains(resp, "Precios Cliente Bajo Costo (1)")
        self.assertContains(resp, "Jugo en Alerta")
        self.assertContains(resp, self.cliente.nombre_cliente)
        self.assertContains(resp, reverse("dashboard_precios_cliente"))
        self.assertContains(resp, f'{reverse("asignar_precios", args=[self.cliente.id])}?precio_id={precio.id}')


class ListaPedidosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("lista_pedidos", password="test123")
        self.client.force_login(self.user)

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Lista",
            rut_cliente="77333333-3",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Bodega",
            cliente_activo=True,
            telefono_cliente="+56933333333",
            correo_cliente="lista@test.local",
            categoria="PYME",
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 4, 30).date(),
            estado_pedido="Pendiente",
            comentario_pedido="Pedido listado",
        )

    def test_lista_pedidos_muestra_numero_como_primera_columna(self):
        resp = self.client.get(reverse("lista_pedidos"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "N° Pedido")

        contenido = resp.content.decode("utf-8")
        self.assertLess(
            contenido.index('<th class="text-center">N° Pedido</th>'),
            contenido.index('<th class="text-center">Cliente</th>'),
        )
        self.assertLess(
            contenido.index(f'<td class="text-center">{self.pedido.id}</td>'),
            contenido.index(f'<td class="text-center">{self.cliente.nombre_cliente}</td>'),
        )


class EliminarPedidoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("eliminar_pedido", password="test123")
        self.client.force_login(self.user)

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Eliminar",
            rut_cliente="77444444-4",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Bodega",
            cliente_activo=True,
            telefono_cliente="+56944444444",
            correo_cliente="eliminar@test.local",
            categoria="PYME",
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 4, 30).date(),
            estado_pedido="Pendiente",
            comentario_pedido="Pedido por eliminar",
        )

    def test_confirmacion_eliminacion_pedido_exige_doble_check(self):
        resp = self.client.get(reverse("eliminar_pedido", args=[self.pedido.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Entiendo que esta accion elimina el registro de forma permanente.")
        self.assertContains(resp, "Escribe")
        self.assertContains(resp, "ELIMINAR")

    def test_post_sin_doble_check_no_elimina_pedido(self):
        resp = self.client.post(reverse("eliminar_pedido", args=[self.pedido.id]), data={})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Pedido.objects.filter(id=self.pedido.id).exists())
        self.assertContains(resp, "Debes marcar la confirmacion y escribir ELIMINAR para eliminar.")

    def test_post_con_doble_check_elimina_pedido(self):
        resp = self.client.post(
            reverse("eliminar_pedido", args=[self.pedido.id]),
            data={
                "confirmar_eliminacion": "on",
                "texto_confirmacion": "ELIMINAR",
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Pedido.objects.filter(id=self.pedido.id).exists())


class CotizacionOrderingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cotizacion", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Cotizacion", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Cotizacion", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Cotizacion", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Cotizacion")
        self.subcategoria = Subcategoria.objects.create(categoria=self.categoria, subcategoria="Sub Cotizacion")

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Cotizacion",
            rut_cliente="77222222-2",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Bodega",
            cliente_activo=True,
            telefono_cliente="+56922222222",
            correo_cliente="cotizacion@test.local",
            categoria="PYME",
        )

        nombres = ["Zanahoria", "Arandano", "Banana"]
        self.lista_precios = []
        for idx, nombre in enumerate(nombres, start=1):
            producto = Producto.objects.create(
                categoria_producto=self.categoria,
                subcategoria_producto=self.subcategoria,
                codigo_producto_interno=f"COT{idx:03d}",
                nombre_producto=nombre,
                qty_terciario=1,
                qty_secundario=1,
                qty_primario=1,
                qty_unidad=1,
                medida="und",
                qty_minima=1,
                empaque_primario=self.emp_p,
                empaque_secundario=self.emp_s,
                empaque_terciario=self.emp_t,
            )
            self.lista_precios.append(
                ListaPrecios.objects.create(
                    nombre_cliente=self.cliente,
                    nombre_producto=producto,
                    empaque="PRIMARIO",
                    precio_venta=Decimal("1000.00"),
                    precio_iva=Decimal("190.00"),
                    precio_total=Decimal("1190.00"),
                    vigencia=timezone.localdate(),
                )
            )

        self.tmpdir = TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_seleccion_productos_cotizacion_muestra_productos_ordenados_alfabeticamente(self):
        resp = self.client.get(reverse("seleccionar_productos_cotizacion", args=[self.cliente.id]))

        self.assertEqual(resp.status_code, 200)
        nombres = [precio.nombre_producto.nombre_producto for precio in resp.context["productos"]]
        self.assertEqual(nombres, ["Arandano", "Banana", "Zanahoria"])

    @patch("Apps.Pedidos.utils_pdf.generar_pdf_cotizacion")
    def test_vista_previa_cotizacion_envia_items_ordenados_alfabeticamente(self, mock_generar_pdf):
        mock_generar_pdf.return_value = BytesIO(b"%PDF-1.4 prueba")
        producto_ids = [str(precio.id) for precio in self.lista_precios]

        with self.settings(MEDIA_ROOT=self.tmpdir.name):
            resp = self.client.post(
                reverse("vista_previa_cotizacion"),
                data={
                    "cliente_id": self.cliente.id,
                    "producto_id": list(reversed(producto_ids)),
                },
            )

        self.assertEqual(resp.status_code, 200)
        items = mock_generar_pdf.call_args.args[2]
        nombres = [item["producto_nombre"] for item in items]
        self.assertEqual(nombres, ["Arandano", "Banana", "Zanahoria"])


class ContabilidadProPymeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("staff", password="test123", is_staff=True)
        self.user_regular = User.objects.create_user("usuario", password="test123", is_staff=False)
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Test", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Test", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Test", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Test")
        self.subcategoria = Subcategoria.objects.create(categoria=self.categoria, subcategoria="Sub Test")

        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Test",
            rut_proveedor="76123456-7",
            direccion_proveedor="Dir 1",
            direccion_bodega_proveedor="Dir 2",
            empresa_activa=True,
            banco_proveedor="Banco Test",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="1234567",
        )

        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="PRODTEST01",
            nombre_producto="Producto Test",
            qty_terciario=10,
            qty_secundario=5,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Test",
            rut_cliente="77123456-2",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Bodega Cliente",
            cliente_activo=True,
            telefono_cliente="+56999999999",
            correo_cliente="cliente@test.local",
            categoria="PYME",
        )

        self.recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=timezone.localdate(),
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=1234,
            total_neto_recepcion=Decimal("1000.00"),
            iva_recepcion=Decimal("190.00"),
            total_recepcion=Decimal("1190.00"),
            incluir_iva=True,
            moneda_recepcion="CLP",
            comentario_recepcion="Test",
        )

        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=20,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion,
        )

        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=timezone.localdate(),
            estado_pedido="Finalizado",
            comentario_pedido="Pedido test",
        )

        self.venta = Venta.objects.create(
            pedidoid=self.pedido,
            fecha_venta=timezone.localdate(),
            documento_pedido="Factura",
            num_documento=5678,
            venta_neto_pedido=Decimal("2000.00"),
            venta_iva_pedido=Decimal("380.00"),
            venta_total_pedido=Decimal("2380.00"),
            ganancia_total=Decimal("500.00"),
            ganancia_porcentaje=Decimal("25.00"),
        )

    def test_resumen_contable_propyme_staff(self):
        resp = self.client.get(reverse("resumen_contable_propyme"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contabilidad Pro Pyme")

    def test_resumen_contable_propyme_usuario_regular(self):
        self.client.force_login(self.user_regular)
        resp = self.client.get(reverse("resumen_contable_propyme"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contabilidad Pro Pyme")

    def test_exportar_libro_ventas_propyme_csv(self):
        resp = self.client.get(
            reverse("exportar_libro_ventas_propyme"),
            data={"year": timezone.localdate().year, "month": timezone.localdate().month},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        contenido = resp.content.decode("utf-8-sig")
        self.assertIn("tipo_documento", contenido)
        self.assertIn("Factura", contenido)


class InventarioPeriodoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("inventario", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Inventario", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Inventario", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Inventario", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Inventario")
        self.subcategoria = Subcategoria.objects.create(categoria=self.categoria, subcategoria="Sub Inventario")
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Inventario",
            rut_proveedor="76111111-1",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Dir Bodega",
            empresa_activa=True,
            banco_proveedor="Banco",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="7654321",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="INVPER001",
            nombre_producto="Producto Inventario",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=5,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

        self.recepcion_enero = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 1, 10).date(),
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=1001,
            total_neto_recepcion=Decimal("1000.00"),
            iva_recepcion=Decimal("190.00"),
            total_recepcion=Decimal("1190.00"),
            incluir_iva=True,
            moneda_recepcion="CLP",
            comentario_recepcion="Recepcion enero",
        )
        self.recepcion_febrero = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 2, 5).date(),
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=1002,
            total_neto_recepcion=Decimal("3000.00"),
            iva_recepcion=Decimal("570.00"),
            total_recepcion=Decimal("3570.00"),
            incluir_iva=True,
            moneda_recepcion="CLP",
            comentario_recepcion="Recepcion febrero",
        )

        self.ingreso_enero = Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=10,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion_enero,
        )
        self.reserva_enero = Stock.objects.create(
            tipo_movimiento="RESERVA",
            producto=self.producto,
            qty=4,
            empaque="PRIMARIO",
            precio_unitario=Decimal("180.00"),
        )
        self.ingreso_febrero = Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=20,
            empaque="PRIMARIO",
            precio_unitario=Decimal("150.00"),
            recepcion=self.recepcion_febrero,
        )
        self.despacho_marzo = Stock.objects.create(
            tipo_movimiento="DESPACHO",
            producto=self.producto,
            qty=2,
            empaque="PRIMARIO",
            precio_unitario=Decimal("180.00"),
        )

        self._actualizar_fecha_movimiento(self.ingreso_enero, datetime(2026, 1, 10, 12, 0, 0))
        self._actualizar_fecha_movimiento(self.reserva_enero, datetime(2026, 1, 20, 12, 0, 0))
        self._actualizar_fecha_movimiento(self.ingreso_febrero, datetime(2026, 2, 5, 12, 0, 0))
        self._actualizar_fecha_movimiento(self.despacho_marzo, datetime(2026, 3, 2, 12, 0, 0))

    def _actualizar_fecha_movimiento(self, stock, fecha):
        Stock.objects.filter(pk=stock.pk).update(fecha_movimiento=fecha.date())

    def _fila_producto(self, year, month):
        filas = filas_stock_contable(Periodo(year=year, month=month))
        return next(fila for fila in filas if fila["codigo_interno"] == self.producto.codigo_producto_interno)

    def test_filas_stock_contable_respetan_periodo_y_stock_total(self):
        fila_enero = self._fila_producto(2026, 1)
        self.assertEqual(fila_enero["cantidad_disponible_uprim"], 6)
        self.assertEqual(fila_enero["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_enero["cantidad_despachada_uprim"], 0)
        self.assertEqual(fila_enero["costo_unitario_compra"], Decimal("100.00"))
        self.assertEqual(fila_enero["total_producto"], Decimal("600.00"))

        fila_febrero = self._fila_producto(2026, 2)
        self.assertEqual(fila_febrero["cantidad_disponible_uprim"], 26)
        self.assertEqual(fila_febrero["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_febrero["cantidad_despachada_uprim"], 0)
        self.assertEqual(fila_febrero["costo_unitario_compra"], Decimal("150.00"))
        self.assertEqual(fila_febrero["total_producto"], Decimal("3900.00"))

        fila_marzo = self._fila_producto(2026, 3)
        self.assertEqual(fila_marzo["cantidad_disponible_uprim"], 24)
        self.assertEqual(fila_marzo["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_marzo["cantidad_despachada_uprim"], 2)
        self.assertEqual(fila_marzo["costo_unitario_compra"], Decimal("150.00"))
        self.assertEqual(fila_marzo["total_producto"], Decimal("3600.00"))

    def test_exportar_inventario_propyme_csv_usa_periodo_consultado(self):
        resp = self.client.get(
            reverse("exportar_inventario_propyme"),
            data={"year": 2026, "month": 1},
        )
        self.assertEqual(resp.status_code, 200)
        contenido = resp.content.decode("utf-8-sig")
        filas = list(csv.DictReader(StringIO(contenido), delimiter=";"))
        fila = next(item for item in filas if item["codigo_interno"] == self.producto.codigo_producto_interno)

        self.assertEqual(fila["cantidad_disponible_uprim"], "6")
        self.assertEqual(fila["cantidad_despachada_uprim"], "0")
        self.assertEqual(fila["costo_unitario_compra"], "100.00")
        self.assertEqual(fila["total_producto"], "600.00")

    def test_stock_productos_permita_filtrar_solo_productos_con_stock(self):
        producto_sin_stock = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="INVPER002",
            nombre_producto="Producto Sin Stock",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=0,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "con_stock"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Solo con stock")
        self.assertContains(resp, self.producto.nombre_producto)
        self.assertNotContains(resp, producto_sin_stock.nombre_producto)

    def test_stock_productos_permita_buscar_por_codigo_y_nombre(self):
        producto_codigo = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="BUSC001",
            nombre_producto="Producto Codigo",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=0,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        producto_nombre = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="OTRO002",
            nombre_producto="Nombre Especial",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=0,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

        resp_codigo = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos", "q": "BUSC001"},
        )
        self.assertEqual(resp_codigo.status_code, 200)
        self.assertEqual(resp_codigo.context["search_term"], "BUSC001")
        self.assertEqual(len(resp_codigo.context["stock_rows"]), 1)
        self.assertContains(resp_codigo, producto_codigo.nombre_producto)
        self.assertNotContains(resp_codigo, producto_nombre.nombre_producto)
        self.assertNotContains(resp_codigo, self.producto.nombre_producto)

        resp_nombre = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos", "q": "Especial"},
        )
        self.assertEqual(resp_nombre.status_code, 200)
        self.assertEqual(resp_nombre.context["search_term"], "Especial")
        self.assertEqual(len(resp_nombre.context["stock_rows"]), 1)
        self.assertContains(resp_nombre, producto_nombre.nombre_producto)
        self.assertNotContains(resp_nombre, producto_codigo.nombre_producto)
        self.assertNotContains(resp_nombre, self.producto.nombre_producto)

    def test_stock_productos_muestre_link_a_flujo(self):
        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            f'{reverse("flujo_inventario_producto", args=[self.producto.id])}?year=2026&month=3&stock_view=todos',
        )

    def test_stock_productos_conserve_busqueda_en_links_de_flujo_y_regreso(self):
        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos", "q": "INVPER001"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            f'{reverse("flujo_inventario_producto", args=[self.producto.id])}?year=2026&month=3&stock_view=todos&q=INVPER001',
        )

        resp_flujo = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos", "q": "INVPER001"},
        )
        self.assertEqual(resp_flujo.status_code, 200)
        self.assertContains(
            resp_flujo,
            f'{reverse("stock_productos")}?year=2026&month=3&stock_view=todos&q=INVPER001',
        )

    def test_stock_productos_renderice_tablas_ordenables(self):
        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "js-sortable-report-table", count=2)
        self.assertContains(resp, '$(".js-sortable-report-table").each(function () {')
        self.assertContains(resp, "Informe de Inventario")
        self.assertContains(resp, "Reservas")
        self.assertNotContains(resp, "Despachos")
        self.assertNotContains(resp, "Revision Detallada de Movimientos")
        self.assertNotContains(resp, "Movimientos del Periodo")
        self.assertNotContains(resp, "Productos Criticos")

    def test_dashboard_inventario_redirige_a_stock_productos(self):
        resp = self.client.get(
            reverse("dashboard_inventario"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            f'{reverse("stock_productos")}?year=2026&month=3&stock_view=todos',
        )

    def test_flujo_inventario_producto_muestre_historial_ordenado(self):
        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Flujo de Inventario")
        self.assertContains(
            resp,
            f'{reverse("stock_productos")}?year=2026&month=3&stock_view=todos',
        )
        self.assertContains(resp, "Sin responsable registrado")
        self.assertContains(resp, "Stock Disponible")
        self.assertNotContains(resp, "Reserva pendiente")

        movimientos = resp.context["movimientos_rows"]
        self.assertEqual(len(movimientos), 3)
        self.assertEqual(movimientos[0]["transaccion"], "Entrada / Factura #1001")
        self.assertEqual(movimientos[1]["transaccion"], "Entrada / Factura #1002")
        self.assertEqual(movimientos[2]["transaccion"], "Salida - Despacho")
        self.assertEqual(movimientos[0]["subtotal"], 10)
        self.assertEqual(movimientos[1]["subtotal"], 30)
        self.assertEqual(movimientos[2]["subtotal"], 28)
        self.assertFalse(movimientos[0]["es_salida"])
        self.assertTrue(movimientos[2]["es_salida"])
        self.assertEqual(resp.context["subtotal_entradas"], 30)
        self.assertEqual(resp.context["subtotal_salidas"], 2)
        self.assertEqual(resp.context["reservas_pendientes"], 4)
        self.assertEqual(resp.context["subtotal_final"], 24)

    def test_flujo_inventario_producto_muestre_responsable_desde_stock(self):
        Stock.objects.filter(pk=self.ingreso_enero.pk).update(responsable=self.user)
        Stock.objects.filter(pk=self.reserva_enero.pk).update(responsable=self.user)

        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        movimientos = resp.context["movimientos_rows"]

        self.assertEqual(movimientos[0]["responsable"], self.user.username)
        self.assertNotIn("Reserva pendiente", [row["transaccion"] for row in movimientos])
        self.assertEqual(resp.context["reservas_pendientes"], 4)

    def test_stock_productos_incluye_reservas_hasta_confirmar_entrega(self):
        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Informe de Inventario")
        self.assertContains(resp, "descuenta reservas pendientes")
        self.assertContains(resp, "confirmar la entrega del pedido")
        self.assertNotContains(resp, "Movimientos del Periodo")
        self.assertNotContains(resp, "Productos Criticos")

        fila = next(row for row in resp.context["stock_rows"] if row["codigo_interno"] == self.producto.codigo_producto_interno)
        self.assertEqual(fila["cantidad_disponible_uprim"], 24)
        self.assertEqual(fila["cantidad_despachada_uprim"], 2)
        self.assertFalse(fila["es_critico"])

    def test_stock_productos_destaca_solo_celda_con_stock_cero_o_negativo(self):
        producto_sin_stock = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="INVPER003",
            nombre_producto="Producto Agotado",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=0,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

        resp = self.client.get(
            reverse("stock_productos"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, producto_sin_stock.nombre_producto)
        self.assertNotContains(resp, 'class="table-danger"')
        self.assertContains(resp, 'class="text-end text-danger fw-semibold" data-order="0"')

    def test_flujo_inventario_producto_prioriza_fechas_de_documento(self):
        self._actualizar_fecha_movimiento(self.ingreso_enero, datetime(2026, 1, 18, 12, 0, 0))

        cliente = Cliente.objects.create(
            nombre_cliente="Cliente Flujo",
            rut_cliente="76000000-1",
            direccion_cliente="Dir Cliente Flujo",
            direccion_bodega_cliente="Bodega Cliente Flujo",
            cliente_activo=True,
            telefono_cliente="+56911112222",
            correo_cliente="flujo@test.local",
            categoria="PYME",
        )
        pedido = Pedido.objects.create(
            nombre_cliente=cliente,
            fecha_pedido=datetime(2026, 3, 1).date(),
            estado_pedido="Entregado",
        )
        despacho_documentado = Stock.objects.create(
            tipo_movimiento="DESPACHO",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("180.00"),
            pedido=pedido,
        )
        self._actualizar_fecha_movimiento(despacho_documentado, datetime(2026, 3, 20, 15, 30, 0))
        venta = Venta.objects.create(
            pedidoid=pedido,
            fecha_venta=datetime(2026, 3, 8).date(),
            documento_pedido="Factura",
            num_documento=2008,
            venta_neto_pedido=Decimal("180.00"),
            venta_iva_pedido=Decimal("34.20"),
            venta_total_pedido=Decimal("214.20"),
        )

        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "La columna Fecha prioriza la fecha del documento de recepci&oacute;n y la fecha de cierre de venta",
        )

        movimientos = resp.context["movimientos_rows"]
        ingreso_row = next(row for row in movimientos if row["movimiento_id"] == self.ingreso_enero.id)
        despacho_row = next(row for row in movimientos if row["movimiento_id"] == despacho_documentado.id)

        self.assertEqual(ingreso_row["fecha"], self.recepcion_enero.fecha_recepcion)
        self.assertEqual(despacho_row["fecha"], venta.fecha_venta)
        self.assertContains(resp, "10-01-2026")
        self.assertContains(resp, "08-03-2026")
        self.assertNotContains(resp, "18-01-2026")
        self.assertNotContains(resp, "20-03-2026")

    def test_flujo_inventario_producto_tolera_fechas_legacy_en_texto_datetime(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE Pedidos_stock SET fecha_movimiento = ? WHERE id = ?",
                ["2026-03-02 12:00:00", self.despacho_marzo.id],
            )

        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Salida - Despacho")
        self.assertEqual(len(resp.context["movimientos_rows"]), 3)

class EntregaPedidoFirmaCompatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("entrega_firma", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Entrega", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Entrega", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Entrega", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Categoria Entrega")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Entrega",
        )
        self.cliente_obj = Cliente.objects.create(
            nombre_cliente="Cliente Entrega",
            rut_cliente="76012345-6",
            direccion_cliente="Direccion Cliente 123",
            direccion_bodega_cliente="Bodega Cliente 123",
            cliente_activo=True,
            telefono_cliente="+56912345678",
            correo_cliente="cliente.entrega@example.com",
            categoria="PYME",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="ENTREGA1",
            nombre_producto="Producto Entrega",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente_obj,
            fecha_pedido=datetime(2026, 3, 1).date(),
            estado_pedido="Pendiente",
            comentario_pedido="Entrega con firma",
        )
        self.stock = Stock.objects.create(
            tipo_movimiento="RESERVA",
            producto=self.producto,
            qty=3,
            empaque="PRIMARIO",
            precio_unitario=Decimal("2500.00"),
            pedido=self.pedido,
        )

    def test_detalle_pedido_renderiza_canvas_compatible_con_ios_y_pc(self):
        resp = self.client.get(reverse("detalle_pedido", args=[self.pedido.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "touch-action:none")
        self.assertContains(resp, "pointerdown")
        self.assertContains(resp, "shown.bs.modal")
        self.assertContains(resp, "canvas.toDataURL('image/png')")

    def test_finalizar_pedido_acepta_firma_dataurl_y_mueve_stock(self):
        firma_b64 = base64.b64encode(b"firma-prueba").decode("ascii")
        fecha_reserva_esperada = self.stock.fecha_movimiento

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                with patch("Apps.Pedidos.utils_pdf.generar_pdf_entrega", return_value=b"%PDF-1.4 prueba"):
                    resp = self.client.post(
                        reverse("finalizar_pedido", args=[self.pedido.id]),
                        data={
                            "entrega_nombre": "Ana Perez",
                            "entrega_rut": "11111111-1",
                            "entrega_fecha": "2026-03-05T10:30",
                            "entrega_firma": f"data:image/png;base64,{firma_b64}",
                        },
                    )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("detalle_pedido", args=[self.pedido.id]))

        self.pedido.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(self.pedido.estado_pedido, "Entregado")
        self.assertEqual(self.stock.tipo_movimiento, "DESPACHO")
        self.assertEqual(self.stock.fecha_movimiento, datetime(2026, 3, 5).date())
        self.assertEqual(self.stock.fecha_reserva, fecha_reserva_esperada)

        entrega = EntregaPedido.objects.get(pedido=self.pedido)
        self.assertEqual(entrega.nombre_receptor, "Ana Perez")
        self.assertTrue(entrega.archivo_pdf.name.endswith(".pdf"))
        self.assertEqual(self.stock.responsable, self.user)

    def test_finalizar_pedido_redirige_a_login_si_no_hay_sesion(self):
        firma_b64 = base64.b64encode(b"firma-prueba").decode("ascii")
        self.client.logout()
        url = reverse("finalizar_pedido", args=[self.pedido.id])

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                with patch("Apps.Pedidos.utils_pdf.generar_pdf_entrega", return_value=b"%PDF-1.4 prueba"):
                    resp = self.client.post(
                        url,
                        data={
                            "entrega_nombre": "Ana Perez",
                            "entrega_rut": "11111111-1",
                            "entrega_fecha": "2026-03-05T10:30",
                            "entrega_firma": f"data:image/png;base64,{firma_b64}",
                        },
                    )

        self.assertRedirects(resp, f"{settings.LOGIN_URL}?next={url}")

        self.pedido.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(self.pedido.estado_pedido, "Pendiente")
        self.assertEqual(self.stock.tipo_movimiento, "RESERVA")
        self.assertFalse(EntregaPedido.objects.filter(pedido=self.pedido).exists())
        self.assertIsNone(self.stock.fecha_reserva)


class PedidoPendienteHibridoCompatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pedido_hibrido", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Hibrida", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Hibrida", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Hibrido", nivel="TERCIARIO")
        self.categoria = Categoria.objects.create(categoria="Categoria Hibrida")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Hibrida",
        )
        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Hibrido",
            rut_cliente="76999999-9",
            direccion_cliente="Dir Hibrida",
            direccion_bodega_cliente="Bodega Hibrida",
            cliente_activo=True,
            telefono_cliente="+56977777777",
            correo_cliente="cliente.hibrido@example.com",
            categoria="PYME",
        )
        self.producto_legacy = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="LEG001",
            nombre_producto="Producto Legacy",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.producto_nuevo = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="NEW001",
            nombre_producto="Producto Nuevo",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 5, 16).date(),
            estado_pedido="Pendiente",
        )

        Stock.objects.create(
            tipo_movimiento="RESERVA",
            producto=self.producto_legacy,
            qty=2,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1000.00"),
            pedido=self.pedido,
        )

        self.linea = PedidoLinea.objects.create(
            pedido=self.pedido,
            producto=self.producto_nuevo,
            tipo_linea="PRODUCTO",
            descripcion=self.producto_nuevo.nombre_producto,
            empaque="PRIMARIO",
            cantidad=3,
            precio_unitario=Decimal("2000.00"),
        )
        Stock.objects.create(
            tipo_movimiento="RESERVA",
            producto=self.producto_nuevo,
            qty=3,
            empaque="PRIMARIO",
            precio_unitario=Decimal("2000.00"),
            pedido=self.pedido,
            linea_pedido=self.linea,
        )

    def test_detalle_pedido_combina_lineas_nuevas_y_reservas_legacy(self):
        filas, total_neto, iva, total, _ = _detalle_lineas_pedido(self.pedido)

        self.assertEqual(len(filas), 2)
        self.assertEqual({fila["nombre"] for fila in filas}, {"Producto Legacy", "Producto Nuevo"})
        self.assertEqual(total_neto, Decimal("8000"))
        self.assertEqual(iva, Decimal("1520"))
        self.assertEqual(total, Decimal("9520"))

        resp = self.client.get(reverse("detalle_pedido", args=[self.pedido.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Producto Legacy")
        self.assertContains(resp, "Producto Nuevo")

    def test_items_pdf_pedido_incluyen_flujo_legacy_y_nuevo(self):
        items = _items_pedido_para_pdf(self.pedido, reservas=Stock.objects.filter(pedido=self.pedido))

        self.assertEqual(len(items), 2)
        self.assertEqual({item["nombre"] for item in items}, {"Producto Legacy", "Producto Nuevo"})
        self.assertEqual(sum(item["subtotal"] for item in items), Decimal("8000.00"))


class StockResponsableTests(TestCase):
    def setUp(self):
        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Historial", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Historial", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Historial", nivel="TERCIARIO")
        self.categoria = Categoria.objects.create(categoria="Categoria Historial")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Historial",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="HIST001",
            nombre_producto="Producto Historial",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.stock = Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
        )

    def test_stock_puede_quedar_sin_responsable(self):
        self.assertIsNone(self.stock.responsable)


class ModelStrTrazabilidadTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Traza",
            rut_cliente="76123456-7",
            direccion_cliente="Av. Uno 123",
            direccion_bodega_cliente="Bodega Uno 123",
            cliente_activo=True,
            telefono_cliente="+56911111111",
            correo_cliente="cliente.traza@example.com",
            categoria="PYME",
        )
        self.cotizacion = Cotizacion.objects.create(
            fecha_cotizacion=datetime(2026, 2, 1).date(),
            num_cotizacion="COT-100",
            nombre_cliente=self.cliente,
        )
        self.producto = Producto.objects.create(
            codigo_producto_interno="TRAZA1",
            nombre_producto="Producto Traza",
            qty_terciario=1,
            qty_secundario=10,
            qty_primario=20,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )

    def test_pedido_venta_y_entrega_priorizan_numero_de_pedido(self):
        pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            num_cotizacion=self.cotizacion,
            fecha_pedido=datetime(2026, 2, 3).date(),
            estado_pedido="Pendiente",
        )
        venta = Venta.objects.create(
            pedidoid=pedido,
            fecha_venta=datetime(2026, 2, 4).date(),
            documento_pedido="Factura",
            num_documento=2001,
            venta_neto_pedido=Decimal("1000.00"),
            venta_iva_pedido=Decimal("190.00"),
            venta_total_pedido=Decimal("1190.00"),
        )
        entrega = EntregaPedido.objects.create(
            pedido=pedido,
            nombre_receptor="Ana Perez",
            rut_receptor="11111111-1",
            fecha_entrega=timezone.make_aware(datetime(2026, 2, 5, 10, 0, 0)),
        )

        self.assertEqual(
            str(pedido),
            f"Pedido #{pedido.id} - Cliente Traza (76123456-7) - 2026-02-03 - Cot. COT-100",
        )
        self.assertEqual(
            str(venta),
            f"Venta #{venta.id} - Pedido #{pedido.id} - Cliente Traza (76123456-7) - Factura #2001",
        )
        self.assertEqual(
            str(entrega),
            f"Entrega #{entrega.id} - Pedido #{pedido.id} - Cliente Traza (76123456-7)",
        )

    def test_stock_muestra_referencia_de_pedido(self):
        pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=datetime(2026, 2, 6).date(),
            estado_pedido="Pendiente",
        )
        stock = Stock.objects.create(
            tipo_movimiento="RESERVA",
            producto=self.producto,
            qty=5,
            empaque="SECUNDARIO",
            precio_unitario=Decimal("2500.00"),
            pedido=pedido,
        )

        self.assertEqual(
            str(stock),
            f"RESERVA - TRAZA1 - Producto Traza (1 und) - 5 (SECUNDARIO) - Pedido #{pedido.id}",
        )


class ListaPreciosSincronizacionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sync_listas", password="test123")
        self.client.force_login(self.user)

        self.categoria = Categoria.objects.create(categoria="Categoria Lista")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Lista",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="LST001",
            nombre_producto="Producto Lista",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        self.lista = ListaPreciosPredeterminada.objects.create(
            nombre_listaprecios="Lista Base",
            descripcion_listaprecios="Lista para sincronizacion",
            activa=True,
        )
        self.item = ListaPreciosPredItem.objects.create(
            listaprecios=self.lista,
            nombre_producto=self.producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("1000.00"),
            precio_iva=Decimal("190.00"),
            precio_total=Decimal("1190.00"),
            vigencia=datetime(2026, 12, 31).date(),
        )
        self.cliente_a = Cliente.objects.create(
            nombre_cliente="Cliente Sync A",
            rut_cliente="76111111-9",
            direccion_cliente="Dir A",
            direccion_bodega_cliente="Bodega A",
            cliente_activo=True,
            telefono_cliente="+56911111111",
            correo_cliente="synca@test.local",
            categoria="PYME",
        )
        self.cliente_b = Cliente.objects.create(
            nombre_cliente="Cliente Sync B",
            rut_cliente="76222222-8",
            direccion_cliente="Dir B",
            direccion_bodega_cliente="Bodega B",
            cliente_activo=True,
            telefono_cliente="+56922222222",
            correo_cliente="syncb@test.local",
            categoria="PYME",
        )

    def test_importar_lista_asocia_cliente_y_marca_origen(self):
        resp = self.client.post(
            reverse("asignar_precios", args=[self.cliente_a.id]),
            data={
                "accion": "importar_lista",
                "lista_predeterminada_id": str(self.lista.id),
            },
        )

        self.assertRedirects(resp, reverse("asignar_precios", args=[self.cliente_a.id]))
        self.cliente_a.refresh_from_db()
        self.assertEqual(self.cliente_a.lista_precios_predeterminada_id, self.lista.id)

        precio = ListaPrecios.objects.get(
            nombre_cliente=self.cliente_a,
            nombre_producto=self.producto,
            empaque="PRIMARIO",
        )
        self.assertEqual(precio.precio_venta, Decimal("1000.00"))
        self.assertEqual(precio.lista_predeterminada_origen_id, self.lista.id)

    def test_asignar_precios_permita_abrir_y_actualizar_precio_en_edicion(self):
        precio = ListaPrecios.objects.create(
            nombre_cliente=self.cliente_a,
            nombre_producto=self.producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("1000.00"),
            precio_iva=Decimal("190.00"),
            precio_total=Decimal("1190.00"),
            vigencia=datetime(2026, 12, 31).date(),
            lista_predeterminada_origen=self.lista,
        )

        resp_get = self.client.get(
            reverse("asignar_precios", args=[self.cliente_a.id]),
            data={"precio_id": precio.id},
        )

        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Actualizar Precio")
        self.assertContains(resp_get, f'name="precio_id" value="{precio.id}"')
        self.assertContains(resp_get, self.producto.nombre_producto)

        resp_post = self.client.post(
            reverse("asignar_precios", args=[self.cliente_a.id]),
            data={
                "accion": "guardar_uno",
                "precio_id": str(precio.id),
                "nombre_producto": str(self.producto.id),
                "empaque": "PRIMARIO",
                "precio_venta": "1250.00",
                "vigencia": "2026-12-31",
            },
        )

        self.assertRedirects(resp_post, reverse("asignar_precios", args=[self.cliente_a.id]))
        precio.refresh_from_db()
        self.assertEqual(precio.precio_venta, Decimal("1250.00"))
        self.assertEqual(precio.precio_iva, Decimal("237.50"))
        self.assertEqual(precio.precio_total, Decimal("1487.50"))
        self.assertIsNone(precio.lista_predeterminada_origen)

    def test_asignar_precios_muestra_compra_diferencia_y_alerta_por_antiguedad(self):
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("800.00"),
        )
        ListaPrecios.objects.create(
            nombre_cliente=self.cliente_a,
            nombre_producto=self.producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("700.00"),
            precio_iva=Decimal("133.00"),
            precio_total=Decimal("833.00"),
            vigencia=datetime(2025, 10, 1).date(),
        )

        with patch("Apps.Pedidos.views.cliente.timezone.localdate", return_value=datetime(2026, 5, 15).date()):
            resp = self.client.get(reverse("asignar_precios", args=[self.cliente_a.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["precios_desactualizados_count"], 1)
        self.assertContains(resp, "Compra")
        self.assertContains(resp, "Dif.")
        self.assertContains(resp, "Desde")
        self.assertContains(resp, "$800")
        self.assertContains(resp, "-$100")
        self.assertContains(resp, "+6 meses sin actualizar")
        self.assertContains(resp, "Hay 1 precio sin actualizar hace")

    def test_asignar_precios_prefill_desde_con_ultima_fecha_cliente_y_lista(self):
        ListaPrecios.objects.create(
            nombre_cliente=self.cliente_a,
            nombre_producto=self.producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("1000.00"),
            precio_iva=Decimal("190.00"),
            precio_total=Decimal("1190.00"),
            vigencia=datetime(2026, 4, 10).date(),
        )
        otro_producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="LST002",
            nombre_producto="Producto Lista 2",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        ListaPrecios.objects.create(
            nombre_cliente=self.cliente_a,
            nombre_producto=otro_producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("1400.00"),
            precio_iva=Decimal("266.00"),
            precio_total=Decimal("1666.00"),
            vigencia=datetime(2026, 5, 12).date(),
        )
        self.item.vigencia = datetime(2026, 5, 8).date()
        self.item.save()
        self.cliente_a.lista_precios_predeterminada = self.lista
        self.cliente_a.save(update_fields=["lista_precios_predeterminada"])

        with patch("Apps.Pedidos.views.cliente.timezone.localdate", return_value=datetime(2026, 5, 15).date()):
            resp = self.client.get(reverse("asignar_precios", args=[self.cliente_a.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            'name="vigencia" id="vigencia" class="form-control form-control-sm" required value="2026-05-12"',
        )
        self.assertContains(
            resp,
            'name="vigencia_import" id="vigencia_import" class="form-control form-control-sm" value="2026-05-08"',
        )
        self.assertContains(resp, 'data-default-desde="2026-05-08"')
        self.assertContains(resp, 'class="btn btn-outline-secondary js-set-hoy" data-target="vigencia" data-today="2026-05-15"')
        self.assertContains(resp, 'class="btn btn-outline-secondary js-set-hoy" data-target="vigencia_import" data-today="2026-05-15"')

    def test_asignar_precios_listaprecios_muestra_compra_diferencia_y_alerta_por_antiguedad(self):
        self.item.vigencia = datetime(2025, 10, 1).date()
        self.item.save()
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1200.00"),
        )

        with patch("Apps.Pedidos.views.listaprecios.timezone.localdate", return_value=datetime(2026, 5, 15).date()):
            resp = self.client.get(reverse("asignar_precios_listaprecios", args=[self.lista.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["precios_desactualizados_count"], 1)
        self.assertContains(resp, "Compra")
        self.assertContains(resp, "Dif.")
        self.assertContains(resp, "Desde")
        self.assertContains(resp, "$1.200")
        self.assertContains(resp, "-$200")
        self.assertContains(resp, "+6 meses sin actualizar")
        self.assertContains(resp, "Hay 1 precio sin actualizar hace")

    def test_asignar_precios_listaprecios_prefill_desde_y_boton_hoy(self):
        self.item.vigencia = datetime(2026, 5, 8).date()
        self.item.save()
        otro_producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="LST003",
            nombre_producto="Producto Lista 3",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        ListaPreciosPredItem.objects.create(
            listaprecios=self.lista,
            nombre_producto=otro_producto,
            empaque="PRIMARIO",
            precio_venta=Decimal("1400.00"),
            precio_iva=Decimal("266.00"),
            precio_total=Decimal("1666.00"),
            vigencia=datetime(2026, 5, 12).date(),
        )

        with patch("Apps.Pedidos.views.listaprecios.timezone.localdate", return_value=datetime(2026, 5, 15).date()):
            resp = self.client.get(reverse("asignar_precios_listaprecios", args=[self.lista.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            'name="vigencia" id="vigencia" class="form-control form-control-sm" required value="2026-05-12"',
        )
        self.assertContains(
            resp,
            'class="btn btn-outline-secondary js-set-hoy" data-target="vigencia" data-today="2026-05-15"',
        )

    def test_actualizar_item_lista_sincroniza_clientes_asociados(self):
        for cliente in (self.cliente_a, self.cliente_b):
            self.client.post(
                reverse("asignar_precios", args=[cliente.id]),
                data={
                    "accion": "importar_lista",
                    "lista_predeterminada_id": str(self.lista.id),
                },
            )

        resp = self.client.post(
            reverse("asignar_precios_listaprecios", args=[self.lista.id]),
            data={
                "producto": str(self.producto.id),
                "empaque": "PRIMARIO",
                "precio_venta": "1250.00",
                "vigencia": "2026-12-31",
            },
        )

        self.assertRedirects(resp, reverse("asignar_precios_listaprecios", args=[self.lista.id]))
        self.assertEqual(
            ListaPrecios.objects.get(nombre_cliente=self.cliente_a, nombre_producto=self.producto, empaque="PRIMARIO").precio_venta,
            Decimal("1250.00"),
        )
        self.assertEqual(
            ListaPrecios.objects.get(nombre_cliente=self.cliente_b, nombre_producto=self.producto, empaque="PRIMARIO").precio_venta,
            Decimal("1250.00"),
        )

    def test_eliminar_item_lista_limpia_precios_sincronizados(self):
        self.client.post(
            reverse("asignar_precios", args=[self.cliente_a.id]),
            data={
                "accion": "importar_lista",
                "lista_predeterminada_id": str(self.lista.id),
            },
        )

        resp = self.client.post(reverse("eliminar_precio_listaprecios", args=[self.item.id]))

        self.assertRedirects(resp, reverse("asignar_precios_listaprecios", args=[self.lista.id]))
        self.assertFalse(
            ListaPrecios.objects.filter(
                nombre_cliente=self.cliente_a,
                nombre_producto=self.producto,
                empaque="PRIMARIO",
            ).exists()
        )


class PackFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("packs", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Pack", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Pack", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Pack", nivel="TERCIARIO")

        self.categoria = Categoria.objects.create(categoria="Sanitizacion")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Limpieza",
        )

        self.cliente_obj = Cliente.objects.create(
            nombre_cliente="Bellemer Laboratory Ltda",
            rut_cliente="76123456-9",
            direccion_cliente="Direccion Cliente 123",
            direccion_bodega_cliente="Bodega Cliente 123",
            cliente_activo=True,
            telefono_cliente="+56912345678",
            correo_cliente="bellemer@example.com",
            categoria="PYME",
        )

        self.producto_cloro = self._crear_producto_simple("CLGI01", "Cloro Gel Igenix 900cc")
        self.producto_aerosol = self._crear_producto_simple("DAIG01", "Aerosol Desinfectante Igenix 360cc")
        self.producto_crema = self._crear_producto_simple("LCWX01", "Limpiador Crema Winnex Amoniaco")

        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto_cloro,
            qty=7,
            empaque="PRIMARIO",
            precio_unitario=Decimal("831.93"),
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto_aerosol,
            qty=16,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1436.97"),
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto_crema,
            qty=14,
            empaque="PRIMARIO",
            precio_unitario=Decimal("815.13"),
        )

    def _crear_producto_simple(self, codigo, nombre):
        return Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            tipo_producto="SIMPLE",
            codigo_producto_interno=codigo,
            nombre_producto=nombre,
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )

    def test_menu_productos_expone_link_crear_pack(self):
        resp = self.client.get(reverse("lista_productos"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("crear_pack"))

    def test_crear_pack_y_venderlo_desglosa_stock_y_utilidad(self):
        resp_get = self.client.get(reverse("crear_pack"))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Componentes del Pack")
        self.assertNotContains(resp_get, "Categoría")
        self.assertNotContains(resp_get, "Subcategoría")
        self.assertNotContains(resp_get, "Empaque visible")
        self.assertNotContains(resp_get, "Stock mínimo referencial")

        resp_pack = self.client.post(
            reverse("crear_pack"),
            data={
                "codigo_producto_interno": "PKBLM01",
                "nombre_producto": "Pack Sanitizacion Bellemer",
                "componentes[0][producto]": str(self.producto_cloro.id),
                "componentes[0][empaque]": "PRIMARIO",
                "componentes[0][cantidad]": "1",
                "componentes[1][producto]": str(self.producto_aerosol.id),
                "componentes[1][empaque]": "PRIMARIO",
                "componentes[1][cantidad]": "1",
                "componentes[2][producto]": str(self.producto_crema.id),
                "componentes[2][empaque]": "PRIMARIO",
                "componentes[2][cantidad]": "1",
            },
        )

        self.assertRedirects(resp_pack, reverse("lista_productos"))

        pack = Producto.objects.get(codigo_producto_interno="PKBLM01")
        self.assertEqual(pack.tipo_producto, "PACK")
        self.assertEqual(PackComponente.objects.filter(pack=pack).count(), 3)

        resp_precio = self.client.post(
            reverse("asignar_precios", args=[self.cliente_obj.id]),
            data={
                "accion": "guardar_uno",
                "nombre_producto": str(pack.id),
                "empaque": "PRIMARIO",
                "precio_venta": "4190.00",
                "vigencia": "2026-12-31",
            },
        )
        self.assertRedirects(resp_precio, reverse("asignar_precios", args=[self.cliente_obj.id]))
        self.assertTrue(
            ListaPrecios.objects.filter(
                nombre_cliente=self.cliente_obj,
                nombre_producto=pack,
                empaque="PRIMARIO",
            ).exists()
        )

        pedido = Pedido.objects.create(
            nombre_cliente=self.cliente_obj,
            fecha_pedido=datetime(2026, 5, 12).date(),
            estado_pedido="Pendiente",
        )

        resp_agregar = self.client.post(
            reverse("agregar_productos_pedido", args=[pedido.id]),
            data={
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-producto_id": str(pack.id),
                "form-0-producto_nombre": pack.nombre_producto,
                "form-0-empaque": "PRIMARIO",
                "form-0-precio_unitario": "4190.00",
                "form-0-cantidad": "2",
            },
        )

        self.assertRedirects(resp_agregar, reverse("detalle_pedido", args=[pedido.id]))

        linea = PedidoLinea.objects.get(pedido=pedido, producto=pack)
        self.assertEqual(linea.tipo_linea, "PACK")
        self.assertEqual(linea.cantidad, 2)
        self.assertEqual(linea.precio_unitario, Decimal("4190.00"))

        reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento="RESERVA").order_by("producto__codigo_producto_interno")
        self.assertEqual(reservas.count(), 3)
        self.assertEqual(
            {
                row.producto.codigo_producto_interno: row.qty
                for row in reservas
            },
            {
                "CLGI01": 2,
                "DAIG01": 2,
                "LCWX01": 2,
            },
        )
        self.assertTrue(all(row.linea_pedido_id == linea.id for row in reservas))

        resp_detalle = self.client.get(reverse("detalle_pedido", args=[pedido.id]))
        self.assertEqual(resp_detalle.status_code, 200)
        self.assertContains(resp_detalle, "Pack Sanitizacion Bellemer")
        self.assertContains(resp_detalle, "PACK")

        firma_b64 = base64.b64encode(b"firma-pack").decode("ascii")
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                with patch("Apps.Pedidos.utils_pdf.generar_pdf_entrega", return_value=b"%PDF-1.4 pack"):
                    resp_entrega = self.client.post(
                        reverse("finalizar_pedido", args=[pedido.id]),
                        data={
                            "entrega_nombre": "Ana Perez",
                            "entrega_rut": "11111111-1",
                            "entrega_fecha": "2026-05-12T15:30",
                            "entrega_firma": f"data:image/png;base64,{firma_b64}",
                        },
                    )

        self.assertRedirects(resp_entrega, reverse("detalle_pedido", args=[pedido.id]))
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado_pedido, "Entregado")
        self.assertEqual(
            Stock.objects.filter(pedido=pedido, tipo_movimiento="DESPACHO").count(),
            3,
        )

        resp_venta = self.client.post(
            reverse("finalizar_venta", args=[pedido.id]),
            data={
                "fecha_venta": "2026-05-12",
                "documento_pedido": "Factura",
                "num_documento": "9001",
            },
        )

        self.assertRedirects(resp_venta, reverse("lista_ventas"))

        venta = Venta.objects.get(pedidoid=pedido)
        self.assertEqual(venta.venta_neto_pedido, Decimal("8380.00"))
        self.assertEqual(venta.venta_iva_pedido, Decimal("1592.20"))
        self.assertEqual(venta.venta_total_pedido, Decimal("9972.20"))
        self.assertEqual(venta.ganancia_total, Decimal("2211.94"))
        self.assertEqual(venta.ganancia_porcentaje, Decimal("26.40"))

        utilidades = UtilidadProducto.objects.filter(venta=venta).order_by("producto__codigo_producto_interno")
        self.assertEqual(utilidades.count(), 3)
        self.assertFalse(utilidades.filter(producto=pack).exists())

        detalle_utilidad = {
            item.producto.codigo_producto_interno: (
                item.cantidad,
                item.precio_compra_unitario,
                item.precio_venta_unitario,
                item.utilidad,
            )
            for item in utilidades
        }
        self.assertEqual(
            detalle_utilidad,
            {
                "CLGI01": (2, Decimal("831.93"), Decimal("1130.27"), Decimal("298.34")),
                "DAIG01": (2, Decimal("1436.97"), Decimal("1952.28"), Decimal("515.31")),
                "LCWX01": (2, Decimal("815.13"), Decimal("1107.45"), Decimal("292.32")),
            },
        )

    def test_crear_pack_permite_un_solo_producto_con_cantidad_mayor_a_uno(self):
        resp = self.client.post(
            reverse("crear_pack"),
            data={
                "codigo_producto_interno": "PKUNI01",
                "nombre_producto": "Pack Doble Cloro",
                "componentes[0][producto]": str(self.producto_cloro.id),
                "componentes[0][empaque]": "PRIMARIO",
                "componentes[0][cantidad]": "2",
            },
        )

        self.assertRedirects(resp, reverse("lista_productos"))

        pack = Producto.objects.get(codigo_producto_interno="PKUNI01")
        self.assertEqual(pack.tipo_producto, "PACK")
        componente = PackComponente.objects.get(pack=pack)
        self.assertEqual(componente.producto_id, self.producto_cloro.id)
        self.assertEqual(componente.cantidad, 2)


class ProductoEstadoBaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("producto_estado", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Estado", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Estado", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Estado", nivel="TERCIARIO")
        self.categoria = Categoria.objects.create(categoria="Categoria Estado")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Estado",
        )
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Estado",
            rut_proveedor="77000000-1",
            direccion_proveedor="Dir Proveedor",
            direccion_bodega_proveedor="Dir Bodega",
            empresa_activa=True,
            banco_proveedor="Banco Estado",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="1234567890",
        )
        self.cliente_comercial = Cliente.objects.create(
            nombre_cliente="Cliente Estado",
            rut_cliente="77111111-1",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Bodega Cliente",
            cliente_activo=True,
            telefono_cliente="+56911112222",
            correo_cliente="cliente.estado@example.com",
            categoria="PYME",
        )

    def crear_producto(self, codigo, nombre, **overrides):
        data = {
            "categoria_producto": self.categoria,
            "subcategoria_producto": self.subcategoria,
            "codigo_producto_interno": codigo,
            "nombre_producto": nombre,
            "qty_terciario": 1,
            "qty_secundario": 1,
            "qty_primario": 1,
            "qty_unidad": 1,
            "medida": "und",
            "qty_minima": 1,
            "empaque_primario": self.emp_p,
            "empaque_secundario": self.emp_s,
            "empaque_terciario": self.emp_t,
            "estado_operativo": Producto.ESTADO_ACTIVO,
        }
        data.update(overrides)
        return Producto.objects.create(**data)

    def crear_pack(self, codigo, nombre, **overrides):
        data = {
            "tipo_producto": "PACK",
            "categoria_producto": None,
            "subcategoria_producto": None,
            "codigo_producto_interno": codigo,
            "nombre_producto": nombre,
            "qty_terciario": 1,
            "qty_secundario": 1,
            "qty_primario": 1,
            "qty_unidad": 1,
            "medida": "und",
            "qty_minima": 0,
            "empaque_primario": None,
            "empaque_secundario": None,
            "empaque_terciario": None,
            "estado_operativo": Producto.ESTADO_ACTIVO,
        }
        data.update(overrides)
        return Producto.objects.create(**data)

    def crear_recepcion(self):
        return Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=datetime(2026, 6, 1).date(),
            estado_recepcion="Pendiente",
            documento_recepcion="Factura",
            num_documento_recepcion=9001,
            total_neto_recepcion=Decimal("0.00"),
            iva_recepcion=Decimal("0.00"),
            total_recepcion=Decimal("0.00"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )

    def crear_precio_cliente(
        self,
        producto,
        *,
        precio="1500.00",
        empaque="PRIMARIO",
        vigencia=None,
        origen=None,
    ):
        neto = Decimal(precio)
        iva = (neto * Decimal("0.19")).quantize(Decimal("0.01"))
        total = neto + iva
        return ListaPrecios.objects.create(
            nombre_cliente=self.cliente_comercial,
            nombre_producto=producto,
            empaque=empaque,
            precio_venta=neto,
            precio_iva=iva,
            precio_total=total,
            vigencia=vigencia or datetime(2026, 6, 1).date(),
            lista_predeterminada_origen=origen,
        )


class ProductoEstadoOperativoTests(ProductoEstadoBaseTests):
    def test_cambiar_estado_producto_persiste_trazabilidad(self):
        producto = self.crear_producto("EST001", "Producto Estado")

        resp = self.client.post(
            reverse("cambiar_estado_producto", args=[producto.id]),
            data={
                "estado_operativo": Producto.ESTADO_SUSPENDIDO_VENTA,
                "motivo_estado": "Suspendido por revision comercial",
            },
        )

        self.assertRedirects(resp, reverse("lista_productos"))
        producto.refresh_from_db()
        self.assertEqual(producto.estado_operativo, Producto.ESTADO_SUSPENDIDO_VENTA)
        self.assertEqual(producto.motivo_estado, "Suspendido por revision comercial")
        self.assertIsNotNone(producto.fecha_estado)
        self.assertEqual(producto.usuario_estado, self.user)

    def test_eliminar_producto_con_historial_redirige_a_cambio_estado(self):
        producto = self.crear_producto("EST002", "Producto Con Historial")
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=producto,
            qty=3,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1200.00"),
            fecha_movimiento=timezone.localdate(),
        )

        resp = self.client.get(reverse("eliminar_producto", args=[producto.id]))

        self.assertRedirects(resp, reverse("cambiar_estado_producto", args=[producto.id]))
        self.assertTrue(Producto.objects.filter(pk=producto.pk).exists())

    def test_pack_no_es_vendible_si_un_componente_esta_suspendido_de_venta(self):
        componente = self.crear_producto(
            "EST003",
            "Componente Suspendido",
            estado_operativo=Producto.ESTADO_SUSPENDIDO_VENTA,
        )
        pack = self.crear_pack("PACK001", "Pack Bloqueado")
        PackComponente.objects.create(
            pack=pack,
            producto=componente,
            empaque="PRIMARIO",
            cantidad=1,
            orden=0,
        )

        pack = Producto.objects.prefetch_related("componentes_pack__producto").get(pk=pack.pk)

        self.assertFalse(pack.venta_habilitada)
        self.assertFalse(pack.precio_habilitado)


class ProductoEstadoRecepcionTests(ProductoEstadoBaseTests):
    def setUp(self):
        super().setUp()
        self.producto_activo = self.crear_producto("REC001", "Producto Recepcion Activo")
        self.producto_suspendido_compra = self.crear_producto(
            "REC002",
            "Producto Recepcion Bloqueado",
            estado_operativo=Producto.ESTADO_SUSPENDIDO_COMPRA,
        )
        self.recepcion = self.crear_recepcion()

    def test_recepcion_excluye_producto_suspendido_compra_del_formulario(self):
        resp = self.client.get(reverse("crear_recepcion_productos", args=[self.recepcion.id]))

        self.assertEqual(resp.status_code, 200)
        producto_ids = set(resp.context["form"].fields["producto"].queryset.values_list("id", flat=True))
        self.assertIn(self.producto_activo.id, producto_ids)
        self.assertNotIn(self.producto_suspendido_compra.id, producto_ids)

    def test_recepcion_rechaza_producto_suspendido_compra_en_post(self):
        resp = self.client.post(
            reverse("crear_recepcion_productos", args=[self.recepcion.id]),
            data={
                "producto": self.producto_suspendido_compra.id,
                "qty": "1",
                "empaque": "PRIMARIO",
                "precio_unitario": "1000.00",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RecepcionLinea.objects.filter(recepcion=self.recepcion).exists())
        self.assertIn("producto", resp.context["form"].errors)


class ProductoEstadoPreciosTests(ProductoEstadoBaseTests):
    def test_asignacion_de_precios_mantiene_historial_visible_y_excluye_bloqueados_del_selector(self):
        producto_activo = self.crear_producto("PRE001", "Producto Precio Activo")
        producto_suspendido = self.crear_producto(
            "PRE002",
            "Producto Precio Bloqueado",
            estado_operativo=Producto.ESTADO_SUSPENDIDO_VENTA,
        )
        self.crear_precio_cliente(producto_suspendido, precio="2990.00")

        resp = self.client.get(reverse("asignar_precios", args=[self.cliente_comercial.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, producto_suspendido.nombre_producto)
        producto_ids = {producto.id for producto in resp.context["productos"]}
        self.assertIn(producto_activo.id, producto_ids)
        self.assertNotIn(producto_suspendido.id, producto_ids)

    def test_sincronizacion_de_lista_omite_producto_bloqueado_y_preserva_precio_existente(self):
        lista = ListaPreciosPredeterminada.objects.create(nombre_listaprecios="Lista Estado")
        producto_activo = self.crear_producto("PRE003", "Producto Sync Activo")
        producto_suspendido = self.crear_producto(
            "PRE004",
            "Producto Sync Bloqueado",
            estado_operativo=Producto.ESTADO_SUSPENDIDO_VENTA,
        )

        ListaPreciosPredItem.objects.create(
            listaprecios=lista,
            nombre_producto=producto_activo,
            empaque="PRIMARIO",
            precio_venta=Decimal("2000.00"),
            precio_iva=Decimal("380.00"),
            precio_total=Decimal("2380.00"),
            vigencia=datetime(2026, 6, 1).date(),
        )
        ListaPreciosPredItem.objects.create(
            listaprecios=lista,
            nombre_producto=producto_suspendido,
            empaque="PRIMARIO",
            precio_venta=Decimal("5000.00"),
            precio_iva=Decimal("950.00"),
            precio_total=Decimal("5950.00"),
            vigencia=datetime(2026, 6, 1).date(),
        )
        precio_historico = self.crear_precio_cliente(
            producto_suspendido,
            precio="1990.00",
            origen=lista,
        )

        stats = sincronizar_lista_predeterminada_a_cliente(self.cliente_comercial, lista)

        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["skipped_disabled"], 1)
        self.assertEqual(stats["deleted"], 0)

        precio_historico.refresh_from_db()
        self.assertEqual(precio_historico.precio_venta, Decimal("1990.00"))
        self.assertTrue(
            ListaPrecios.objects.filter(
                nombre_cliente=self.cliente_comercial,
                nombre_producto=producto_activo,
                empaque="PRIMARIO",
            ).exists()
        )


class ProductoEstadoVentaTests(ProductoEstadoBaseTests):
    def setUp(self):
        super().setUp()
        self.producto_activo = self.crear_producto("VEN001", "Producto Venta Activo")
        self.producto_suspendido = self.crear_producto(
            "VEN002",
            "Producto Venta Bloqueado",
            estado_operativo=Producto.ESTADO_SUSPENDIDO_VENTA,
        )
        self.crear_precio_cliente(self.producto_activo, precio="3100.00")
        self.crear_precio_cliente(self.producto_suspendido, precio="4100.00")
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente_comercial,
            fecha_pedido=datetime(2026, 6, 2).date(),
            estado_pedido="Pendiente",
        )

    def test_agregar_productos_pedido_excluye_producto_suspendido_de_venta(self):
        resp = self.client.get(reverse("agregar_productos_pedido", args=[self.pedido.id]))

        self.assertEqual(resp.status_code, 200)
        producto_ids = {int(form.initial["producto_id"]) for form in resp.context["formset"].forms}
        self.assertIn(self.producto_activo.id, producto_ids)
        self.assertNotIn(self.producto_suspendido.id, producto_ids)

    def test_agregar_productos_pedido_rechaza_post_de_producto_suspendido(self):
        resp = self.client.post(
            reverse("agregar_productos_pedido", args=[self.pedido.id]),
            data={
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-producto_id": str(self.producto_suspendido.id),
                "form-0-producto_nombre": self.producto_suspendido.nombre_producto,
                "form-0-empaque": "PRIMARIO",
                "form-0-precio_unitario": "4100.00",
                "form-0-cantidad": "1",
            },
        )

        self.assertRedirects(resp, reverse("agregar_productos_pedido", args=[self.pedido.id]))
        self.assertFalse(PedidoLinea.objects.filter(pedido=self.pedido).exists())
        self.assertFalse(Stock.objects.filter(pedido=self.pedido, tipo_movimiento="RESERVA").exists())

    def test_cotizacion_excluye_producto_suspendido_de_venta(self):
        resp = self.client.get(reverse("seleccionar_productos_cotizacion", args=[self.cliente_comercial.id]))

        self.assertEqual(resp.status_code, 200)
        producto_ids = {precio.nombre_producto_id for precio in resp.context["productos"]}
        self.assertIn(self.producto_activo.id, producto_ids)
        self.assertNotIn(self.producto_suspendido.id, producto_ids)


class BoletaElectronicaFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("boleta_user", password="test123")
        self.client.force_login(self.user)

        self.emp_p = CategoriaEmpaque.objects.create(nombre="Unidad Boleta", nivel="PRIMARIO")
        self.emp_s = CategoriaEmpaque.objects.create(nombre="Caja Boleta", nivel="SECUNDARIO")
        self.emp_t = CategoriaEmpaque.objects.create(nombre="Pallet Boleta", nivel="TERCIARIO")
        self.categoria = Categoria.objects.create(categoria="Categoria Boleta")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Subcategoria Boleta",
        )
        self.cliente_obj = Cliente.objects.create(
            nombre_cliente="Cliente Boleta",
            rut_cliente="11111111-1",
            razon_social="Cliente Boleta SpA",
            giro_cliente="Venta de insumos",
            direccion_cliente="Direccion Cliente 123",
            direccion_bodega_cliente="Bodega Cliente 123",
            comuna_cliente="Santiago",
            ciudad_cliente="Santiago",
            cliente_activo=True,
            telefono_cliente="+56912345678",
            correo_cliente="cliente.boleta@example.com",
            categoria="PYME",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="BOL001",
            nombre_producto="Producto Boleta",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
            empaque_primario=self.emp_p,
            empaque_secundario=self.emp_s,
            empaque_terciario=self.emp_t,
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente_obj,
            fecha_pedido=datetime(2026, 6, 30).date(),
            estado_pedido="Entregado",
            comentario_pedido="Pedido para boleta",
        )
        Stock.objects.create(
            tipo_movimiento="DESPACHO",
            producto=self.producto,
            qty=2,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1000.00"),
            pedido=self.pedido,
        )

    def test_finalizar_venta_boleta_genera_documento_xml(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            habilita_factura=True,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            acteco_principal="521900",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            resolucion_numero=80,
            resolucion_fecha=datetime(2024, 1, 15).date(),
            correo_intercambio="dte@saam.cl",
            ruta_caf_tipo_33="caf/tipo33.xml",
            ruta_caf_tipo_39="caf/tipo39.xml",
        )

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                resp = self.client.post(
                    reverse("finalizar_venta", args=[self.pedido.id]),
                    data={
                        "fecha_venta": "2026-06-30",
                        "documento_pedido": "Boleta",
                        "num_documento": "",
                    },
                )

                venta = Venta.objects.get(pedidoid=self.pedido)
                self.assertRedirects(resp, reverse("detalle_venta", args=[venta.id]))

                boleta = BoletaElectronica.objects.get(venta=venta)
                self.assertEqual(venta.num_documento, None)
                self.assertEqual(boleta.estado, BoletaElectronica.ESTADO_XML_PREPARADO)
                self.assertTrue(boleta.xml_borrador.name.endswith(".xml"))
                self.assertEqual(boleta.payload["meta"]["tipo_dte"], 39)
                self.assertEqual(boleta.payload["receptor"]["rut"], "11111111-1")
                self.assertEqual(boleta.payload["receptor"]["nombre"], "Cliente Boleta SpA")
                self.assertEqual(len(boleta.payload["detalle"]), 1)

    def test_generar_documento_boleta_sin_configuracion_queda_incompleta(self):
        venta = Venta.objects.create(
            pedidoid=self.pedido,
            fecha_venta=datetime(2026, 6, 30).date(),
            documento_pedido="Boleta",
            num_documento=None,
            venta_neto_pedido=Decimal("2000.00"),
            venta_iva_pedido=Decimal("380.00"),
            venta_total_pedido=Decimal("2380.00"),
            ganancia_total=Decimal("500.00"),
            ganancia_porcentaje=Decimal("25.00"),
        )
        self.pedido.estado_pedido = "Finalizado"
        self.pedido.save(update_fields=["estado_pedido"])

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                resp = self.client.post(reverse("generar_documento_venta", args=[venta.id]))

        self.assertRedirects(resp, reverse("detalle_venta", args=[venta.id]))

        boleta = BoletaElectronica.objects.get(venta=venta)
        self.assertEqual(boleta.estado, BoletaElectronica.ESTADO_DATOS_INCOMPLETOS)
        self.assertIn(
            "No existe una configuracion SII activa para boleta electronica.",
            boleta.errores_validacion,
        )

    def test_generar_documento_boleta_no_duplica_expediente(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            habilita_factura=False,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            ruta_caf_tipo_39="caf/tipo39.xml",
        )
        venta = Venta.objects.create(
            pedidoid=self.pedido,
            fecha_venta=datetime(2026, 6, 30).date(),
            documento_pedido="Boleta",
            num_documento=None,
            venta_neto_pedido=Decimal("2000.00"),
            venta_iva_pedido=Decimal("380.00"),
            venta_total_pedido=Decimal("2380.00"),
            ganancia_total=Decimal("500.00"),
            ganancia_porcentaje=Decimal("25.00"),
        )

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                resp_1 = self.client.post(reverse("generar_documento_venta", args=[venta.id]))
                resp_2 = self.client.post(reverse("generar_documento_venta", args=[venta.id]))

        self.assertRedirects(resp_1, reverse("detalle_venta", args=[venta.id]))
        self.assertRedirects(resp_2, reverse("detalle_venta", args=[venta.id]))
        self.assertEqual(BoletaElectronica.objects.filter(venta=venta).count(), 1)
        boleta = BoletaElectronica.objects.get(venta=venta)
        self.assertEqual(boleta.estado, BoletaElectronica.ESTADO_XML_PREPARADO)

    def test_boleta_bajo_135_uf_configurado_no_exige_rut_receptor(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            ruta_caf_tipo_39="caf/tipo39.xml",
            monto_identificacion_receptor_boleta=Decimal("5000000.00"),
        )
        cliente = Cliente.objects.create(
            nombre_cliente="Consumidor Menor",
            rut_cliente="123",
            razon_social="",
            giro_cliente="",
            direccion_cliente="",
            direccion_bodega_cliente="",
            comuna_cliente="",
            ciudad_cliente="",
            cliente_activo=True,
            telefono_cliente="",
            correo_cliente="",
            categoria="PERSONA NATURAL",
        )
        pedido = Pedido.objects.create(
            nombre_cliente=cliente,
            fecha_pedido=datetime(2026, 6, 30).date(),
            estado_pedido="Finalizado",
        )
        Stock.objects.create(
            tipo_movimiento="DESPACHO",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1000.00"),
            pedido=pedido,
        )
        venta = Venta.objects.create(
            pedidoid=pedido,
            fecha_venta=datetime(2026, 6, 30).date(),
            documento_pedido="Boleta",
            num_documento=None,
            venta_neto_pedido=Decimal("1000.00"),
            venta_iva_pedido=Decimal("190.00"),
            venta_total_pedido=Decimal("1190.00"),
            ganancia_total=Decimal("100.00"),
            ganancia_porcentaje=Decimal("10.00"),
        )

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                resp = self.client.post(reverse("generar_documento_venta", args=[venta.id]))

        self.assertRedirects(resp, reverse("detalle_venta", args=[venta.id]))
        boleta = BoletaElectronica.objects.get(venta=venta)
        self.assertEqual(boleta.estado, BoletaElectronica.ESTADO_XML_PREPARADO)
        self.assertEqual(boleta.payload["receptor"]["rut"], "66666666-6")
        self.assertFalse(boleta.payload["receptor"]["identificacion_obligatoria"])

    def test_boleta_sobre_135_uf_configurado_exige_rut_receptor_valido(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            ruta_caf_tipo_39="caf/tipo39.xml",
            monto_identificacion_receptor_boleta=Decimal("1000.00"),
        )
        cliente = Cliente.objects.create(
            nombre_cliente="Consumidor Mayor",
            rut_cliente="123",
            razon_social="",
            giro_cliente="",
            direccion_cliente="",
            direccion_bodega_cliente="",
            comuna_cliente="",
            ciudad_cliente="",
            cliente_activo=True,
            telefono_cliente="",
            correo_cliente="",
            categoria="PERSONA NATURAL",
        )
        pedido = Pedido.objects.create(
            nombre_cliente=cliente,
            fecha_pedido=datetime(2026, 6, 30).date(),
            estado_pedido="Finalizado",
        )
        Stock.objects.create(
            tipo_movimiento="DESPACHO",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("1000.00"),
            pedido=pedido,
        )
        venta = Venta.objects.create(
            pedidoid=pedido,
            fecha_venta=datetime(2026, 6, 30).date(),
            documento_pedido="Boleta",
            num_documento=None,
            venta_neto_pedido=Decimal("1000.00"),
            venta_iva_pedido=Decimal("190.00"),
            venta_total_pedido=Decimal("1190.00"),
            ganancia_total=Decimal("100.00"),
            ganancia_porcentaje=Decimal("10.00"),
        )

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                resp = self.client.post(reverse("generar_documento_venta", args=[venta.id]))

        self.assertRedirects(resp, reverse("detalle_venta", args=[venta.id]))
        boleta = BoletaElectronica.objects.get(venta=venta)
        self.assertEqual(boleta.estado, BoletaElectronica.ESTADO_DATOS_INCOMPLETOS)
        self.assertIn(
            "La boleta supera el monto configurado para 135 UF y el RUT del receptor no es valido.",
            boleta.errores_validacion,
        )


class ConfiguracionDashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff_config", password="test123", is_staff=True)
        self.regular = User.objects.create_user("regular_config", password="test123", is_staff=False)

    def test_staff_ve_link_de_configuracion_en_topbar(self):
        self.client.force_login(self.staff)

        resp = self.client.get(reverse("home"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("configuracion"))

    def test_staff_puede_abrir_pantalla_configuracion(self):
        ConfiguracionBoletaSii.objects.create(
            nombre="Principal",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            habilita_factura=True,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            acteco_principal="521900",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            correo_intercambio="dte@saam.cl",
            ruta_caf_tipo_33="caf/tipo33.xml",
            ruta_caf_tipo_39="caf/tipo39.xml",
        )
        self.client.force_login(self.staff)

        resp = self.client.get(reverse("configuracion"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Configuraciones Registradas")
        self.assertContains(resp, "Principal")
        self.assertContains(resp, "Factura 33")
        self.assertContains(resp, "sii-help-icon")
        self.assertContains(resp, "Se obtiene desde Mi SII")
        self.assertContains(resp, "No ingresar claves ni contrasenas")
        self.assertContains(resp, "Timbraje electronico")

    def test_staff_puede_crear_configuracion_desde_formulario_html(self):
        self.client.force_login(self.staff)

        resp = self.client.post(
            reverse("configuracion"),
            data={
                "nombre": "Formulario SAAM",
                "activa": "on",
                "ambiente": ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
                "habilita_boleta": "on",
                "habilita_factura": "on",
                "rut_emisor": "22222222-2",
                "razon_social": "SAAM Demo SpA",
                "giro": "Servicios logistica",
                "acteco_principal": "521900",
                "direccion_origen": "Av. Apoquindo 1234",
                "comuna_origen": "Las Condes",
                "ciudad_origen": "Santiago",
                "resolucion_numero": "80",
                "resolucion_fecha": "2024-01-15",
                "certificado_alias": "cert-saam",
                "correo_intercambio": "dte@saam.cl",
                "ruta_caf_tipo_33": "caf/tipo33.xml",
                "ruta_caf_tipo_39": "caf/tipo39.xml",
                "observaciones": "Configuracion creada por formulario.",
            },
        )

        self.assertRedirects(resp, reverse("configuracion"))
        cfg = ConfiguracionBoletaSii.objects.get(nombre="Formulario SAAM")
        self.assertEqual(cfg.rut_emisor, "22222222-2")
        self.assertTrue(cfg.activa)
        self.assertTrue(cfg.habilita_factura)
        self.assertEqual(cfg.ruta_caf_tipo_33, "caf/tipo33.xml")

    def test_staff_puede_editar_configuracion_desde_formulario_html(self):
        cfg = ConfiguracionBoletaSii.objects.create(
            nombre="Editable",
            activa=True,
            ambiente=ConfiguracionBoletaSii.AMBIENTE_CERTIFICACION,
            habilita_boleta=True,
            habilita_factura=False,
            rut_emisor="22222222-2",
            razon_social="SAAM Demo SpA",
            giro="Servicios logistica",
            acteco_principal="521900",
            direccion_origen="Av. Apoquindo 1234",
            comuna_origen="Las Condes",
            ciudad_origen="Santiago",
            correo_intercambio="dte@saam.cl",
            ruta_caf_tipo_33="",
            ruta_caf_tipo_39="caf/tipo39.xml",
        )
        self.client.force_login(self.staff)

        resp = self.client.post(
            reverse("configuracion"),
            data={
                "config_id": str(cfg.id),
                "nombre": "Editable v2",
                "ambiente": ConfiguracionBoletaSii.AMBIENTE_PRODUCCION,
                "habilita_boleta": "on",
                "habilita_factura": "on",
                "rut_emisor": "22222222-2",
                "razon_social": "SAAM Produccion SpA",
                "giro": "Servicios portuarios",
                "acteco_principal": "522090",
                "direccion_origen": "Av. Providencia 1000",
                "comuna_origen": "Providencia",
                "ciudad_origen": "Santiago",
                "resolucion_numero": "81",
                "resolucion_fecha": "2024-02-01",
                "certificado_alias": "cert-prod",
                "correo_intercambio": "dte-prod@saam.cl",
                "ruta_caf_tipo_33": "caf/produccion33.xml",
                "ruta_caf_tipo_39": "caf/produccion39.xml",
                "observaciones": "Actualizada por formulario.",
            },
        )

        self.assertRedirects(resp, reverse("configuracion"))
        cfg.refresh_from_db()
        self.assertEqual(cfg.nombre, "Editable v2")
        self.assertEqual(cfg.ambiente, ConfiguracionBoletaSii.AMBIENTE_PRODUCCION)
        self.assertEqual(cfg.comuna_origen, "Providencia")
        self.assertTrue(cfg.habilita_factura)
        self.assertEqual(cfg.ruta_caf_tipo_33, "caf/produccion33.xml")

    def test_usuario_no_staff_no_puede_abrir_configuracion(self):
        self.client.force_login(self.regular)

        resp = self.client.get(reverse("configuracion"))

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp.url)
