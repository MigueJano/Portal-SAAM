"""
Dashboard - Vistas para la app Pedidos

Este módulo contiene las vistas relacionadas con la página principal del sistema (inicio)
y funciones de búsqueda general.

Fecha de documentación: 2025-08-08
"""

from django.shortcuts import render
from decimal import Decimal, ROUND_HALF_UP
from Apps.Pedidos.models import Recepcion, Pedido, Stock
from Apps.Pedidos.services.listaprecios_alertas import (
    filas_precios_cliente,
)

IVA_RATE = Decimal('0.19')
DOS_DEC = Decimal('0.01')


def _calcular_total_pedido_dashboard(pedido, movimiento_principal):
    if pedido.lineas.exists():
        total_neto = sum(
            (
                Decimal(linea.cantidad or 0) * Decimal(linea.precio_unitario or 0)
                for linea in pedido.lineas.all()
            ),
            start=Decimal('0'),
        )
    else:
        reservas = Stock.objects.filter(
            pedido=pedido,
            precio_unitario__isnull=False,
        )
        if movimiento_principal == 'DESPACHO':
            reservas = list(reservas.filter(tipo_movimiento='DESPACHO'))
            if not reservas:
                reservas = list(
                    Stock.objects.filter(
                        pedido=pedido,
                        precio_unitario__isnull=False,
                        tipo_movimiento__in=['RESERVA', 'DESPACHO'],
                    )
                )
        else:
            reservas = list(reservas.filter(tipo_movimiento='RESERVA'))

        total_neto = sum(
            (Decimal(reserva.qty or 0) * Decimal(reserva.precio_unitario or 0) for reserva in reservas),
            start=Decimal('0'),
        )

    total_neto = Decimal(total_neto).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva = (total_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    return (total_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def home(request):
    """
    Vista principal del sistema (inicio).

    Muestra:
    - Recepciones pendientes
    - Pedidos pendientes con totales
    - Pedidos entregados no pagados (con totales)

    Returns:
        HttpResponse: Renderiza home.html con datos de negocio.
    """
    recepciones_qs = Recepcion.objects.exclude(estado_recepcion='Finalizado').order_by('-fecha_recepcion')
    recepciones = list(recepciones_qs)
    cantidad_recepciones = len(recepciones)

    pedidos_qs = Pedido.objects.filter(estado_pedido='Pendiente').order_by('-fecha_pedido')
    pedidos = list(pedidos_qs)
    cantidad_pedidos_pendiente = len(pedidos)
    monto_pedidos_pendientes = Decimal('0.00')

    # Calcular total de cada pedido pendiente
    for pedido in pedidos:
        pedido.total_pedido_pendiente = _calcular_total_pedido_dashboard(
            pedido,
            movimiento_principal='RESERVA',
        )
        monto_pedidos_pendientes += pedido.total_pedido_pendiente

    pedidos_no_pagados = list(Pedido.objects.filter(estado_pedido='Entregado').order_by('-fecha_pedido'))
    monto_pedidos_no_pagados = Decimal('0.00')

    # Calcular total de cada pedido entregado no pagado
    for pedido in pedidos_no_pagados:
        pedido.total_pedido_no_pagado = _calcular_total_pedido_dashboard(
            pedido,
            movimiento_principal='DESPACHO',
        )
        monto_pedidos_no_pagados += pedido.total_pedido_no_pagado

    cantidad_pedidos_no_pagados = len(pedidos_no_pagados)

    filas_clientes = filas_precios_cliente()
    precios_cliente_bajo_costo = sorted(
        [
            row for row in filas_clientes
            if row["diferencia"] is not None and row["diferencia"] < 0
        ],
        key=lambda row: (row["diferencia"], row["cliente"], row["producto"]),
    )
    cantidad_precios_cliente_bajo_costo = len(precios_cliente_bajo_costo)
    precios_cliente_bajo_costo_preview = precios_cliente_bajo_costo[:5]

    return render(request, './views/dashboard/home.html', {
        'recepciones': recepciones,
        'cantidad_recepciones': cantidad_recepciones,
        'pedidos': pedidos,
        'pedidos_no_pagados': pedidos_no_pagados,
        'cantidad_pedidos_pendiente': cantidad_pedidos_pendiente,
        'cantidad_pedidos_no_pagados': cantidad_pedidos_no_pagados,
        'monto_pedidos_pendientes': monto_pedidos_pendientes,
        'monto_pedidos_no_pagados': monto_pedidos_no_pagados,
        'precios_cliente_bajo_costo': precios_cliente_bajo_costo_preview,
        'cantidad_precios_cliente_bajo_costo': cantidad_precios_cliente_bajo_costo,
        'precios_cliente_bajo_costo_restantes': max(
            cantidad_precios_cliente_bajo_costo - len(precios_cliente_bajo_costo_preview),
            0,
        ),
    })
