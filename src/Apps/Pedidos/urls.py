"""
URL configuration for the Pedidos app.

Este archivo define todas las rutas internas de la aplicacion de gestion de pedidos,
incluyendo proveedores, productos, recepcion, clientes, ventas, cotizaciones, etc.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views


def _private(view):
    return login_required(view, login_url=settings.LOGIN_URL)


urlpatterns = [
    # Autenticacion y navegacion inicial
    path("inicio/", _private(views.home), name="home"),
    path("index/", _private(views.home), name="home"),

    # Proveedores
    path("proveedores/", _private(views.lista_proveedores), name="lista_proveedores"),
    path("proveedor/crear", _private(views.crear_proveedor), name="crear_proveedor"),
    path("proveedores/eliminar/<int:id>", _private(views.eliminar_proveedor), name="eliminar_proveedor"),
    path("proveedores/editar/<int:id>", _private(views.editar_proveedor), name="editar_proveedor"),

    # Contactos
    path("contacto/", _private(views.lista_contacto), name="lista_contacto"),
    path("contacto/crear", _private(views.crear_contacto), name="crear_contacto"),
    path("contacto/asociar/<int:proveedor_id>/", _private(views.asociar_contacto), name="asociar_contacto"),
    path("contacto/eliminar/<int:id>", _private(views.eliminar_contacto), name="eliminar_contacto"),
    path("contacto/editar/<int:id>", _private(views.editar_contacto), name="editar_contacto"),

    # Recepcion de productos
    path("recepcion/", _private(views.lista_recepciones), name="lista_recepcion"),
    path("recepcion/crear", _private(views.crear_recepcion), name="crear_recepcion"),
    path("recepcion/eliminar/<int:id>/", _private(views.eliminar_recepcion), name="eliminar_recepcion"),
    path(
        "recepcion/eliminar-producto/<int:producto_id>/",
        _private(views.eliminar_recepcion_producto),
        name="eliminar_recepcion_producto",
    ),
    path("recepcion/editar/<int:id>", _private(views.editar_recepcion), name="editar_recepcion"),
    path(
        "recepcion/<int:recepcion_id>/productos/crear/",
        _private(views.crear_recepcion_productos),
        name="crear_recepcion_productos",
    ),
    path(
        "recepcion/<int:documentoid>/productos/historico/",
        _private(views.recepcion_productos_historico),
        name="recepcion_productos_historico",
    ),
    path("recepcion/historico", _private(views.lista_recepcion_historico), name="lista_recepcion_historico"),
    path("recepcion/finalizar/<int:id>/", _private(views.finalizar_recepcion), name="finalizar_recepcion"),

    # Productos
    path("productos/", _private(views.lista_productos), name="lista_productos"),
    path("productos/stock", _private(views.stock_productos), name="stock_productos"),
    path("productos/crear/", _private(views.crear_producto), name="crear_producto"),
    path("productos/crear-pack/", _private(views.crear_pack), name="crear_pack"),
    path("productos/editar/<int:id>/", _private(views.editar_producto), name="editar_producto"),
    path("productos/editar-pack/<int:id>/", _private(views.editar_pack), name="editar_pack"),
    path("productos/eliminar/<int:id>/", _private(views.eliminar_producto), name="eliminar_producto"),
    path("productos/lista-precios/", _private(views.lista_precios), name="lista_precios"),

    # Categorias y empaques
    path("categorias/", _private(views.categorias_y_subcategorias), name="categorias_y_subcategorias"),
    path("subcategorias/editar/<int:id>/", _private(views.editar_subcategoria), name="editar_subcategoria"),
    path("subcategorias/eliminar/<int:id>/", _private(views.eliminar_subcategoria), name="eliminar_subcategoria"),
    path("empaques/", _private(views.categorias_empaque), name="categorias_empaque"),

    # Clientes
    path("clientes/", _private(views.lista_clientes), name="lista_clientes"),
    path("clientes/historico", _private(views.lista_clientes_historicos), name="lista_clientes_historico"),
    path("clientes/nuevo/", _private(views.crear_cliente), name="crear_cliente"),
    path("clientes/editar/<int:cliente_id>/", _private(views.editar_cliente), name="editar_cliente"),
    path("clientes/<int:cliente_id>/asignar-precios/", _private(views.asignar_precios), name="asignar_precios"),
    path("eliminar-precio/<int:precio_id>/", _private(views.eliminar_precio), name="eliminar_precio"),
    path("calculadora-precios/", _private(views.calculadora_precios), name="calculadora_precios"),
    path(
        "clientes/<int:cliente_id>/bulk-25/<int:categoria_id>/",
        _private(views.bulk_25_por_categoria),
        name="bulk_25_por_categoria",
    ),

    # Lista de Precios
    path("listas-precios/", _private(views.lista_listaprecios), name="lista_listaprecios"),
    path("listas-precios/crear/", _private(views.crear_listaprecios), name="crear_listaprecios"),
    path(
        "listas-precios/<int:listaprecios_id>/editar/",
        _private(views.editar_listaprecios),
        name="editar_listaprecios",
    ),
    path(
        "listas-precios/<int:listaprecios_id>/asignar/",
        _private(views.asignar_precios_listaprecios),
        name="asignar_precios_listaprecios",
    ),
    path(
        "listas-precios/<int:listaprecios_id>/sincronizar/",
        _private(views.sincronizar_clientes_listaprecios),
        name="sincronizar_clientes_listaprecios",
    ),
    path(
        "listas-precios/item/<int:item_id>/eliminar/",
        _private(views.eliminar_precio_listaprecios),
        name="eliminar_precio_listaprecios",
    ),

    # Pedidos
    path("pedidos/", _private(views.pedidos_en_proceso), name="lista_pedidos"),
    path("pedido/crear/", _private(views.crear_pedido), name="crear_pedido"),
    path("pedido/<int:pedido_id>/productos/", _private(views.agregar_productos_pedido), name="agregar_productos_pedido"),
    path("pedido/<int:pedido_id>/detalle/", _private(views.detalle_pedido), name="detalle_pedido"),
    path("pedidos/eliminar/<int:id>", _private(views.eliminar_pedido), name="eliminar_pedido"),
    path("pedido/<int:pedido_id>/pdf/", _private(views.exportar_pdf_pedido), name="generar_pdf_pedido"),
    path("pedido/<int:pedido_id>/editar/", _private(views.editar_pedido), name="editar_pedido"),
    path(
        "pedido/<int:pedido_id>/producto/<int:producto_id>/eliminar/",
        _private(views.eliminar_producto_pedido),
        name="eliminar_producto_pedido",
    ),
    path(
        "pedido/<int:pedido_id>/linea/<int:linea_id>/eliminar/",
        _private(views.eliminar_linea_pedido),
        name="eliminar_linea_pedido",
    ),
    path("pedidos/pedido/<int:pedido_id>/finalizar/", _private(views.finalizar_pedido), name="finalizar_pedido"),

    # Cotizaciones
    path("cotizacion/", _private(views.lista_cotizaciones), name="lista_cotizaciones"),
    path("cotizacion/crear/", _private(views.seleccionar_cliente_cotizacion), name="crear_cotizacion"),
    path(
        "cotizacion/seleccionar/<int:cliente_id>/",
        _private(views.seleccionar_productos_cotizacion),
        name="seleccionar_productos_cotizacion",
    ),
    path("cotizacion/vista-previa/", _private(views.vista_previa_cotizacion), name="vista_previa_cotizacion"),
    path("cotizacion/descargar/", _private(views.descargar_cotizacion_pdf), name="descargar_cotizacion_pdf"),

    # Ventas
    path("pedido/<int:pedido_id>/finalizar-venta/", _private(views.finalizar_venta), name="finalizar_venta"),
    path("ventas/", _private(views.lista_ventas), name="lista_ventas"),
    path("ventas/<int:venta_id>/detalle/", _private(views.detalle_venta), name="detalle_venta"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
