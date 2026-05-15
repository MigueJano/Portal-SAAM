from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, IntegerField, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from Apps.Pedidos.models import (
    Categoria,
    Cliente,
    ListaPrecios,
    ListaPreciosPredItem,
    ListaPreciosPredeterminada,
    Producto,
    Recepcion,
    Stock,
    Subcategoria,
    UtilidadProducto,
    Venta,
)
from Apps.Pedidos.services import costo_referencial_pack, es_pack
from Apps.indicadores.services.contabilidad import _normalizar_precio_unidad_primaria
from .common import periodo_desde_request


DOS_DEC = Decimal("0.01")
WINDOW_CHOICES = (
    (6, "Ultimos 6 meses"),
    (12, "Ultimos 12 meses"),
    (24, "Ultimos 24 meses"),
)


def _q2(valor):
    return Decimal(valor or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _promedio(valores):
    if not valores:
        return Decimal("0.00")
    return _q2(sum(valores, Decimal("0.00")) / Decimal(len(valores)))


def _month_start(fecha: date):
    return date(fecha.year, fecha.month, 1)


def _shift_month(fecha: date, delta: int):
    year = fecha.year
    month = fecha.month + delta
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return date(year, month, 1)


def _mes_anterior(fecha: date):
    inicio = _shift_month(_month_start(fecha), -1)
    fin = date(inicio.year, inicio.month, monthrange(inicio.year, inicio.month)[1])
    return inicio, fin


def _ultimos_meses(fin_periodo: date, n: int):
    meses = []
    cursor = date(fin_periodo.year, fin_periodo.month, 1)
    for _ in range(n):
        meses.append(cursor)
        cursor = _shift_month(cursor, -1)
    meses.reverse()
    return meses


def _fecha_mes(valor):
    return valor.date() if hasattr(valor, "date") else valor


def _historical_window_from_request(request):
    try:
        range_months = int(request.GET.get("range_months", 12))
    except (TypeError, ValueError):
        range_months = 12
    valid_ranges = {choice for choice, _ in WINDOW_CHOICES}
    if range_months not in valid_ranges:
        range_months = 12

    fin = timezone.localdate()
    inicio = _shift_month(_month_start(fin), -(range_months - 1))
    return range_months, inicio, fin


def _category_filters_from_request(request):
    categorias = Categoria.objects.all().order_by("categoria")

    try:
        categoria_id = int(request.GET.get("categoria", "") or 0) or None
    except (TypeError, ValueError):
        categoria_id = None

    try:
        subcategoria_id = int(request.GET.get("subcategoria", "") or 0) or None
    except (TypeError, ValueError):
        subcategoria_id = None

    selected_categoria = categorias.filter(pk=categoria_id).first() if categoria_id else None
    selected_subcategoria = None

    if subcategoria_id:
        selected_subcategoria = Subcategoria.objects.select_related("categoria").filter(pk=subcategoria_id).first()
        if selected_subcategoria:
            if selected_categoria and selected_subcategoria.categoria_id != selected_categoria.id:
                selected_subcategoria = None
                subcategoria_id = None
            elif not selected_categoria:
                selected_categoria = selected_subcategoria.categoria
                categoria_id = selected_categoria.id

    subcategorias = Subcategoria.objects.all().order_by("subcategoria")
    if selected_categoria:
        subcategorias = subcategorias.filter(categoria=selected_categoria)
        if subcategoria_id and not selected_subcategoria:
            selected_subcategoria = subcategorias.filter(pk=subcategoria_id).first()

    return {
        "categorias": categorias,
        "subcategorias": subcategorias,
        "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id,
        "selected_categoria": selected_categoria,
        "selected_subcategoria": selected_subcategoria,
    }


def _producto_filters(categoria_id=None, subcategoria_id=None):
    filtros = {}
    if categoria_id:
        filtros["producto__categoria_producto_id"] = categoria_id
    if subcategoria_id:
        filtros["producto__subcategoria_producto_id"] = subcategoria_id
    return filtros


def _precio_base_row(producto: Producto):
    return {
        "producto_id": producto.id,
        "categoria": producto.categoria_producto.categoria if producto.categoria_producto else "-",
        "subcategoria": producto.subcategoria_producto.subcategoria if producto.subcategoria_producto else "-",
        "codigo_interno": producto.codigo_producto_interno,
        "nombre": producto.nombre_producto,
        "precio_minimo_compra": None,
        "precio_maximo_compra": None,
        "precio_minimo_venta": None,
        "precio_maximo_venta": None,
        "referencias_compra": 0,
        "referencias_venta": 0,
        "dispersion_compra": None,
        "dispersion_venta": None,
        "margen_piso": None,
        "margen_techo": None,
    }


def _actualizar_rango(row: dict, *, minimo: str, maximo: str, valor):
    if valor is None:
        return

    valor = _q2(valor)
    if row[minimo] is None or valor < row[minimo]:
        row[minimo] = valor
    if row[maximo] is None or valor > row[maximo]:
        row[maximo] = valor


def _enriquecer_row_precios(row: dict):
    if row["precio_minimo_compra"] is not None and row["precio_maximo_compra"] is not None:
        row["dispersion_compra"] = _q2(row["precio_maximo_compra"] - row["precio_minimo_compra"])
    if row["precio_minimo_venta"] is not None and row["precio_maximo_venta"] is not None:
        row["dispersion_venta"] = _q2(row["precio_maximo_venta"] - row["precio_minimo_venta"])
    if row["precio_maximo_compra"] is not None and row["precio_minimo_venta"] is not None:
        row["margen_piso"] = _q2(row["precio_minimo_venta"] - row["precio_maximo_compra"])
    if row["precio_minimo_compra"] is not None and row["precio_maximo_venta"] is not None:
        row["margen_techo"] = _q2(row["precio_maximo_venta"] - row["precio_minimo_compra"])
    return row


def _filas_tabla_precios(inicio: date, fin: date, *, categoria_id=None, subcategoria_id=None):
    rows: dict[int, dict] = {}
    filtros_producto = _producto_filters(categoria_id, subcategoria_id)

    compras_qs = (
        Stock.objects.filter(
            recepcion__isnull=False,
            recepcion__fecha_recepcion__range=(inicio, fin),
            recepcion__estado_recepcion="Finalizado",
            tipo_movimiento="DISPONIBLE",
            precio_unitario__isnull=False,
            **filtros_producto,
        )
        .select_related("producto__categoria_producto", "producto__subcategoria_producto")
        .order_by("producto__nombre_producto", "recepcion__fecha_recepcion", "id")
    )
    for stock in compras_qs:
        row = rows.setdefault(stock.producto_id, _precio_base_row(stock.producto))
        row["referencias_compra"] += 1
        _actualizar_rango(
            row,
            minimo="precio_minimo_compra",
            maximo="precio_maximo_compra",
            valor=_normalizar_precio_unidad_primaria(stock),
        )

    ventas_qs = (
        UtilidadProducto.objects.filter(
            venta__fecha_venta__range=(inicio, fin),
            **filtros_producto,
        )
        .select_related("producto__categoria_producto", "producto__subcategoria_producto")
        .order_by("producto__nombre_producto", "venta__fecha_venta", "id")
    )
    for detalle in ventas_qs:
        row = rows.setdefault(detalle.producto_id, _precio_base_row(detalle.producto))
        row["referencias_venta"] += 1
        _actualizar_rango(
            row,
            minimo="precio_minimo_venta",
            maximo="precio_maximo_venta",
            valor=detalle.precio_venta_unitario,
        )

    return sorted(
        [_enriquecer_row_precios(row) for row in rows.values()],
        key=lambda row: (
            row["categoria"],
            row["subcategoria"],
            row["codigo_interno"],
            row["nombre"],
        ),
    )


def _detalle_compras_producto(producto: Producto, inicio: date, fin: date):
    compras_qs = (
        Stock.objects.filter(
            producto=producto,
            recepcion__isnull=False,
            recepcion__fecha_recepcion__range=(inicio, fin),
            recepcion__estado_recepcion="Finalizado",
            tipo_movimiento="DISPONIBLE",
            precio_unitario__isnull=False,
        )
        .select_related("recepcion__proveedor")
        .order_by("-recepcion__fecha_recepcion", "-recepcion__num_documento_recepcion", "-id")
    )

    return [
        {
            "fecha": stock.recepcion.fecha_recepcion,
            "documento": stock.recepcion.num_documento_recepcion,
            "tipo_documento": stock.recepcion.documento_recepcion,
            "proveedor": stock.recepcion.proveedor.nombre_proveedor,
            "empaque": stock.empaque,
            "precio_registrado": _q2(stock.precio_unitario),
            "precio_unitario": _normalizar_precio_unidad_primaria(stock),
        }
        for stock in compras_qs
    ]


def _detalle_ventas_producto(producto: Producto, inicio: date, fin: date):
    ventas_qs = (
        UtilidadProducto.objects.filter(
            producto=producto,
            venta__fecha_venta__range=(inicio, fin),
        )
        .select_related("venta__pedidoid__nombre_cliente")
        .order_by("-venta__fecha_venta", "-venta__num_documento", "-id")
    )

    return [
        {
            "fecha": detalle.venta.fecha_venta,
            "documento": detalle.venta.num_documento,
            "tipo_documento": detalle.venta.documento_pedido,
            "cliente": detalle.venta.pedidoid.nombre_cliente.nombre_cliente,
            "empaque": detalle.empaque,
            "precio_compra_unitario": _q2(detalle.precio_compra_unitario),
            "precio_unitario": _q2(detalle.precio_venta_unitario),
        }
        for detalle in ventas_qs
    ]


def _comparativo_mensual(fin: date):
    dec_15_2 = DecimalField(max_digits=15, decimal_places=2)
    meses_serie = _ultimos_meses(fin, 6)
    inicio_serie = meses_serie[0]

    ventas_mensual_qs = (
        Venta.objects.filter(fecha_venta__gte=inicio_serie, fecha_venta__lte=fin)
        .annotate(mes=TruncMonth("fecha_venta"))
        .values("mes")
        .annotate(total=Coalesce(Sum("venta_total_pedido"), Value(Decimal("0.00"), output_field=dec_15_2)))
    )
    compras_mensual_qs = (
        Recepcion.objects.filter(fecha_recepcion__gte=inicio_serie, fecha_recepcion__lte=fin)
        .exclude(estado_recepcion="Rechazado")
        .annotate(mes=TruncMonth("fecha_recepcion"))
        .values("mes")
        .annotate(total=Coalesce(Sum("total_neto_recepcion"), Value(Decimal("0.00"), output_field=dec_15_2)))
    )

    ventas_mensual_map = {_fecha_mes(row["mes"]): row["total"] for row in ventas_mensual_qs}
    compras_mensual_map = {_fecha_mes(row["mes"]): row["total"] for row in compras_mensual_qs}

    comparativo_rows = []
    for mes_inicio in meses_serie:
        ventas_total = ventas_mensual_map.get(mes_inicio, Decimal("0.00"))
        compras_total = compras_mensual_map.get(mes_inicio, Decimal("0.00"))
        comparativo_rows.append(
            {
                "mes_label": mes_inicio.strftime("%b %Y").upper(),
                "ventas_total": ventas_total,
                "compras_total": compras_total,
                "margen_bruto": ventas_total - compras_total,
            }
        )
    return comparativo_rows


def _lecturas_informe(kpis, top_clientes, top_productos, comparativo_rows):
    cliente_lider = top_clientes[0] if top_clientes else None
    producto_lider = top_productos[0] if top_productos else None
    mejor_mes = max(comparativo_rows, key=lambda row: row["ventas_total"], default=None)
    presion_compra = round((kpis["compras_netas"] / kpis["ingresos"]) * 100, 2) if kpis["ingresos"] else Decimal("0.00")

    return {
        "cliente_lider": cliente_lider,
        "producto_lider": producto_lider,
        "mejor_mes": mejor_mes,
        "presion_compra": presion_compra,
    }


def _resumen_estrategia_precios(pricing_rows):
    rows_con_referencia = [
        row
        for row in pricing_rows
        if row["precio_minimo_compra"] is not None and row["precio_minimo_venta"] is not None
    ]
    rows_con_alerta = [row for row in rows_con_referencia if row["margen_piso"] is not None and row["margen_piso"] <= 0]
    amplitudes_venta = [row["dispersion_venta"] for row in pricing_rows if row["dispersion_venta"] is not None]

    alertas_rows = sorted(
        [row for row in rows_con_referencia if row["margen_piso"] is not None],
        key=lambda row: (row["margen_piso"], row["nombre"]),
    )[:8]
    oportunidad_rows = sorted(
        [row for row in rows_con_referencia if row["margen_techo"] is not None],
        key=lambda row: (row["margen_techo"], row["nombre"]),
        reverse=True,
    )[:8]

    return {
        "productos_evaluados": len(pricing_rows),
        "productos_con_referencia": len(rows_con_referencia),
        "productos_en_riesgo": len(rows_con_alerta),
        "amplitud_promedio_venta": _promedio(amplitudes_venta),
        "alertas_rows": alertas_rows,
        "oportunidad_rows": oportunidad_rows,
    }


def _normalizar_precio_producto(producto: Producto, empaque: str, precio) -> Decimal:
    base = type(
        "PrecioProducto",
        (),
        {
            "producto": producto,
            "empaque": empaque,
            "precio_unitario": precio,
        },
    )()
    return _normalizar_precio_unidad_primaria(base)


def _nombre_empaque_producto(producto: Producto, empaque: str) -> str:
    nivel = (empaque or "").upper().strip()
    if nivel == "PRIMARIO" and producto.empaque_primario:
        return producto.empaque_primario.nombre
    if nivel == "SECUNDARIO" and producto.empaque_secundario:
        return producto.empaque_secundario.nombre
    if nivel == "TERCIARIO" and producto.empaque_terciario:
        return producto.empaque_terciario.nombre
    return nivel.title() if nivel else "-"


def _maximos_compra_por_producto(product_ids):
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

    maximos = {}
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


def _filas_lista_precios_vigentes(lista):
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


def _resumen_lista_precios_vigentes(rows):
    rows_con_compra = [row for row in rows if row["precio_compra"] is not None]
    rows_en_riesgo = [row for row in rows_con_compra if row["diferencia"] is not None and row["diferencia"] <= 0]

    return {
        "items_evaluados": len(rows),
        "items_con_compra": len(rows_con_compra),
        "items_en_riesgo": len(rows_en_riesgo),
        "diferencia_promedio": _promedio(
            [row["diferencia"] for row in rows_con_compra if row["diferencia"] is not None]
        ),
    }


def _filas_precios_cliente(cliente):
    if not cliente:
        return []

    items = list(
        ListaPrecios.objects.filter(nombre_cliente=cliente)
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


@login_required
def dashboard_estrategia(request):
    periodo, inicio, fin, meses = periodo_desde_request(request)
    inicio_prev, fin_prev = _mes_anterior(inicio)

    ventas_qs = Venta.objects.filter(fecha_venta__range=(inicio, fin))
    ventas_prev_qs = Venta.objects.filter(fecha_venta__range=(inicio_prev, fin_prev))
    compras_qs = Recepcion.objects.filter(fecha_recepcion__range=(inicio, fin)).exclude(estado_recepcion="Rechazado")

    dec_15_2 = DecimalField(max_digits=15, decimal_places=2)
    utilidad_total = Coalesce(Sum("ganancia_total"), Value(Decimal("0.00"), output_field=dec_15_2))

    ventas_neto = ventas_qs.aggregate(total=Coalesce(Sum("venta_neto_pedido"), Value(Decimal("0.00"), output_field=dec_15_2)))[
        "total"
    ]
    ventas_total = ventas_qs.aggregate(total=Coalesce(Sum("venta_total_pedido"), Value(Decimal("0.00"), output_field=dec_15_2)))[
        "total"
    ]
    ventas_total_prev = ventas_prev_qs.aggregate(
        total=Coalesce(Sum("venta_total_pedido"), Value(Decimal("0.00"), output_field=dec_15_2))
    )["total"]
    utilidad_periodo = ventas_qs.aggregate(total=utilidad_total)["total"]
    compras_total = compras_qs.aggregate(total=Coalesce(Sum("total_neto_recepcion"), Value(Decimal("0.00"), output_field=dec_15_2)))[
        "total"
    ]

    margen_utilidad = round((utilidad_periodo / ventas_neto) * 100, 2) if ventas_neto else Decimal("0.00")
    crecimiento_ventas = (
        round(((ventas_total - ventas_total_prev) / ventas_total_prev) * 100, 2) if ventas_total_prev else Decimal("0.00")
    )

    ventas_count = ventas_qs.count()
    ticket_promedio = round(ventas_total / ventas_count, 2) if ventas_count else Decimal("0.00")
    clientes_activos = ventas_qs.values("pedidoid__nombre_cliente").distinct().count()

    utilidad_linea_expr = ExpressionWrapper(
        F("cantidad") * F("utilidad"),
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )

    top_clientes = list(
        ventas_qs.values("pedidoid__nombre_cliente__nombre_cliente")
        .annotate(total=Coalesce(Sum("venta_total_pedido"), Value(Decimal("0.00"), output_field=dec_15_2)))
        .order_by("-total", "pedidoid__nombre_cliente__nombre_cliente")[:10]
    )
    top_productos = list(
        UtilidadProducto.objects.filter(venta__fecha_venta__range=(inicio, fin))
        .values("producto__codigo_producto_interno", "producto__nombre_producto")
        .annotate(
            unidades=Coalesce(Sum("cantidad"), Value(0, output_field=IntegerField())),
            utilidad_total=Coalesce(Sum(utilidad_linea_expr), Value(Decimal("0.00"), output_field=dec_15_2)),
        )
        .order_by("-unidades", "producto__nombre_producto")[:10]
    )

    comparativo_rows = _comparativo_mensual(fin)

    kpis = {
        "ingresos": ventas_total,
        "ganancia_bruta": utilidad_periodo,
        "margen_utilidad": margen_utilidad,
        "compras_netas": compras_total,
        "ticket_promedio": ticket_promedio,
        "clientes_activos": clientes_activos,
        "crecimiento_ventas": crecimiento_ventas,
    }
    lecturas = _lecturas_informe(kpis, top_clientes, top_productos, comparativo_rows)

    return render(
        request,
        "indicadores/estrategia.html",
        {
            "periodo": periodo,
            "meses": meses,
            "inicio": inicio,
            "fin": fin,
            "kpis": kpis,
            "top_clientes": top_clientes,
            "top_productos": top_productos,
            "comparativo_rows": comparativo_rows,
            **lecturas,
        },
    )


@login_required
def dashboard_estrategia_precios(request):
    filtros_categoria = _category_filters_from_request(request)
    range_months, inicio, fin = _historical_window_from_request(request)

    pricing_rows = _filas_tabla_precios(
        inicio,
        fin,
        categoria_id=filtros_categoria["categoria_id"],
        subcategoria_id=filtros_categoria["subcategoria_id"],
    )
    resumen = _resumen_estrategia_precios(pricing_rows)

    return render(
        request,
        "indicadores/estrategia_precios.html",
        {
            "inicio": inicio,
            "fin": fin,
            "range_months": range_months,
            "window_choices": WINDOW_CHOICES,
            "pricing_rows": pricing_rows,
            **filtros_categoria,
            **resumen,
        },
    )


@login_required
def dashboard_lista_precios_vigentes(request):
    listas = ListaPreciosPredeterminada.objects.all().order_by("nombre_listaprecios")

    try:
        lista_id = int(request.GET.get("lista", "") or 0) or None
    except (TypeError, ValueError):
        lista_id = None

    selected_lista = listas.filter(pk=lista_id).first() if lista_id else None
    if not selected_lista:
        selected_lista = listas.filter(activa=True).first() or listas.first()

    pricing_rows = _filas_lista_precios_vigentes(selected_lista)
    resumen = _resumen_lista_precios_vigentes(pricing_rows)

    return render(
        request,
        "indicadores/listas_precios_vigentes.html",
        {
            "listas": listas,
            "lista_id": selected_lista.id if selected_lista else None,
            "selected_lista": selected_lista,
            "pricing_rows": pricing_rows,
            **resumen,
        },
    )


@login_required
def dashboard_precios_cliente(request):
    clientes = Cliente.objects.all().order_by("nombre_cliente")

    try:
        cliente_id = int(request.GET.get("cliente", "") or 0) or None
    except (TypeError, ValueError):
        cliente_id = None

    selected_cliente = clientes.filter(pk=cliente_id).first() if cliente_id else None
    if not selected_cliente:
        selected_cliente = clientes.filter(cliente_activo=True).first() or clientes.first()

    pricing_rows = _filas_precios_cliente(selected_cliente)
    resumen = _resumen_lista_precios_vigentes(pricing_rows)

    return render(
        request,
        "indicadores/precios_cliente.html",
        {
            "clientes": clientes,
            "cliente_id": selected_cliente.id if selected_cliente else None,
            "selected_cliente": selected_cliente,
            "pricing_rows": pricing_rows,
            **resumen,
        },
    )


@login_required
def detalle_precios_estrategia(request, producto_id):
    range_months, inicio, fin = _historical_window_from_request(request)
    filtros_categoria = _category_filters_from_request(request)
    producto = get_object_or_404(
        Producto.objects.select_related("categoria_producto", "subcategoria_producto"),
        pk=producto_id,
    )
    compras_detalle = _detalle_compras_producto(producto, inicio, fin)
    ventas_detalle = _detalle_ventas_producto(producto, inicio, fin)

    return render(
        request,
        "indicadores/estrategia_detalle_precios.html",
        {
            "inicio": inicio,
            "fin": fin,
            "range_months": range_months,
            "producto": producto,
            "compras_detalle": compras_detalle,
            "ventas_detalle": ventas_detalle,
            **filtros_categoria,
        },
    )
