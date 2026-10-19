from django.contrib import admin

from .models import (
    ConciliacionPago,
    CorreoEnviado,
    DocumentoTributarioEntrante,
    MovimientoBancario,
    SaldoBancario,
)


@admin.register(MovimientoBancario)
class MovimientoBancarioAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "monto", "descripcion", "estado")
    list_filter = ("tipo", "estado", "moneda")
    search_fields = ("descripcion", "referencia", "rut_contraparte", "identificador_externo")


admin.site.register(ConciliacionPago)
admin.site.register(DocumentoTributarioEntrante)
admin.site.register(CorreoEnviado)
admin.site.register(SaldoBancario)
