"""
Gestión de Pedidos

Este módulo incluye funcionalidades para:
- Crear, editar y eliminar pedidos.
- Agregar productos desde precios por cliente.
- Visualizar detalle del pedido con totales.
- Exportar pedidos en PDF.
- Ver pedidos en proceso.
"""
import base64
import uuid
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.forms import formset_factory
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.core.files.base import ContentFile
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from Apps.Pedidos.models import Pedido, Stock, Producto, ListaPrecios, EntregaPedido
from Apps.Pedidos.forms import PedidoForm, ProductoReservaForm

# --- Decimal helpers ---
from decimal import Decimal, ROUND_HALF_UP
DOS_DEC = Decimal('0.01')
PESO    = Decimal('1')
IVA_RATE = Decimal('0.19')
CIEN    = Decimal('100')


def eliminar_pedido(request, id):
    """
    Elimina un pedido si no está finalizado.
    Requiere confirmación explícita vía POST.
    """
    pedido = get_object_or_404(Pedido, id=id)

    if pedido.estado_pedido == 'Finalizado':
        messages.error(request, "No se puede eliminar un pedido finalizado.")
        return redirect('lista_pedidos')

    if request.method == 'POST':
        with transaction.atomic():
            Stock.objects.filter(pedido=pedido).delete()
            pedido.delete()
        messages.success(request, "Pedido y productos asociados eliminados correctamente.")
        return redirect('lista_pedidos')

    campos = [
        {'nombre': 'Cliente', 'valor': pedido.nombre_cliente},
        {'nombre': 'Fecha Pedido', 'valor': pedido.fecha_pedido},
        {'nombre': 'Estado', 'valor': pedido.estado_pedido},
        {'nombre': 'Cotización', 'valor': pedido.num_cotizacion or 'Sin cotización'},
    ]
    return render(request, './views/apps/confirmar_eliminar.html', {
        'modelo': 'Pedido',
        'campos': campos,
        'pedido': pedido,
    })


def crear_pedido(request):
    """
    Crea un nuevo pedido con el formulario de cliente y fecha.
    """
    if request.method == 'POST':
        form = PedidoForm(request.POST)
        if form.is_valid():
            pedido = form.save()
            return redirect('agregar_productos_pedido', pedido_id=pedido.id)
        messages.error(request, "No fue posible crear el pedido. Revisa los datos ingresados.")
    else:
        form = PedidoForm()

    return render(request, './views/pedido/crear_pedido.html', {'form': form})


