"""
URL configuration for the Pedidos app.

Este archivo define todas las rutas internas de la aplicación de gestión de pedidos,
incluyendo proveedores, productos, recepción, clientes, ventas, cotizaciones, etc.
"""

from django.contrib.auth import views as auth_views
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views


urlpatterns = [
    # 🔐 Autenticación y navegación inicial
    path('inicio/', views.home, name='home'),
    path('index/', views.home, name='home'),

    # 📦 Proveedores
    path('proveedores/', views.lista_proveedores, name='lista_proveedores'),
    path('proveedor/crear', views.crear_proveedor, name='crear_proveedor'),
    path('proveedores/eliminar/<int:id>', views.eliminar_proveedor, name='eliminar_proveedor'),
    path('proveedores/editar/<int:id>', views.editar_proveedor, name='editar_proveedor'),

    # 👥 Contactos
    path('contacto/', views.lista_contacto, name='lista_contacto'),
    path('contacto/crear', views.crear_contacto, name='crear_contacto'),
    path('contacto/asociar/<int:proveedor_id>/', views.asociar_contacto, name='asociar_contacto'),
    path('contacto/eliminar/<int:id>', views.eliminar_contacto, name='eliminar_contacto'),
    path('contacto/editar/<int:id>', views.editar_contacto, name='editar_contacto'),

    # 📥 Recepción de productos
    path('recepcion/', views.lista_recepciones, name='lista_recepcion'),
    path('recepcion/crear', views.crear_recepcion, name='crear_recepcion'),
    path('recepcion/eliminar/<int:id>/', views.eliminar_recepcion, name='eliminar_recepcion'),
    path('recepcion/eliminar-producto/<int:producto_id>/', views.eliminar_recepcion_producto, name='eliminar_recepcion_producto'),
    path('recepcion/editar/<int:id>', views.editar_recepcion, name='editar_recepcion'),
    path('recepcion/<int:recepcion_id>/productos/crear/', views.crear_recepcion_productos, name='crear_recepcion_productos'),
    path('recepcion/<int:documentoid>/productos/historico/', views.recepcion_productos_historico, name='recepcion_productos_historico'),
    path('recepcion/historico', views.lista_recepcion_historico, name='lista_recepcion_historico'),
    path('recepcion/finalizar/<int:id>/', views.finalizar_recepcion, name='finalizar_recepcion'),

    # 📦 Productos
    path('productos/', views.lista_productos, name='lista_productos'),
    path('productos/stock', views.stock_productos, name='stock_productos'),
    path('productos/crear/', views.crear_producto, name='crear_producto'),
    path('productos/editar/<int:id>/', views.editar_producto, name='editar_producto'),
    path('productos/eliminar/<int:id>/', views.eliminar_producto, name='eliminar_producto'),
    path('productos/lista-precios/', views.lista_precios, name='lista_precios'),

    # 🗂️ Categorías y empaques
    path('categorias/', views.categorias_y_subcategorias, name='categorias_y_subcategorias'),
    path('subcategorias/editar/<int:id>/', views.editar_subcategoria, name='editar_subcategoria'),
    path('subcategorias/eliminar/<int:id>/', views.eliminar_subcategoria, name='eliminar_subcategoria'),
    path('empaques/', views.categorias_empaque, name='categorias_empaque'),

    # 👤 Clientes
    path('clientes/', views.lista_clientes, name='lista_clientes'),
    path('clientes/historico', views.lista_clientes_historicos, name='lista_clientes_historico'),
    path('clientes/nuevo/', views.crear_cliente, name='crear_cliente'),
    path('clientes/editar/<int:cliente_id>/', views.editar_cliente, name='editar_cliente'),
    path('clientes/<int:cliente_id>/asignar-precios/', views.asignar_precios, name='asignar_precios'),
    path('eliminar-precio/<int:precio_id>/', views.eliminar_precio, name='eliminar_precio'),
    path('calculadora-precios/', views.calculadora_precios, name='calculadora_precios'),
    path('clientes/<int:cliente_id>/bulk-25/<int:categoria_id>/', views.bulk_25_por_categoria, name='bulk_25_por_categoria'),

    # 🧾 Lista de Precios
    path("listas-precios/", views.lista_listaprecios, name="lista_listaprecios"),
    path("listas-precios/crear/", views.crear_listaprecios, name="crear_listaprecios"),
    path("listas-precios/<int:listaprecios_id>/editar/", views.editar_listaprecios, name="editar_listaprecios"),
    path("listas-precios/<int:listaprecios_id>/asignar/", views.asignar_precios_listaprecios, name="asignar_precios_listaprecios"),
    path("listas-precios/item/<int:item_id>/eliminar/", views.eliminar_precio_listaprecios, name="eliminar_precio_listaprecios"),


    # 🧾 Pedidos
    path('pedidos/', views.pedidos_en_proceso, name='lista_pedidos'),
    path('pedido/crear/', views.crear_pedido, name='crear_pedido'),
    path('pedido/<int:pedido_id>/productos/', views.agregar_productos_pedido, name='agregar_productos_pedido'),
    path('pedido/<int:pedido_id>/detalle/', views.detalle_pedido, name='detalle_pedido'),
    path('pedidos/eliminar/<int:id>', views.eliminar_pedido, name='eliminar_pedido'),
    path('pedido/<int:pedido_id>/pdf/', views.exportar_pdf_pedido, name='generar_pdf_pedido'),
    path('pedido/<int:pedido_id>/editar/', views.editar_pedido, name='editar_pedido'),
    path('pedido/<int:pedido_id>/producto/<int:producto_id>/eliminar/', views.eliminar_producto_pedido, name='eliminar_producto_pedido'),
    path('pedidos/pedido/<int:pedido_id>/finalizar/', views.finalizar_pedido, name='finalizar_pedido'),

    # 💼 Cotizaciones
    path('cotizacion/', views.lista_cotizaciones, name='lista_cotizaciones'),
    path('cotizacion/crear/', views.seleccionar_cliente_cotizacion, name='crear_cotizacion'),
    path('cotizacion/seleccionar/<int:cliente_id>/', views.seleccionar_productos_cotizacion, name='seleccionar_productos_cotizacion'),
    path('cotizacion/vista-previa/', views.vista_previa_cotizacion, name='vista_previa_cotizacion'),
    path('cotizacion/descargar/', views.descargar_cotizacion_pdf, name='descargar_cotizacion_pdf'),

    # 💳 Ventas
    path('pedido/<int:pedido_id>/finalizar-venta/', views.finalizar_venta, name='finalizar_venta'),
    path('ventas/', views.lista_ventas, name='lista_ventas'),
    path('ventas/<int:venta_id>/detalle/', views.detalle_venta, name='detalle_venta'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
