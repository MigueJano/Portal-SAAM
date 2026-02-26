# Apps/indicadores/views/operaciones.py

"""
Vista del dashboard de operaciones logísticas.

Este módulo mostrará indicadores como:
- Tiempo promedio de entrega
- Cumplimiento de pedidos
- Tiempos de recepción
- Órdenes pendientes vs entregadas
"""

from django.shortcuts import render

def dashboard_operaciones(request):
    """
    Renderiza el dashboard de operaciones logísticas.

    Returns:
        HttpResponse: Template con KPIs de operaciones.
    """
    # En el futuro: llamar a calcular_kpis_operaciones()
    return render(request, './indicadores/operaciones.html', {
        'titulo': 'Dashboard Operaciones'
    })
