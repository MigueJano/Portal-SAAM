# Apps/indicadores/views/estrategia.py

from django.shortcuts import render
from Apps.indicadores.utils import calcular_kpis_estrategia
from Apps.indicadores.charts import grafico_crecimiento_mensual

def dashboard_estrategia(request):
    """
    Renderiza el dashboard estratégico del negocio con indicadores clave
    y gráfico de crecimiento de pedidos mensuales.

    Returns:
        HttpResponse
    """
    kpis = calcular_kpis_estrategia()
    grafico = grafico_crecimiento_mensual()
    print("KPI estrategia:", kpis)
    return render(request, 'indicadores/estrategia.html', {
        'kpis': kpis,
        'grafico': grafico,
    })
