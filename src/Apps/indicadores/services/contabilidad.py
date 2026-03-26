"""
Servicios contables para Pro Pyme.

Concentra calculos de ventas, compras e inventario y la exportacion
de libros electronicos en formato CSV/ZIP.
"""

from __future__ import annotations

import csv
import zipfile
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO, StringIO
from typing import Iterable

from django.db.models import Case, F, IntegerField, Sum, Value, When

from Apps.Pedidos.models import Producto, Recepcion, Stock, Venta


DOS_DEC = Decimal("0.01")
ZERO = Decimal("0.00")


VENTAS_FIELDS = [
    "periodo",
    "tipo_documento",
    "folio",
    "fecha_emision",
    "rut_receptor",
    "razon_social_receptor",
    "monto_exento",
    "monto_neto",
    "monto_iva",
    "monto_total",
    "estado_dte",
    "referencia_interna",
]

COMPRAS_FIELDS = [
    "periodo",
    "tipo_documento",
    "folio",
    "fecha_emision",
    "rut_emisor",
    "razon_social_emisor",
    "monto_exento",
    "monto_neto",
    "monto_iva",
    "monto_total",
    "estado_dte",
    "referencia_interna",
]

STOCK_FIELDS = [
    "codigo_interno",
    "producto",
    "cantidad_disponible_uprim",
    "cantidad_despachada_uprim",
    "costo_unitario_compra",
    "total_producto",
]


