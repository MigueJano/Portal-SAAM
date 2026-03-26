"""
Vistas de contabilidad Pro Pyme.

Incluye:
- Revision mensual de ventas, compras e inventario.
- Descarga de libros electronicos (CSV).
- Descarga de paquete ZIP con todos los libros.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from Apps.indicadores.services.contabilidad import (
    COMPRAS_FIELDS,
    STOCK_FIELDS,
    VENTAS_FIELDS,
    csv_bytes,
    filas_libro_compras,
    filas_libro_ventas,
    filas_stock_contable,
    normalizar_periodo,
    obtener_compras_periodo,
    obtener_resumen_periodo,
    obtener_ventas_periodo,
    zip_libros_bytes,
)


def _obtener_periodo_request(request):
    hoy = timezone.localdate()
    return normalizar_periodo(
        request.GET.get("year", hoy.year),
        request.GET.get("month", hoy.month),
        hoy=hoy,
    )


def _csv_response(nombre_archivo: str, contenido: bytes) -> HttpResponse:
    resp = HttpResponse(contenido, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'
    return resp


@login_required
def resumen_contable_propyme(request):
    periodo = _obtener_periodo_request(request)

    ventas_qs = obtener_ventas_periodo(periodo)
    compras_qs = obtener_compras_periodo(periodo)
    filas_ventas = filas_libro_ventas(periodo, ventas_qs)
    filas_compras = filas_libro_compras(periodo, compras_qs)
    filas_stock = filas_stock_contable(periodo)

    total_stock_ref = sum((f["total_producto"] for f in filas_stock), start=0)
    resumen = obtener_resumen_periodo(periodo)

    meses = [
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

    return render(
        request,
        "indicadores/contabilidad/resumen_propyme.html",
        {
            "periodo": periodo,
            "resumen": resumen,
            "ventas_rows": filas_ventas,
            "compras_rows": filas_compras,
            "stock_rows": filas_stock,
            "total_stock_ref": total_stock_ref,
            "meses": meses,
        },
    )


@login_required
def exportar_libro_ventas_propyme(request):
    periodo = _obtener_periodo_request(request)
    filas = filas_libro_ventas(periodo, obtener_ventas_periodo(periodo))
    contenido = csv_bytes(VENTAS_FIELDS, filas)
    nombre = f"libro_ventas_propyme_{periodo.year:04d}{periodo.month:02d}.csv"
    return _csv_response(nombre, contenido)


@login_required
def exportar_libro_compras_propyme(request):
    periodo = _obtener_periodo_request(request)
    filas = filas_libro_compras(periodo, obtener_compras_periodo(periodo))
    contenido = csv_bytes(COMPRAS_FIELDS, filas)
    nombre = f"libro_compras_propyme_{periodo.year:04d}{periodo.month:02d}.csv"
    return _csv_response(nombre, contenido)


@login_required
def exportar_inventario_propyme(request):
    periodo = _obtener_periodo_request(request)
    filas = filas_stock_contable(periodo)
    contenido = csv_bytes(STOCK_FIELDS, filas)
    nombre = f"inventario_propyme_{periodo.year:04d}{periodo.month:02d}.csv"
    return _csv_response(nombre, contenido)


@login_required
def exportar_libros_propyme_zip(request):
    periodo = _obtener_periodo_request(request)
    filas_ventas = filas_libro_ventas(periodo, obtener_ventas_periodo(periodo))
    filas_compras = filas_libro_compras(periodo, obtener_compras_periodo(periodo))
    filas_stock = filas_stock_contable(periodo)

    contenido = zip_libros_bytes(periodo, filas_ventas, filas_compras, filas_stock)
    nombre = f"libros_propyme_{periodo.year:04d}{periodo.month:02d}.zip"
    resp = HttpResponse(contenido, content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return resp
