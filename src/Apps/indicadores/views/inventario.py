from datetime import date
from decimal import Decimal
import unicodedata

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from Apps.Pedidos.models import Producto, Stock, Venta
from Apps.indicadores.services.contabilidad import _normalizar_precio_unidad_primaria, filas_stock_contable
from .common import periodo_desde_request

INVENTARIO_TEMPLATE = "views/producto/stock_productos.html"


def _stock_relacion(movimiento):
    return movimiento


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


def _tipo_transaccion_label(movimiento) -> str:
    base_rel = _stock_relacion(movimiento)

    if movimiento.tipo_movimiento == "DISPONIBLE":
        base = "Entrada"
    elif movimiento.tipo_movimiento == "RESERVA":
        base = "Reserva"
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


def _ventas_por_pedido_ids(pedido_ids):
    if not pedido_ids:
        return {}

    ventas = (
        Venta.objects.filter(pedidoid_id__in=pedido_ids)
        .select_related("pedidoid")
        .order_by("pedidoid_id", "-fecha_venta", "-id")
    )

    ventas_por_pedido = {}
    for venta in ventas:
        ventas_por_pedido.setdefault(venta.pedidoid_id, venta)
    return ventas_por_pedido


def _fecha_referencia_movimiento(movimiento, ventas_por_pedido):
    base_rel = _stock_relacion(movimiento)
    fecha_movimiento = getattr(movimiento, "fecha_movimiento", None)

    if getattr(base_rel, "recepcion_id", None) and base_rel.recepcion and base_rel.recepcion.fecha_recepcion:
        return base_rel.recepcion.fecha_recepcion, fecha_movimiento

    pedido_id = getattr(base_rel, "pedido_id", None)
    venta = ventas_por_pedido.get(pedido_id) if pedido_id else None
    if venta and venta.fecha_venta:
        return venta.fecha_venta, fecha_movimiento

    if getattr(base_rel, "fecha_reserva", None):
        return base_rel.fecha_reserva, fecha_movimiento

    if getattr(base_rel, "pedido_id", None) and base_rel.pedido and base_rel.pedido.fecha_pedido:
        return base_rel.pedido.fecha_pedido, fecha_movimiento

    return fecha_movimiento, fecha_movimiento


def _sort_key_fuente(item):
    fecha_base = item["fecha"] or item["fecha_movimiento"] or getattr(item["obj"], "fecha_reserva", None) or date.min
    fecha_movimiento = item["fecha_movimiento"] or getattr(item["obj"], "fecha_reserva", None) or fecha_base
    return (
        fecha_base,
        fecha_movimiento,
        item["sort_id"],
    )


def _delta_subtotal(tipo_movimiento: str, cantidad: int) -> int:
    if tipo_movimiento == "DESPACHO":
        return -cantidad
    if tipo_movimiento == "RESERVA":
        return 0
    if tipo_movimiento == "DISPONIBLE":
        return cantidad
    return 0


def _normalizar_texto_busqueda(valor) -> str:
    texto = str(valor or "").strip().casefold()
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )


def _coincide_busqueda_stock(row: dict, termino: str) -> bool:
    termino_normalizado = _normalizar_texto_busqueda(termino)
    if not termino_normalizado:
        return True

    return (
        termino_normalizado in _normalizar_texto_busqueda(row.get("codigo_interno"))
        or termino_normalizado in _normalizar_texto_busqueda(row.get("producto"))
    )


def render_informe_inventario(request):
    periodo, inicio, fin, meses = periodo_desde_request(request)

    minimos = {
        p.codigo_producto_interno: int(p.qty_minima or 0)
        for p in Producto.objects.only("codigo_producto_interno", "qty_minima")
    }

    filtro_stock = request.GET.get("stock_view", "todos")
    search_term = (request.GET.get("q") or "").strip()
    stock_rows_base = [
        row
        for row in filas_stock_contable(periodo)
        if _coincide_busqueda_stock(row, search_term)
    ]
    for row in stock_rows_base:
        qty_minima = int(minimos.get(row["codigo_interno"], 0))
        row["qty_minima"] = qty_minima
        row["es_critico"] = row["cantidad_disponible_uprim"] <= qty_minima

    if filtro_stock == "con_stock":
        stock_rows = [row for row in stock_rows_base if row["cantidad_disponible_uprim"] > 0]
    else:
        filtro_stock = "todos"
        stock_rows = stock_rows_base

    total_stock_ref = sum((row["total_producto"] for row in stock_rows), start=Decimal("0.00"))
    kpis = {
        "productos_total": len(stock_rows),
        "unidades_disponibles": sum((row["cantidad_disponible_uprim"] for row in stock_rows), start=0),
        "unidades_reservadas": sum((row["cantidad_reservada_uprim"] for row in stock_rows), start=0),
        "valor_total_inventario": total_stock_ref,
    }

    return render(
        request,
        INVENTARIO_TEMPLATE,
        {
            "periodo": periodo,
            "meses": meses,
            "inicio": inicio,
            "fin": fin,
            "filtro_stock": filtro_stock,
            "search_term": search_term,
            "productos_total_general": len(stock_rows_base),
            "productos_con_stock": sum(1 for row in stock_rows_base if row["cantidad_disponible_uprim"] > 0),
            "kpis": kpis,
            "stock_rows": stock_rows,
        },
    )


