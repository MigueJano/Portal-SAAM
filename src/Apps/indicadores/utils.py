from django.db.models import Sum, Count, Avg, F
from django.utils import timezone
from datetime import timedelta, datetime, date

from Apps.Pedidos.models import (
    Pedido,
    Venta,
    Stock,
    Producto,
    Cliente,
    Categoria,
)

def calcular_kpis_financieros(filtros):
    """
    Calcula indicadores financieros con filtros aplicados:
    - Fecha de inicio y fin
    - Cliente específico
    - Categoría de producto

    Args:
        filtros (dict): Diccionario con claves posibles: 'fecha_inicio', 'fecha_fin', 'cliente', 'categoria'

    Returns:
        dict: KPIs como ventas netas, ventas con IVA y cantidad de pedidos vendidos
    """

    ventas = Venta.objects.all()

    # --- Filtro por fecha ---
    fecha_inicio = filtros.get('fecha_inicio')
    fecha_fin = filtros.get('fecha_fin')
    if fecha_inicio and fecha_fin:
        try:
            if isinstance(fecha_inicio, str):
                fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
            if isinstance(fecha_fin, str):
                fecha_fin = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
            ventas = ventas.filter(fecha_venta__range=(fecha_inicio, fecha_fin))
        except ValueError:
            pass  # Fechas inválidas ignoradas

    # --- Filtro por cliente ---
    cliente_filtro = filtros.get('cliente')
    if cliente_filtro:
        try:
            if isinstance(cliente_filtro, Cliente):
                cliente = cliente_filtro
            else:
                cliente = Cliente.objects.get(id=int(cliente_filtro))
            pedidos_cliente = Pedido.objects.filter(nombre_cliente=cliente)
            ventas = ventas.filter(pedidoid__in=pedidos_cliente)
        except (Cliente.DoesNotExist, ValueError, TypeError):
            pass  # Cliente inválido o no encontrado


    # --- Filtro por categoría ---
    categoria_id = filtros.get('categoria')
    if categoria_id:
        try:
            categoria = Categoria.objects.get(id=int(categoria_id))
            pedidos_con_categoria = Stock.objects.filter(
                producto__categoria_producto=categoria
            ).values_list('pedido_id', flat=True).distinct()
            ventas = ventas.filter(pedidoid_id__in=pedidos_con_categoria)
        except (Categoria.DoesNotExist, ValueError):
            pass  # Categoría inválida o no encontrada

    # --- KPIs ---
    total_neto = ventas.aggregate(Sum('venta_neto_pedido'))['venta_neto_pedido__sum'] or 0
    total_iva = ventas.aggregate(Sum('venta_iva_pedido'))['venta_iva_pedido__sum'] or 0
    total_ventas = ventas.aggregate(Sum('venta_total_pedido'))['venta_total_pedido__sum'] or 0
    total_pedidos = ventas.values('pedidoid').distinct().count()
    ganancia_total = ventas.aggregate(Sum('ganancia_total'))['ganancia_total__sum'] or 0
    ganancia_pct = ventas.aggregate(Avg('ganancia_porcentaje'))['ganancia_porcentaje__avg'] or 0


    return {
        'ventas_netas': total_neto,
        'ventas_iva': total_iva,
        'ventas_total': total_ventas,
        'cantidad_pedidos': total_pedidos,
        'ingresos': total_ventas,
        'ganancia_bruta': ganancia_total,
        'margen_utilidad': round(ganancia_pct, 2),

    }

def calcular_kpis_inventario():
    """
    Calcula los principales indicadores de inventario usando la tabla unificada Stock.

    Incluye:
        - stock_total
        - productos_criticos
        - productos_reservados
        - rotacion_estimada (últimos 30 días)
        - cobertura_inventario_dias

    Returns:
        dict
    """
    ahora = timezone.now()
    hace_30_dias = ahora - timedelta(days=30)

    total_entradas = Stock.objects.filter(tipo_movimiento='RECEPCION').aggregate(total=Sum('qty'))['total'] or 0
    total_salidas = Stock.objects.filter(tipo_movimiento='DESPACHO').aggregate(total=Sum('qty'))['total'] or 0
    stock_total = total_entradas - total_salidas

    productos_criticos = 0
    for producto in Producto.objects.all():
        entradas = Stock.objects.filter(producto=producto, tipo_movimiento='RECEPCION').aggregate(q=Sum('qty'))['q'] or 0
        salidas = Stock.objects.filter(producto=producto, tipo_movimiento='DESPACHO').aggregate(q=Sum('qty'))['q'] or 0
        stock_actual = entradas - salidas

        if producto.qty_minima and stock_actual < producto.qty_minima:
            productos_criticos += 1

    productos_reservados = Stock.objects.filter(tipo_movimiento='RESERVA').aggregate(total=Sum('qty'))['total'] or 0

    salidas_30 = Stock.objects.filter(tipo_movimiento='DESPACHO', fecha_movimiento__gte=hace_30_dias)
    total_salidas_30 = salidas_30.aggregate(total=Sum('qty'))['total'] or 0
    rotacion_estimada = round(total_salidas_30 / 30, 2) if total_salidas_30 else 0

    cobertura_inventario_dias = round(stock_total / rotacion_estimada, 2) if rotacion_estimada else 0

    return {
        'stock_total': stock_total,
        'productos_criticos': productos_criticos,
        'productos_reservados': productos_reservados,
        'rotacion_estimada': rotacion_estimada,
        'cobertura_inventario_dias': cobertura_inventario_dias,
    }

