import csv
from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
    ListaPrecios,
    MovimientoStockHistorico,
    Pedido,
    Producto,
    Proveedor,
    Recepcion,
    Stock,
    Subcategoria,
    Venta,
)
from Apps.Pedidos.templatetags.custom_filters import formatear_miles
from Apps.Pedidos.utils_pdf import formatear_miles_punto
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


class RedondeoSiiFormattingTests(SimpleTestCase):
    def test_formatear_miles_redondea_final_con_regla_sii(self):
        self.assertEqual(formatear_miles(Decimal("10.49")), "10")
        self.assertEqual(formatear_miles(Decimal("10.50")), "11")
        self.assertEqual(formatear_miles(Decimal("1238.50")), "1.239")

    def test_formatear_miles_pdf_redondea_final_con_regla_sii(self):
        self.assertEqual(formatear_miles_punto(Decimal("10.49")), "10")
        self.assertEqual(formatear_miles_punto(Decimal("10.50")), "11")
        self.assertEqual(formatear_miles_punto(Decimal("1238.50")), "1.239")


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

    def test_eliminar_producto_recalcula_neto_desde_lineas_restantes(self):
        Stock.objects.create(
            tipo_movimiento="RECEPCION",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("100.00"),
            recepcion=self.recepcion,
        )
        otra_linea = Stock.objects.create(
            tipo_movimiento="RECEPCION",
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
        Stock.objects.create(
            tipo_movimiento="RECEPCION",
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
        total_lineas = Stock.objects.filter(recepcion=self.recepcion).count()

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
        self.assertEqual(Stock.objects.filter(recepcion=self.recepcion).count(), total_lineas)

    def test_post_eliminar_producto_no_modifica_recepcion_finalizada(self):
        resp = self.client.post(reverse("eliminar_recepcion_producto", args=[self.stock.id]))

        self.assertRedirects(
            resp,
            reverse("recepcion_productos_historico", args=[self.recepcion.id]),
        )
        self.assertTrue(Stock.objects.filter(id=self.stock.id).exists())

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
