from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Sum

from Apps.Pedidos.models import PedidoEstadoEvento, Recepcion

from .models import AccionOperacional, RegistroTiempo


DOS_DEC = Decimal("0.01")
ESTADO_POR_BASE = {
    AccionOperacional.DESPACHADO: "Despachado",
    AccionOperacional.ENTREGADO: "Entregado",
    AccionOperacional.PAGADO: "Pagado",
    AccionOperacional.RECEPCION: "Recepcion",
}


def _q2(valor):
    return Decimal(valor or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def costos_configurados_pedido(pedido):
    """Calcula los costos del pedido solo desde sus hitos y la configuracion activa."""
    eventos = {
        evento.estado: evento
        for evento in pedido.eventos_estado.all()
    }
    bases_pedido = {
        AccionOperacional.DESPACHADO,
        AccionOperacional.ENTREGADO,
        AccionOperacional.PAGADO,
    }
    filas = []
    total = Decimal("0")
    for accion in AccionOperacional.objects.filter(
        activa=True,
        base_calculo__in=bases_pedido,
    ):
        estado = ESTADO_POR_BASE[accion.base_calculo]
        evento = eventos.get(estado)
        if not evento:
            continue
        minutos = accion.minutos_estandar if accion.tipo_costo == AccionOperacional.TIEMPO else 0
        costo_tiempo = _q2(Decimal(minutos) * accion.valor_hora / Decimal("60"))
        costo_fijo = _q2(accion.costo_fijo_evento)
        costo_total = _q2(costo_tiempo + costo_fijo)
        filas.append({
            "accion": accion,
            "evento": evento,
            "minutos": minutos,
            "costo_tiempo": costo_tiempo,
            "costo_fijo": costo_fijo,
            "total": costo_total,
        })
        total += costo_total
    return {"filas": filas, "total": _q2(total)}


def carga_estandar_hitos(desde, hasta):
    recuentos = {
        fila["estado"]: fila["cantidad"]
        for fila in PedidoEstadoEvento.objects.filter(
            ocurrido_en__date__range=(desde, hasta),
            estado__in=tuple(ESTADO_POR_BASE.values()),
        ).values("estado").annotate(cantidad=Count("pedido_id"))
    }
    recuentos["Recepcion"] = Recepcion.objects.filter(
        estado_recepcion="Finalizado",
        fecha_recepcion__range=(desde, hasta),
    ).count()
    filas = []
    for accion in AccionOperacional.objects.filter(activa=True).exclude(
        base_calculo=AccionOperacional.MANUAL
    ):
        cantidad = recuentos.get(ESTADO_POR_BASE[accion.base_calculo], 0)
        minutos = cantidad * accion.minutos_estandar if accion.tipo_costo == AccionOperacional.TIEMPO else 0
        costo_tiempo = _q2(Decimal(minutos) * accion.valor_hora / Decimal("60"))
        costo_fijo = _q2(Decimal(cantidad) * accion.costo_fijo_evento)
        filas.append({
            "accion": accion,
            "cantidad": cantidad,
            "minutos": minutos,
            "costo_tiempo": costo_tiempo,
            "costo_fijo": costo_fijo,
            "total": _q2(costo_tiempo + costo_fijo),
        })
    return filas


def resumen_costos_operacionales(desde, hasta):
    """Combina tiempo real con estándar faltante y separa gastos fijos."""
    estandar = {fila["accion"].id: fila for fila in carga_estandar_hitos(desde, hasta)}
    reales_qs = RegistroTiempo.objects.filter(
        estado=RegistroTiempo.FINALIZADO,
        iniciado_en__date__range=(desde, hasta),
    )
    reales = {
        fila["accion_id"]: fila
        for fila in reales_qs.values("accion_id").annotate(
            registros=Count("id"),
            pedidos_medidos=Count("pedido_id", distinct=True),
            recepciones_medidas=Count("recepcion_id", distinct=True),
            minutos=Sum("minutos_reales"),
            costo=Sum("costo"),
        )
    }

    filas = []
    total_tiempo_real = Decimal("0")
    total_tiempo_estimado = Decimal("0")
    total_gastos_fijos = Decimal("0")
    total_bencina = Decimal("0")
    acciones = AccionOperacional.objects.filter(activa=True)
    for accion in acciones:
        fila_estandar = estandar.get(accion.id)
        fila_real = reales.get(accion.id, {})
        cantidad_hitos = fila_estandar["cantidad"] if fila_estandar else 0
        referencias_medidas = (
            fila_real.get("recepciones_medidas") or 0
            if accion.base_calculo == AccionOperacional.RECEPCION
            else fila_real.get("pedidos_medidos") or 0
        )
        faltantes = max(cantidad_hitos - referencias_medidas, 0)
        costo_real = _q2(fila_real.get("costo")) if accion.tipo_costo == AccionOperacional.TIEMPO else Decimal("0")
        minutos_reales = fila_real.get("minutos") or 0 if accion.tipo_costo == AccionOperacional.TIEMPO else 0
        minutos_estimados = faltantes * accion.minutos_estandar if accion.tipo_costo == AccionOperacional.TIEMPO else 0
        costo_estimado = _q2(Decimal(minutos_estimados) * accion.valor_hora / Decimal("60"))
        costo_fijo = fila_estandar["costo_fijo"] if fila_estandar else Decimal("0")
        if not (cantidad_hitos or fila_real.get("registros") or costo_fijo):
            continue
        total_tiempo_real += costo_real
        total_tiempo_estimado += costo_estimado
        total_gastos_fijos += costo_fijo
        if accion.nombre.strip().casefold() == "bencina":
            total_bencina += costo_fijo
        filas.append({
            "accion": accion,
            "cantidad": cantidad_hitos,
            "registros_reales": fila_real.get("registros") or 0,
            "minutos_reales": minutos_reales,
            "minutos_estimados": minutos_estimados,
            "costo_real": costo_real,
            "costo_estimado": costo_estimado,
            "costo_fijo": costo_fijo,
            "total": _q2(costo_real + costo_estimado + costo_fijo),
        })
    return {
        "filas": filas,
        "costo_tiempo_real": _q2(total_tiempo_real),
        "costo_tiempo_estimado": _q2(total_tiempo_estimado),
        "costo_tiempo_total": _q2(total_tiempo_real + total_tiempo_estimado),
        "gastos_fijos": _q2(total_gastos_fijos),
        "bencina": _q2(total_bencina),
        "otros_gastos_fijos": _q2(total_gastos_fijos - total_bencina),
        "total": _q2(total_tiempo_real + total_tiempo_estimado + total_gastos_fijos),
    }
