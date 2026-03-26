from calendar import monthrange
from datetime import date

from django.utils import timezone

from Apps.indicadores.services.contabilidad import normalizar_periodo


MESES_ANIO = [
    (1, "Enero"),
    (2, "Febrero"),
    (3, "Marzo"),
    (4, "Abril"),
    (5, "Mayo"),
    (6, "Junio"),
    (7, "Julio"),
    (8, "Agosto"),
    (9, "Septiembre"),
    (10, "Octubre"),
    (11, "Noviembre"),
    (12, "Diciembre"),
]


def periodo_desde_request(request):
    hoy = timezone.localdate()
    periodo = normalizar_periodo(
        request.GET.get("year", hoy.year),
        request.GET.get("month", hoy.month),
        hoy=hoy,
    )
    inicio = date(periodo.year, periodo.month, 1)
    fin = date(periodo.year, periodo.month, monthrange(periodo.year, periodo.month)[1])
    return periodo, inicio, fin, MESES_ANIO
