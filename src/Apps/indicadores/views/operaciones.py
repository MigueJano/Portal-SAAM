from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render

from Apps.Pedidos.models import Pedido, Recepcion, Venta
from .common import periodo_desde_request


@login_required
def dashboard_operaciones(request):
    periodo, inicio, fin, meses = periodo_desde_request(request)

    recepciones_qs = (
        Recepcion.objects.filter(fecha_recepcion__range=(inicio, fin))
        .select_related("proveedor")
        .order_by("-fecha_recepcion", "-id")
    )

    ventas_periodo = list(
        Venta.objects.filter(fecha_venta__range=(inicio, fin))
        .values(
            "pedidoid_id",
            "fecha_venta",
            "documento_pedido",
            "num_documento",
            "venta_neto_pedido",
            "venta_total_pedido",
        )
        .order_by("-fecha_venta")
    )

    # El periodo de Operaciones representa el cierre comercial. Un pedido
    # pertenece al mes cuando su venta se registra dentro del periodo, aunque
    # el pedido se haya creado en un mes anterior.
    pedidos_qs = (
        Pedido.objects.filter(id__in={venta["pedidoid_id"] for venta in ventas_periodo})
        .select_related("nombre_cliente")
        .order_by("-fecha_pedido", "-id")
    )
    venta_por_pedido = {}
    for venta in ventas_periodo:
        venta_por_pedido.setdefault(venta["pedidoid_id"], venta)

    pedidos_rows = []
    dias_ciclo_vals = []
    for pedido in pedidos_qs:
        venta = venta_por_pedido.get(pedido.id)
        dias_ciclo = None
        if venta:
            dias_ciclo = (venta["fecha_venta"] - pedido.fecha_pedido).days
            if dias_ciclo >= 0:
                dias_ciclo_vals.append(dias_ciclo)

        pedidos_rows.append(
            {
                "id": pedido.id,
                "fecha_pedido": pedido.fecha_pedido,
                "cliente": pedido.nombre_cliente.nombre_cliente,
                "estado_pedido": pedido.estado_pedido,
                "fecha_venta": venta["fecha_venta"] if venta else None,
                "documento_venta": venta["documento_pedido"] if venta else "",
                "folio_venta": venta["num_documento"] if venta else "",
                "dias_ciclo": dias_ciclo,
                "neto_sin_iva": venta["venta_neto_pedido"] if venta else None,
                "total_con_iva": venta["venta_total_pedido"] if venta else None,
            }
        )

    pedidos_rows.sort(key=lambda row: (row["fecha_venta"], row["id"]), reverse=True)

    total_pedidos = len(pedidos_rows)
    pedidos_con_venta = len(venta_por_pedido)
    pedidos_pendientes = max(total_pedidos - pedidos_con_venta, 0)
    cumplimiento = round((pedidos_con_venta / total_pedidos) * 100, 2) if total_pedidos else 0
    ciclo_promedio = round(sum(dias_ciclo_vals) / len(dias_ciclo_vals), 1) if dias_ciclo_vals else None

    recepciones_ok = recepciones_qs.filter(estado_recepcion__in=["Recibido", "Finalizado"]).count()
    recepciones_rech = recepciones_qs.filter(estado_recepcion="Rechazado").count()
    total_recepciones = recepciones_qs.count()

    kpis = {
        "total_pedidos": total_pedidos,
        "pedidos_cumplidos": pedidos_con_venta,
        "pedidos_pendientes": pedidos_pendientes,
        "cumplimiento": cumplimiento,
        "ciclo_promedio_dias": ciclo_promedio,
        "recepciones_total": total_recepciones,
        "recepciones_ok": recepciones_ok,
        "recepciones_rechazadas": recepciones_rech,
    }

    resumen_pedidos_por_estado = {}
    for pedido in pedidos_rows:
        estado = pedido["estado_pedido"]
        resumen = resumen_pedidos_por_estado.setdefault(
            estado,
            {"estado_pedido": estado, "cantidad": 0, "neto_sin_iva": 0, "total_con_iva": 0},
        )
        resumen["cantidad"] += 1
        resumen["neto_sin_iva"] += pedido["neto_sin_iva"] or 0
        resumen["total_con_iva"] += pedido["total_con_iva"] or 0
    resumen_pedidos_estado = sorted(
        resumen_pedidos_por_estado.values(), key=lambda row: row["cantidad"], reverse=True
    )
    resumen_recepciones_estado = list(
        recepciones_qs.values("estado_recepcion")
        .annotate(
            cantidad=Count("id"),
            neto_sin_iva=Sum("total_neto_recepcion"),
            total_con_iva=Sum("total_recepcion"),
        )
        .order_by("-cantidad")
    )

    return render(
        request,
        "indicadores/operaciones.html",
        {
            "periodo": periodo,
            "meses": meses,
            "inicio": inicio,
            "fin": fin,
            "kpis": kpis,
            "pedidos_rows": pedidos_rows,
            "recepciones_rows": recepciones_qs,
            "resumen_pedidos_estado": resumen_pedidos_estado,
            "resumen_recepciones_estado": resumen_recepciones_estado,
        },
    )