@login_required
def dashboard_inventario(request):
    destino = reverse("stock_productos")
    query = request.GET.urlencode()
    if query:
        destino = f"{destino}?{query}"
    return redirect(destino)


@login_required
def flujo_inventario_producto(request, producto_id):
    producto = get_object_or_404(
        Producto.objects.select_related("empaque_primario", "empaque_secundario", "empaque_terciario"),
        pk=producto_id,
    )
    movimientos = list(
        Stock.objects.filter(producto=producto)
        .select_related("responsable", "producto", "recepcion__proveedor", "pedido__nombre_cliente")
        .order_by("fecha_movimiento", "id")
    )

    pedido_ids = {
        movimiento.pedido_id
        for movimiento in movimientos
        if movimiento.pedido_id
    }
    ventas_por_pedido = _ventas_por_pedido_ids(pedido_ids)

    fuentes = []
    for movimiento in movimientos:
        fecha_referencia, fecha_movimiento = _fecha_referencia_movimiento(movimiento, ventas_por_pedido)
        fuentes.append(
            {
                "obj": movimiento,
                "fecha": fecha_referencia,
                "fecha_movimiento": fecha_movimiento,
                "sort_id": movimiento.id,
            }
        )

    fuentes.sort(key=_sort_key_fuente)

    reservas_pendientes = sum(
        _qty_unidad_movimiento(fuente["obj"])
        for fuente in fuentes
        if fuente["obj"].tipo_movimiento == "RESERVA"
        and getattr(_stock_relacion(fuente["obj"]), "tipo_movimiento", "") == "RESERVA"
    )

    movimientos_rows = []
    subtotal = 0
    subtotal_entradas = 0
    subtotal_salidas = 0

    for fuente in fuentes:
        movimiento = fuente["obj"]
        if movimiento.tipo_movimiento == "RESERVA":
            continue

        cantidad = _qty_unidad_movimiento(movimiento)
        valor_unitario = _normalizar_precio_movimiento(movimiento)
        total = (Decimal(cantidad) * valor_unitario).quantize(Decimal("0.01"))
        delta = _delta_subtotal(movimiento.tipo_movimiento, cantidad)

        if delta > 0:
            subtotal_entradas += delta
        elif delta < 0:
            subtotal_salidas += abs(delta)

        subtotal += delta

        if movimiento.tipo_movimiento == "DESPACHO":
            fecha_class = "text-danger"
        elif movimiento.tipo_movimiento == "DISPONIBLE":
            fecha_class = "text-success"
        else:
            fecha_class = "text-warning"

        movimientos_rows.append(
            {
                "movimiento_id": movimiento.id,
                "fecha": fuente["fecha"],
                "transaccion": _tipo_transaccion_label(movimiento),
                "cantidad": cantidad,
                "valor": valor_unitario,
                "total": total,
                "subtotal": subtotal,
                "cliente_proveedor": _cliente_proveedor_label(movimiento),
                "responsable": _responsable_label(movimiento),
                "es_salida": movimiento.tipo_movimiento == "DESPACHO",
                "es_reserva": False,
                "fecha_class": fecha_class,
            }
        )

    stock_disponible = subtotal - reservas_pendientes

    return render(
        request,
        "indicadores/flujo_inventario.html",
        {
            "producto": producto,
            "movimientos_rows": movimientos_rows,
            "subtotal_entradas": subtotal_entradas,
            "subtotal_salidas": subtotal_salidas,
            "reservas_pendientes": reservas_pendientes,
            "subtotal_final": stock_disponible,
            "year": request.GET.get("year", ""),
            "month": request.GET.get("month", ""),
            "stock_view": request.GET.get("stock_view", "todos"),
            "search_term": (request.GET.get("q") or "").strip(),
        },
    )
