"""
Recepción de Productos - Vistas relacionadas con la gestión de recepciones.

Este módulo permite:
- Listar recepciones registradas.
- Crear, editar y finalizar recepciones.
- Agregar y eliminar productos asociados.
- Visualizar detalles de cada recepción.

Fecha de generación automática: 2025-08-04
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from decimal import Decimal, ROUND_HALF_UP

from Apps.Pedidos.models import Proveedor, Producto, Stock, Recepcion, CategoriaEmpaque, CodigoProveedor
from Apps.Pedidos.forms import CrearRecepcionForm, CrearRecepcionProductoForm
from Apps.Pedidos.utils import eliminar_generica

# --- Constantes Decimal ---
DOS_DEC    = Decimal('0.01')
IVA_FACTOR = Decimal('1.19')


def lista_recepciones(request):
    """
    Lista todas las recepciones no finalizadas, ordenadas por fecha descendente.
    """
    recepciones = Recepcion.objects.exclude(estado_recepcion='Finalizado').order_by('-fecha_recepcion')
    return render(request, './views/recepcion/lista_recepcion.html', {'recepciones': recepciones})

def crear_recepcion(request):
    proveedores = Proveedor.objects.all().order_by('nombre_proveedor')

    if request.method == 'POST':
        form = CrearRecepcionForm(request.POST)
        if form.is_valid():
            nueva_recepcion = form.save(commit=False)
            nueva_recepcion.usuario = request.user
            nueva_recepcion.save()
            nueva_recepcion.actualizar_totales()
            messages.success(request, "Recepción creada correctamente.")
            return redirect('lista_recepcion')
    else:
        form = CrearRecepcionForm()

    return render(request, './views/recepcion/crear_recepcion.html', {
        'form': form,
        'proveedores': proveedores
    })

def editar_recepcion(request, id):
    recepcion = get_object_or_404(Recepcion, id=id)
    proveedores = Proveedor.objects.all()
    if request.method == 'POST':
        form = CrearRecepcionForm(request.POST, instance=recepcion)
        if form.is_valid():
            form.save()
            messages.success(request, "Recepción actualizada.")
            return redirect('lista_recepcion')
    else:
        form = CrearRecepcionForm(instance=recepcion)
    return render(request, './views/recepcion/editar_recepcion.html', {'form': form, 'recepcion': recepcion, 'proveedores': proveedores})


    proveedores = Proveedor.objects.all().order_by('nombre_proveedor')

    if request.method == 'POST':
        form = CrearRecepcionForm(request.POST)
        if form.is_valid():
            nueva_recepcion = form.save(commit=False)
            nueva_recepcion.usuario = request.user
            nueva_recepcion.save()
            nueva_recepcion.actualizar_totales()
            messages.success(request, "Recepción creada correctamente.")
            return redirect('lista_recepcion')
    else:
        form = CrearRecepcionForm()

    return render(request, './views/recepcion/crear_recepcion.html', {
        'form': form,
        'proveedores': proveedores
    })

def crear_recepcion_productos(request, recepcion_id):
    recepcion = get_object_or_404(Recepcion, id=recepcion_id)

    if request.method == 'POST':
        form = CrearRecepcionProductoForm(request.POST, documento=recepcion)
        if form.is_valid():
            # Guardar línea
            linea = form.save(commit=False)

            # Normaliza el precio unitario a NETO si el checkbox viene marcado
            incluye_iva = bool(request.POST.get('precio_incluye_iva'))
            if linea.precio_unitario is None:
                linea.precio_unitario = Decimal('0.00')
            else:
                linea.precio_unitario = Decimal(linea.precio_unitario)

            if incluye_iva:
                linea.precio_unitario = (linea.precio_unitario / IVA_FACTOR).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

            linea.recepcion = recepcion

            # OPCIONAL: si quieres guardar el código de proveedor usado en la línea, descomenta
            # y agrega un <input type="hidden" name="codigo_proveedor_usado" ...> en el template.
            # linea.codigo_proveedor_usado = (request.POST.get('codigo_proveedor_usado') or '').strip()[:50]

            linea.save()

            # Actualiza neto/iva/total de la recepción
            try:
                qty = Decimal(linea.qty or 0)
                subtotal_neto = (qty * linea.precio_unitario).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            except Exception:
                subtotal_neto = Decimal('0.00')

            nuevo_neto = (recepcion.total_neto_recepcion or Decimal('0.00')) + subtotal_neto
            recepcion.total_neto_recepcion = nuevo_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            recepcion.save(update_fields=['total_neto_recepcion'])
            recepcion.actualizar_totales()

            messages.success(request, "Producto agregado a la recepción.")
            return redirect('crear_recepcion_productos', recepcion_id=recepcion.id)
    else:
        form = CrearRecepcionProductoForm(documento=recepcion)

    # Productos para el selector
    productos_disponibles = Producto.objects.all().order_by('nombre_producto')

    # Códigos de proveedor SOLO del proveedor de esta recepción
    codigos_qs = CodigoProveedor.objects.filter(
        proveedor=recepcion.proveedor
    ).values('codigo_proveedor', 'producto_id')
    codigos_proveedor = list(codigos_qs)

    # Líneas ya agregadas
    productos_agregados = Stock.objects.filter(recepcion=recepcion)

    return render(request, './views/recepcion/crear_recepcion_productos.html', {
        'form': form,
        'productos': productos_disponibles,
        'recepcion': recepcion,
        'documento': recepcion,                 # por compatibilidad con tu template
        'recepciones': productos_agregados,     # items ya agregados
        'total_recepcion': recepcion.total_recepcion,
        'codigos_proveedor': codigos_proveedor  # 👈 requerido por el template nuevo
    })

def recepcion_productos_historico(request, documentoid):
    documento = get_object_or_404(Recepcion, pk=documentoid)
    recepciones = Stock.objects.filter(recepcion=documento)

    if request.method == 'POST':
        form = CrearRecepcionProductoForm(request.POST, documento=documento)
        if form.is_valid():
            form.save()
            messages.success(request, "Producto agregado correctamente.")
            return redirect('crear_recepcion_productos', recepcion_id=documento.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f"{form.fields[field].label}: {error}")
    else:
        form = CrearRecepcionProductoForm(documento=documento)

    categorias_empaque = CategoriaEmpaque.objects.all()

    return render(request, './views/recepcion/recepcion_productos_historico.html', {
        'documento': documento,
        'recepciones': recepciones,
        'form': form,
        'categorias_empaque': categorias_empaque,
    })

def lista_recepcion_historico(request):
    recepciones = Recepcion.objects.filter(estado_recepcion='Finalizado').order_by('-fecha_recepcion')
    return render(request, './views/recepcion/lista_recepcion_historico.html', {'recepciones': recepciones})

@require_POST
def eliminar_recepcion_producto(request, producto_id):
    producto = get_object_or_404(Stock, id=producto_id)
    documento = producto.recepcion

    # Calcula el subtotal neto de la línea para restarlo del neto de la recepción
    try:
        qty = Decimal(producto.qty or 0)
        precio_neto = Decimal(producto.precio_unitario or 0)
        subtotal_neto = (qty * precio_neto).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    except Exception:
        subtotal_neto = Decimal('0.00')

    producto.delete()

    # Resta del neto y no dejes números negativos por seguridad
    neto_actual = (documento.total_neto_recepcion or Decimal('0.00')) - subtotal_neto
    if neto_actual < 0:
        neto_actual = Decimal('0.00')

    documento.total_neto_recepcion = neto_actual.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    documento.save(update_fields=['total_neto_recepcion'])

    # Deriva IVA y Total desde el neto
    documento.actualizar_totales()
    return redirect('crear_recepcion_productos', recepcion_id=documento.id)

def eliminar_recepcion(request, id):
    recepcion = get_object_or_404(Recepcion, pk=id)
    if Stock.objects.filter(recepcion=recepcion, tipo_movimiento='RECEPCION').exists():
        messages.error(request, "No se puede eliminar: existen productos asociados.")
        return redirect('lista_recepcion')
    return eliminar_generica(request, Recepcion, id, 'lista_recepcion')

def finalizar_recepcion(request, id):
    documento = get_object_or_404(Recepcion, id=id)

    if request.method == 'POST':
        documento.actualizar_totales()  # 🔄 asegura que los totales estén correctos

        productos_asociados = Stock.objects.filter(
            recepcion=documento, tipo_movimiento='RECEPCION'
        )
        productos_asociados.update(tipo_movimiento='DISPONIBLE')

        documento.estado_recepcion = 'Finalizado'
        documento.save(update_fields=['estado_recepcion'])

        messages.success(request, "Recepción finalizada correctamente.")
        return redirect('lista_recepcion')

    return redirect('lista_recepcion')
