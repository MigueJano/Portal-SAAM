from django.contrib import admin

from .models import AccionOperacional, CategoriaGasto, GastoRecepcion, RegistroTiempo

admin.site.register((CategoriaGasto, GastoRecepcion, AccionOperacional, RegistroTiempo))
