from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from Apps.Pedidos.models import ListaPrecios, ListaPreciosPredItem, ListaPreciosPredeterminada, Producto, Stock
from Apps.Pedidos.services.packs import costo_referencial_pack, es_pack, factor_empaque


DOS_DEC = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def seleccionar_lista_precios_alerta() -> ListaPreciosPredeterminada | None:
    listas = ListaPreciosPredeterminada.objects.all().order_by("nombre_listaprecios")
    return listas.filter(activa=True).first() or listas.first()


def _normalizar_precio_producto(producto: Producto, empaque: str, precio) -> Decimal:
    factor = Decimal(factor_empaque(producto, empaque))
    if factor <= 0:
        factor = Decimal("1")
    return _q2(Decimal(precio or 0) / factor)


def _nombre_empaque_producto(producto: Producto, empaque: str) -> str:
    nivel = (empaque or "").upper().strip()
    if nivel == "PRIMARIO" and producto.empaque_primario:
        return producto.empaque_primario.nombre
    if nivel == "SECUNDARIO" and producto.empaque_secundario:
        return producto.empaque_secundario.nombre
    if nivel == "TERCIARIO" and producto.empaque_terciario:
        return producto.empaque_terciario.nombre
    return nivel.title() if nivel else "-"


def _maximos_compra_por_producto(product_ids) -> dict[int, Decimal]:
    if not product_ids:
        return {}

    productos = {
        producto.id: producto
        for producto in Producto.objects.filter(id__in=product_ids).select_related(
            "empaque_primario",
            "empaque_secundario",
            "empaque_terciario",
        )
    }

    compras_qs = (
        Stock.objects.filter(
            producto_id__in=product_ids,
            recepcion__isnull=False,
            recepcion__estado_recepcion="Finalizado",
            tipo_movimiento="DISPONIBLE",
            precio_unitario__isnull=False,
        )
        .select_related("producto")
        .order_by("producto__nombre_producto", "id")
    )

    maximos: dict[int, Decimal] = {}
    for producto_id, producto in productos.items():
        if es_pack(producto):
            precio_pack = costo_referencial_pack(producto)
            if precio_pack > 0:
                maximos[producto_id] = _q2(precio_pack)

    for stock in compras_qs:
        precio = _normalizar_precio_producto(stock.producto, stock.empaque, stock.precio_unitario)
        actual = maximos.get(stock.producto_id)
        if actual is None or precio > actual:
            maximos[stock.producto_id] = precio

    return maximos


def filas_lista_precios_vigentes(lista: ListaPreciosPredeterminada | None) -> list[dict]:
    if not lista:
        return []

    items = list(
        ListaPreciosPredItem.objects.filter(listaprecios=lista)
        .select_related(
            "nombre_producto__categoria_producto",
            "nombre_producto__subcategoria_producto",
            "nombre_producto__empaque_primario",
            "nombre_producto__empaque_secundario",
            "nombre_producto__empaque_terciario",
        )
        .order_by("nombre_producto__nombre_producto", "empaque")
    )
    maximos_compra = _maximos_compra_por_producto({item.nombre_producto_id for item in items})

    rows = []
    for item in items:
        producto = item.nombre_producto
        precio_venta = _normalizar_precio_producto(producto, item.empaque, item.precio_venta)
        precio_compra = maximos_compra.get(producto.id)
        diferencia = _q2(precio_venta - precio_compra) if precio_compra is not None else None
        utilidad = diferencia
        ganancia_pct = _q2((utilidad / precio_compra) * Decimal("100")) if precio_compra and precio_compra > 0 else None

        rows.append(
            {
                "producto_id": producto.id,
                "codigo_interno": producto.codigo_producto_interno,
                "producto": producto.nombre_producto,
                "empaque": item.empaque,
                "empaque_label": _nombre_empaque_producto(producto, item.empaque),
                "vigencia": item.vigencia,
                "precio_venta": precio_venta,
                "precio_compra": precio_compra,
                "diferencia": diferencia,
                "utilidad": utilidad,
                "ganancia_pct": ganancia_pct,
            }
        )

    return rows


def filas_precios_cliente(cliente=None) -> list[dict]:
    items_qs = (
        ListaPrecios.objects.select_related(
            "nombre_cliente",
            "nombre_producto__categoria_producto",
            "nombre_producto__subcategoria_producto",
            "nombre_producto__empaque_primario",
            "nombre_producto__empaque_secundario",
            "nombre_producto__empaque_terciario",
        )
        .order_by("nombre_cliente__nombre_cliente", "nombre_producto__nombre_producto", "empaque")
    )
    if cliente is not None:
        items_qs = items_qs.filter(nombre_cliente=cliente)

    items = list(items_qs)
    maximos_compra = _maximos_compra_por_producto({item.nombre_producto_id for item in items})

    rows = []
    for item in items:
        producto = item.nombre_producto
        precio_venta = _normalizar_precio_producto(producto, item.empaque, item.precio_venta)
        precio_compra = maximos_compra.get(producto.id)
        diferencia = _q2(precio_venta - precio_compra) if precio_compra is not None else None
        utilidad = diferencia
        ganancia_pct = _q2((utilidad / precio_compra) * Decimal("100")) if precio_compra and precio_compra > 0 else None

        rows.append(
            {
                "precio_id": item.id,
                "cliente_id": item.nombre_cliente_id,
                "cliente": item.nombre_cliente.nombre_cliente,
                "producto_id": producto.id,
                "codigo_interno": producto.codigo_producto_interno,
                "producto": producto.nombre_producto,
                "empaque": item.empaque,
                "empaque_label": _nombre_empaque_producto(producto, item.empaque),
                "vigencia": item.vigencia,
                "precio_cliente": _q2(item.precio_venta),
                "precio_venta": precio_venta,
                "precio_compra": precio_compra,
                "diferencia": diferencia,
                "utilidad": utilidad,
                "ganancia_pct": ganancia_pct,
            }
        )

    return rows
