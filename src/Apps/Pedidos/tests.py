import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from Apps.Pedidos.models import (
    Categoria,
    CategoriaEmpaque,
    Cliente,
    MovimientoStockHistorico,
    Pedido,
    Producto,
    Proveedor,
    Recepcion,
    Stock,
    Subcategoria,
    Venta,
)
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
        fecha_aware = timezone.make_aware(fecha)
        Stock.objects.filter(pk=stock.pk).update(fecha_movimiento=fecha_aware)

    def _fila_producto(self, year, month):
        filas = filas_stock_contable(Periodo(year=year, month=month))
        return next(fila for fila in filas if fila["codigo_interno"] == self.producto.codigo_producto_interno)

    def test_filas_stock_contable_respetan_periodo_y_stock_total(self):
        fila_enero = self._fila_producto(2026, 1)
        self.assertEqual(fila_enero["cantidad_disponible_uprim"], 14)
        self.assertEqual(fila_enero["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_enero["cantidad_despachada_uprim"], 0)
        self.assertEqual(fila_enero["costo_unitario_compra"], Decimal("100.00"))
        self.assertEqual(fila_enero["total_producto"], Decimal("1400.00"))

        fila_febrero = self._fila_producto(2026, 2)
        self.assertEqual(fila_febrero["cantidad_disponible_uprim"], 34)
        self.assertEqual(fila_febrero["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_febrero["cantidad_despachada_uprim"], 0)
        self.assertEqual(fila_febrero["costo_unitario_compra"], Decimal("150.00"))
        self.assertEqual(fila_febrero["total_producto"], Decimal("5100.00"))

        fila_marzo = self._fila_producto(2026, 3)
        self.assertEqual(fila_marzo["cantidad_disponible_uprim"], 32)
        self.assertEqual(fila_marzo["cantidad_reservada_uprim"], 4)
        self.assertEqual(fila_marzo["cantidad_despachada_uprim"], 2)
        self.assertEqual(fila_marzo["costo_unitario_compra"], Decimal("150.00"))
        self.assertEqual(fila_marzo["total_producto"], Decimal("4800.00"))

    def test_exportar_inventario_propyme_csv_usa_periodo_consultado(self):
        resp = self.client.get(
            reverse("exportar_inventario_propyme"),
            data={"year": 2026, "month": 1},
        )
        self.assertEqual(resp.status_code, 200)
        contenido = resp.content.decode("utf-8-sig")
        filas = list(csv.DictReader(StringIO(contenido), delimiter=";"))
        fila = next(item for item in filas if item["codigo_interno"] == self.producto.codigo_producto_interno)

        self.assertEqual(fila["cantidad_disponible_uprim"], "14")
        self.assertEqual(fila["cantidad_despachada_uprim"], "0")
        self.assertEqual(fila["costo_unitario_compra"], "100.00")
        self.assertEqual(fila["total_producto"], "1400.00")

    def test_dashboard_inventario_permita_filtrar_solo_productos_con_stock(self):
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
            reverse("dashboard_inventario"),
            data={"year": 2026, "month": 3, "stock_view": "con_stock"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Solo con stock")
        self.assertContains(resp, self.producto.nombre_producto)
        self.assertNotContains(resp, producto_sin_stock.nombre_producto)

    def test_dashboard_inventario_muestre_link_a_flujo(self):
        resp = self.client.get(
            reverse("dashboard_inventario"),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            f'{reverse("flujo_inventario_producto", args=[self.producto.id])}?year=2026&month=3&stock_view=todos',
        )

    def test_flujo_inventario_producto_muestre_historial_ordenado(self):
        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Flujo de Inventario")
        self.assertContains(resp, "Sin responsable registrado")
        self.assertContains(resp, "Subtotal Final")

        movimientos = resp.context["movimientos_rows"]
        self.assertEqual(len(movimientos), 4)
        self.assertEqual(movimientos[0]["transaccion"], "Entrada / Factura #1001")
        self.assertEqual(movimientos[1]["transaccion"], "Reserva pendiente")
        self.assertEqual(movimientos[2]["transaccion"], "Entrada / Factura #1002")
        self.assertEqual(movimientos[3]["transaccion"], "Salida - Despacho")
        self.assertEqual(movimientos[0]["subtotal"], 10)
        self.assertEqual(movimientos[1]["subtotal"], 10)
        self.assertEqual(movimientos[2]["subtotal"], 30)
        self.assertEqual(movimientos[3]["subtotal"], 28)
        self.assertFalse(movimientos[0]["es_salida"])
        self.assertTrue(movimientos[3]["es_salida"])
        self.assertEqual(resp.context["subtotal_entradas"], 30)
        self.assertEqual(resp.context["subtotal_salidas"], 2)
        self.assertEqual(resp.context["reservas_pendientes"], 4)
        self.assertEqual(resp.context["subtotal_final"], 28)

    def test_flujo_inventario_producto_muestre_responsable_desde_historial(self):
        fecha_ingreso = timezone.make_aware(datetime(2026, 1, 10, 12, 0, 0))
        fecha_reserva = timezone.make_aware(datetime(2026, 1, 20, 12, 0, 0))
        MovimientoStockHistorico.objects.create(
            stock=self.ingreso_enero,
            tipo_movimiento="RECEPCION",
            qty=self.ingreso_enero.qty,
            empaque=self.ingreso_enero.empaque,
            precio_unitario=self.ingreso_enero.precio_unitario,
            fecha_movimiento=fecha_ingreso,
            responsable=self.user,
        )
        MovimientoStockHistorico.objects.create(
            stock=self.reserva_enero,
            tipo_movimiento="RESERVA",
            qty=self.reserva_enero.qty,
            empaque=self.reserva_enero.empaque,
            precio_unitario=self.reserva_enero.precio_unitario,
            fecha_movimiento=fecha_reserva,
            responsable=self.user,
        )

        resp = self.client.get(
            reverse("flujo_inventario_producto", args=[self.producto.id]),
            data={"year": 2026, "month": 3, "stock_view": "todos"},
        )
        self.assertEqual(resp.status_code, 200)
        movimientos = resp.context["movimientos_rows"]

        self.assertEqual(movimientos[0]["responsable"], self.user.username)
        self.assertEqual(movimientos[1]["responsable"], self.user.username)
        self.assertEqual(movimientos[1]["transaccion"], "Reserva pendiente")
        self.assertEqual(movimientos[1]["subtotal"], 10)
