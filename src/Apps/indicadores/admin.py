from django.contrib import admin

from .models import RevisionCambioPrecioCompra


@admin.register(RevisionCambioPrecioCompra)
class RevisionCambioPrecioCompraAdmin(admin.ModelAdmin):
    list_display = ("stock", "estado", "revisado_por", "revisado_en")
    list_filter = ("estado", "revisado_en")
    search_fields = ("stock__producto__nombre_producto", "stock__recepcion__num_documento_recepcion", "comentario")
    autocomplete_fields = ("stock", "revisado_por")
    readonly_fields = ("revisado_en",)