@dataclass(frozen=True)
class Periodo:
    year: int
    month: int

    @property
    def etiqueta(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def normalizar_periodo(year: int | str, month: int | str, *, hoy: date | None = None) -> Periodo:
    hoy = hoy or date.today()
    try:
        y = int(year)
    except (TypeError, ValueError):
        y = hoy.year
    try:
        m = int(month)
    except (TypeError, ValueError):
        m = hoy.month

    if y < 2000 or y > 2100:
        y = hoy.year
    if m < 1 or m > 12:
        m = hoy.month
    return Periodo(year=y, month=m)


def _q2(valor: Decimal | int | float | None) -> Decimal:
    return Decimal(valor or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _factor_empaque(producto: Producto, empaque: str | None) -> Decimal:
    empaque = (empaque or "").upper().strip()
    q2 = Decimal(producto.qty_secundario or 1)
    q3 = Decimal(producto.qty_terciario or 1)
    if empaque == "SECUNDARIO":
        factor = q2
    elif empaque == "TERCIARIO":
        factor = q2 * q3
    else:
        factor = Decimal(1)
    if factor <= 0:
        return Decimal(1)
    return factor


def _normalizar_precio_unidad_primaria(stock: Stock) -> Decimal:
    precio = Decimal(stock.precio_unitario or 0)
    factor = _factor_empaque(stock.producto, stock.empaque)
    return _q2(precio / factor)


def _qty_unidad_expr():
    return Case(
        When(
            empaque__iexact="TERCIARIO",
            then=F("qty") * F("producto__qty_terciario") * F("producto__qty_secundario"),
        ),
        When(empaque__iexact="SECUNDARIO", then=F("qty") * F("producto__qty_secundario")),
        When(empaque__iexact="PRIMARIO", then=F("qty")),
        default=Value(0),
        output_field=IntegerField(),
    )


def _fecha_corte_periodo(periodo: Periodo | None) -> date | None:
    if not periodo:
        return None
    return date(periodo.year, periodo.month, monthrange(periodo.year, periodo.month)[1])


def _stock_qs(tipo: str, *, fecha_corte: date | None = None):
    qs = Stock.objects.filter(tipo_movimiento=tipo)
    if fecha_corte:
        qs = qs.filter(fecha_movimiento__date__lte=fecha_corte)
    return qs


def _agregar_por_producto(tipo: str, *, fecha_corte: date | None = None) -> dict[int, int]:
    filas = (
        _stock_qs(tipo, fecha_corte=fecha_corte)
        .annotate(qty_unidad=_qty_unidad_expr())
        .values("producto")
        .annotate(total=Sum("qty_unidad"))
    )
    return {f["producto"]: int(f["total"] or 0) for f in filas}


def _costos_compra_por_producto(*, fecha_corte: date | None = None) -> dict[int, Decimal]:
    costos: dict[int, Decimal] = {}
    qs = (
        _stock_qs("DISPONIBLE", fecha_corte=fecha_corte)
        .filter(precio_unitario__isnull=False)
        .select_related("producto")
        .order_by("producto_id", "-fecha_movimiento", "-id")
    )
    for stock in qs:
        if stock.producto_id not in costos:
            costos[stock.producto_id] = _normalizar_precio_unidad_primaria(stock)
    return costos


def obtener_resumen_periodo(periodo: Periodo) -> dict[str, Decimal | int]:
    ventas = Venta.objects.filter(fecha_venta__year=periodo.year, fecha_venta__month=periodo.month)
    compras = Recepcion.objects.filter(
        fecha_recepcion__year=periodo.year,
        fecha_recepcion__month=periodo.month,
    ).exclude(estado_recepcion="Rechazado")

    ventas_total_neto = _q2(ventas.aggregate(total=Sum("venta_neto_pedido"))["total"])
    ventas_total_iva = _q2(ventas.aggregate(total=Sum("venta_iva_pedido"))["total"])
    ventas_total = _q2(ventas.aggregate(total=Sum("venta_total_pedido"))["total"])

    compras_total_neto = _q2(compras.aggregate(total=Sum("total_neto_recepcion"))["total"])
    compras_total_iva = _q2(compras.aggregate(total=Sum("iva_recepcion"))["total"])
    compras_total = _q2(compras.aggregate(total=Sum("total_recepcion"))["total"])

    margen_bruto = _q2(ventas_total_neto - compras_total_neto)

    return {
        "ventas_count": ventas.count(),
        "compras_count": compras.count(),
        "ventas_total_neto": ventas_total_neto,
        "ventas_total_iva": ventas_total_iva,
        "ventas_total": ventas_total,
        "compras_total_neto": compras_total_neto,
        "compras_total_iva": compras_total_iva,
        "compras_total": compras_total,
        "margen_bruto": margen_bruto,
    }


def obtener_ventas_periodo(periodo: Periodo):
    return (
        Venta.objects.filter(fecha_venta__year=periodo.year, fecha_venta__month=periodo.month)
        .select_related("pedidoid__nombre_cliente")
        .order_by("fecha_venta", "num_documento")
    )


def obtener_compras_periodo(periodo: Periodo):
    return (
        Recepcion.objects.filter(
            fecha_recepcion__year=periodo.year,
            fecha_recepcion__month=periodo.month,
        )
        .exclude(estado_recepcion="Rechazado")
        .select_related("proveedor")
        .order_by("fecha_recepcion", "num_documento_recepcion")
    )


def filas_libro_ventas(periodo: Periodo, ventas) -> list[dict]:
    filas: list[dict] = []
    for venta in ventas:
        cliente = venta.pedidoid.nombre_cliente
        filas.append(
            {
                "periodo": periodo.etiqueta,
                "tipo_documento": venta.documento_pedido,
                "folio": venta.num_documento,
                "fecha_emision": venta.fecha_venta.isoformat(),
                "rut_receptor": cliente.rut_cliente,
                "razon_social_receptor": cliente.nombre_cliente,
                "monto_exento": _q2(0),
                "monto_neto": _q2(venta.venta_neto_pedido),
                "monto_iva": _q2(venta.venta_iva_pedido),
                "monto_total": _q2(venta.venta_total_pedido),
                "estado_dte": "VIGENTE",
                "referencia_interna": f"Pedido #{venta.pedidoid_id}",
            }
        )
    return filas


def filas_libro_compras(periodo: Periodo, compras) -> list[dict]:
    filas: list[dict] = []
    for compra in compras:
        proveedor = compra.proveedor
        filas.append(
            {
                "periodo": periodo.etiqueta,
                "tipo_documento": compra.documento_recepcion,
                "folio": compra.num_documento_recepcion,
                "fecha_emision": compra.fecha_recepcion.isoformat(),
                "rut_emisor": proveedor.rut_proveedor,
                "razon_social_emisor": proveedor.nombre_proveedor,
                "monto_exento": _q2(0),
                "monto_neto": _q2(compra.total_neto_recepcion),
                "monto_iva": _q2(compra.iva_recepcion),
                "monto_total": _q2(compra.total_recepcion),
                "estado_dte": compra.estado_recepcion.upper(),
                "referencia_interna": f"Recepcion #{compra.id}",
            }
        )
    return filas


def filas_stock_contable(periodo: Periodo | None = None) -> list[dict]:
    fecha_corte = _fecha_corte_periodo(periodo)
    ingresos = _agregar_por_producto("DISPONIBLE", fecha_corte=fecha_corte)
    reservas = _agregar_por_producto("RESERVA", fecha_corte=fecha_corte)
    despachos = _agregar_por_producto("DESPACHO", fecha_corte=fecha_corte)
    costos_compra = _costos_compra_por_producto(fecha_corte=fecha_corte)

    productos = Producto.objects.all().order_by("nombre_producto")
    filas: list[dict] = []
    for prod in productos:
        qty_ingresado = int(ingresos.get(prod.id, 0))
        qty_res = int(reservas.get(prod.id, 0))
        qty_des = int(despachos.get(prod.id, 0))
        qty_disp = qty_ingresado + qty_res - qty_des

        costo_compra = costos_compra.get(prod.id, ZERO)
        total_producto = _q2(Decimal(qty_disp) * costo_compra)

        filas.append(
            {
                "codigo_interno": prod.codigo_producto_interno,
                "producto_id": prod.id,
                "producto": prod.nombre_producto,
                "cantidad_disponible_uprim": qty_disp,
                "cantidad_reservada_uprim": qty_res,
                "cantidad_despachada_uprim": qty_des,
                "costo_unitario_compra": costo_compra,
                "valor_producto_unitario": costo_compra,
                "total_producto": total_producto,
                "valor_inventario_compra": total_producto,
                "costo_unitario_referencia": costo_compra,
                "valor_inventario_referencia": total_producto,
            }
        )
    return filas


def _serializar_valor(valor):
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    return valor


def csv_bytes(fieldnames: list[str], filas: Iterable[dict]) -> bytes:
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for fila in filas:
        writer.writerow({k: _serializar_valor(v) for k, v in fila.items()})
    return out.getvalue().encode("utf-8-sig")


def zip_libros_bytes(periodo: Periodo, filas_ventas: list[dict], filas_compras: list[dict], filas_stock: list[dict]) -> bytes:
    contenido = BytesIO()
    with zipfile.ZipFile(contenido, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        sufijo = f"{periodo.year:04d}{periodo.month:02d}"
        zf.writestr(f"libro_ventas_propyme_{sufijo}.csv", csv_bytes(VENTAS_FIELDS, filas_ventas))
        zf.writestr(f"libro_compras_propyme_{sufijo}.csv", csv_bytes(COMPRAS_FIELDS, filas_compras))
        zf.writestr(f"inventario_propyme_{sufijo}.csv", csv_bytes(STOCK_FIELDS, filas_stock))
    contenido.seek(0)
    return contenido.getvalue()
