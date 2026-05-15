"""
URL_ajax configuration for the Pedidos app.

Este archivo define todas las rutas AJAX utilizadas para consultas dinamicas
desde los templates via JavaScript, sin recargar la pagina completa.
"""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views


def _private(view):
    return login_required(view, login_url=settings.LOGIN_URL)


urlpatterns = [
    # AJAX relacionado a recepcion de productos
    path(
        "eliminar-recepcion/<int:producto_id>/",
        _private(views.eliminar_recepcion_producto),
        name="ajax_eliminar_recepcion_producto",
    ),
    path(
        "empaques-producto/<int:producto_id>/",
        _private(views.obtener_empaques_producto),
        name="ajax_obtener_empaques_producto",
    ),
    path("resolver-codigo/", _private(views.resolver_codigo_proveedor), name="ajax_resolver_codigo"),

    # AJAX para productos
    path("precio_maximo/<int:producto_id>/", _private(views.obtener_precio_maximo), name="ajax_precio_maximo"),
    path("subcategorias/", _private(views.obtener_subcategorias), name="ajax_obtener_subcategorias"),

    # AJAX para clientes
    path(
        "precio-base-compra/<int:producto_id>/",
        _private(views.obtener_precio_base_compra),
        name="ajax_precio_base_compra",
    ),

    # Compatibilidad legacy (prefijo duplicado /ajax/ajax/*)
    path(
        "ajax/empaques-producto/<int:producto_id>/",
        _private(views.ajax_empaques_producto),
        name="ajax_empaques_producto_legacy",
    ),
    path(
        "ajax/precio-base-compra/<int:producto_id>/",
        _private(views.ajax_precio_base_compra),
        name="ajax_precio_base_compra_legacy",
    ),

    # AJAX para proveedores
    path("proveedores/", _private(views.lista_proveedores), name="ajax_lista_proveedores"),
]
