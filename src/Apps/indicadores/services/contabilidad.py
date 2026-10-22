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
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO, StringIO
from typing import Iterable

from django.db.models import Case, F, IntegerField, Sum, Value, When

from Apps.Pedidos.models import Producto, Recepcion, Stock, Venta
from Apps.integraciones.models import ConciliacionPago, MovimientoBancario


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
    "cantidad_reservada_uprim",
    "cantidad_existencia_contable_uprim",
    "cantidad_despachada_uprim",
    "costo_unitario_fifo",
    "valor_inventario_fifo",
    "capas_fifo",
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
        qs = qs.filter(fecha_movimiento__lte=fecha_corte)
    return qs


def _agregar_por_producto(tipo: str, *, fecha_corte: date | None = None) -> dict[int, int]:
    filas = (
        _stock_qs(tipo, fecha_corte=fecha_corte)
        .annotate(qty_unidad=_qty_unidad_expr())
        .values("producto")
        .annotate(total=Sum("qty_unidad"))
    )
    return {f["producto"]: int(f["total"] or 0) for f in filas}


def _cantidad_unidad_primaria(stock: Stock) -> Decimal:
    return Decimal(stock.qty or 0) * _factor_empaque(stock.producto, stock.empaque)


def _valor_compras_inventario(fecha_inicio: date, fecha_fin: date) -> Decimal:
    """Costo neto real de la mercaderia ingresada durante el periodo."""
    total = ZERO
    ingresos = (
        Stock.objects.filter(
            tipo_movimiento="DISPONIBLE",
            fecha_movimiento__range=(fecha_inicio, fecha_fin),
        )
        .select_related("producto")
        .order_by("fecha_movimiento", "id")
    )
    for ingreso in ingresos:
        total += _cantidad_unidad_primaria(ingreso) * _normalizar_precio_unidad_primaria(ingreso)
    return _q2(total)


def _valuacion_fifo_por_producto(*, fecha_corte: date | None = None) -> dict[int, dict]:
    """Reconstruye las capas FIFO desde el historial real de ingresos y despachos.

    Las reservas se informan por separado: siguen siendo inventario de la empresa
    hasta que el pedido se despacha. El precio de venta de una salida nunca se usa
    como costo.
    """
    movimientos = Stock.objects.filter(tipo_movimiento__in=("DISPONIBLE", "DESPACHO"))
    if fecha_corte:
        movimientos = movimientos.filter(fecha_movimiento__lte=fecha_corte)
    movimientos = movimientos.select_related("producto", "recepcion").order_by(
        "producto_id", "fecha_movimiento", "id"
    )

    resultados: dict[int, dict] = {}
    for movimiento in movimientos:
        resultado = resultados.setdefault(
            movimiento.producto_id,
            {
                "capas": [],
                "cantidad_despachada": Decimal(0),
                "deficit_pendiente": Decimal(0),
                "salida_sin_recepcion_historica": Decimal(0),
            },
        )
        cantidad = _cantidad_unidad_primaria(movimiento)
        if cantidad <= 0:
            continue

        if movimiento.tipo_movimiento == "DISPONIBLE":
            cantidad_documento = cantidad
            if resultado["deficit_pendiente"]:
                regularizada = min(cantidad, resultado["deficit_pendiente"])
                resultado["deficit_pendiente"] -= regularizada
                cantidad -= regularizada
            if cantidad <= 0:
                continue
            resultado["capas"].append(
                {
                    "stock_id": movimiento.id,
                    "recepcion_id": movimiento.recepcion_id,
                    "fecha": movimiento.fecha_movimiento,
                    "cantidad_documento": cantidad_documento,
                    "cantidad": cantidad,
                    "costo_unitario": _normalizar_precio_unidad_primaria(movimiento),
                }
            )
            continue

        resultado["cantidad_despachada"] += cantidad
        pendiente = cantidad
        for capa in resultado["capas"]:
            if pendiente <= 0:
                break
            consumida = min(capa["cantidad"], pendiente)
            capa["cantidad"] -= consumida
            pendiente -= consumida
        resultado["capas"] = [capa for capa in resultado["capas"] if capa["cantidad"] > 0]
        resultado["deficit_pendiente"] += pendiente
        resultado["salida_sin_recepcion_historica"] += pendiente

    for resultado in resultados.values():
        cantidad = sum((capa["cantidad"] for capa in resultado["capas"]), start=Decimal(0))
        valor = sum(
            (capa["cantidad"] * capa["costo_unitario"] for capa in resultado["capas"]),
            start=ZERO,
        )
        resultado["cantidad"] = cantidad - resultado["deficit_pendiente"]
        resultado["valor"] = _q2(valor)
        resultado["costo_unitario"] = _q2(valor / cantidad) if cantidad else ZERO
    return resultados


