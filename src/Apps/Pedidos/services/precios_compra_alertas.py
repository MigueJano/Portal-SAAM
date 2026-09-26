from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from Apps.Pedidos.models import Producto, Stock
from Apps.Pedidos.services.packs import factor_empaque


DOS_DEC = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _nombre_empaque_producto(producto: Producto, empaque: str) -> str:
    nivel = (empaque or "").upper().strip()
    if nivel == "PRIMARIO" and producto.empaque_primario:
        return producto.empaque_primario.nombre
    if nivel == "SECUNDARIO" and producto.empaque_secundario:
        return producto.empaque_secundario.nombre
    if nivel == "TERCIARIO" and producto.empaque_terciario:
        return producto.empaque_terciario.nombre
    return nivel.title() if nivel else "-"


def _normalizar_precio_primario(producto: Producto, empaque: str, precio) -> Decimal:
    factor = Decimal(factor_empaque(producto, empaque))
    if factor <= 0:
        factor = Decimal("1")
    return _q2(Decimal(precio or 0) / factor)


def filas_cambios_precio_compra(
    *,
    inicio=None,
    fin=None,
    categoria_id=None,
    subcategoria_id=None,
) -> list[dict]:
    filtros = {}
    if inicio and fin:
        filtros["fecha_movimiento__range"] = (inicio, fin)
    elif inicio:
        filtros["fecha_movimiento__gte"] = inicio
    elif fin:
        filtros["fecha_movimiento__lte"] = fin
    if categoria_id:
        filtros["producto__categoria_producto_id"] = categoria_id
    if subcategoria_id:
        filtros["producto__subcategoria_producto_id"] = subcategoria_id

    compras = (
        Stock.objects.filter(
            tipo_movimiento="DISPONIBLE",
            recepcion__isnull=False,
            recepcion__estado_recepcion="Finalizado",
            precio_unitario__isnull=False,
            **filtros,
        )
        .select_related(
            "recepcion__proveedor",
            "producto__categoria_producto",
            "producto__subcategoria_producto",
            "producto__empaque_primario",
            "producto__empaque_secundario",
            "producto__empaque_terciario",
        )
        .order_by("producto_id", "fecha_movimiento", "id")
    )

    anterior_por_producto: dict[int, dict] = {}
    cambios = []

    for compra in compras:
        producto = compra.producto
        empaque = (compra.empaque or "").upper().strip()
        precio_nuevo = _normalizar_precio_primario(producto, empaque, compra.precio_unitario)
        anterior = anterior_por_producto.get(compra.producto_id)

        if anterior is not None:
            diferencia = _q2(precio_nuevo - anterior["precio"])
            if diferencia != 0:
                cambios.append(
                    {
                        "stock_id": compra.id,
                        "producto_id": producto.id,
                        "categoria": producto.categoria_producto.categoria if producto.categoria_producto else "-",
                        "subcategoria": producto.subcategoria_producto.subcategoria if producto.subcategoria_producto else "-",
                        "codigo_interno": producto.codigo_producto_interno,
                        "producto": producto.nombre_producto,
                        "proveedor_id": compra.recepcion.proveedor_id,
                        "proveedor": compra.recepcion.proveedor.nombre_proveedor,
                        "documento": compra.recepcion.num_documento_recepcion,
                        "tipo_documento": compra.recepcion.documento_recepcion,
                        "empaque": empaque,
                        "empaque_label": _nombre_empaque_producto(producto, empaque),
                        "precio_anterior": anterior["precio"],
                        "precio_nuevo": precio_nuevo,
                        "diferencia": diferencia,
                        "diferencia_abs": abs(diferencia),
                        "es_alza": diferencia > 0,
                        "fecha_cambio": compra.fecha_movimiento,
                    }
                )

        anterior_por_producto[compra.producto_id] = {
            "precio": precio_nuevo,
            "fecha": compra.fecha_movimiento,
            "stock_id": compra.id,
        }

    return sorted(
        cambios,
        key=lambda row: (row["fecha_cambio"], row["stock_id"]),
        reverse=True,
    )
