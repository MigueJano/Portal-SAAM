from django.conf import settings
from django.db import models


class ActaReunion(models.Model):
    fecha = models.DateField(verbose_name="Fecha de reunión")
    acta = models.TextField(verbose_name="Acta")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actas_reunion_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Acta de reunión"
        verbose_name_plural = "Actas de reuniones"

    def __str__(self):
        return f"Acta del {self.fecha:%d/%m/%Y}"