def calcular_kpis_ventas():
    """
    Calcula indicadores de ventas y clientes.

    Incluye:
        - total_ventas
        - ticket_promedio
        - clientes_activos
        - clientes_frecuentes
        - producto_mas_vendido

    Returns:
        dict
    """
    total_ventas = Venta.objects.aggregate(total=Sum('venta_total_pedido'))['total'] or 0
    num_ventas = Venta.objects.count()
    ticket_promedio = round(total_ventas / num_ventas, 2) if num_ventas else 0

    clientes_activos = Cliente.objects.filter(pedido__isnull=False).distinct().count()

    clientes_frecuentes = Cliente.objects.annotate(num=Count('pedido')).filter(num__gt=1).count()

    producto_top = Stock.objects.filter(tipo_movimiento='RESERVA') \
        .values('producto__nombre_producto') \
        .annotate(q=Sum('qty')).order_by('-q').first()

    return {
        'total_ventas': total_ventas,
        'ticket_promedio': ticket_promedio,
        'clientes_activos': clientes_activos,
        'clientes_frecuentes': clientes_frecuentes,
        'producto_mas_vendido': producto_top['producto__nombre_producto'] if producto_top else "N/D",
    }

def calcular_kpis_operaciones():
    """
    Calcula indicadores operacionales del proceso de ventas.

    Incluye:
        - total_pedidos
        - pedidos_cumplidos
        - cumplimiento (%)
        - pedidos_pendientes
        - tiempo_promedio_entrega (si disponible)

    Returns:
        dict
    """
    total_pedidos = Pedido.objects.count()
    pedidos_con_venta = Pedido.objects.filter(venta__isnull=False).count()
    cumplimiento = round((pedidos_con_venta / total_pedidos) * 100, 2) if total_pedidos else 0

    pedidos_pendientes = Pedido.objects.filter(venta__isnull=True).count()

    tiempo_promedio = None
    try:
        tiempo_promedio = Pedido.objects.filter(venta__isnull=False) \
            .annotate(duracion=F('venta__fecha_venta') - F('fecha_pedido')) \
            .aggregate(promedio=Avg('duracion'))['promedio']
    except:
        pass

    return {
        'total_pedidos': total_pedidos,
        'pedidos_cumplidos': pedidos_con_venta,
        'cumplimiento': cumplimiento,
        'pedidos_pendientes': pedidos_pendientes,
        'tiempo_promedio_entrega': tiempo_promedio,
    }

def calcular_kpis_estrategia():
    """
    Calcula indicadores estratégicos de crecimiento basados en pedidos.

    Returns:
        dict
    """
    hoy = timezone.now().date()
    inicio_mes = hoy.replace(day=1)

    # Pedidos de este mes
    pedidos_mes = Pedido.objects.filter(fecha_pedido__gte=inicio_mes)

    # Pedidos del mes anterior (30 días antes de inicio del mes actual)
    pedidos_mes_anterior = Pedido.objects.filter(
        fecha_pedido__gte=inicio_mes - timedelta(days=30),
        fecha_pedido__lt=inicio_mes,
    )

    # Cálculo de crecimiento
    crecimiento = 0
    if pedidos_mes_anterior.count():
        crecimiento = round(
            ((pedidos_mes.count() - pedidos_mes_anterior.count()) / pedidos_mes_anterior.count()) * 100, 2
        )

    return {
        'pedidos_mes_actual': pedidos_mes.count(),
        'crecimiento_vs_mes_anterior': crecimiento
    }
