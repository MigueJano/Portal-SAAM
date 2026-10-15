from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ActualizacionSistema, Observacion, VersionRegistro
from .services import GitStatus, SystemUpdateError


class ResolverObservacionTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff", password="secret123", is_staff=True
        )
        self.client.force_login(self.staff_user)

    def _crear_observacion(self, **kwargs):
        data = {
            "usuario": self.staff_user,
            "url": "http://testserver/pedidos/",
            "observacion": "Se detecto un comportamiento a revisar.",
            "tipo": "ERROR",
        }
        data.update(kwargs)
        return Observacion.objects.create(**data)

    def test_resolver_sin_cambio_mantiene_version_actual(self):
        VersionRegistro.objects.create(
            version_mayor=1, version_menor=2, version_patch=3, impacto="PATCH",
            resumen="Base", detalle="Version actual previa.", creado_por=self.staff_user,
        )
        observacion = self._crear_observacion(tipo="MEJORA")
        response = self.client.post(
            reverse("resolver_observacion", args=[observacion.pk]),
            {"impacto": "SIN_CAMBIO", "resumen": "No requiere despliegue", "detalle": "La observacion corresponde a una mejora menor."},
        )
        self.assertRedirects(response, reverse("lista_observaciones"))
        observacion.refresh_from_db()
        version = observacion.version_registro
        self.assertTrue(observacion.lista)
        self.assertEqual(version.impacto, "SIN_CAMBIO")
        self.assertEqual(version.version_str, "1.2.3")

    def test_observacion_lista_abre_detalle_en_modo_revision(self):
        observacion = self._crear_observacion(lista=True)
        VersionRegistro.objects.create(
            version_mayor=2, version_menor=0, version_patch=0, impacto="MAYOR",
            resumen="Cambio estructural", detalle="Se reviso y documento la resolucion.",
            observacion=observacion, creado_por=self.staff_user,
        )
        response = self.client.get(reverse("resolver_observacion", args=[observacion.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["modo_revision"])
        self.assertContains(response, "Revision de observacion")
        self.assertContains(response, "v2.0.0")
        self.assertNotContains(response, "Confirmar y marcar como lista")

    def test_observacion_lista_no_permita_post_de_edicion(self):
        observacion = self._crear_observacion(lista=True)
        VersionRegistro.objects.create(
            version_mayor=2, version_menor=1, version_patch=0, impacto="MENOR",
            resumen="Resolucion previa", detalle="Ya estaba cerrada.",
            observacion=observacion, creado_por=self.staff_user,
        )
        response = self.client.post(
            reverse("resolver_observacion", args=[observacion.pk]),
            {"impacto": "MAYOR", "resumen": "Intento de cambio", "detalle": "No deberia reemplazar la resolucion."},
        )
        self.assertRedirects(response, reverse("resolver_observacion", args=[observacion.pk]))
        self.assertEqual(VersionRegistro.objects.filter(observacion=observacion).count(), 1)
        observacion.refresh_from_db()
        self.assertTrue(observacion.lista)


class ActualizacionesSistemaTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="staff-update", password="secret123", is_staff=True)
        self.superuser = user_model.objects.create_superuser(
            username="admin-update", password="secret123", email="admin@example.com"
        )

    @patch("Apps.observaciones.views.git_status")
    def test_staff_puede_ver_estado_pero_no_instalar(self, status_mock):
        status_mock.return_value = GitStatus(
            available=True, branch="main", current_commit="abc123", remote_commit="def456", behind=1
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("actualizaciones_sistema"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Actualizaciones del sistema")
        self.assertContains(response, "Solo un superusuario")

    @patch("Apps.observaciones.views.git_status")
    def test_staff_no_puede_ejecutar_acciones(self, status_mock):
        status_mock.return_value = GitStatus(available=True, branch="main")
        self.client.force_login(self.staff)
        response = self.client.post(reverse("actualizaciones_sistema"), {"accion": "instalar"})
        self.assertRedirects(response, reverse("actualizaciones_sistema"))
        self.assertEqual(ActualizacionSistema.objects.count(), 0)

    @patch("Apps.observaciones.views.git_status")
    def test_error_de_fetch_no_se_reemplaza_por_estado_obsoleto(self, status_mock):
        status_mock.return_value = GitStatus(available=False, error="fetch sin permisos")
        self.client.force_login(self.superuser)

        response = self.client.post(reverse("actualizaciones_sistema"), {"accion": "buscar"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(status_mock.call_count, 1)
        self.assertContains(response, "fetch sin permisos")
        self.assertContains(response, "Git no disponible")

    @patch("Apps.observaciones.views.git_status")
    @patch("Apps.observaciones.views.apply_system_update")
    def test_superusuario_instala_y_registra_resultado(self, apply_mock, status_mock):
        status_mock.return_value = GitStatus(
            available=True, branch="main", current_commit="abc123", remote_commit="def456", behind=1
        )
        apply_mock.return_value = {
            "changed": True,
            "status": GitStatus(available=True, branch="main", current_commit="def456", remote_commit="def456"),
            "previous_commit": "abc123",
            "backup_path": "Respaldos/actualizaciones/SAAM.db",
            "log": "Actualizacion correcta",
        }
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("actualizaciones_sistema"), {"accion": "instalar"})
        self.assertEqual(response.status_code, 200)
        registro = ActualizacionSistema.objects.get()
        self.assertEqual(registro.estado, "EXITOSA")
        self.assertEqual(registro.commit_anterior, "abc123")
        self.assertEqual(registro.commit_nuevo, "def456")

    @patch("Apps.observaciones.views.git_status")
    @patch("Apps.observaciones.views.apply_system_update")
    def test_error_de_actualizacion_queda_registrado(self, apply_mock, status_mock):
        status_mock.return_value = GitStatus(available=True, branch="main", current_commit="abc123")
        apply_mock.side_effect = SystemUpdateError("fallo controlado")
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("actualizaciones_sistema"), {"accion": "instalar"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ActualizacionSistema.objects.get().estado, "FALLIDA")
        self.assertContains(response, "fallo controlado")
