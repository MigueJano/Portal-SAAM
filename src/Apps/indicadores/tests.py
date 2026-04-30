from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Apps.Pedidos.models import (
    Categoria,
    Cliente,
    Pedido,
    Producto,
    Proveedor,
    Recepcion,
    Stock,
    Subcategoria,
    UtilidadProducto,
    Venta,
)


class IndicadoresViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("usuario_indicadores", password="test123")
        self.urls = [
            reverse("dashboard_financiero_simple"),
            reverse("dashboard_ventas"),
            reverse("dashboard_inventario"),
            reverse("dashboard_operaciones"),
            reverse("dashboard_estrategia"),
            reverse("dashboard_estrategia_precios"),
        ]

    def test_dashboards_requieren_autenticacion(self):
        for url in self.urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/auth/login/", resp.url)

    def test_dashboards_renderizan_para_usuario_autenticado(self):
        self.client.force_login(self.user)
        for url in self.urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)

    def test_menu_contabilidad_en_indicadores(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contabilidad Pro Pyme", count=1)
        self.assertContains(resp, "css/style_base.css?v=")
        self.assertContains(resp, "css/colors.css?v=")

    def test_urls_contabilidad_resueltas_en_indicadores(self):
        self.assertTrue(reverse("resumen_contable_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libro_ventas_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libro_compras_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_inventario_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libros_propyme_zip").startswith("/indicadores/"))


class DashboardFinancieroPpmTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ppm_financiero", password="test123")
        self.client.force_login(self.user)

        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente PPM",
            rut_cliente="77555555-5",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Bodega",
            cliente_activo=True,
            telefono_cliente="+56955555555",
            correo_cliente="ppm@test.local",
            categoria="PYME",
        )
        self.pedido = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=timezone.localdate(),
            estado_pedido="Finalizado",
            comentario_pedido="Pedido PPM",
        )
        self.venta = Venta.objects.create(
            pedidoid=self.pedido,
            fecha_venta=timezone.localdate(),
            documento_pedido="Factura",
            num_documento=9001,
            venta_neto_pedido=Decimal("1000.00"),
            venta_iva_pedido=Decimal("190.00"),
            venta_total_pedido=Decimal("1190.00"),
            ganancia_total=Decimal("300.00"),
            ganancia_porcentaje=Decimal("30.00"),
        )

    def test_dashboard_financiero_calcula_ppm_al_uno_por_ciento(self):
        fecha = timezone.localdate().isoformat()
        resp = self.client.get(
            reverse("dashboard_financiero_simple"),
            data={"fecha_desde": fecha, "fecha_hasta": fecha},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["ppm_periodo"], Decimal("10.00"))
        self.assertEqual(resp.context["ppm_total"]["total"], Decimal("10.00"))
        self.assertEqual(resp.context["total_general_total"]["neto"], Decimal("990.00"))
        self.assertEqual(resp.context["total_general_total"]["iva"], Decimal("190.00"))
        self.assertEqual(resp.context["total_general_total"]["total"], Decimal("1180.00"))
        self.assertContains(resp, "PPM (1%)")
        self.assertContains(resp, "PPM (1% s/ ventas netas)")

    def test_dashboard_financiero_redondea_ppm_como_sii_al_peso_entero(self):
        self.venta.venta_neto_pedido = Decimal("1050.00")
        self.venta.venta_iva_pedido = Decimal("199.50")
        self.venta.venta_total_pedido = Decimal("1249.50")
        self.venta.save(
            update_fields=["venta_neto_pedido", "venta_iva_pedido", "venta_total_pedido"]
        )

        fecha = timezone.localdate().isoformat()
        resp = self.client.get(
            reverse("dashboard_financiero_simple"),
            data={"fecha_desde": fecha, "fecha_hasta": fecha},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["ppm_periodo"], Decimal("11.00"))
        self.assertEqual(resp.context["ppm_total"]["total"], Decimal("11.00"))
        self.assertEqual(resp.context["total_general_total"]["neto"], Decimal("1039.00"))
        self.assertEqual(resp.context["total_general_total"]["total"], Decimal("1238.50"))


class EstrategiaPreciosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("estrategia_precios", password="test123")
        self.client.force_login(self.user)
        self.hoy = timezone.localdate()

        self.categoria = Categoria.objects.create(categoria="Bebidas")
        self.subcategoria = Subcategoria.objects.create(
            categoria=self.categoria,
            subcategoria="Jugos",
        )
        self.producto = Producto.objects.create(
            categoria_producto=self.categoria,
            subcategoria_producto=self.subcategoria,
            codigo_producto_interno="P-001",
            nombre_producto="Jugo Mango",
            qty_terciario=2,
            qty_secundario=6,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        self.proveedor = Proveedor.objects.create(
            nombre_proveedor="Proveedor Estrategia",
            rut_proveedor="76111111-1",
            direccion_proveedor="Dir 1",
            direccion_bodega_proveedor="Dir Bodega 1",
            empresa_activa=True,
            banco_proveedor="Banco 1",
            cta_proveedor="Corriente",
            num_cuenta_proveedor="123456",
        )
        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente Estrategia",
            rut_cliente="77111111-1",
            direccion_cliente="Dir Cliente",
            direccion_bodega_cliente="Dir Cliente Bodega",
            cliente_activo=True,
            telefono_cliente="+56911111111",
            correo_cliente="cliente@estrategia.local",
            categoria="PYME",
        )

        recepcion_1 = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=self.hoy,
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=5001,
            total_neto_recepcion=Decimal("600.00"),
            iva_recepcion=Decimal("114.00"),
            total_recepcion=Decimal("714.00"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )
        recepcion_2 = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=self.hoy,
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=5002,
            total_neto_recepcion=Decimal("150.00"),
            iva_recepcion=Decimal("28.50"),
            total_recepcion=Decimal("178.50"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="SECUNDARIO",
            precio_unitario=Decimal("600.00"),
            recepcion=recepcion_1,
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=self.producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("150.00"),
            recepcion=recepcion_2,
        )

        pedido_1 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=self.hoy,
            estado_pedido="Finalizado",
        )
        pedido_2 = Pedido.objects.create(
            nombre_cliente=self.cliente,
            fecha_pedido=self.hoy,
            estado_pedido="Finalizado",
        )
        venta_1 = Venta.objects.create(
            pedidoid=pedido_1,
            fecha_venta=self.hoy,
            documento_pedido="Factura",
            num_documento=7001,
            venta_neto_pedido=Decimal("1000.00"),
            venta_iva_pedido=Decimal("190.00"),
            venta_total_pedido=Decimal("1190.00"),
            ganancia_total=Decimal("400.00"),
            ganancia_porcentaje=Decimal("40.00"),
        )
        venta_2 = Venta.objects.create(
            pedidoid=pedido_2,
            fecha_venta=self.hoy,
            documento_pedido="Factura",
            num_documento=7002,
            venta_neto_pedido=Decimal("1200.00"),
            venta_iva_pedido=Decimal("228.00"),
            venta_total_pedido=Decimal("1428.00"),
            ganancia_total=Decimal("450.00"),
            ganancia_porcentaje=Decimal("37.50"),
        )
        UtilidadProducto.objects.create(
            venta=venta_1,
            producto=self.producto,
            empaque="PRIMARIO",
            cantidad=10,
            precio_compra_unitario=Decimal("100.00"),
            precio_venta_unitario=Decimal("200.00"),
            utilidad=Decimal("100.00"),
            utilidad_porcentaje=Decimal("100.00"),
            fecha=timezone.now(),
        )
        UtilidadProducto.objects.create(
            venta=venta_2,
            producto=self.producto,
            empaque="PRIMARIO",
            cantidad=8,
            precio_compra_unitario=Decimal("150.00"),
            precio_venta_unitario=Decimal("240.00"),
            utilidad=Decimal("90.00"),
            utilidad_porcentaje=Decimal("60.00"),
            fecha=timezone.now() + timedelta(seconds=1),
        )

    def test_dashboard_estrategia_renderiza_lectura_rapida(self):
        resp = self.client.get(
            reverse("dashboard_estrategia"),
            data={"month": self.hoy.month, "year": self.hoy.year},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Informe Estrategico")
        self.assertContains(resp, "Lectura Rapida")
        self.assertContains(resp, "Cliente Estrategia")
        self.assertContains(resp, reverse("dashboard_estrategia_precios"))

    def test_dashboard_estrategia_precios_muestra_tabla_historica(self):
        resp = self.client.get(
            reverse("dashboard_estrategia_precios"),
            data={"range_months": 6},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estrategia de Precios")
        self.assertContains(resp, "P-001")
        self.assertContains(resp, reverse("detalle_precios_estrategia", args=[self.producto.id]))
        self.assertEqual(len(resp.context["pricing_rows"]), 1)
        row = resp.context["pricing_rows"][0]
        self.assertEqual(row["precio_minimo_compra"], Decimal("100.00"))
        self.assertEqual(row["precio_maximo_compra"], Decimal("150.00"))
        self.assertEqual(row["precio_minimo_venta"], Decimal("200.00"))
        self.assertEqual(row["precio_maximo_venta"], Decimal("240.00"))
        self.assertEqual(resp.context["productos_en_riesgo"], 0)

    def test_detalle_precios_estrategia_muestra_respaldo_del_periodo(self):
        resp = self.client.get(
            reverse("detalle_precios_estrategia", args=[self.producto.id]),
            data={"range_months": 6},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Detalle Historico de Precios")
        self.assertContains(resp, "Proveedor Estrategia")
        self.assertContains(resp, "Cliente Estrategia")
        self.assertContains(resp, "Factura #5001")
        self.assertContains(resp, "Factura #7001")
        self.assertEqual(len(resp.context["compras_detalle"]), 2)
        self.assertEqual(len(resp.context["ventas_detalle"]), 2)
        self.assertEqual(resp.context["compras_detalle"][0]["precio_unitario"], Decimal("150.00"))
        self.assertEqual(resp.context["compras_detalle"][1]["precio_unitario"], Decimal("100.00"))
        self.assertEqual(resp.context["ventas_detalle"][0]["precio_unitario"], Decimal("240.00"))
        self.assertEqual(resp.context["ventas_detalle"][1]["precio_unitario"], Decimal("200.00"))

    def test_dashboard_estrategia_precios_filtra_por_categoria_y_subcategoria(self):
        otra_categoria = Categoria.objects.create(categoria="Aseo")
        otra_subcategoria = Subcategoria.objects.create(categoria=otra_categoria, subcategoria="Limpieza")
        otro_producto = Producto.objects.create(
            categoria_producto=otra_categoria,
            subcategoria_producto=otra_subcategoria,
            codigo_producto_interno="P-002",
            nombre_producto="Detergente",
            qty_terciario=1,
            qty_secundario=1,
            qty_primario=1,
            qty_unidad=1,
            medida="und",
            qty_minima=1,
        )
        recepcion = Recepcion.objects.create(
            proveedor=self.proveedor,
            fecha_recepcion=self.hoy,
            estado_recepcion="Finalizado",
            documento_recepcion="Factura",
            num_documento_recepcion=5003,
            total_neto_recepcion=Decimal("90.00"),
            iva_recepcion=Decimal("17.10"),
            total_recepcion=Decimal("107.10"),
            incluir_iva=False,
            moneda_recepcion="CLP",
        )
        Stock.objects.create(
            tipo_movimiento="DISPONIBLE",
            producto=otro_producto,
            qty=1,
            empaque="PRIMARIO",
            precio_unitario=Decimal("90.00"),
            recepcion=recepcion,
        )

        resp = self.client.get(
            reverse("dashboard_estrategia_precios"),
            data={"range_months": 6, "categoria": self.categoria.id, "subcategoria": self.subcategoria.id},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Jugo Mango")
        self.assertNotContains(resp, "Detergente")
        self.assertEqual(len(resp.context["pricing_rows"]), 1)
