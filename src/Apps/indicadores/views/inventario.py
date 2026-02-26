# Apps/indicadores/views/inventario.py

"""
Vista del dashboard de inventario.
"""

from django.shortcuts import render
from Apps.indicadores.utils import calcular_kpis_inventario
from Apps.indicadores.charts import grafico_stock_vs_minimo

def dashboard_inventario(request):
    """
    Renderiza el dashboard de inventario con KPIs y gráfico de stock.

    Returns:
        HttpResponse: Template con datos y gráfico.
    """
    kpis = calcular_kpis_inventario()
    grafico = grafico_stock_vs_minimo()
    return render(request, './indicadores/inventario.html', {
        'kpis': kpis,
        'grafico': grafico,
        'titulo': 'Dashboard Inventario'
    })
