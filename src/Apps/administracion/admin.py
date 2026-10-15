from django.contrib import admin

from .models import ActaReunion


@admin.register(ActaReunion)
class ActaReunionAdmin(admin.ModelAdmin):
    list_display = ("fecha", "creado_por", "actualizado_en")
    search_fields = ("acta", "creado_por__username")
    date_hierarchy = "fecha"
