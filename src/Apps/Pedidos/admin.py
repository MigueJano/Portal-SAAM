# Apps/Pedidos/admin.py
"""
Admin - Registro de modelos en el panel administrativo de Django.
Actualizado para mostrar el ID y optimizar búsqueda/filtros.
"""

from django.contrib import admin
from django.utils.html import format_html
from decimal import Decimal

from .models import (
    Proveedor, Contacto, Recepcion, Producto, CodigoProveedor, Stock, ListaPrecios, Cliente,
    Pedido, Venta, Categoria, Subcategoria, Cotizacion, CategoriaEmpaque,
    EntregaPedido, ListaPreciosPredeterminada, ListaPreciosPredItem,
)

# ---------- Inlines ----------
class ContactoInline(admin.TabularInline):
    model = Contacto
    extra = 0
    fields = ('id', 'nombre_contacto', 'apellido_contacto', 'cargo_contacto', 'telefono_contacto', 'correo_contacto')
    readonly_fields = ('id',)
    show_change_link = True

class SubcategoriaInline(admin.TabularInline):
    model = Subcategoria
    extra = 0
    fields = ('id', 'subcategoria')
    readonly_fields = ('id',)
    show_change_link = True

class EntregaPedidoInline(admin.TabularInline):
    model = EntregaPedido
    extra = 0
    fields = ('id', 'nombre_receptor', 'rut_receptor', 'fecha_entrega', 'archivo_link', 'foto_link', 'creado')
    readonly_fields = ('id', 'archivo_link', 'foto_link', 'creado')
    show_change_link = True

    def archivo_link(self, obj):
        if obj.archivo_pdf:
            return format_html('<a href="{}" target="_blank">Ver PDF</a>', obj.archivo_pdf.url)
        return "—"
    archivo_link.short_description = "Archivo PDF"

    def foto_link(self, obj):
        if obj.foto:
            return format_html('<a href="{}" target="_blank">Ver Foto</a>', obj.foto.url)
        return "—"
    foto_link.short_description = "Foto"


# ---------- ModelAdmins ----------
@admin.register(CategoriaEmpaque)
class CategoriaEmpaqueAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'nivel')
    search_fields = ('nombre',)
    list_filter = ('nivel',)
    ordering = ('id',)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'categoria')
    search_fields = ('categoria',)
    ordering = ('id',)
    inlines = [SubcategoriaInline]


@admin.register(Subcategoria)
class SubcategoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'subcategoria', 'categoria')
    search_fields = ('subcategoria', 'categoria__categoria')
    list_filter = ('categoria',)
    ordering = ('id',)
    autocomplete_fields = ('categoria',)


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_proveedor', 'rut_proveedor', 'empresa_activa', 'banco_proveedor', 'cta_proveedor', 'num_cuenta_proveedor')
    search_fields = ('nombre_proveedor', 'rut_proveedor', 'num_cuenta_proveedor')
    list_filter = ('empresa_activa', 'banco_proveedor', 'cta_proveedor')
    ordering = ('-id',)
    inlines = [ContactoInline]


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_contacto', 'apellido_contacto', 'cargo_contacto', 'proveedor', 'telefono_contacto', 'correo_contacto')
    search_fields = ('nombre_contacto', 'apellido_contacto', 'cargo_contacto', 'proveedor__nombre_proveedor', 'correo_contacto')
    list_filter = ('proveedor',)
    ordering = ('-id',)
    autocomplete_fields = ('proveedor',)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_producto', 'codigo_producto_interno','categoria_producto', 'subcategoria_producto', 'qty_unidad', 'medida',
                    'empaque_primario', 'empaque_secundario', 'empaque_terciario')
    search_fields = ('nombre_producto', 'codigo_producto_interno', 'codigo_producto_proveedor')
    list_filter = ('categoria_producto', 'subcategoria_producto', 'medida')
    ordering = ('-id',)
    autocomplete_fields = ('categoria_producto', 'subcategoria_producto',
                           'empaque_primario', 'empaque_secundario', 'empaque_terciario')

@admin.register(CodigoProveedor)
class CodigoProveedorAdmin(admin.ModelAdmin):
    list_display = ('id', 'proveedor', 'producto', 'codigo_proveedor')
    list_filter = ('proveedor',)
    search_fields = ('codigo_proveedor', 'producto__nombre_producto', 'proveedor__nombre_proveedor')
    ordering = ('proveedor', 'codigo_proveedor')

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_cliente', 'rut_cliente', 'categoria', 'cliente_activo', 'telefono_cliente', 'correo_cliente')
    search_fields = ('nombre_cliente', 'rut_cliente', 'correo_cliente')
    list_filter = ('cliente_activo', 'categoria')
    ordering = ('-id',)


