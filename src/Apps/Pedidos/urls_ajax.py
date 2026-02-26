"""
URL_ajax configuration for the Pedidos app.

Este archivo define todas las rutas AJAX utilizadas para consultas dinámicas
desde los templates vía JavaScript, sin recargar la página completa.

Estas rutas permiten obtener datos relacionados con:
- Recepción de productos
- Productos y empaques
- Clientes y precios

Las vistas asignadas retornan respuestas tipo JSON para ser procesadas en el frontend.
"""

from django.urls import path
from . import views

urlpatterns = [
    # 🔁 AJAX relacionado a recepción de productos
    path('eliminar-recepcion/<int:producto_id>/', views.eliminar_recepcion_producto, name='ajax_eliminar_recepcion_producto'),
    path('empaques-producto/<int:producto_id>/', views.obtener_empaques_producto, name='ajax_obtener_empaques_producto'),
    path('resolver-codigo/', views.resolver_codigo_proveedor, name='ajax_resolver_codigo'),


    # 🔁 AJAX para productos
    path('precio_maximo/<int:producto_id>/', views.obtener_precio_maximo, name='ajax_precio_maximo'),
    path('subcategorias/', views.obtener_subcategorias, name='ajax_obtener_subcategorias'),

    # 🔁 AJAX para clientes
    path('precio-base-compra/<int:producto_id>/', views.obtener_precio_base_compra, name='ajax_precio_base_compra'),

    # 🔁 Compatibilidad legacy (prefijo duplicado /ajax/ajax/*)
    path("ajax/empaques-producto/<int:producto_id>/", views.ajax_empaques_producto, name="ajax_empaques_producto_legacy"),
    path("ajax/precio-base-compra/<int:producto_id>/", views.ajax_precio_base_compra, name="ajax_precio_base_compra_legacy"),

    # 🔁 AJAX para proveedores (uso dinámico de tabla)
    path('proveedores/', views.lista_proveedores, name='ajax_lista_proveedores'),
]
