import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime, timedelta
from django.db.models import Count, Sum
from Apps.Pedidos.models import Pedido, Producto, Venta

def generar_grafico_barras(nombres, valores, titulo='', color='skyblue'):
    """
    Genera un gráfico de barras horizontal como imagen base64.
    """
    fig, ax = plt.subplots(figsize=(10, len(nombres) * 0.5))
    ax.barh(nombres, valores, color=color)
    ax.set_xlabel('Cantidad')
    ax.set_title(titulo)
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    imagen_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)

    return imagen_base64

def grafico_stock_vs_minimo():
    """
    Gráfico de productos con menor stock que el mínimo establecido.
    """
    productos = Producto.objects.all()
    nombres = []
    stocks_actuales = []
    stocks_minimos = []

    for producto in productos:
        stock_actual = producto.stock_set.aggregate(total=Count('id'))['total'] or 0
        if producto.qty_minima and stock_actual < producto.qty_minima:
            nombres.append(producto.nombre_producto)
            stocks_actuales.append(stock_actual)
            stocks_minimos.append(producto.qty_minima)

    if not nombres:
        return None  # Sin datos para graficar

    fig, ax = plt.subplots(figsize=(10, len(nombres) * 0.5))
    ax.barh(nombres, stocks_minimos, color='lightgray', label='Stock Mínimo')
    ax.barh(nombres, stocks_actuales, color='salmon', label='Stock Actual')
    ax.set_xlabel('Cantidad')
    ax.set_title('Stock actual vs mínimo por producto')
    ax.legend()
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    imagen_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)

    return imagen_base64

def grafico_crecimiento_mensual():
    """
    Gráfico de barras de la cantidad de pedidos en los últimos 6 meses.
    """
    hoy = datetime.now()
    meses = []
    cantidades = []

    for i in range(5, -1, -1):
        inicio_mes = (hoy.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        fin_mes = (inicio_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        pedidos_mes = Pedido.objects.filter(fecha_pedido__range=(inicio_mes, fin_mes)).count()
        nombre_mes = inicio_mes.strftime('%b').capitalize()
        meses.append(nombre_mes)
        cantidades.append(pedidos_mes)

    return generar_grafico_barras(meses, cantidades, titulo='Evolución de Pedidos (últimos 6 meses)', color='mediumseagreen')

def convertir_grafico_a_base64(fig):
    """
    Convierte un gráfico de matplotlib en una imagen base64 para mostrar en plantillas.
    """
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    image_png = buffer.getvalue()
    buffer.close()
    return base64.b64encode(image_png).decode('utf-8')

def grafico_ingresos_por_cliente(filtros=None):
    """
    Genera un gráfico de barras con los ingresos totales por cliente a partir de las ventas.
    
    Args:
        filtros (dict, opcional): Diccionario con filtros aplicables, como por ejemplo cliente.
    
    Returns:
        str: Imagen base64 del gráfico generado.
    """
    ventas = Venta.objects.all()

    # Aplica filtro por cliente si viene desde el formulario
    if filtros and filtros.get('cliente'):
        ventas = ventas.filter(pedidoid__nombre_cliente=filtros['cliente'])

    # Agrupa por cliente (nombre_cliente dentro de pedidoid)
    datos = ventas.values('pedidoid__nombre_cliente__nombre_cliente') \
                  .annotate(total=Sum('venta_total_pedido')) \
                  .order_by('-total')[:10]  # Top 10 clientes

    # Prepara datos para gráfico
    nombres = [item['pedidoid__nombre_cliente__nombre_cliente'] for item in datos]
    ingresos = [item['total'] for item in datos]

    # Generar gráfico
    fig, ax = plt.subplots(figsize=(10, len(nombres) * 0.5))
    ax.barh(nombres, ingresos, color='skyblue')
    ax.set_xlabel('Ingresos ($)')
    ax.set_title('Top 10 Clientes por Ingresos')
    ax.invert_yaxis()  # Clientes más importantes arriba
    plt.tight_layout()

    # Convertir gráfico a base64 para usar en la plantilla
    return convertir_grafico_a_base64(fig)
