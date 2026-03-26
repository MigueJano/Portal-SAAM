from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, F, IntegerField, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from Apps.Pedidos.models import MovimientoStockHistorico, Producto, Stock
from Apps.indicadores.services.contabilidad import _normalizar_precio_unidad_primaria, filas_stock_contable
from .common import periodo_desde_request


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


def _stock_relacion(movimiento):
    return getattr(movimiento, "stock", None) or movimiento


def _producto_movimiento(movimiento):
    base = _stock_relacion(movimiento)
    return getattr(base, "producto", None)


def _qty_unidad_movimiento(movimiento) -> int:
    producto = _producto_movimiento(movimiento)
    empaque = (getattr(movimiento, "empaque", "") or "").upper().strip()
    qty = int(getattr(movimiento, "qty", 0) or 0)
    if empaque == "TERCIARIO":
        return qty * int(producto.qty_terciario or 1) * int(producto.qty_secundario or 1)
    if empaque == "SECUNDARIO":
        return qty * int(producto.qty_secundario or 1)
    return qty


def _normalizar_precio_movimiento(movimiento) -> Decimal:
    precio_unitario = getattr(movimiento, "precio_unitario", None)
    if precio_unitario is None:
        return Decimal("0.00")

    producto = _producto_movimiento(movimiento)
    base = type(
        "MovimientoValor",
        (),
        {
            "producto": producto,
            "empaque": getattr(movimiento, "empaque", ""),
            "precio_unitario": precio_unitario,
        },
    )()
    return _normalizar_precio_unidad_primaria(base)


def _tipo_transaccion_label(movimiento, *, reserva_pendiente: bool = False) -> str:
    base_rel = _stock_relacion(movimiento)

    if movimiento.tipo_movimiento in {"DISPONIBLE", "RECEPCION"}:
        base = "Entrada"
    elif movimiento.tipo_movimiento == "RESERVA":
        base = "Reserva pendiente" if reserva_pendiente else "Reserva"
    elif movimiento.tipo_movimiento == "DESPACHO":
        base = "Salida - Despacho"
    else:
        base = movimiento.tipo_movimiento.title()

    if getattr(base_rel, "recepcion_id", None) and base_rel.recepcion:
        return f"{base} / {base_rel.recepcion.documento_recepcion} #{base_rel.recepcion.num_documento_recepcion}"
    if getattr(base_rel, "pedido_id", None):
        return f"{base} / Pedido #{base_rel.pedido_id}"
    return base


def _cliente_proveedor_label(movimiento) -> str:
    base_rel = _stock_relacion(movimiento)
    if getattr(base_rel, "recepcion_id", None) and base_rel.recepcion and base_rel.recepcion.proveedor_id:
        return base_rel.recepcion.proveedor.nombre_proveedor
    if getattr(base_rel, "pedido_id", None) and base_rel.pedido and base_rel.pedido.nombre_cliente_id:
        return base_rel.pedido.nombre_cliente.nombre_cliente
    return "Sin cliente/proveedor"


def _responsable_label(movimiento) -> str:
    responsable = getattr(movimiento, "responsable", None)
    if not responsable:
        return "Sin responsable registrado"
    return responsable.get_full_name().strip() or responsable.username


def _delta_subtotal(tipo_movimiento: str, cantidad: int, *, es_legado: bool = False) -> int:
    if tipo_movimiento == "DESPACHO":
        return -cantidad
    if tipo_movimiento == "RESERVA":
        return 0
    if tipo_movimiento == "RECEPCION":
        return cantidad
    if tipo_movimiento == "DISPONIBLE":
        return cantidad if es_legado else 0
    return 0


@login_required
def dashboard_inventario(request):
    periodo, inicio, fin, meses = periodo_desde_request(request)

    filtro_stock = request.GET.get("stock_view", "todos")
    stock_rows_base = filas_stock_contable(periodo)
    if filtro_stock == "con_stock":
        stock_rows = [row for row in stock_rows_base if row["cantidad_disponible_uprim"] > 0]
    else:
        filtro_stock = "todos"
        stock_rows = stock_rows_base

    minimos = {
        p.codigo_producto_interno: int(p.qty_minima or 0)
        for p in Producto.objects.only("codigo_producto_interno", "qty_minima")
    }
    criticos = [
        row
        for row in stock_rows
        if row["cantidad_disponible_uprim"] <= int(minimos.get(row["codigo_interno"], 0))
    ]
    criticos.sort(key=lambda row: row["cantidad_disponible_uprim"] - int(minimos.get(row["codigo_interno"], 0)))

    total_stock_ref = sum((row["total_producto"] for row in stock_rows), start=Decimal("0.00"))
    kpis = {
        "productos_total": len(stock_rows),
        "productos_criticos": len(criticos),
        "unidades_disponibles": sum((row["cantidad_disponible_uprim"] for row in stock_rows), start=0),
        "unidades_despachadas": sum((row["cantidad_despachada_uprim"] for row in stock_rows), start=0),
        "valor_total_inventario": total_stock_ref,
    }

    movimientos_qs = Stock.objects.filter(fecha_movimiento__date__range=(inicio, fin)).annotate(
        qty_unidad=_qty_unidad_expr()
    )
    tipo_labels = dict(Stock.MOVIMIENTO_CHOICES)

    movimientos_tipo = list(
        movimientos_qs.values("tipo_movimiento")
        .annotate(
            movimientos=Count("id"),
            unidades=Coalesce(Sum("qty_unidad"), Value(0, output_field=IntegerField())),
        )
        .order_by("tipo_movimiento")
    )
    for row in movimientos_tipo:
        row["tipo_label"] = tipo_labels.get(row["tipo_movimiento"], row["tipo_movimiento"])

    movimientos_rows = list(
        movimientos_qs.values(
            "producto__codigo_producto_interno",
            "producto__nombre_producto",
            "tipo_movimiento",
        )
        .annotate(
            movimientos=Count("id"),
            unidades=Coalesce(Sum("qty_unidad"), Value(0, output_field=IntegerField())),
        )
        .order_by("producto__nombre_producto", "tipo_movimiento")
    )
    for row in movimientos_rows:
        row["tipo_label"] = tipo_labels.get(row["tipo_movimiento"], row["tipo_movimiento"])

    return render(
        request,
        "indicadores/inventario.html",
        {
            "periodo": periodo,
            "meses": meses,
            "inicio": inicio,
            "fin": fin,
            "filtro_stock": filtro_stock,
            "productos_total_general": len(stock_rows_base),
            "productos_con_stock": sum(1 for row in stock_rows_base if row["cantidad_disponible_uprim"] > 0),
            "kpis": kpis,
            "stock_rows": stock_rows,
            "criticos_rows": criticos[:20],
            "movimientos_tipo": movimientos_tipo,
            "movimientos_rows": movimientos_rows,
        },
    )


