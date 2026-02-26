from django.contrib import admin
from .models import Observacion, VersionRegistro

@admin.register(Observacion)
class ObservacionAdmin(admin.ModelAdmin):
    list_display = ('id','tipo','usuario','url','creado_en','lista')
    list_filter  = ('tipo','creado_en','lista')
    search_fields = ('observacion','url','usuario__username')

@admin.register(VersionRegistro)
class VersionRegistroAdmin(admin.ModelAdmin):
    list_display = ('version_mayor','version_menor','version_patch','impacto','resumen','creado_en','creado_por')
    list_filter  = ('impacto','creado_en')
    search_fields = ('resumen','detalle')
    readonly_fields = ()
