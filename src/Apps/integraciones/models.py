from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class MovimientoBancario(models.Model):
    TIPO_ABONO = "ABONO"
    TIPO_CARGO = "CARGO"
    TIPOS = ((TIPO_ABONO, "Abono"), (TIPO_CARGO, "Cargo"))

    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_CONCILIADO = "CONCILIADO"
    ESTADO_IGNORADO = "IGNORADO"
    ESTADOS = (
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_CONCILIADO, "Conciliado"),
        (ESTADO_IGNORADO, "Ignorado"),
    )

    proveedor_api = models.CharField(max_length=40, default="BANCO_CHILE")
    identificador_externo = models.CharField(max_length=160)
    cuenta_enmascarada = models.CharField(max_length=40, blank=True)
    fecha = models.DateField()
    descripcion = models.CharField(max_length=500, blank=True)
    referencia = models.CharField(max_length=160, blank=True)
    rut_contraparte = models.CharField(max_length=20, blank=True)
    nombre_contraparte = models.CharField(max_length=160, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    monto = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    moneda = models.CharField(max_length=4, default="CLP")
    estado = models.CharField(max_length=12, choices=ESTADOS, default=ESTADO_PENDIENTE)
    datos_origen = models.JSONField(default=dict, blank=True)
    importado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("proveedor_api", "identificador_externo"),
                name="integraciones_movimiento_externo_unico",
            )
        ]

    def __str__(self):
        return f"{self.fecha} {self.tipo} ${self.monto} - {self.descripcion}"


class SaldoBancario(models.Model):
    proveedor_api = models.CharField(max_length=40, default="BANCO_CHILE")
    cuenta_enmascarada = models.CharField(max_length=40)
    moneda = models.CharField(max_length=4, default="CLP")
    nombre_titular = models.CharField(max_length=160, blank=True)
    saldo_disponible = models.DecimalField(max_digits=16, decimal_places=2)
    saldo_contable = models.DecimalField(max_digits=16, decimal_places=2)
    total_cargos = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_abonos = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    saldo_inicio = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    saldo_final = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    periodo_desde = models.DateField(null=True, blank=True)
    periodo_hasta = models.DateField(null=True, blank=True)
    respuesta_hash = models.CharField(max_length=64, unique=True)
    datos_origen = models.JSONField(default=dict, blank=True)
    consultado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-consultado_en", "-id")
        verbose_name = "Saldo bancario"
        verbose_name_plural = "Saldos bancarios"

    def __str__(self):
        return f"{self.cuenta_enmascarada} - disponible ${self.saldo_disponible}"


class ConciliacionPago(models.Model):
    ESTADO_PROPUESTA = "PROPUESTA"
    ESTADO_CONFIRMADA = "CONFIRMADA"
    ESTADO_RECHAZADA = "RECHAZADA"
    ESTADOS = (
        (ESTADO_PROPUESTA, "Propuesta"),
        (ESTADO_CONFIRMADA, "Confirmada"),
        (ESTADO_RECHAZADA, "Rechazada"),
    )

    movimiento = models.ForeignKey(
        MovimientoBancario, on_delete=models.PROTECT, related_name="conciliaciones"
    )
    pedido = models.ForeignKey(
        "Pedidos.Pedido", on_delete=models.PROTECT, related_name="conciliaciones_pago"
    )
    monto_aplicado = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    estado = models.CharField(max_length=12, choices=ESTADOS, default=ESTADO_PROPUESTA)
    criterio = models.CharField(max_length=255, blank=True)
    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    confirmado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-creado_en",)
        constraints = [
            models.UniqueConstraint(
                fields=("movimiento", "pedido"), name="integraciones_movimiento_pedido_unico"
            )
        ]


class DocumentoTributarioEntrante(models.Model):
    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_ASOCIADO = "ASOCIADO"
    ESTADO_DESCARTADO = "DESCARTADO"
    ESTADOS = (
        (ESTADO_PENDIENTE, "Pendiente de revisión"),
        (ESTADO_ASOCIADO, "Asociado"),
        (ESTADO_DESCARTADO, "Descartado"),
    )

    gmail_message_id = models.CharField(max_length=160)
    remitente = models.EmailField(max_length=254)
    asunto = models.CharField(max_length=500, blank=True)
    recibido_en = models.DateTimeField()
    nombre_archivo = models.CharField(max_length=255)
    archivo = models.FileField(upload_to="documentos_tributarios/%Y/%m/")
    sha256 = models.CharField(max_length=64, unique=True)
    tipo_documento = models.CharField(max_length=40, blank=True)
    folio = models.CharField(max_length=40, blank=True)
    rut_emisor = models.CharField(max_length=20, blank=True)
    monto_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default=ESTADO_PENDIENTE)
    recepcion = models.ForeignKey(
        "Pedidos.Recepcion", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documentos_tributarios",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-recibido_en", "-id")


class CorreoEnviado(models.Model):
    destinatario = models.EmailField(max_length=254)
    asunto = models.CharField(max_length=255)
    cuerpo = models.TextField()
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    enviado_en = models.DateTimeField(auto_now_add=True)
    exitoso = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-enviado_en",)

