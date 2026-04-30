"""
Recepcion de Productos - Vistas relacionadas con la gestion de recepciones.

Este modulo permite:
- Listar recepciones registradas.
- Crear, editar y finalizar recepciones.
- Agregar y eliminar productos asociados.
- Visualizar detalles de cada recepcion.

Fecha de generacion automatica: 2025-08-04
"""

from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from Apps.Pedidos.forms import CrearRecepcionForm, CrearRecepcionProductoForm
from Apps.Pedidos.models import (
    CategoriaEmpaque,
    CodigoProveedor,
    Producto,
    Proveedor,
    Recepcion,
    Stock,
)
from Apps.Pedidos.services import registrar_movimiento_stock
from Apps.Pedidos.utils import eliminar_generica

# --- Constantes Decimal ---
DOS_DEC = Decimal("0.01")
IVA_FACTOR = Decimal("1.19")


def _total_neto_desde_lineas(recepcion):
    expr = ExpressionWrapper(
        F("qty") * F("precio_unitario"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    total = Stock.objects.filter(recepcion=recepcion).aggregate(total=Sum(expr))["total"]
    return (total or Decimal("0.00")).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _sincronizar_totales_recepcion(recepcion):
    """
    Mantiene el neto del documento alineado con la suma real de sus lineas.

    Esto evita dobles conteos cuando el encabezado ya trae un neto manual
    y luego se agregan productos cuyo subtotal coincide con ese mismo valor.
    """
    recepcion.total_neto_recepcion = _total_neto_desde_lineas(recepcion)
    recepcion.save(update_fields=["total_neto_recepcion"])
    recepcion.actualizar_totales()


def _redirigir_recepcion_finalizada(request, recepcion):
    messages.warning(request, "La recepcion esta finalizada y no admite edicion.")
    return redirect("recepcion_productos_historico", documentoid=recepcion.id)


def lista_recepciones(request):
    """
    Lista todas las recepciones no finalizadas, ordenadas por fecha descendente.
    """
    recepciones = Recepcion.objects.exclude(estado_recepcion="Finalizado").order_by("-fecha_recepcion")
    return render(request, "./views/recepcion/lista_recepcion.html", {"recepciones": recepciones})


def crear_recepcion(request):
    proveedores = Proveedor.objects.all().order_by("nombre_proveedor")

    if request.method == "POST":
        form = CrearRecepcionForm(request.POST)
        if form.is_valid():
            nueva_recepcion = form.save()
            nueva_recepcion.actualizar_totales()
            messages.success(request, "Recepcion creada correctamente.")
            return redirect("lista_recepcion")
        messages.error(request, "No fue posible crear la recepcion. Revisa los datos ingresados.")
    else:
        form = CrearRecepcionForm()

    return render(
        request,
        "./views/recepcion/crear_recepcion.html",
        {
            "form": form,
            "proveedores": proveedores,
        },
    )


def editar_recepcion(request, id):
    recepcion = get_object_or_404(Recepcion, id=id)
    if recepcion.estado_recepcion == "Finalizado":
        return _redirigir_recepcion_finalizada(request, recepcion)

    proveedores = Proveedor.objects.all().order_by("nombre_proveedor")

    if request.method == "POST":
        form = CrearRecepcionForm(request.POST, instance=recepcion)
        if form.is_valid():
            recepcion = form.save()
            recepcion.actualizar_totales()
            messages.success(request, "Recepcion actualizada.")
            return redirect("lista_recepcion")
        messages.error(request, "No fue posible actualizar la recepcion. Revisa los datos ingresados.")
    else:
        form = CrearRecepcionForm(instance=recepcion)

    return render(
        request,
        "./views/recepcion/editar_recepcion.html",
        {
            "form": form,
            "recepcion": recepcion,
            "proveedores": proveedores,
        },
    )


def crear_recepcion_productos(request, recepcion_id):
    recepcion = get_object_or_404(Recepcion, id=recepcion_id)
    if recepcion.estado_recepcion == "Finalizado":
        return _redirigir_recepcion_finalizada(request, recepcion)

    if request.method == "POST":
        form = CrearRecepcionProductoForm(request.POST, documento=recepcion)
        if form.is_valid():
            linea = form.save(commit=False)

            # Normaliza el precio unitario a neto si el valor ingresado venia con IVA.
            incluye_iva = bool(request.POST.get("precio_incluye_iva"))
            if linea.precio_unitario is None:
                linea.precio_unitario = Decimal("0.00")
            else:
                linea.precio_unitario = Decimal(linea.precio_unitario)

            if incluye_iva:
                linea.precio_unitario = (linea.precio_unitario / IVA_FACTOR).quantize(
                    DOS_DEC, rounding=ROUND_HALF_UP
                )

            linea.recepcion = recepcion
            linea.save()
            registrar_movimiento_stock(linea, responsable=request.user)

            # El neto del documento se deriva de la suma de lineas, no por acumulacion.
            _sincronizar_totales_recepcion(recepcion)

            messages.success(request, "Producto agregado a la recepcion.")
            return redirect("crear_recepcion_productos", recepcion_id=recepcion.id)
    else:
        form = CrearRecepcionProductoForm(documento=recepcion)

    productos_disponibles = Producto.objects.all().order_by("nombre_producto")
    codigos_qs = CodigoProveedor.objects.filter(proveedor=recepcion.proveedor).values(
        "codigo_proveedor",
        "producto_id",
    )
    codigos_proveedor = list(codigos_qs)
    productos_agregados = Stock.objects.filter(recepcion=recepcion)

    return render(
        request,
        "./views/recepcion/crear_recepcion_productos.html",
        {
            "form": form,
            "productos": productos_disponibles,
            "recepcion": recepcion,
            "documento": recepcion,
            "recepciones": productos_agregados,
            "total_recepcion": recepcion.total_recepcion,
            "codigos_proveedor": codigos_proveedor,
        },
    )


def recepcion_productos_historico(request, documentoid):
    documento = get_object_or_404(Recepcion, pk=documentoid)
    recepciones = Stock.objects.filter(recepcion=documento)

    if request.method == "POST":
        if documento.estado_recepcion == "Finalizado":
            return _redirigir_recepcion_finalizada(request, documento)

        form = CrearRecepcionProductoForm(request.POST, documento=documento)
        if form.is_valid():
            form.save()
            messages.success(request, "Producto agregado correctamente.")
            return redirect("crear_recepcion_productos", recepcion_id=documento.id)
        for field, errors in form.errors.items():
            for error in errors:
                if field == "__all__":
                    messages.error(request, error)
                else:
                    messages.error(request, f"{form.fields[field].label}: {error}")
    else:
        form = CrearRecepcionProductoForm(documento=documento)

    categorias_empaque = CategoriaEmpaque.objects.all()

    return render(
        request,
        "./views/recepcion/recepcion_productos_historico.html",
        {
            "documento": documento,
            "recepciones": recepciones,
            "form": form,
            "categorias_empaque": categorias_empaque,
        },
    )


def lista_recepcion_historico(request):
    recepciones = Recepcion.objects.filter(estado_recepcion="Finalizado").order_by("-fecha_recepcion")
    return render(request, "./views/recepcion/lista_recepcion_historico.html", {"recepciones": recepciones})


@require_POST
def eliminar_recepcion_producto(request, producto_id):
    producto = get_object_or_404(Stock, id=producto_id)
    documento = producto.recepcion
    if documento.estado_recepcion == "Finalizado":
        return _redirigir_recepcion_finalizada(request, documento)

    producto.delete()
    _sincronizar_totales_recepcion(documento)
    return redirect("crear_recepcion_productos", recepcion_id=documento.id)


def eliminar_recepcion(request, id):
    recepcion = get_object_or_404(Recepcion, pk=id)
    if recepcion.estado_recepcion == "Finalizado":
        return _redirigir_recepcion_finalizada(request, recepcion)

    if Stock.objects.filter(recepcion=recepcion, tipo_movimiento="RECEPCION").exists():
        messages.error(request, "No se puede eliminar: existen productos asociados.")
        return redirect("lista_recepcion")
    return eliminar_generica(request, Recepcion, id, "lista_recepcion")


def finalizar_recepcion(request, id):
    documento = get_object_or_404(Recepcion, id=id)
    if documento.estado_recepcion == "Finalizado":
        return _redirigir_recepcion_finalizada(request, documento)

    if request.method == "POST":
        _sincronizar_totales_recepcion(documento)

        productos_asociados = Stock.objects.filter(recepcion=documento, tipo_movimiento="RECEPCION")
        productos_asociados.update(tipo_movimiento="DISPONIBLE")

        documento.estado_recepcion = "Finalizado"
        documento.save(update_fields=["estado_recepcion"])

        messages.success(request, "Recepcion finalizada correctamente.")
        return redirect("lista_recepcion")

    return redirect("lista_recepcion")
