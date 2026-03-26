from django.contrib import admin

from .models import ClonacionBaseDatos


@admin.register(ClonacionBaseDatos)
class ClonacionBaseDatosAdmin(admin.ModelAdmin):
    list_display = (
        "fecha_clonacion",
        "usuario",
        "motor_base",
        "base_activa_size_bytes",
        "destino_size_bytes",
    )
    list_filter = ("motor_base", "fecha_clonacion")
    search_fields = ("usuario__username", "origen_path", "destino_path", "snapshot_path")
