from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Apps.Pedidos.models import Pedido, PedidoEstadoEvento, Proveedor, Recepcion, Cliente

from .models import AccionOperacional, CategoriaGasto, GastoRecepcion, RegistroTiempo
from Apps.indicadores.services.reportes import informe_resultados


class CostosOperacionalesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("operador", password="clave")
        self.client.force_login(self.user)
        self.proveedor = Proveedor.objects.create(
            rut_proveedor="1-9", nombre_proveedor="Proveedor", direccion_proveedor="Dir",
            direccion_bodega_proveedor="Bodega", banco_proveedor="Banco",
            cta_proveedor="Corriente", num_cuenta_proveedor="1",
        )
        self.cliente = Cliente.objects.create(
            nombre_cliente="Cliente", rut_cliente="2-7", direccion_cliente="Dir",
            direccion_bodega_cliente="Bodega", telefono_cliente="1", correo_cliente="c@example.com",
            categoria="PYME",
        )
        self.pedido = Pedido.objects.create(nombre_cliente=self.cliente, fecha_pedido=timezone.localdate(), estado_pedido="Pendiente")
        self.recepcion = Recepcion.objects.create(
            proveedor=self.proveedor, fecha_recepcion=timezone.localdate(), estado_recepcion="Pendiente",
            documento_recepcion="Factura", num_documento_recepcion=1, moneda_recepcion="CLP",
        )
        self.categoria = CategoriaGasto.objects.create(nombre="Despacho")
        self.accion, _ = AccionOperacional.objects.update_or_create(
            nombre="Embalaje", defaults={"minutos_estandar": 15, "valor_hora": Decimal("6000")}
        )

    def test_gasto_externo_se_suma_a_la_misma_recepcion(self):
        response = self.client.post(reverse("costos:agregar_gasto_recepcion", args=[self.recepcion.id]), {
            "categoria": self.categoria.id, "descripcion": "Despacho factura", "monto_neto": "10000",
            "pedido": self.pedido.id, "refacturable": "on",
        })
        self.assertRedirects(response, reverse("crear_recepcion_productos", args=[self.recepcion.id]))
        self.recepcion.refresh_from_db()
        self.assertEqual(self.recepcion.total_neto_recepcion, Decimal("10000.00"))
        self.assertEqual(self.recepcion.total_recepcion, Decimal("11900.00"))
        self.assertEqual(GastoRecepcion.objects.count(), 1)

    def test_cronometro_conserva_tarifa_y_calcula_costo(self):
        self.client.post(reverse("costos:iniciar_tiempo"), {"accion": self.accion.id, "pedido": self.pedido.id})
        registro = RegistroTiempo.objects.get()
        registro.iniciado_en = timezone.now() - timedelta(minutes=30)
        registro.save(update_fields=("iniciado_en",))
        self.client.post(reverse("costos:cambiar_tiempo", args=[registro.id, "finalizar"]))
        registro.refresh_from_db()
        self.assertEqual(registro.estado, RegistroTiempo.FINALIZADO)
        self.assertGreaterEqual(registro.minutos_reales, 30)
        self.assertGreaterEqual(registro.costo, Decimal("3000"))

    def test_resultado_operacional_incluye_gasto_y_tiempo(self):
        GastoRecepcion.objects.create(
            recepcion=self.recepcion, categoria=self.categoria,
            descripcion="Servicio", monto_neto=Decimal("10000"), creado_por=self.user,
        )
        RegistroTiempo.objects.create(
            accion=self.accion, usuario=self.user, pedido=self.pedido,
            estado=RegistroTiempo.FINALIZADO, iniciado_en=timezone.now(), finalizado_en=timezone.now(),
            minutos_estandar=15, minutos_reales=30, valor_hora=Decimal("6000"), costo=Decimal("3000"),
        )
        informe = informe_resultados(timezone.localdate(), timezone.localdate())
        self.assertEqual(informe["gastos_externos"], Decimal("10000.00"))
        self.assertEqual(informe["costos_personal"], Decimal("3000.00"))
        self.assertEqual(informe["resultado_operacional"], Decimal("-13000.00"))

    def test_resultados_usa_tiempo_estandar_y_separa_bencina(self):
        self.accion.base_calculo = AccionOperacional.DESPACHADO
        self.accion.tipo_costo = AccionOperacional.TIEMPO
        self.accion.save(update_fields=("base_calculo", "tipo_costo"))
        bencina, _ = AccionOperacional.objects.update_or_create(
            nombre="Bencina",
            defaults={
                "tipo_costo": AccionOperacional.GASTO_FIJO,
                "base_calculo": AccionOperacional.ENTREGADO,
                "minutos_estandar": 0,
                "valor_hora": Decimal("0"),
                "costo_fijo_evento": Decimal("1000"),
                "activa": True,
            },
        )
        PedidoEstadoEvento.objects.create(
            pedido=self.pedido, estado="Despachado", ocurrido_en=timezone.now(), usuario=self.user,
        )
        PedidoEstadoEvento.objects.create(
            pedido=self.pedido, estado="Entregado", ocurrido_en=timezone.now(), usuario=self.user,
        )

        informe = informe_resultados(timezone.localdate(), timezone.localdate())

        self.assertEqual(informe["costos_personal_real"], Decimal("0.00"))
        self.assertEqual(informe["costos_personal_estimado"], Decimal("1500.00"))
        self.assertEqual(informe["gasto_bencina"], Decimal("1000.00"))
        self.assertEqual(informe["gastos_operacionales_hitos"], Decimal("1000.00"))
        self.assertEqual(informe["resultado_operacional"], Decimal("-2500.00"))
        self.assertEqual(bencina.get_tipo_costo_display(), "Gasto fijo por hito")

        response = self.client.get(
            reverse("dashboard_financiero_simple"),
            data={
                "informe": "resultados",
                "fecha_desde": timezone.localdate().isoformat(),
                "fecha_hasta": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bencina y costos fijos")
        self.assertContains(response, "Gasto fijo por hito")
        self.assertContains(response, "Detalle de costos operacionales por hitos")

    def test_panel_y_pedido_tiempos_renderizan(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("costos:panel")).status_code, 200)
        self.assertEqual(self.client.get(reverse("costos:pedido_tiempos", args=[self.pedido.id])).status_code, 200)

    def test_panel_usa_filtro_de_fechas_y_rangos_rapidos(self):
        response = self.client.get(
            reverse("costos:panel"),
            {"fecha_desde": "2026-10-01", "fecha_hasta": "2026-10-31"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["desde"].isoformat(), "2026-10-01")
        self.assertEqual(response.context["hasta"].isoformat(), "2026-10-31")
        self.assertContains(response, 'name="fecha_desde"')
        self.assertContains(response, 'value="2026-10-01"')
        self.assertContains(response, 'name="fecha_hasta"')
        self.assertContains(response, 'value="2026-10-31"')
        self.assertContains(response, 'id="preset-range"')
        self.assertContains(response, "applyPreset()")

    def test_costos_pedido_son_calculados_por_hitos_sin_ingreso_manual(self):
        self.accion.base_calculo = AccionOperacional.DESPACHADO
        self.accion.tipo_costo = AccionOperacional.TIEMPO
        self.accion.save(update_fields=("base_calculo", "tipo_costo"))
        PedidoEstadoEvento.objects.create(
            pedido=self.pedido,
            estado="Despachado",
            ocurrido_en=timezone.now(),
            usuario=self.user,
        )

        response = self.client.get(reverse("costos:pedido_tiempos", args=[self.pedido.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["costos_pedido"]["total"], Decimal("1500.00"))
        self.assertContains(response, "Costos calculados del pedido")
        self.assertContains(response, "Ganancia real")
        self.assertContains(response, 'class="collapse mt-3"')
        self.assertContains(response, "Embalaje")
        self.assertNotContains(response, reverse("costos:iniciar_tiempo"))
        self.assertNotContains(response, "Iniciar cron")

        detalle = self.client.get(reverse("detalle_pedido", args=[self.pedido.id]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, "Costos:")
        self.assertContains(detalle, "Ganancia real:")
        self.assertContains(detalle, "Ver detalle de costos")

    def test_recepcion_no_muestra_cronometro_y_se_calcula_por_hito(self):
        response = self.client.get(reverse("crear_recepcion_productos", args=[self.recepcion.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Tiempo de trabajo")
        self.assertNotContains(response, reverse("costos:iniciar_tiempo"))

        accion, _ = AccionOperacional.objects.update_or_create(
            nombre="Recepcion de mercaderia",
            defaults={
                "tipo_costo": AccionOperacional.TIEMPO,
                "base_calculo": AccionOperacional.RECEPCION,
                "minutos_estandar": 20,
                "valor_hora": Decimal("6000"),
                "activa": True,
            },
        )
        self.recepcion.estado_recepcion = "Finalizado"
        self.recepcion.save(update_fields=("estado_recepcion",))

        informe = informe_resultados(timezone.localdate(), timezone.localdate())

        fila = next(f for f in informe["detalle_costos_operacionales"] if f["accion"] == accion)
        self.assertEqual(fila["cantidad"], 1)
        self.assertEqual(fila["minutos_estimados"], 20)
        self.assertEqual(fila["costo_estimado"], Decimal("2000.00"))
        self.assertEqual(informe["costos_personal"], Decimal("2000.00"))

    def test_panel_agrupa_persona_y_actividad_en_una_fila(self):
        for minutos in (10, 20):
            RegistroTiempo.objects.create(
                accion=self.accion, usuario=self.user, pedido=self.pedido,
                estado=RegistroTiempo.FINALIZADO, iniciado_en=timezone.now(), finalizado_en=timezone.now(),
                minutos_estandar=15, minutos_reales=minutos, valor_hora=Decimal("6000"), costo=Decimal(minutos * 100),
            )
        hoy = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("costos:panel"),
            {"fecha_desde": hoy, "fecha_hasta": hoy},
        )
        filas = response.context["por_persona_actividad"]
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["registros"], 2)
        self.assertEqual(filas[0]["minutos"], 30)
        self.assertContains(response, 'name="fecha_desde"')
        self.assertContains(response, 'name="fecha_hasta"')
        self.assertContains(response, 'id="preset-range"')
        self.assertContains(response, "Rango rápido")
        self.assertEqual(response.context["desde"], timezone.localdate())
        self.assertEqual(response.context["hasta"], timezone.localdate())

    def test_panel_calcula_carga_mensual_desde_hitos_de_pedidos(self):
        self.accion.base_calculo = AccionOperacional.DESPACHADO
        self.accion.costo_fijo_evento = Decimal("500")
        self.accion.save(update_fields=("base_calculo", "costo_fijo_evento"))
        PedidoEstadoEvento.objects.create(
            pedido=self.pedido,
            estado="Despachado",
            ocurrido_en=timezone.now(),
            usuario=self.user,
        )

        hoy = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("costos:panel"),
            {"fecha_desde": hoy, "fecha_hasta": hoy},
        )

        embalaje = next(f for f in response.context["carga_estandar"] if f["accion"] == self.accion)
        self.assertEqual(embalaje["cantidad"], 1)
        self.assertEqual(embalaje["minutos"], 15)
        self.assertEqual(embalaje["costo_tiempo"], Decimal("1500.00"))
        self.assertEqual(embalaje["total"], Decimal("2000.00"))

    def test_configuracion_muestra_dos_secciones_en_cards_por_fila(self):
        self.user.is_staff = True
        self.user.save(update_fields=("is_staff",))
        response = self.client.get(reverse("costos:configuracion") + f"?accion_id={self.accion.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="card shadow-sm"', count=2)
