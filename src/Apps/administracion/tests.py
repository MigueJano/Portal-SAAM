from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ActaReunion


class ActasReunionTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user("usuario", password="clave-segura")
        self.client.force_login(self.usuario)

    def test_menu_muestra_administracion_y_sistema(self):
        self.usuario.is_staff = True
        self.usuario.save(update_fields=["is_staff"])
        response = self.client.get(reverse("lista_actas"))
        self.assertContains(response, "Administraci&oacute;n")
        self.assertContains(response, "Sistema")
        self.assertNotContains(response, "Administradores")

    def test_crear_acta_muestra_acta_anterior(self):
        anterior = ActaReunion.objects.create(
            fecha=date(2026, 10, 1), acta="<p>Acuerdo anterior</p>", creado_por=self.usuario
        )
        response = self.client.get(reverse("crear_acta") + "?fecha=2026-10-15")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["acta_anterior"], anterior)
        self.assertContains(response, "Acuerdo anterior")

    def test_guarda_formato_permitido_y_elimina_script(self):
        response = self.client.post(
            reverse("crear_acta"),
            {"fecha": "2026-10-15", "acta": '<p><strong>Tarea</strong><script>alert(1)</script></p>'},
        )
        self.assertEqual(response.status_code, 302)
        acta = ActaReunion.objects.get()
        self.assertIn("<strong>Tarea</strong>", acta.acta)
        self.assertNotIn("<script>", acta.acta)
        self.assertIn("alert(1)", acta.acta)

    def test_requiere_autenticacion(self):
        self.client.logout()
        response = self.client.get(reverse("lista_actas"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)

    def test_fecha_invalida_no_produce_error_del_servidor(self):
        response = self.client.post(
            reverse("crear_acta"), {"fecha": "fecha-invalida", "acta": "<p>Contenido</p>"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Introduzca una fecha válida")

    def test_post_invalido_no_reinyecta_html_peligroso(self):
        response = self.client.post(
            reverse("crear_acta"), {"fecha": "", "acta": '<img src=x onerror="alert(1)">Texto'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<img src=x onerror="alert(1)">', html=False)
        self.assertContains(response, ">Texto</div>", html=False)
