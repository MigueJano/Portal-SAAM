from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class IndicadoresViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("usuario_indicadores", password="test123")
        self.urls = [
            reverse("dashboard_financiero_simple"),
            reverse("dashboard_ventas"),
            reverse("dashboard_inventario"),
            reverse("dashboard_operaciones"),
            reverse("dashboard_estrategia"),
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

    def test_urls_contabilidad_resueltas_en_indicadores(self):
        self.assertTrue(reverse("resumen_contable_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libro_ventas_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libro_compras_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_inventario_propyme").startswith("/indicadores/"))
        self.assertTrue(reverse("exportar_libros_propyme_zip").startswith("/indicadores/"))