@admin.register(Recepcion)
class RecepcionAdmin(admin.ModelAdmin):
    list_display = ('id', 'num_documento_recepcion', 'proveedor', 'fecha_recepcion', 'documento_recepcion',
                    'estado_recepcion', 'moneda_recepcion', 'total_neto_recepcion', 'iva_recepcion', 'total_recepcion', 'incluir_iva')
    search_fields = ('num_documento_recepcion', 'proveedor__nombre_proveedor')
    list_filter = ('estado_recepcion', 'documento_recepcion', 'moneda_recepcion', 'incluir_iva', 'fecha_recepcion', 'proveedor')
    date_hierarchy = 'fecha_recepcion'
    ordering = ('-id',)
    autocomplete_fields = ('proveedor',)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('id', 'tipo_movimiento', 'producto', 'qty', 'empaque', 'precio_unitario',
                    'fecha_movimiento', 'recepcion', 'pedido')
    search_fields = ('producto__nombre_producto', 'recepcion__num_documento_recepcion', 'pedido__id')
    list_filter = ('tipo_movimiento', 'empaque', 'fecha_movimiento', 'producto')
    date_hierarchy = 'fecha_movimiento'
    ordering = ('-id',)
    autocomplete_fields = ('producto', 'recepcion', 'pedido')
    list_select_related = ('producto', 'recepcion', 'pedido')


@admin.register(ListaPrecios)
class ListaPreciosAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_cliente', 'nombre_producto', 'empaque', 'precio_venta', 'precio_iva', 'precio_total', 'vigencia')
    search_fields = ('nombre_cliente__nombre_cliente', 'nombre_producto__nombre_producto')
    list_filter = ('empaque', 'vigencia', 'nombre_cliente')
    date_hierarchy = 'vigencia'
    ordering = ('-id',)
    autocomplete_fields = ('nombre_cliente', 'nombre_producto')


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'num_cotizacion', 'nombre_cliente', 'fecha_cotizacion', 'archivo_link')
    search_fields = ('num_cotizacion', 'nombre_cliente__nombre_cliente')
    list_filter = ('fecha_cotizacion', 'nombre_cliente')
    date_hierarchy = 'fecha_cotizacion'
    ordering = ('-id',)
    autocomplete_fields = ('nombre_cliente',)

    def archivo_link(self, obj):
        if obj.archivo_pdf:
            return format_html('<a href="{}" target="_blank">Ver PDF</a>', obj.archivo_pdf.url)
        return "—"
    archivo_link.short_description = "Archivo PDF"


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_cliente', 'num_cotizacion', 'fecha_pedido', 'estado_pedido', 'comentario_pedido')
    search_fields = ('id', 'nombre_cliente__nombre_cliente', 'num_cotizacion__num_cotizacion')
    list_filter = ('estado_pedido', 'fecha_pedido', 'nombre_cliente')
    date_hierarchy = 'fecha_pedido'
    ordering = ('-id',)
    autocomplete_fields = ('nombre_cliente', 'num_cotizacion')
    inlines = [EntregaPedidoInline]


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ('id', 'pedidoid', 'fecha_venta', 'documento_pedido', 'num_documento',
                    'venta_neto_pedido', 'venta_iva_pedido', 'venta_total_pedido',
                    'ganancia_total', 'ganancia_porcentaje')
    search_fields = ('pedidoid__id', 'num_documento')
    list_filter = ('documento_pedido', 'fecha_venta')
    date_hierarchy = 'fecha_venta'
    ordering = ('-id',)
    autocomplete_fields = ('pedidoid',)


@admin.register(EntregaPedido)
class EntregaPedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'pedido', 'nombre_receptor', 'rut_receptor', 'fecha_entrega', 'archivo_link', 'foto_link', 'creado')
    search_fields = ('pedido__id', 'nombre_receptor', 'rut_receptor')
    list_filter = ('fecha_entrega', 'pedido')
    date_hierarchy = 'fecha_entrega'
    ordering = ('-id',)
    autocomplete_fields = ('pedido',)
    readonly_fields = ('archivo_link', 'foto_link', 'creado')

    def archivo_link(self, obj):
        if obj.archivo_pdf:
            return format_html('<a href="{}" target="_blank">Ver PDF</a>', obj.archivo_pdf.url)
        return "—"
    archivo_link.short_description = "Archivo PDF"

    def foto_link(self, obj):
        if obj.foto:
            return format_html('<a href="{}" target="_blank">Ver Foto</a>', obj.foto.url)
        return "—"
    foto_link.short_description = "Foto"


