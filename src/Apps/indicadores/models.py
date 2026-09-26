from django.db import models


class RevisionCambioPrecioCompra(models.Model):
    ESTADO_OK = "OK"
    ESTADO_REVISAR = "REVISAR"
    ESTADO_CHOICES = (
        (ESTADO_OK, "OK"),
        (ESTADO_REVISAR, "Revisar"),
    )

    stock = models.OneToOneField(
        "Pedidos.Stock",
        on_delete=models.CASCADE,
        related_name="revision_cambio_precio_compra",
    )
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=ESTADO_OK)
    comentario = models.CharField(max_length=255, blank=True, default="")
    revisado_por = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisiones_cambios_precio_compra",
    )
    revisado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-revisado_en", "-id")
        verbose_name = "Revision de cambio de precio de compra"
        verbose_name_plural = "Revisiones de cambios de precio de compra"

    def __str__(self):
        return f"Stock #{self.stock_id} - {self.estado}"
