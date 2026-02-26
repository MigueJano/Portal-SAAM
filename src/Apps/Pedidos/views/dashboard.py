"""
Dashboard - Vistas para la app Pedidos

Este módulo contiene las vistas relacionadas con la página principal del sistema (inicio)
y funciones de búsqueda general.

Fecha de documentación: 2025-08-08
"""

from django.shortcuts import render
from decimal import Decimal, ROUND_HALF_UP
from Apps.Pedidos.models import Recepcion, Pedido, Stock


def home(request):
    """
    Vista principal del sistema (inicio).

    Muestra:
    - Recepciones pendientes (últimas 3)
    - Pedidos pendientes (últimos 3 con totales)
    - Pedidos entregados no pagados (con totales)

    Returns:
        HttpResponse: Renderiza home.html con datos de negocio.
    """
    recepciones_qs = Recepcion.objects.exclude(estado_recepcion='Finalizado').order_by('-fecha_recepcion')
    recepciones = list(recepciones_qs[:3])
    cantidad_recepciones = recepciones_qs.count()

    pedidos_qs = Pedido.objects.filter(estado_pedido='Pendiente').order_by('-fecha_pedido')
    pedidos = list(pedidos_qs[:3])
    cantidad_pedidos_pendiente = pedidos_qs.count()

    # Calcular total de cada pedido pendiente
    for pedido in pedidos:
        reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='RESERVA')
        total_pedido = sum(r.qty * (r.precio_unitario or 0) for r in reservas)
        total_pedido_iva = Decimal(total_pedido) * Decimal('1.19')
        pedido.total_pedido_pendiente = total_pedido_iva.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    pedidos_no_pagados = Pedido.objects.filter(estado_pedido='Entregado').order_by('-fecha_pedido')

    # Calcular total de cada pedido entregado no pagado
    for pedido in pedidos_no_pagados:
        reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')
        total_pedido_no_pagado = sum(r.qty * (r.precio_unitario or 0) for r in reservas)
        total_pedido_no_pagado_iva = Decimal(total_pedido_no_pagado) * Decimal('1.19')
        pedido.total_pedido_no_pagado = total_pedido_no_pagado_iva.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    cantidad_pedidos_no_pagados = pedidos_no_pagados.count()

    return render(request, './views/dashboard/home.html', {
        'recepciones': recepciones,
        'cantidad_recepciones': cantidad_recepciones,
        'pedidos': pedidos,
        'pedidos_no_pagados': pedidos_no_pagados,
        'cantidad_pedidos_pendiente': cantidad_pedidos_pendiente,
        'cantidad_pedidos_no_pagados': cantidad_pedidos_no_pagados,
    })
