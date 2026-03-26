# Apps/indicadores/urls.py
from django.urls import path
from .views import (
    dashboard_estrategia,
    dashboard_financiero_simple,
    flujo_inventario_producto,
    dashboard_inventario,
    dashboard_operaciones,
    dashboard_ventas,
    exportar_inventario_propyme,
    exportar_libro_compras_propyme,
    exportar_libro_ventas_propyme,
    exportar_libros_propyme_zip,
    resumen_contable_propyme,
)

urlpatterns = [
    path('financiero-simple/', dashboard_financiero_simple, name='dashboard_financiero_simple'),
    path('ventas/', dashboard_ventas, name='dashboard_ventas'),
    path('inventario/', dashboard_inventario, name='dashboard_inventario'),
    path('inventario/flujo/<int:producto_id>/', flujo_inventario_producto, name='flujo_inventario_producto'),
    path('operaciones/', dashboard_operaciones, name='dashboard_operaciones'),
    path('estrategia/', dashboard_estrategia, name='dashboard_estrategia'),
    path('contabilidad/propyme/', resumen_contable_propyme, name='resumen_contable_propyme'),
    path('contabilidad/propyme/libro-ventas/', exportar_libro_ventas_propyme, name='exportar_libro_ventas_propyme'),
    path('contabilidad/propyme/libro-compras/', exportar_libro_compras_propyme, name='exportar_libro_compras_propyme'),
    path('contabilidad/propyme/inventario/', exportar_inventario_propyme, name='exportar_inventario_propyme'),
    path('contabilidad/propyme/paquete/', exportar_libros_propyme_zip, name='exportar_libros_propyme_zip'),
]