def agregar_productos_pedido(request, pedido_id):
    """
    Agrega productos al pedido desde los precios asignados al cliente.
    Crea registros en `Stock` con tipo_movimiento='RESERVA'.
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    cliente = pedido.nombre_cliente
    precios = (ListaPrecios.objects
               .filter(nombre_cliente=cliente)
               .select_related('nombre_producto')
               .order_by('nombre_producto__nombre_producto'))
    ProductoFormSet = formset_factory(ProductoReservaForm, extra=0)

    if request.method == 'POST':
        formset = ProductoFormSet(request.POST)
        if formset.is_valid():
            total_neto = Decimal('0')

            for form in formset:
                qty = form.cleaned_data.get('cantidad')
                if qty and qty > 0:
                    producto = Producto.objects.get(id=form.cleaned_data['producto_id'])
                    empaque = form.cleaned_data['empaque']
                    precio_unitario = Decimal(form.cleaned_data['precio_unitario'])

                    empaque_map = {
                        'UNIDAD': 'PRIMARIO',
                        'PAQUETE': 'PRIMARIO',
                        'MANGA': 'SECUNDARIO',
                        'MULTIPACK': 'SECUNDARIO'
                    }
                    empaque_normalizado = empaque_map.get(empaque.upper(), empaque.upper())

                    total_neto += Decimal(qty) * precio_unitario

                    Stock.objects.create(
                        tipo_movimiento='RESERVA',
                        producto=producto,
                        qty=qty,
                        empaque=empaque_normalizado,
                        precio_unitario=precio_unitario,
                        pedido=pedido
                    )

            total_neto = total_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            iva = (total_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            total = (total_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

            messages.success(
                request,
                f"Productos agregados. Total neto: ${total_neto:,.2f}, IVA: ${iva:,.2f}, Total: ${total:,.2f}"
            )
            return redirect('detalle_pedido', pedido_id=pedido.id)
        else:
            messages.error(request, "Hubo un error al procesar los productos.")
    else:
        initial = []
        for lp in precios:
            producto = lp.nombre_producto
            initial.append({
                'producto_id': producto.id,
                'producto_codigo': producto.codigo_producto_interno,
                'producto_nombre': producto.nombre_producto,
                'empaque': lp.empaque,
                'precio_unitario': lp.precio_venta,  # DecimalField en el form
                'cantidad': 0,
                'empaque_primario_nombre': producto.empaque_primario.nombre if producto.empaque_primario else '',
                'empaque_secundario_nombre': producto.empaque_secundario.nombre if producto.empaque_secundario else '',
                'qty_minima': producto.qty_minima,
            })

        formset = ProductoFormSet(initial=initial)

    return render(request, './views/pedido/agregar_productos_pedido.html', {
        'pedido': pedido,
        'formset': formset
    })


def calcular_precio_maximo_normalizado(producto_id):
    """
    Devuelve el precio máximo de compra por unidad para un producto,
    considerando el tipo de empaque (normalizado a PRIMARIO).
    """
    recepciones = Stock.objects.filter(
        producto_id=producto_id,
        tipo_movimiento='DISPONIBLE',
        precio_unitario__isnull=False
    )

    precios_normalizados = []
    for r in recepciones:
        precio = Decimal(r.precio_unitario)

        # factor a unidades primarias
        producto = r.producto
        q2 = Decimal(producto.qty_secundario or 1)
        q3 = Decimal(producto.qty_terciario or 1)

        if r.empaque == 'SECUNDARIO':
            factor = q2
        elif r.empaque == 'TERCIARIO':
            factor = q2 * q3
        else:
            factor = Decimal(1)

        if factor <= 0:
            factor = Decimal(1)

        precios_normalizados.append((precio / factor).quantize(DOS_DEC, rounding=ROUND_HALF_UP))

    return max(precios_normalizados) if precios_normalizados else Decimal('0')


def detalle_pedido(request, pedido_id):
    """
    Muestra el detalle del pedido con los productos reservados,
    incluyendo cálculo de ganancias por producto.
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if pedido.estado_pedido == 'Entregado':
            # Preferir DESPACHO; si (por falla puntual) aún no existen, caer a RESERVA.
            base_qs = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')
            if not base_qs.exists():
                base_qs = Stock.objects.filter(pedido=pedido, tipo_movimiento__in=['RESERVA','DESPACHO'])
    else:
        base_qs = Stock.objects.filter(pedido=pedido, tipo_movimiento='RESERVA')

    reservas = list(
        base_qs
        .values(
            'producto',
            'producto__nombre_producto',
            'empaque',
            'precio_unitario',
            'producto__empaque_primario__nombre',
            'producto__empaque_secundario__nombre',
            'producto__empaque_terciario__nombre'
        )
        .annotate(qty_sum=Sum('qty'))
        .order_by('producto')
    )

    total_neto = Decimal('0')
    ganancia_total = Decimal('0')

    for r in reservas:
        producto_id = r['producto']
        precio_venta = Decimal(r['precio_unitario'])
        qty = int(r['qty_sum'])
        empaque = r['empaque']

        producto = Producto.objects.get(id=producto_id)

        # Subtotal de venta tal como fue vendido (sin normalizar)
        subtotal = Decimal(qty) * precio_venta

        # Factor de venta (unidades primarias por empaque)
        if empaque == 'SECUNDARIO':
            factor_venta = Decimal(producto.qty_secundario or 1)
        elif empaque == 'TERCIARIO':
            factor_venta = Decimal(producto.qty_secundario or 1) * Decimal(producto.qty_terciario or 1)
        else:
            factor_venta = Decimal(1)

        # Precio venta por unidad primaria
        precio_venta_unitario = (precio_venta / factor_venta).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

        # Precio compra máximo por unidad primaria
        precio_compra_unitario = calcular_precio_maximo_normalizado(producto_id)

        # Ganancia a nivel unidad y cantidad en unidades
        qty_unidades = Decimal(qty) * factor_venta
        costo_total = (qty_unidades * precio_compra_unitario)
        ingreso_total = (qty_unidades * precio_venta_unitario)
        ganancia = ingreso_total - costo_total

        ganancia_pct = Decimal('0')
        if costo_total > 0:
            ganancia_pct = ((ganancia / costo_total) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

        # Mostrar en CLP (enteros)
        r['subtotal'] = subtotal.quantize(PESO, rounding=ROUND_HALF_UP)
        r['precio_compra'] = precio_compra_unitario.quantize(PESO, rounding=ROUND_HALF_UP)
        r['ganancia'] = ganancia.quantize(PESO, rounding=ROUND_HALF_UP)
        r['ganancia_pct'] = ganancia_pct  # 2 decimales

        total_neto += subtotal
        ganancia_total += ganancia

    total_neto = total_neto.quantize(PESO, rounding=ROUND_HALF_UP)
    iva = (total_neto * IVA_RATE).quantize(PESO, rounding=ROUND_HALF_UP)
    total = (total_neto + iva).quantize(PESO, rounding=ROUND_HALF_UP)

    return render(request, './views/pedido/detalle_pedido.html', {
        'pedido': pedido,
        'reservas': reservas,
        'total_neto': total_neto,
        'iva': iva,
        'total': total,
        'ganancia_total': ganancia_total.quantize(PESO, rounding=ROUND_HALF_UP),
    })


@require_POST
def eliminar_producto_pedido(request, pedido_id, producto_id):
    """
    Elimina un producto específico del pedido (sólo tipo RESERVA).
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    Stock.objects.filter(pedido=pedido, producto_id=producto_id, tipo_movimiento='RESERVA').delete()
    messages.success(request, "Producto eliminado del pedido.")
    return redirect('detalle_pedido', pedido_id=pedido.id)

def exportar_pdf_pedido(request, pedido_id):
    """
    Genera y devuelve el PDF del pedido con los productos reservados.
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    try:
        from Apps.Pedidos.utils_pdf import generar_pdf_pedido
    except Exception as e:
        messages.error(request, f"No se pudo generar el PDF en este entorno: {e}")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    if pedido.estado_pedido == 'Entregado':
        reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')
        if not reservas.exists():
            reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='RESERVA')
    else:
        reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='RESERVA')

    pdf_buffer = generar_pdf_pedido(pedido, reservas)
    return HttpResponse(pdf_buffer, content_type='application/pdf')

