from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Observacion(models.Model):
    TIPO_CHOICES = [
        ('MEJORA', 'Mejora'),
        ('ERROR', 'Error'),
        ('PREGUNTA', 'Pregunta'),
    ]

    usuario     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    url         = models.URLField(max_length=500)
    observacion = models.TextField()
    tipo        = models.CharField(max_length=10, choices=TIPO_CHOICES)
    creado_en   = models.DateTimeField(auto_now_add=True)
    lista = models.BooleanField(default=False)

    def __str__(self):
        usuario = self.usuario.username if self.usuario else "anonimo"
        referencia = f"Obs #{self.pk}" if self.pk else "Obs"
        return f"{referencia} - [{self.tipo}] - {usuario} - {self.creado_en:%Y-%m-%d}"

class VersionRegistro(models.Model):
    """
    Registro histórico de versiones del sistema (SemVer).
    Se crea un registro cada vez que se resuelve una observación
    y se clasifica el cambio como PATCH / MENOR / MAYOR.
    """
    IMPACTO = (
        ('SIN_CAMBIO', 'Sin cambio de version'),
        ('PATCH', 'Corrección (Z)'),
        ('MENOR', 'Funcionalidad menor (Y)'),
        ('MAYOR', 'Cambio mayor (X)'),
    )

    # Versión resultante post-cambio
    version_mayor = models.PositiveIntegerField(default=0)
    version_menor = models.PositiveIntegerField(default=0)
    version_patch = models.PositiveIntegerField(default=1)

    impacto = models.CharField(max_length=10, choices=IMPACTO)
    resumen = models.CharField(max_length=200, help_text="Resumen corto del cambio")
    detalle = models.TextField(help_text="Descripción de la solución aplicada")

    observacion = models.OneToOneField(
        'Observacion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='version_registro',
        help_text="Observación que originó este cambio (opcional)."
    )
    creado_en = models.DateTimeField(default=timezone.now)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        referencia = f"Version #{self.pk}" if self.pk else "Version"
        origen = f" - Obs #{self.observacion_id}" if self.observacion_id else ""
        return f"{referencia} - v{self.version_mayor}.{self.version_menor}.{self.version_patch} - {self.get_impacto_display()}{origen}"

    @property
    def version_str(self) -> str:
        return f"{self.version_mayor}.{self.version_menor}.{self.version_patch}"
