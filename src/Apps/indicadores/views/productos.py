from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from Apps.Pedidos.models import UtilidadProducto
from Apps.indicadores.forms import (
    FiltroComprasClienteForm,
    FiltroProductosForm,
    inicio_tres_meses_naturales,
    ultimo_mes_natural,
)


DOS_DEC = Decimal("0.01")
IVA_FACTOR = Decimal("1.19")


def _q2(valor):
    return Decimal(valor or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


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


@login_required
def informe_compras_cliente(request):
    filtros = request.GET.copy()
    desde_default, hasta_default = ultimo_mes_natural(date.today())
    if not filtros.get("fecha_desde"):
        filtros["fecha_desde"] = desde_default.isoformat()
    if not filtros.get("fecha_hasta"):
        filtros["fecha_hasta"] = hasta_default.isoformat()
    form = FiltroComprasClienteForm(filtros)
    if form.is_valid():
        inicio = form.cleaned_data["fecha_desde"]
        fin = form.cleaned_data["fecha_hasta"]
        cliente = form.cleaned_data.get("cliente")
    else:
        inicio, fin = desde_default, hasta_default
        cliente = None

    registros = (
        UtilidadProducto.objects.filter(
            venta__isnull=False,
            venta__fecha_venta__range=(inicio, fin),
        )
        .select_related(
            "producto",
            "producto__empaque_primario",
            "venta__pedidoid__nombre_cliente",
        )
    )
    if cliente:
        registros = registros.filter(venta__pedidoid__nombre_cliente=cliente)

    agrupadas = {}
    for registro in registros:
        cliente_fila = registro.venta.pedidoid.nombre_cliente
        mes = registro.venta.fecha_venta.replace(day=1)
        clave = (mes, cliente_fila.pk, registro.producto_id)
        fila = agrupadas.setdefault(
            clave,
            {
                "mes": mes,
                "cliente": cliente_fila,
                "producto": registro.producto,
                "cantidad": Decimal("0"),
                "total_neto": Decimal("0"),
            },
        )
        cantidad = Decimal(registro.cantidad or 0)
        fila["cantidad"] += cantidad
        fila["total_neto"] += cantidad * Decimal(registro.precio_venta_unitario or 0)

    filas = []
    for fila in agrupadas.values():
        fila["total_neto"] = _q2(fila["total_neto"])
        fila["precio_promedio"] = _q2(
            fila["total_neto"] / fila["cantidad"] if fila["cantidad"] else 0
        )
        fila["total_compra"] = _q2(fila["total_neto"] * IVA_FACTOR)
        fila["unidad"] = (
            fila["producto"].empaque_primario.nombre
            if fila["producto"].empaque_primario_id
            else "Unidad primaria"
        )
        filas.append(fila)
    filas.sort(
        key=lambda fila: (
            -fila["mes"].toordinal(),
            fila["cliente"].nombre_cliente,
            fila["producto"].nombre_producto,
        ),
    )

    total_neto = _q2(sum((fila["total_neto"] for fila in filas), start=Decimal("0")))
    total_compra = _q2(sum((fila["total_compra"] for fila in filas), start=Decimal("0")))
    return render(
        request,
        "indicadores/compras_cliente.html",
        {
            "form": form,
            "inicio": inicio,
            "fin": fin,
            "cliente": cliente,
            "filas": filas,
            "resumen": {
                "cantidad": sum((fila["cantidad"] for fila in filas), start=Decimal("0")),
                "total_neto": total_neto,
                "total_compra": total_compra,
                "productos": len({fila["producto"].pk for fila in filas}),
            },
        },
    )
