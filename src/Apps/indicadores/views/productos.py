from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from Apps.Pedidos.models import UtilidadProducto
from Apps.indicadores.forms import FiltroProductosForm, inicio_tres_meses_naturales


DOS_DEC = Decimal("0.01")


def _factor_unidad(producto, unidad):
    if unidad == "SECUNDARIO":
        return Decimal(max(int(producto.qty_secundario or 1), 1))
    return Decimal("1")


@login_required
def informe_productos(request):
    if request.GET:
        hoy = date.today()
        filtros = request.GET.copy()
        if not filtros.get("fecha_desde"):
            filtros["fecha_desde"] = inicio_tres_meses_naturales(hoy).isoformat()
        if not filtros.get("fecha_hasta"):
            filtros["fecha_hasta"] = hoy.isoformat()
        form = FiltroProductosForm(filtros)
        form.is_valid()
        inicio = form.cleaned_data["fecha_desde"]
        fin = form.cleaned_data["fecha_hasta"]
        producto = form.cleaned_data.get("producto")
        unidad = form.cleaned_data["unidad"]
    else:
        hoy = date.today()
        inicio = inicio_tres_meses_naturales(hoy)
        fin = hoy
        producto = None
        unidad = "PRIMARIO"
        form = FiltroProductosForm(
            initial={"fecha_desde": inicio, "fecha_hasta": fin, "unidad": unidad}
        )

    registros = (
        UtilidadProducto.objects.filter(
            venta__isnull=False,
            venta__fecha_venta__range=(inicio, fin),
        )
        .select_related(
            "producto",
            "producto__empaque_primario",
            "producto__empaque_secundario",
            "venta",
            "venta__pedidoid",
            "venta__pedidoid__nombre_cliente",
        )
        .order_by("-venta__fecha_venta", "producto__nombre_producto", "id")
    )
    if producto:
        registros = registros.filter(producto=producto)

    filas = []
    compradores = set()
    productos = set()
    total_cantidad = Decimal("0")
    total_venta = Decimal("0")
    serie = defaultdict(lambda: Decimal("0"))
    agrupar_por_mes = (fin - inicio).days > 62

    for registro in registros:
        factor = _factor_unidad(registro.producto, unidad)
        cantidad_primaria = Decimal(registro.cantidad or 0)
        cantidad = cantidad_primaria / factor
        precio = Decimal(registro.precio_venta_unitario or 0) * factor
        total = (cantidad_primaria * Decimal(registro.precio_venta_unitario or 0)).quantize(
            DOS_DEC,
            rounding=ROUND_HALF_UP,
        )
        cliente = registro.venta.pedidoid.nombre_cliente
        fecha = registro.venta.fecha_venta
        clave_serie = fecha.replace(day=1) if agrupar_por_mes else fecha
        serie[clave_serie] += cantidad
        compradores.add(cliente.pk)
        productos.add(registro.producto_id)
        total_cantidad += cantidad
        total_venta += total

        if unidad == "SECUNDARIO":
            nombre_unidad = (
                registro.producto.empaque_secundario.nombre
                if registro.producto.empaque_secundario_id
                else "Secundaria"
            )
        else:
            nombre_unidad = (
                registro.producto.empaque_primario.nombre
                if registro.producto.empaque_primario_id
                else "Primaria"
            )

        filas.append(
            {
                "fecha": fecha,
                "producto": registro.producto,
                "cliente": cliente,
                "venta": registro.venta,
                "cantidad": cantidad,
                "nombre_unidad": nombre_unidad,
                "precio": precio.quantize(DOS_DEC, rounding=ROUND_HALF_UP),
                "total": total,
            }
        )

    formato_fecha = "%m-%Y" if agrupar_por_mes else "%d-%m-%Y"
    grafico = [
        {
            "fecha": fecha.strftime(formato_fecha),
            "cantidad": float(cantidad.quantize(DOS_DEC, rounding=ROUND_HALF_UP)),
        }
        for fecha, cantidad in sorted(serie.items())
    ]

    return render(
        request,
        "indicadores/productos.html",
        {
            "form": form,
            "filas": filas,
            "inicio": inicio,
            "fin": fin,
            "unidad": unidad,
            "unidad_label": "secundarias" if unidad == "SECUNDARIO" else "primarias",
            "grafico": grafico,
            "resumen": {
                "cantidad": total_cantidad,
                "total_venta": total_venta,
                "compradores": len(compradores),
                "productos": len(productos),
            },
        },
    )
