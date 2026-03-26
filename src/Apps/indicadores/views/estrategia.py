from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, IntegerField, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render

from Apps.Pedidos.models import Recepcion, UtilidadProducto, Venta
from .common import periodo_desde_request


def _mes_anterior(fecha: date):
    year = fecha.year
    month = fecha.month - 1
    if month == 0:
        month = 12
        year -= 1
    inicio = date(year, month, 1)
    fin = date(year, month, monthrange(year, month)[1])
    return inicio, fin


def _ultimos_meses(fin_periodo: date, n: int):
    meses = []
    cursor = date(fin_periodo.year, fin_periodo.month, 1)
    for _ in range(n):
        meses.append(cursor)
        year = cursor.year
        month = cursor.month - 1
        if month == 0:
            month = 12
            year -= 1
        cursor = date(year, month, 1)
    meses.reverse()
    return meses


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

    ventas_mensual_map = {row["mes"].date(): row["total"] for row in ventas_mensual_qs}
    compras_mensual_map = {row["mes"].date(): row["total"] for row in compras_mensual_qs}

    comparativo_rows = []
    for mes_inicio in meses_serie:
        v_total = ventas_mensual_map.get(mes_inicio, Decimal("0.00"))
        c_total = compras_mensual_map.get(mes_inicio, Decimal("0.00"))
        comparativo_rows.append(
            {
                "mes_label": mes_inicio.strftime("%b %Y").upper(),
                "ventas_total": v_total,
                "compras_total": c_total,
                "margen_bruto": v_total - c_total,
            }
        )

    kpis = {
        "ingresos": ventas_total,
        "ganancia_bruta": utilidad_periodo,
        "margen_utilidad": margen_utilidad,
        "compras_netas": compras_total,
        "ticket_promedio": ticket_promedio,
        "clientes_activos": clientes_activos,
        "crecimiento_ventas": crecimiento_ventas,
    }

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
        },
    )
