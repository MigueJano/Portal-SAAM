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

from Apps.Pedidos.models import Pedido, PedidoLinea, Stock, Producto, ListaPrecios, EntregaPedido
from Apps.Pedidos.forms import PedidoForm, ProductoReservaForm
from Apps.Pedidos.services import (
    cantidad_primaria,
    componentes_pack,
    costo_maximo_unitario,
    costo_referencial_pack,
    desglose_ingreso_pack,
    es_pack,
    factor_empaque,
    registrar_movimiento_stock,
    registrar_movimientos_stock,
    stock_cache_simple,
    stock_disponible_pack,
    validar_stock_pack,
)
from Apps.Pedidos.utils import DELETE_CONFIRMATION_TEXT, validacion_doble_check_eliminacion

# --- Decimal helpers ---
from decimal import Decimal, ROUND_HALF_UP
DOS_DEC = Decimal('0.01')
PESO    = Decimal('1')
IVA_RATE = Decimal('0.19')
CIEN    = Decimal('100')


def _responsable_desde_request(request):
    user = getattr(request, "user", None)
    return user if getattr(user, "is_authenticated", False) else None


def _empaque_normalizado(empaque: str) -> str:
    empaque_map = {
        'UNIDAD': 'PRIMARIO',
        'PAQUETE': 'PRIMARIO',
        'MANGA': 'SECUNDARIO',
        'MULTIPACK': 'SECUNDARIO',
    }
    return empaque_map.get((empaque or '').upper(), (empaque or '').upper())


def _nombre_empaque(producto: Producto, empaque: str) -> str:
    nivel = (empaque or 'PRIMARIO').upper()
    if nivel == 'SECUNDARIO' and producto.empaque_secundario:
        return producto.empaque_secundario.nombre
    if nivel == 'TERCIARIO' and producto.empaque_terciario:
        return producto.empaque_terciario.nombre
    if producto.empaque_primario:
        return producto.empaque_primario.nombre
    if es_pack(producto):
        return 'Pack'
    return nivel


def _tipo_linea_desde_producto(producto: Producto) -> str:
    return 'PACK' if es_pack(producto) else 'PRODUCTO'


def _linea_pedido_existente(pedido: Pedido, producto: Producto, empaque: str, precio_unitario: Decimal):
    return (
        PedidoLinea.objects
        .filter(
            pedido=pedido,
            producto=producto,
            tipo_linea=_tipo_linea_desde_producto(producto),
            empaque=empaque,
            precio_unitario=precio_unitario,
        )
        .first()
    )


def _upsert_linea_pedido(pedido: Pedido, producto: Producto, empaque: str, precio_unitario: Decimal, cantidad: int):
    linea = _linea_pedido_existente(pedido, producto, empaque, precio_unitario)
    if linea:
        linea.cantidad += int(cantidad or 0)
        linea.save(update_fields=['cantidad', 'actualizado'])
        return linea

    return PedidoLinea.objects.create(
        pedido=pedido,
        producto=producto,
        tipo_linea=_tipo_linea_desde_producto(producto),
        descripcion=producto.nombre_producto,
        empaque=empaque,
        cantidad=int(cantidad or 0),
        precio_unitario=precio_unitario,
    )


