"""
Ventas - Módulo de vistas para gestión del proceso de venta.

Este archivo incluye:
- Finalización de pedidos (transformación de reservas en ventas).
- Registro de utilidad AGREGADA POR LÍNEA (no por unidad).
- Listado de ventas realizadas.
- Visualización detallada de productos vendidos por pedido.

Fecha de documentación: 2025-08-07
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Case, When, F, Value, CharField, ExpressionWrapper, DecimalField
from django.db.models.functions import Coalesce

from Apps.Pedidos.models import Pedido, PedidoLinea, Stock, Venta, UtilidadProducto, EntregaPedido
from Apps.Pedidos.services import costo_maximo_unitario, desglose_ingreso_pack, es_pack, factor_empaque

from django.db import transaction
from Apps.Pedidos.forms import FinalizarVentaForm

# --- Constantes Decimal ---
DOS_DEC   = Decimal('0.01')
IVA_RATE  = Decimal('0.19')
CIEN      = Decimal('100')
UNO_TENTH = Decimal('0.1')  # para porcentajes con 1 decimal


def _lineas_comerciales_venta(pedido: Pedido):
    return list(
        pedido.lineas
        .select_related('producto')
        .order_by('id')
    )


def _empaque_display_venta(producto, empaque):
    nivel = (empaque or 'PRIMARIO').upper()
    if nivel == 'SECUNDARIO' and getattr(producto, 'empaque_secundario', None):
        return producto.empaque_secundario.nombre
    if nivel == 'TERCIARIO' and getattr(producto, 'empaque_terciario', None):
        return producto.empaque_terciario.nombre
    if getattr(producto, 'empaque_primario', None):
        return producto.empaque_primario.nombre
    if es_pack(producto):
        return 'Pack'
    return nivel

def finalizar_venta(request, pedido_id):
    """
    Ahora finaliza la venta sumando todos los productos del pedido que estén DESPACHADOS.
    No modifica movimientos; solo consolida y registra la Venta + UtilidadProducto.
    """
    pedido = get_object_or_404(Pedido, id=pedido_id)

    # Evitar duplicados por pedido
    if Venta.objects.filter(pedidoid=pedido).exists():
        messages.info(request, "Este pedido ya tiene una venta registrada.")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    # Base: solo movimientos DESPACHADO del pedido
    despachados = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')

    if not despachados.exists():
        messages.warning(request, "No hay productos DESPACHADOS asociados a este pedido para consolidar la venta.")
        return redirect('detalle_pedido', pedido_id=pedido.id)

    total_neto = Decimal('0')
    ganancia_total = Decimal('0')

    # Buckets para registrar utilidades por línea (producto + empaque + precios unitarios)
    buckets = defaultdict(lambda: {
        'producto': None,
        'empaque': None,
        'cantidad': 0,         # cantidad en UNIDADES PRIMARIAS
        'pc_unit': None,       # precio compra por unidad primaria
        'pv_unit': None,       # precio venta por unidad primaria
    })

    lineas = _lineas_comerciales_venta(pedido)
    if lineas:
        for linea in lineas:
            producto = linea.producto
            qty_linea = int(linea.cantidad or 0)
            precio_linea = Decimal(linea.precio_unitario or 0)
            total_neto += precio_linea * Decimal(qty_linea)

            if linea.tipo_linea == 'PACK' or es_pack(producto):
                for row in desglose_ingreso_pack(producto, precio_linea, qty_linea):
                    pc_unit = row['costo_unit_primary']
                    pv_unit = row['pv_unit_primary']
                    key = (row['producto'].id, row['empaque'], pc_unit, pv_unit)
                    bucket = buckets[key]
                    bucket['producto'] = row['producto']
                    bucket['empaque'] = row['empaque']
                    bucket['pc_unit'] = pc_unit
                    bucket['pv_unit'] = pv_unit
                    bucket['cantidad'] += int(row['qty_primary_total'])
                    ganancia_total += Decimal(row['utilidad_total'])
            else:
                factor = max(factor_empaque(producto, linea.empaque), 1)
                pv_unit = (precio_linea / Decimal(factor)).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
                pc_unit = costo_maximo_unitario(producto)
                unidades = qty_linea * factor
                key = (producto.id, linea.empaque, pc_unit, pv_unit)

                bucket = buckets[key]
                bucket['producto'] = producto
                bucket['empaque'] = linea.empaque
                bucket['pc_unit'] = pc_unit
                bucket['pv_unit'] = pv_unit
                bucket['cantidad'] += unidades
                ganancia_total += (pv_unit - pc_unit) * Decimal(unidades)
    else:
        for r in despachados:
            producto = r.producto
            empaque  = r.empaque
            pv       = Decimal(r.precio_unitario or 0)  # precio del movimiento (por empaque del movimiento)
            qty_mov  = int(r.qty or 0)

            factor = max(factor_empaque(producto, empaque), 1)
            pv_unit = (pv / Decimal(factor)).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            pc_unit = costo_maximo_unitario(producto)

            unidades = qty_mov * factor
            key = (producto.id, empaque, pc_unit, pv_unit)

            b = buckets[key]
            b['producto'] = producto
            b['empaque']  = empaque
            b['pc_unit']  = pc_unit
            b['pv_unit']  = pv_unit
            b['cantidad'] += unidades

            total_neto     += (pv * Decimal(qty_mov))
            ganancia_total += (pv_unit - pc_unit) * Decimal(unidades)

    total_neto = total_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva        = (total_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    total      = (total_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    ganancia_porcentaje = ((ganancia_total / total_neto) * CIEN).quantize(UNO_TENTH, rounding=ROUND_HALF_UP) if total_neto > 0 else Decimal('0')

    # GET: pantalla de confirmación
    if request.method == 'GET':
        from Apps.Pedidos.forms import FinalizarVentaForm
        form = FinalizarVentaForm(pedido=pedido)
        return render(request, './views/venta/finalizar_venta.html', {
            'pedido': pedido,
            'form': form,
            'total_neto': total_neto,
            'iva': iva,
            'total': total,
        })

    # POST: crear Venta + utilidades
    from Apps.Pedidos.forms import FinalizarVentaForm
    form = FinalizarVentaForm(request.POST, pedido=pedido)
    if not form.is_valid():
        messages.error(request, "Revisa los datos del formulario.")
        return render(request, './views/venta/finalizar_venta.html', {
            'pedido': pedido,
            'form': form,
            'total_neto': total_neto,
            'iva': iva,
            'total': total,
        })

    with transaction.atomic():
        venta = form.save(commit=False)
        venta.pedidoid            = pedido
        venta.venta_neto_pedido   = total_neto
        venta.venta_iva_pedido    = iva
        venta.venta_total_pedido  = total
        venta.ganancia_total      = ganancia_total.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        venta.ganancia_porcentaje = ganancia_porcentaje
        venta.save()

        ahora = timezone.now()
        utilidades = []
        for (_pid, empaque, pc_unit, pv_unit), b in buckets.items():
            utilidad_unit = (pv_unit - pc_unit).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
            # antes: utilidad_pct = (utilidad_unit / pc_unit) * 100
            utilidad_pct  = ((utilidad_unit / pv_unit) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP) if pv_unit > 0 else Decimal('0')
            utilidades.append(UtilidadProducto(
                venta=venta,
                producto=b['producto'],
                empaque=empaque,
                cantidad=b['cantidad'],                  # cantidad en unidades primarias
                precio_compra_unitario=pc_unit,
                precio_venta_unitario=pv_unit,
                utilidad=utilidad_unit,                  # utilidad por unidad primaria
                utilidad_porcentaje=utilidad_pct,
                fecha=ahora,
            ))
        if utilidades:
            UtilidadProducto.objects.bulk_create(utilidades)

        # Actualiza estado del pedido si quieres cerrarlo aquí
        pedido.estado_pedido = 'Finalizado'
        pedido.save(update_fields=['estado_pedido'])

    messages.success(request, "Venta consolidada a partir de DESPACHADOS y registrada correctamente.")
    return redirect('lista_ventas')

def lista_ventas(request):
    """
    Muestra el historial de todas las ventas realizadas.
    """
    ventas = Venta.objects.select_related('pedidoid', 'pedidoid__nombre_cliente').order_by('-fecha_venta')
    return render(request, './views/venta/lista_ventas.html', {'ventas': ventas})


def detalle_venta(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id)
    lineas_comerciales = []
    for linea in _lineas_comerciales_venta(venta.pedidoid):
        lineas_comerciales.append({
            'descripcion': linea.descripcion,
            'tipo_linea': linea.tipo_linea,
            'cantidad': linea.cantidad,
            'empaque': linea.empaque,
            'empaque_display': _empaque_display_venta(linea.producto, linea.empaque),
            'precio_unitario': linea.precio_unitario,
            'subtotal': Decimal(linea.cantidad or 0) * Decimal(linea.precio_unitario or 0),
        })

    productos = (
        UtilidadProducto.objects
        .filter(venta=venta)
        .select_related('producto')
        .annotate(
            # Nombre “humano” del empaque configurado en Producto
            empaque_nombre=Coalesce(
                Case(
                    When(empaque='PRIMARIO',   then=F('producto__empaque_primario__nombre')),
                    When(empaque='SECUNDARIO', then=F('producto__empaque_secundario__nombre')),
                    When(empaque='TERCIARIO',  then=F('producto__empaque_terciario__nombre')),
                    default=F('empaque'),
                    output_field=CharField(),
                ),
                F('empaque'),
            ),
            # ---- FACTOR DE EMPAQUE ----
            factor_empaque=Case(
                When(empaque='PRIMARIO',   then=Value(1)),
                When(empaque='SECUNDARIO', then=Coalesce(F('producto__qty_secundario'), Value(1))),
                When(
                    empaque='TERCIARIO',
                    then=ExpressionWrapper(
                        Coalesce(F('producto__qty_secundario'), Value(1)) * Coalesce(F('producto__qty_terciario'), Value(1)),
                        output_field=DecimalField(max_digits=18, decimal_places=6)
                    )
                ),
                default=Value(1),
                output_field=DecimalField(max_digits=18, decimal_places=6),
            ),
        )
        .annotate(
            # Cantidad mostrada en la unidad de venta (dividir las unidades primarias por el factor)
            cantidad_empaque=ExpressionWrapper(
                F('cantidad') / F('factor_empaque'),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            # Precio de venta por empaque (subir desde unitario primario)
            precio_venta_empaque=ExpressionWrapper(
                F('precio_venta_unitario') * F('factor_empaque'),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            # Precio de compra por empaque (idem)
            precio_compra_empaque=ExpressionWrapper(
                F('precio_compra_unitario') * F('factor_empaque'),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            # Total línea se mantiene consistente (pv_unitario_primario * cantidad_primaria)
            total_linea=ExpressionWrapper(
                F('precio_venta_unitario') * F('cantidad'),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
        )
        .order_by('producto__nombre_producto', 'empaque_nombre')
    )

    ingreso_total  = sum((p.precio_venta_unitario * p.cantidad for p in productos), start=Decimal('0'))
    ganancia_total = sum((p.utilidad              * p.cantidad for p in productos), start=Decimal('0'))

    ingreso_total  = ingreso_total.quantize(DOS_DEC,  rounding=ROUND_HALF_UP)
    ganancia_total = ganancia_total.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    ganancia_total_pct = ((ganancia_total / ingreso_total) * CIEN).quantize(DOS_DEC, rounding=ROUND_HALF_UP) if ingreso_total > 0 else Decimal('0')

    entregas = EntregaPedido.objects.filter(pedido=venta.pedidoid).order_by('-fecha_entrega', '-id')

    return render(request, './views/venta/detalle_venta.html', {
        'venta': venta,
        'lineas_comerciales': lineas_comerciales,
        'productos': productos,
        'ingreso_total': ingreso_total,
        'ganancia_total': ganancia_total,
        'ganancia_total_pct': ganancia_total_pct,
        'entregas': entregas,
    })