# =========================
# Inlines (ítems en cabecera)
# =========================
class ListaPreciosPredItemInline(admin.TabularInline):
    model = ListaPreciosPredItem
    extra = 0
    fields = (
        'nombre_producto',
        'empaque',
        'precio_venta',
        'precio_iva',
        'precio_total',
        'vigencia',
        'actualizado',
    )
    readonly_fields = ('precio_iva', 'precio_total', 'actualizado')
    autocomplete_fields = ('nombre_producto',)
    show_change_link = True


# =========================
# Admin de la cabecera (Lista)
# =========================
@admin.register(ListaPreciosPredeterminada)
class ListaPreciosPredeterminadaAdmin(admin.ModelAdmin):
    list_display = (
        'nombre_listaprecios',
        'descripcion_resumida',
        'activa',
        'cant_items',
        'creado',
        'actualizado',
    )
    list_filter = ('activa', 'creado', 'actualizado')
    search_fields = ('nombre_listaprecios', 'descripcion_listaprecios')
    ordering = ('nombre_listaprecios',)
    inlines = [ListaPreciosPredItemInline]
    readonly_fields = ('creado', 'actualizado')

    actions = ['activar_listas', 'desactivar_listas']

    def descripcion_resumida(self, obj: ListaPreciosPredeterminada):
        if not obj.descripcion_listaprecios:
            return '-'
        txt = obj.descripcion_listaprecios
        return txt if len(txt) <= 60 else f"{txt[:57]}..."
    descripcion_resumida.short_description = "Descripción"

    def cant_items(self, obj: ListaPreciosPredeterminada):
        return obj.items.count()
    cant_items.short_description = "Ítems"

    def activar_listas(self, request, queryset):
        updated = queryset.update(activa=True)
        self.message_user(request, f"{updated} lista(s) activada(s).")
    activar_listas.short_description = "Activar listas seleccionadas"

    def desactivar_listas(self, request, queryset):
        updated = queryset.update(activa=False)
        self.message_user(request, f"{updated} lista(s) desactivada(s).")
    desactivar_listas.short_description = "Desactivar listas seleccionadas"


# =========================
# Admin de los ítems
# =========================
@admin.register(ListaPreciosPredItem)
class ListaPreciosPredItemAdmin(admin.ModelAdmin):
    list_display = (
        'listaprecios',
        'nombre_producto',
        'empaque',
        'empaque_nombre_admin',
        'precio_venta_admin',
        'precio_iva_admin',
        'precio_total_admin',
        'vigencia',
        'actualizado',
    )
    list_filter = (
        'empaque',
        'vigencia',
        ('listaprecios', admin.RelatedOnlyFieldListFilter),
        ('nombre_producto', admin.RelatedOnlyFieldListFilter),
        'actualizado',
    )
    search_fields = (
        'listaprecios__nombre_listaprecios',
        'nombre_producto__nombre_producto',
    )
    date_hierarchy = 'vigencia'
    ordering = ('listaprecios__nombre_listaprecios', 'nombre_producto__nombre_producto', 'empaque', '-vigencia')

    autocomplete_fields = ('listaprecios', 'nombre_producto')
    readonly_fields = ('creado', 'actualizado', 'precio_iva', 'precio_total')

    list_editable = ('empaque', 'vigencia',)

    fieldsets = (
        (None, {
            'fields': (
                'listaprecios',
                'nombre_producto',
                'empaque',
                'vigencia',
            )
        }),
        ("Precios", {
            'fields': (
                'precio_venta',
                ('precio_iva', 'precio_total'),
            )
        }),
        ("Trazabilidad", {
            'fields': ('creado', 'actualizado'),
        }),
    )

    # ----- Helpers de display -----
    def empaque_nombre_admin(self, obj: ListaPreciosPredItem):
        return obj.empaque_nombre()
    empaque_nombre_admin.short_description = "Empaque (nombre)"

    def precio_venta_admin(self, obj: ListaPreciosPredItem):
        return self._fmt_clp(obj.precio_venta)
    precio_venta_admin.short_description = "Neto"

    def precio_iva_admin(self, obj: ListaPreciosPredItem):
        return self._fmt_clp(obj.precio_iva)
    precio_iva_admin.short_description = "IVA"

    def precio_total_admin(self, obj: ListaPreciosPredItem):
        return format_html("<strong>{}</strong>", self._fmt_clp(obj.precio_total))
    precio_total_admin.short_description = "Total"

    def _fmt_clp(self, val: Decimal | None) -> str:
        if val is None:
            return "$0"
        entero = int(Decimal(val).quantize(Decimal('1')))
        s = f"{entero:,}".replace(",", ".")
        return f"${s}"
