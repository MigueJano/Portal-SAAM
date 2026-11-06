from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


DOS_DEC = Decimal("0.01")


class CategoriaGasto(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class GastoRecepcion(models.Model):
    """Cargo externo incluido en la misma factura de una recepcion."""

    recepcion = models.ForeignKey(
        "Pedidos.Recepcion", on_delete=models.CASCADE, related_name="gastos_externos"
    )
    categoria = models.ForeignKey(CategoriaGasto, on_delete=models.PROTECT)
    descripcion = models.CharField(max_length=160)
    monto_neto = models.DecimalField(max_digits=12, decimal_places=2)
    pedido = models.ForeignKey(
        "Pedidos.Pedido", on_delete=models.SET_NULL, null=True, blank=True, related_name="gastos_externos"
    )
    refacturable = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("id",)

    def clean(self):
        if self.monto_neto is not None and self.monto_neto < 0:
            raise ValidationError({"monto_neto": "El monto neto no puede ser negativo."})
        if self.refacturable and not self.pedido_id:
            raise ValidationError({"pedido": "Un gasto refacturable debe asociarse a un pedido."})

    def __str__(self):
        return f"{self.descripcion} - ${self.monto_neto}"


class AccionOperacional(models.Model):
    TIEMPO = "TIEMPO"
    GASTO_FIJO = "GASTO_FIJO"
    TIPOS_COSTO = (
        (TIEMPO, "Tiempo de personal"),
        (GASTO_FIJO, "Gasto fijo por hito"),
    )
    MANUAL = "MANUAL"
    DESPACHADO = "DESPACHADO"
    ENTREGADO = "ENTREGADO"
    PAGADO = "PAGADO"
    RECEPCION = "RECEPCION"
    BASES_CALCULO = (
        (MANUAL, "Registro manual"),
        (DESPACHADO, "Pedido despachado"),
        (ENTREGADO, "Pedido entregado"),
        (PAGADO, "Pedido pagado"),
        (RECEPCION, "Recepción finalizada"),
    )

    nombre = models.CharField(max_length=80, unique=True)
    tipo_costo = models.CharField(max_length=10, choices=TIPOS_COSTO, default=TIEMPO)
    minutos_estandar = models.PositiveIntegerField(default=0)
    valor_hora = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    costo_fijo_evento = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    base_calculo = models.CharField(max_length=12, choices=BASES_CALCULO, default=MANUAL)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class RegistroTiempo(models.Model):
    EN_CURSO = "EN_CURSO"
    PAUSADO = "PAUSADO"
    FINALIZADO = "FINALIZADO"
    ESTADOS = ((EN_CURSO, "En curso"), (PAUSADO, "Pausado"), (FINALIZADO, "Finalizado"))

    accion = models.ForeignKey(AccionOperacional, on_delete=models.PROTECT, related_name="registros")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tiempos_operacionales")
    pedido = models.ForeignKey("Pedidos.Pedido", on_delete=models.CASCADE, null=True, blank=True, related_name="tiempos")
    recepcion = models.ForeignKey("Pedidos.Recepcion", on_delete=models.CASCADE, null=True, blank=True, related_name="tiempos")
    estado = models.CharField(max_length=12, choices=ESTADOS, default=EN_CURSO)
    iniciado_en = models.DateTimeField(default=timezone.now)
    finalizado_en = models.DateTimeField(null=True, blank=True)
    pausa_iniciada_en = models.DateTimeField(null=True, blank=True)
    segundos_pausa = models.PositiveIntegerField(default=0)
    minutos_estandar = models.PositiveIntegerField(default=0)
    valor_hora = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minutos_reales = models.PositiveIntegerField(default=0)
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacion = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("-iniciado_en", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("usuario",),
                condition=Q(estado__in=("EN_CURSO", "PAUSADO")),
                name="un_cronometro_activo_por_usuario",
            )
        ]

    def clean(self):
        if not self.pedido_id and not self.recepcion_id:
            raise ValidationError("El tiempo debe asociarse a un pedido o una recepcion.")
        if self.pedido_id and self.recepcion_id:
            raise ValidationError("Seleccione solo un pedido o una recepcion.")

    def calcular_y_finalizar(self, ahora=None):
        ahora = ahora or timezone.now()
        pausa = self.segundos_pausa
        if self.estado == self.PAUSADO and self.pausa_iniciada_en:
            pausa += max(0, int((ahora - self.pausa_iniciada_en).total_seconds()))
        segundos = max(0, int((ahora - self.iniciado_en).total_seconds()) - pausa)
        self.minutos_reales = max(1, (segundos + 59) // 60)
        self.costo = (
            Decimal(self.minutos_reales) * Decimal(self.valor_hora or 0) / Decimal(60)
        ).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        self.segundos_pausa = pausa
        self.pausa_iniciada_en = None
        self.finalizado_en = ahora
        self.estado = self.FINALIZADO

    @property
    def referencia(self):
        return self.pedido or self.recepcion
