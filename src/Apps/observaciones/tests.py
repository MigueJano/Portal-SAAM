from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Observacion, VersionRegistro


class ResolverObservacionTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff_user = self.user_model.objects.create_user(
            username="staff",
            password="secret123",
            is_staff=True,
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
            version_mayor=1,
            version_menor=2,
            version_patch=3,
            impacto="PATCH",
            resumen="Base",
            detalle="Version actual previa.",
            creado_por=self.staff_user,
        )
        observacion = self._crear_observacion(tipo="MEJORA")

        response = self.client.post(
            reverse("resolver_observacion", args=[observacion.pk]),
            {
                "impacto": "SIN_CAMBIO",
                "resumen": "No requiere despliegue",
                "detalle": "La observacion corresponde a una mejora menor.",
            },
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
            version_mayor=2,
            version_menor=0,
            version_patch=0,
            impacto="MAYOR",
            resumen="Cambio estructural",
            detalle="Se reviso y documento la resolucion.",
            observacion=observacion,
            creado_por=self.staff_user,
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
            version_mayor=2,
            version_menor=1,
            version_patch=0,
            impacto="MENOR",
            resumen="Resolucion previa",
            detalle="Ya estaba cerrada.",
            observacion=observacion,
            creado_por=self.staff_user,
        )

        response = self.client.post(
            reverse("resolver_observacion", args=[observacion.pk]),
            {
                "impacto": "MAYOR",
                "resumen": "Intento de cambio",
                "detalle": "No deberia reemplazar la resolucion.",
            },
        )

        self.assertRedirects(response, reverse("resolver_observacion", args=[observacion.pk]))
        self.assertEqual(VersionRegistro.objects.filter(observacion=observacion).count(), 1)
        observacion.refresh_from_db()
        self.assertTrue(observacion.lista)
