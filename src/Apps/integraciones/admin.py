from django.contrib import admin

from .models import (
    ConciliacionPago,
    CompraAgil,
    CorreoEnviado,
    DocumentoTributarioEntrante,
    FiltroCompraAgil,
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


@admin.register(CompraAgil)
class CompraAgilAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "fecha_cierre_primer_llamado",
        "monto",
        "organismo_comprador",
        "estado_gestion",
        "coincide_filtros",
    )
    list_filter = ("estado_gestion", "coincide_filtros", "estado_api", "region")
    search_fields = ("codigo", "nombre", "descripcion", "organismo_comprador")


@admin.register(FiltroCompraAgil)
class FiltroCompraAgilAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "lugar", "actualizado_en")
    list_filter = ("activo",)