def _resumen_linea_pack(linea: PedidoLinea) -> dict:
    desglose = desglose_ingreso_pack(linea.producto, Decimal(linea.precio_unitario), int(linea.cantidad or 0))
    costo_total = sum((row['costo_total_pack'] * int(linea.cantidad or 0) for row in desglose), start=Decimal('0'))
    subtotal = Decimal(linea.cantidad or 0) * Decimal(linea.precio_unitario or 0)
    ganancia = subtotal - costo_total
    ganancia_pct = Decimal('0')
    if costo_total > 0:
        ganancia_pct = ((ganancia / costo_total) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

    return {
        'linea_id': linea.id,
        'legacy_producto_id': None,
        'nombre': linea.descripcion,
        'cantidad': int(linea.cantidad or 0),
        'empaque': linea.empaque,
        'empaque_display': _nombre_empaque(linea.producto, linea.empaque),
        'precio_unitario': Decimal(linea.precio_unitario or 0).quantize(PESO, rounding=ROUND_HALF_UP),
        'subtotal': subtotal.quantize(PESO, rounding=ROUND_HALF_UP),
        'precio_compra': costo_referencial_pack(linea.producto).quantize(PESO, rounding=ROUND_HALF_UP),
        'ganancia': ganancia.quantize(PESO, rounding=ROUND_HALF_UP),
        'ganancia_pct': ganancia_pct,
        'es_pack': True,
    }


def _resumen_linea_producto(linea: PedidoLinea) -> dict:
    producto = linea.producto
    factor_venta = Decimal(factor_empaque(producto, linea.empaque))
    precio_venta = Decimal(linea.precio_unitario or 0)
    subtotal = Decimal(linea.cantidad or 0) * precio_venta
    precio_venta_unitario = (precio_venta / factor_venta).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    precio_compra_unitario = costo_maximo_unitario(producto)
    qty_unidades = Decimal(linea.cantidad or 0) * factor_venta
    costo_total = qty_unidades * precio_compra_unitario
    ganancia = subtotal - costo_total
    ganancia_pct = Decimal('0')
    if costo_total > 0:
        ganancia_pct = ((ganancia / costo_total) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

    return {
        'linea_id': linea.id,
        'legacy_producto_id': None,
        'nombre': linea.descripcion,
        'cantidad': int(linea.cantidad or 0),
        'empaque': linea.empaque,
        'empaque_display': _nombre_empaque(producto, linea.empaque),
        'precio_unitario': precio_venta.quantize(PESO, rounding=ROUND_HALF_UP),
        'subtotal': subtotal.quantize(PESO, rounding=ROUND_HALF_UP),
        'precio_compra': precio_compra_unitario.quantize(PESO, rounding=ROUND_HALF_UP),
        'ganancia': ganancia.quantize(PESO, rounding=ROUND_HALF_UP),
        'ganancia_pct': ganancia_pct,
        'es_pack': False,
    }


def _detalle_lineas_pedido(pedido: Pedido) -> tuple[list[dict], Decimal, Decimal, Decimal, Decimal]:
    lineas = list(
        pedido.lineas
        .select_related(
            'producto',
            'producto__empaque_primario',
            'producto__empaque_secundario',
            'producto__empaque_terciario',
        )
        .order_by('id')
    )

    if lineas:
        filas = []
        total_neto = Decimal('0')
        ganancia_total = Decimal('0')
        for linea in lineas:
            fila = _resumen_linea_pack(linea) if linea.tipo_linea == 'PACK' else _resumen_linea_producto(linea)
            filas.append(fila)
            total_neto += Decimal(fila['subtotal'])
            ganancia_total += Decimal(fila['ganancia'])

        total_neto = total_neto.quantize(PESO, rounding=ROUND_HALF_UP)
        iva = (total_neto * IVA_RATE).quantize(PESO, rounding=ROUND_HALF_UP)
        total = (total_neto + iva).quantize(PESO, rounding=ROUND_HALF_UP)
        return filas, total_neto, iva, total, ganancia_total.quantize(PESO, rounding=ROUND_HALF_UP)

    if pedido.estado_pedido == 'Entregado':
        base_qs = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')
        if not base_qs.exists():
            base_qs = Stock.objects.filter(pedido=pedido, tipo_movimiento__in=['RESERVA', 'DESPACHO'])
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

    filas = []
    total_neto = Decimal('0')
    ganancia_total = Decimal('0')
    for r in reservas:
        producto = Producto.objects.get(id=r['producto'])
        precio_venta = Decimal(r['precio_unitario'] or 0)
        qty = int(r['qty_sum'] or 0)
        factor_venta = Decimal(factor_empaque(producto, r['empaque']))
        subtotal = Decimal(qty) * precio_venta
        precio_venta_unitario = (precio_venta / factor_venta).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        precio_compra_unitario = costo_maximo_unitario(producto)
        qty_unidades = Decimal(qty) * factor_venta
        costo_total = qty_unidades * precio_compra_unitario
        ganancia = subtotal - costo_total
        ganancia_pct = Decimal('0')
        if costo_total > 0:
            ganancia_pct = ((ganancia / costo_total) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

        filas.append({
            'linea_id': None,
            'legacy_producto_id': r['producto'],
            'nombre': r['producto__nombre_producto'],
            'cantidad': qty,
            'empaque': r['empaque'],
            'empaque_display': _nombre_empaque(producto, r['empaque']),
            'precio_unitario': precio_venta.quantize(PESO, rounding=ROUND_HALF_UP),
            'subtotal': subtotal.quantize(PESO, rounding=ROUND_HALF_UP),
            'precio_compra': precio_compra_unitario.quantize(PESO, rounding=ROUND_HALF_UP),
            'ganancia': ganancia.quantize(PESO, rounding=ROUND_HALF_UP),
            'ganancia_pct': ganancia_pct,
            'es_pack': False,
        })
        total_neto += subtotal
        ganancia_total += ganancia

    total_neto = total_neto.quantize(PESO, rounding=ROUND_HALF_UP)
    iva = (total_neto * IVA_RATE).quantize(PESO, rounding=ROUND_HALF_UP)
    total = (total_neto + iva).quantize(PESO, rounding=ROUND_HALF_UP)
    return filas, total_neto, iva, total, ganancia_total.quantize(PESO, rounding=ROUND_HALF_UP)


def eliminar_pedido(request, id):
    """
    Elimina un pedido si no está finalizado.
    Requiere confirmación explícita vía POST.
    """
    pedido = get_object_or_404(Pedido, id=id)

    if pedido.estado_pedido == 'Finalizado':
        messages.error(request, "No se puede eliminar un pedido finalizado.")
        return redirect('lista_pedidos')

    campos = [
        {'nombre': 'Cliente', 'valor': pedido.nombre_cliente},
        {'nombre': 'Fecha Pedido', 'valor': pedido.fecha_pedido},
        {'nombre': 'Estado', 'valor': pedido.estado_pedido},
        {'nombre': 'CotizaciÃ³n', 'valor': pedido.num_cotizacion or 'Sin cotizaciÃ³n'},
    ]

    if request.method == 'POST':
        if not validacion_doble_check_eliminacion(request):
            messages.error(
                request,
                f"Debes marcar la confirmacion y escribir {DELETE_CONFIRMATION_TEXT} para eliminar."
            )
            return render(request, './views/apps/confirmar_eliminar.html', {
                'modelo': 'Pedido',
                'campos': campos,
                'pedido': pedido,
                'texto_confirmacion_requerido': DELETE_CONFIRMATION_TEXT,
            })

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
        'texto_confirmacion_requerido': DELETE_CONFIRMATION_TEXT,
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
            acciones = []
            stock_disponible = stock_cache_simple()
            errores = []

            for form in formset:
                qty = int(form.cleaned_data.get('cantidad') or 0)
                if qty <= 0:
                    continue

                producto = Producto.objects.get(id=form.cleaned_data['producto_id'])
                empaque = form.cleaned_data['empaque']
                precio_unitario = Decimal(form.cleaned_data['precio_unitario'])
                empaque_normalizado = _empaque_normalizado(empaque)

                total_neto += Decimal(qty) * precio_unitario
                acciones.append({
                    'producto': producto,
                    'empaque': empaque_normalizado,
                    'precio_unitario': precio_unitario,
                    'cantidad': qty,
                })

                if es_pack(producto):
                    faltantes = validar_stock_pack(producto, qty, cache=stock_disponible)
                    if faltantes:
                        detalle = ", ".join(
                            f"{item['producto'].nombre_producto}: disponible {item['disponible']}, requerido {item['requerido']}"
                            for item in faltantes
                        )
                        errores.append(f"Stock insuficiente para el pack {producto.nombre_producto}. {detalle}.")
                        continue

                    for item in componentes_pack(producto):
                        requerido = cantidad_primaria(item.producto, item.empaque, item.cantidad * qty)
                        stock_disponible[item.producto_id] = stock_disponible.get(item.producto_id, 0) - requerido
                else:
                    requerido = cantidad_primaria(producto, empaque_normalizado, qty)
                    stock_disponible[producto.id] = stock_disponible.get(producto.id, 0) - requerido

            if errores:
                for error in errores:
                    messages.error(request, error)
                messages.error(request, "No fue posible guardar las reservas por problemas de stock.")
                return redirect('agregar_productos_pedido', pedido_id=pedido.id)

            with transaction.atomic():
                for accion in acciones:
                    producto = accion['producto']
                    empaque = accion['empaque']
                    precio_unitario = accion['precio_unitario']
                    qty = accion['cantidad']

                    linea = _upsert_linea_pedido(
                        pedido,
                        producto,
                        empaque,
                        precio_unitario,
                        qty,
                    )

                    if es_pack(producto):
                        for item in componentes_pack(producto):
                            reserva = Stock.objects.create(
                                tipo_movimiento='RESERVA',
                                producto=item.producto,
                                qty=item.cantidad * qty,
                                empaque=item.empaque,
                                precio_unitario=None,
                                pedido=pedido,
                                linea_pedido=linea,
                            )
                            registrar_movimiento_stock(
                                reserva,
                                responsable=_responsable_desde_request(request),
                            )
                    else:
                        reserva = Stock.objects.create(
                            tipo_movimiento='RESERVA',
                            producto=producto,
                            qty=qty,
                            empaque=empaque,
                            precio_unitario=precio_unitario,
                            pedido=pedido,
                            linea_pedido=linea
                        )
                        registrar_movimiento_stock(
                            reserva,
                            responsable=_responsable_desde_request(request),
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
        stock_actual = stock_cache_simple()
        for lp in precios:
            producto = lp.nombre_producto
            initial.append({
                'producto_id': producto.id,
                'producto_codigo': producto.codigo_producto_interno,
                'producto_nombre': f"[PACK] {producto.nombre_producto}" if es_pack(producto) else producto.nombre_producto,
                'empaque': lp.empaque,
                'precio_unitario': lp.precio_venta,  # DecimalField en el form
                'cantidad': 0,
                'empaque_primario_nombre': producto.empaque_primario.nombre if producto.empaque_primario else ('Pack' if es_pack(producto) else ''),
                'empaque_secundario_nombre': producto.empaque_secundario.nombre if producto.empaque_secundario else '',
                'qty_minima': producto.qty_minima,
                'es_pack': es_pack(producto),
                'stock_pack_disponible': stock_disponible_pack(producto, cache=stock_actual) if es_pack(producto) else None,
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
    producto = Producto.objects.get(id=producto_id)
    return costo_maximo_unitario(producto)


def detalle_pedido(request, pedido_id):
    """
    Muestra el detalle del pedido con los productos reservados,
    incluyendo cálculo de ganancias por producto.
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    lineas, total_neto, iva, total, ganancia_total = _detalle_lineas_pedido(pedido)

    return render(request, './views/pedido/detalle_pedido.html', {
        'pedido': pedido,
        'lineas': lineas,
        'total_neto': total_neto,
        'iva': iva,
        'total': total,
        'ganancia_total': ganancia_total,
    })


@require_POST
def eliminar_producto_pedido(request, pedido_id, producto_id):
    """
    Elimina un producto específico del pedido (sólo tipo RESERVA).
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)
    Stock.objects.filter(
        pedido=pedido,
        producto_id=producto_id,
        tipo_movimiento='RESERVA',
        linea_pedido__isnull=True,
    ).delete()
    messages.success(request, "Producto eliminado del pedido.")
    return redirect('detalle_pedido', pedido_id=pedido.id)


@require_POST
def eliminar_linea_pedido(request, pedido_id, linea_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    linea = get_object_or_404(PedidoLinea, id=linea_id, pedido=pedido)
    linea.delete()
    messages.success(request, "Línea eliminada del pedido.")
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
        if pedido.lineas.exists():
            total_neto = sum(
                (Decimal(linea.cantidad or 0) * Decimal(linea.precio_unitario or 0) for linea in pedido.lineas.all()),
                start=Decimal('0')
            )
        else:
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

            reservas_list = list(reservas)
            registrar_movimientos_stock(
                reservas_list,
                tipo_movimiento='DESPACHO',
                responsable=_responsable_desde_request(request),
                fecha_movimiento=timezone.now(),
            )
            reservas.update(tipo_movimiento='DESPACHO')
    except Exception as e:
        messages.error(request, f"No se pudo registrar la entrega: {e}")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    messages.success(request, "Entrega registrada, PDF generado y pedido marcado como ENTREGADO.")
    return redirect('detalle_pedido', pedido_id=pedido.id)