def obtener_costo_ventas_periodo(periodo: Periodo) -> dict[str, Decimal | int]:
    inicio = date(periodo.year, periodo.month, 1)
    fin = _fecha_corte_periodo(periodo)
    inventario_inicial = sum(
        (fila["valor"] for fila in _valuacion_fifo_por_producto(fecha_corte=inicio - timedelta(days=1)).values()),
        start=ZERO,
    )
    valuacion_final = _valuacion_fifo_por_producto(fecha_corte=fin)
    inventario_final = sum((fila["valor"] for fila in valuacion_final.values()), start=ZERO)
    compras = _valor_compras_inventario(inicio, fin)
    costo_salidas_movimiento = _q2(inventario_inicial + compras - inventario_final)
    ventas_periodo = Venta.objects.filter(
        fecha_venta__year=periodo.year,
        fecha_venta__month=periodo.month,
    )
    costo_ventas = ZERO
    for venta in ventas_periodo.only("venta_neto_pedido", "ganancia_total"):
        costo_ventas += Decimal(venta.venta_neto_pedido or 0) - Decimal(venta.ganancia_total or 0)
    costo_ventas = _q2(costo_ventas)
    return {
        "inventario_inicial": _q2(inventario_inicial),
        "compras_inventario": compras,
        "inventario_final": _q2(inventario_final),
        "costo_ventas": costo_ventas,
        "costo_salidas_movimiento": costo_salidas_movimiento,
        "diferencia_temporal_costo": _q2(costo_ventas - costo_salidas_movimiento),
        "salidas_sin_recepcion_uprim": int(
            sum(
                (fila["salida_sin_recepcion_historica"] for fila in valuacion_final.values()),
                start=Decimal(0),
            )
        ),
        "deficit_inventario_uprim": int(
            sum((fila["deficit_pendiente"] for fila in valuacion_final.values()), start=Decimal(0))
        ),
    }


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

    costo_ventas = obtener_costo_ventas_periodo(periodo)
    margen_bruto = _q2(ventas_total_neto - costo_ventas["costo_ventas"])
    abonos = MovimientoBancario.objects.filter(
        fecha__year=periodo.year,
        fecha__month=periodo.month,
        tipo=MovimientoBancario.TIPO_ABONO,
    )
    pagos_confirmados = ConciliacionPago.objects.filter(
        movimiento__fecha__year=periodo.year,
        movimiento__fecha__month=periodo.month,
        estado=ConciliacionPago.ESTADO_CONFIRMADA,
    )

    return {
        "ventas_count": ventas.count(),
        "compras_count": compras.count(),
        "ventas_total_neto": ventas_total_neto,
        "ventas_total_iva": ventas_total_iva,
        "ventas_total": ventas_total,
        "compras_total_neto": compras_total_neto,
        "compras_total_iva": compras_total_iva,
        "compras_total": compras_total,
        **costo_ventas,
        "margen_bruto": margen_bruto,
        "abonos_bancarios_count": abonos.count(),
        "abonos_bancarios_total": _q2(abonos.aggregate(total=Sum("monto"))["total"]),
        "pagos_conciliados_total": _q2(pagos_confirmados.aggregate(total=Sum("monto_aplicado"))["total"]),
        "abonos_pendientes_count": abonos.filter(estado=MovimientoBancario.ESTADO_PENDIENTE).count(),
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
    reservas = _agregar_por_producto("RESERVA", fecha_corte=fecha_corte)
    despachos = _agregar_por_producto("DESPACHO", fecha_corte=fecha_corte)
    valuacion = _valuacion_fifo_por_producto(fecha_corte=fecha_corte)

    # Los packs son productos comerciales virtuales: su disponibilidad se
    # obtiene desde sus componentes y no constituye una existencia fisica
    # adicional. Incluirlos aqui duplicaria el catalogo de inventario y podria
    # inducir a sumar dos veces las mismas unidades.
    productos = Producto.objects.filter(tipo_producto="SIMPLE").order_by("nombre_producto")
    filas: list[dict] = []
    for prod in productos:
        qty_res = int(reservas.get(prod.id, 0))
        qty_des = int(despachos.get(prod.id, 0))
        resultado = valuacion.get(prod.id, {})
        qty_contable = int(resultado.get("cantidad", 0))
        qty_disp = qty_contable - qty_res
        costo_fifo = resultado.get("costo_unitario", ZERO)
        total_producto = resultado.get("valor", ZERO)
        capas = resultado.get("capas", [])
        capas_resumen = " | ".join(
            f"{capa['fecha'].isoformat()} R{capa['recepcion_id'] or '-'}: "
            f"{int(capa['cantidad'])} x ${capa['costo_unitario']:.2f}"
            for capa in capas
        )

        filas.append(
            {
                "codigo_interno": prod.codigo_producto_interno,
                "producto_id": prod.id,
                "producto": prod.nombre_producto,
                "cantidad_disponible_uprim": qty_disp,
                "cantidad_reservada_uprim": qty_res,
                "cantidad_existencia_contable_uprim": qty_contable,
                "cantidad_despachada_uprim": qty_des,
                "costo_unitario_fifo": costo_fifo,
                "valor_inventario_fifo": total_producto,
                "capas_fifo": capas_resumen,
                "salida_sin_capa_uprim": int(resultado.get("deficit_pendiente", 0)),
                "salida_sin_recepcion_historica_uprim": int(
                    resultado.get("salida_sin_recepcion_historica", 0)
                ),
                # Alias de compatibilidad para vistas que aun consumen estos nombres.
                "costo_unitario_compra": costo_fifo,
                "valor_producto_unitario": costo_fifo,
                "total_producto": total_producto,
                "valor_inventario_compra": total_producto,
                "costo_unitario_referencia": costo_fifo,
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
