from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Case, F, IntegerField, Sum, Value, When

from Apps.Pedidos.models import PackComponente, Producto, Stock


ZERO = Decimal("0.00")
DOS_DEC = Decimal("0.01")
CIEN = Decimal("100")


def q2(value) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def es_pack(producto: Producto) -> bool:
    return getattr(producto, "tipo_producto", "SIMPLE") == "PACK"


def factor_empaque(producto: Producto, empaque: str | None) -> int:
    nivel = (empaque or "PRIMARIO").upper()
    qty_sec = int(producto.qty_secundario or 1) or 1
    qty_ter = int(producto.qty_terciario or 1) or 1
    if nivel == "SECUNDARIO":
        return max(qty_sec, 1)
    if nivel == "TERCIARIO":
        return max(qty_sec, 1) * max(qty_ter, 1)
    return 1


def cantidad_primaria(producto: Producto, empaque: str | None, cantidad: int) -> int:
    return int(cantidad or 0) * factor_empaque(producto, empaque)


def componentes_pack(pack: Producto):
    return (
        PackComponente.objects
        .filter(pack=pack)
        .select_related(
            "producto",
            "producto__empaque_primario",
            "producto__empaque_secundario",
            "producto__empaque_terciario",
        )
        .order_by("orden", "id")
    )


def costo_maximo_unitario(producto: Producto) -> Decimal:
    if es_pack(producto):
        return costo_referencial_pack(producto)

    movimientos = (
        Stock.objects
        .filter(
            producto=producto,
            tipo_movimiento="DISPONIBLE",
            precio_unitario__isnull=False,
        )
        .only("precio_unitario", "empaque")
    )

    max_unit = ZERO
    for item in movimientos:
        precio = Decimal(item.precio_unitario or 0)
        factor = Decimal(factor_empaque(producto, item.empaque))
        unitario = q2(precio / factor)
        if unitario > max_unit:
            max_unit = unitario

    return max_unit


def snapshot_pack(pack: Producto) -> list[dict]:
    snapshot = []
    for componente in componentes_pack(pack):
        factor = factor_empaque(componente.producto, componente.empaque)
        qty_primary = int(componente.cantidad or 0) * factor
        costo_unit = costo_maximo_unitario(componente.producto)
        costo_total = q2(costo_unit * Decimal(qty_primary))
        snapshot.append({
            "componente": componente,
            "producto": componente.producto,
            "empaque": componente.empaque,
            "cantidad_empaque": int(componente.cantidad or 0),
            "qty_primary_per_pack": qty_primary,
            "factor_empaque": factor,
            "costo_unit_primary": costo_unit,
            "costo_total_pack": costo_total,
        })
    return snapshot


def costo_referencial_pack(pack: Producto) -> Decimal:
    total = ZERO
    for row in snapshot_pack(pack):
        total += row["costo_total_pack"]
    return q2(total)


def stock_cache_simple() -> dict[int, int]:
    filas = (
        Stock.objects
        .annotate(
            qty_unidad=Case(
                When(
                    empaque__iexact="TERCIARIO",
                    then=F("qty") * F("producto__qty_terciario") * F("producto__qty_secundario"),
                ),
                When(empaque__iexact="SECUNDARIO", then=F("qty") * F("producto__qty_secundario")),
                When(empaque__iexact="PRIMARIO", then=F("qty")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .values("producto", "tipo_movimiento")
        .annotate(total=Sum("qty_unidad"))
    )

    base: dict[int, dict[str, int]] = {}
    for fila in filas:
        producto_id = fila["producto"]
        base.setdefault(producto_id, {"DISPONIBLE": 0, "RESERVA": 0, "DESPACHO": 0})
        base[producto_id][fila["tipo_movimiento"]] = int(fila["total"] or 0)

    return {
        producto_id: valores["DISPONIBLE"] - valores["RESERVA"] - valores["DESPACHO"]
        for producto_id, valores in base.items()
    }


def stock_disponible_primario(producto: Producto, cache: dict[int, int] | None = None) -> int:
    if cache is not None and producto.id in cache:
        return int(cache[producto.id] or 0)

    if es_pack(producto):
        return stock_disponible_pack(producto, cache=cache)

    agregados = stock_cache_simple()
    return int(agregados.get(producto.id, 0))


def stock_disponible_pack(pack: Producto, cache: dict[int, int] | None = None) -> int:
    if not es_pack(pack):
        return stock_disponible_primario(pack, cache=cache)

    componentes = snapshot_pack(pack)
    if not componentes:
        return 0

    disponibles = []
    for row in componentes:
        requerido = int(row["qty_primary_per_pack"] or 0)
        if requerido <= 0:
            continue
        disponible = stock_disponible_primario(row["producto"], cache=cache)
        disponibles.append(disponible // requerido)

    return max(0, min(disponibles)) if disponibles else 0


def validar_stock_pack(pack: Producto, cantidad_packs: int, cache: dict[int, int] | None = None) -> list[dict]:
    faltantes = []
    for row in snapshot_pack(pack):
        requerido = row["qty_primary_per_pack"] * int(cantidad_packs or 0)
        disponible = stock_disponible_primario(row["producto"], cache=cache)
        if requerido > disponible:
            faltantes.append({
                "producto": row["producto"],
                "requerido": requerido,
                "disponible": disponible,
            })
    return faltantes


def desglose_ingreso_pack(pack: Producto, precio_pack_neto: Decimal, cantidad_packs: int = 1) -> list[dict]:
    rows = snapshot_pack(pack)
    if not rows:
        return []

    precio_pack_neto = q2(precio_pack_neto)
    costo_total_pack = sum((row["costo_total_pack"] for row in rows), ZERO)
    ingreso_asignado = ZERO
    desglose = []

    for idx, row in enumerate(rows):
        if idx == len(rows) - 1:
            ingreso_pack = q2(precio_pack_neto - ingreso_asignado)
        elif costo_total_pack > 0:
            ingreso_pack = q2(precio_pack_neto * row["costo_total_pack"] / costo_total_pack)
            ingreso_asignado += ingreso_pack
        else:
            ingreso_pack = q2(precio_pack_neto / Decimal(len(rows)))
            ingreso_asignado += ingreso_pack

        qty_primary_pack = int(row["qty_primary_per_pack"] or 0)
        qty_primary_total = qty_primary_pack * int(cantidad_packs or 0)
        ingreso_total = q2(ingreso_pack * Decimal(cantidad_packs or 0))

        pv_unit_primary = ZERO
        if qty_primary_pack > 0:
            pv_unit_primary = q2(ingreso_pack / Decimal(qty_primary_pack))

        utilidad_unit = q2(pv_unit_primary - row["costo_unit_primary"])
        utilidad_total = q2(utilidad_unit * Decimal(qty_primary_total))
        utilidad_pct_venta = ZERO
        if pv_unit_primary > 0:
            utilidad_pct_venta = q2((utilidad_unit / pv_unit_primary) * CIEN)

        desglose.append({
            **row,
            "ingreso_pack": ingreso_pack,
            "ingreso_total": ingreso_total,
            "qty_primary_total": qty_primary_total,
            "pv_unit_primary": pv_unit_primary,
            "utilidad_unit_primary": utilidad_unit,
            "utilidad_total": utilidad_total,
            "utilidad_pct_venta": utilidad_pct_venta,
        })

    return desglose