@login_required
def flujo_inventario_producto(request, producto_id):
    producto = get_object_or_404(
        Producto.objects.select_related("empaque_primario", "empaque_secundario", "empaque_terciario"),
        pk=producto_id,
    )
    historico = list(
        MovimientoStockHistorico.objects.filter(stock__producto=producto)
        .select_related(
            "responsable",
            "stock__producto",
            "stock__recepcion__proveedor",
            "stock__pedido__nombre_cliente",
        )
        .order_by("fecha_movimiento", "id")
    )
    legacy = list(
        Stock.objects.filter(producto=producto)
        .select_related("producto", "recepcion__proveedor", "pedido__nombre_cliente")
        .annotate(historial_count=Count("historial_movimientos"))
        .filter(historial_count=0)
        .order_by("fecha_movimiento", "id")
    )

    fuentes = [
        {
            "obj": movimiento,
            "fecha": movimiento.fecha_movimiento,
            "sort_id": movimiento.id,
            "es_legado": False,
        }
        for movimiento in historico
    ]
    fuentes.extend(
        {
            "obj": movimiento,
            "fecha": movimiento.fecha_movimiento,
            "sort_id": movimiento.id,
            "es_legado": True,
        }
        for movimiento in legacy
    )
    fuentes.sort(key=lambda item: (item["fecha"], item["sort_id"]))

    movimientos_rows = []
    subtotal = 0
    subtotal_entradas = 0
    subtotal_salidas = 0
    reservas_pendientes = 0

    for fuente in fuentes:
        movimiento = fuente["obj"]
        cantidad = _qty_unidad_movimiento(movimiento)
        valor_unitario = _normalizar_precio_movimiento(movimiento)
        total = (Decimal(cantidad) * valor_unitario).quantize(Decimal("0.01"))
        base_rel = _stock_relacion(movimiento)
        reserva_pendiente = movimiento.tipo_movimiento == "RESERVA" and getattr(base_rel, "tipo_movimiento", "") == "RESERVA"
        delta = _delta_subtotal(movimiento.tipo_movimiento, cantidad, es_legado=fuente["es_legado"])

        if delta > 0:
            subtotal_entradas += delta
        elif delta < 0:
            subtotal_salidas += abs(delta)
        if reserva_pendiente:
            reservas_pendientes += cantidad

        subtotal += delta

        if movimiento.tipo_movimiento == "DESPACHO":
            fecha_class = "text-danger"
        elif movimiento.tipo_movimiento in {"DISPONIBLE", "RECEPCION"}:
            fecha_class = "text-success"
        else:
            fecha_class = "text-warning"

        movimientos_rows.append(
            {
                "movimiento_id": movimiento.id,
                "fecha": fuente["fecha"],
                "transaccion": _tipo_transaccion_label(movimiento, reserva_pendiente=reserva_pendiente),
                "cantidad": cantidad,
                "valor": valor_unitario,
                "total": total,
                "subtotal": subtotal,
                "cliente_proveedor": _cliente_proveedor_label(movimiento),
                "responsable": _responsable_label(movimiento),
                "es_salida": movimiento.tipo_movimiento == "DESPACHO",
                "es_reserva": movimiento.tipo_movimiento == "RESERVA",
                "fecha_class": fecha_class,
            }
        )

    return render(
        request,
        "indicadores/flujo_inventario.html",
        {
            "producto": producto,
            "movimientos_rows": movimientos_rows,
            "subtotal_entradas": subtotal_entradas,
            "subtotal_salidas": subtotal_salidas,
            "reservas_pendientes": reservas_pendientes,
            "subtotal_final": subtotal,
            "year": request.GET.get("year", ""),
            "month": request.GET.get("month", ""),
            "stock_view": request.GET.get("stock_view", "todos"),
        },
    )