def editar_pedido(request, pedido_id):
    """
    Permite editar los datos generales de un pedido (cliente, fecha).
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    if request.method == 'POST':
        form = PedidoForm(request.POST, instance=pedido)
        if form.is_valid():
            form.save()
            messages.success(request, 'Pedido actualizado correctamente.')
            return redirect('lista_pedidos')
        else:
            messages.error(request, 'Error al actualizar el pedido. Por favor, revisa los datos.')
    else:
        form = PedidoForm(instance=pedido)

    return render(request, './views/pedido/editar_pedido.html', {
        'form': form,
        'pedido': pedido
    })

def pedidos_en_proceso(request):
    """
    Muestra todos los pedidos que aún no están finalizados, con el total calculado.
    - Si el pedido está ENTREGADO: sumar DESPACHO (fallback a RESERVA si no existieran).
    - Si NO está entregado: sumar RESERVA.
    - Mostrar TOTAL con IVA (neto + IVA) en pedido.total_pedido.
    """
    pedidos = Pedido.objects.exclude(estado_pedido='Finalizado')

    subtotal_expr = ExpressionWrapper(
        F('qty') * F('precio_unitario'),
        output_field=DecimalField(max_digits=18, decimal_places=6),
    )

    for pedido in pedidos:
        qs_base = Stock.objects.filter(
            pedido=pedido,
            precio_unitario__isnull=False,
        )

        if pedido.estado_pedido == 'Entregado':
            base_qs = qs_base.filter(tipo_movimiento='DESPACHO')
            if not base_qs.exists():
                base_qs = qs_base.filter(tipo_movimiento__in=['RESERVA', 'DESPACHO'])
        else:
            base_qs = qs_base.filter(tipo_movimiento='RESERVA')

        total_neto = base_qs.aggregate(total=Sum(subtotal_expr))['total'] or Decimal('0')
        total_neto = Decimal(total_neto).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva        = (total_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        total      = (total_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

        # Lo que usas en la tabla
        pedido.total_pedido = total

    return render(request, './views/pedido/lista_pedidos.html', {'pedidos': pedidos})

def finalizar_pedido(request, pedido_id):
    """
    Registra la entrega del pedido:
    - Lee datos del receptor (nombre, RUT, fecha, firma base64) desde el modal.
    - Genera el PDF de Recepción con el mismo estilo del PDF de Pedido.
    - Crea EntregaPedido y adjunta el PDF en archivo_pdf.
    - Marca el pedido como 'Entregado'.
    - Actualiza Stock de RESERVA -> DESPACHO.
    """
    pedido = get_object_or_404(Pedido, pk=pedido_id)

    if request.method != 'POST':
        return redirect('detalle_pedido', pedido_id=pedido.id)

    # --- Datos del formulario ---
    nombre = (request.POST.get('entrega_nombre') or '').strip()
    rut = (request.POST.get('entrega_rut') or '').strip()
    fecha_str = request.POST.get('entrega_fecha')
    firma_dataurl = request.POST.get('entrega_firma')
    foto_file = request.FILES.get('entrega_foto')

    # Validaciones mínimas
    if not (nombre and rut and fecha_str and firma_dataurl):
        messages.error(request, "Faltan datos obligatorios o la firma.")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    # Fecha a datetime (aware)
    fecha = parse_datetime(fecha_str) if fecha_str else None
    if fecha is None:
        fecha = timezone.now()
    elif timezone.is_naive(fecha):
        fecha = timezone.make_aware(fecha, timezone.get_current_timezone())

    # Decodificar firma base64 -> bytes
    firma_bytes = None
    try:
        if firma_dataurl.startswith('data:image'):
            _, b64data = firma_dataurl.split(',', 1)
            firma_bytes = base64.b64decode(b64data)
        else:
            raise ValueError("Formato de firma inválido.")
    except Exception as e:
        messages.error(request, f"Error al procesar la firma: {e}")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='RESERVA')
    if not reservas.exists():
        messages.warning(request, "El pedido no tiene productos en reserva para entregar.")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    # --- Generar PDF de Recepción (estilo Pedido) ---
    try:
        from Apps.Pedidos.utils_pdf import generar_pdf_entrega

        receptor = {
            'nombre': nombre,
            'rut': rut,
            'fecha': fecha,
            'comentario': getattr(pedido, 'comentario_pedido', ''),
        }
        pdf_bytes = generar_pdf_entrega(pedido, reservas, receptor, firma_bytes=firma_bytes)
    except Exception as e:
        messages.error(request, f"No se pudo generar el PDF: {e}")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    # --- Crear EntregaPedido, marcar estado y mover stock ---
    try:
        with transaction.atomic():
            entrega = EntregaPedido.objects.create(
                pedido=pedido,
                nombre_receptor=nombre,
                rut_receptor=rut,
                fecha_entrega=fecha,
                foto=foto_file if foto_file else None,
            )
            filename = f"entrega_pedido_{pedido.id}_{uuid.uuid4().hex}.pdf"
            entrega.archivo_pdf.save(filename, ContentFile(pdf_bytes), save=False)
            entrega.save(update_fields=['archivo_pdf', 'foto'] if foto_file else ['archivo_pdf'])

            pedido.estado_pedido = 'Entregado'
            pedido.save(update_fields=['estado_pedido'])

            reservas.update(tipo_movimiento='DESPACHO')
    except Exception as e:
        messages.error(request, f"No se pudo registrar la entrega: {e}")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    messages.success(request, "Entrega registrada, PDF generado y pedido marcado como ENTREGADO.")
    return redirect('detalle_pedido', pedido_id=pedido.id)
