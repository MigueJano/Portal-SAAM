from django.conf import settings
from django.db import models


class ClonacionBaseDatos(models.Model):
    fecha_clonacion = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clonaciones_bd",
    )
    motor_base = models.CharField(max_length=100)
    origen_path = models.CharField(max_length=500)
    destino_path = models.CharField(max_length=500)
    snapshot_path = models.CharField(max_length=500, blank=True, default="")
    base_activa_actualizada_at = models.DateTimeField(null=True, blank=True)
    base_activa_size_bytes = models.BigIntegerField(default=0)
    destino_size_bytes = models.BigIntegerField(default=0)

    class Meta:
        ordering = ("-fecha_clonacion",)
        verbose_name = "Clonación de Base de Datos"
        verbose_name_plural = "Clonaciones de Base de Datos"

    def __str__(self):
        return f"Clonación BD {self.fecha_clonacion:%Y-%m-%d %H:%M} -> {self.destino_path}"
