"""
Clientes - Vistas relacionadas con la gestión de clientes.

Este módulo permite:
- Listar clientes activos e históricos.
- Crear y editar clientes.
- Asignar precios personalizados a productos por cliente.
- Consultar precios de compra base por producto.

Fecha de documentación: 2025-08-04
Autor: Miguel Plasencia
"""
from django.db.models import F, Max
from django.db import transaction 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from Apps.Pedidos.models import Cliente, Producto, ListaPrecios, Stock
from Apps.Pedidos.forms import ClienteForm, ListaPreciosForm
from Apps.Pedidos.services import (
    costo_maximo_unitario,
    es_pack,
    sincronizar_lista_predeterminada_a_cliente,
)

# --- Decimal helpers para dinero ---
from decimal import Decimal, ROUND_HALF_UP


DOS_DEC = Decimal('0.01')
MESES_ALERTA_ACTUALIZACION = 6


# ------------------------------------------------------------------
# Listado de clientes
# ------------------------------------------------------------------

def lista_clientes(request):
    """
    Muestra la lista de clientes activos registrados en el sistema.

    Returns:
        HttpResponse: Página con listado de clientes activos.
    """
    clientes = Cliente.objects.filter(cliente_activo=True)
    return render(request, './views/clientes/lista_clientes.html', {'clientes': clientes})


def lista_clientes_historicos(request):
    """
    Muestra la lista de clientes inactivos o desactivados.

    Returns:
        HttpResponse: Página con listado de clientes históricos.
    """
    clientes = Cliente.objects.filter(cliente_activo=False)
    return render(request, './views/clientes/lista_clientes_historico.html', {'clientes': clientes})


# ------------------------------------------------------------------
# Creación y edición de clientes
# ------------------------------------------------------------------

def crear_cliente(request):
    """
    Vista para registrar un nuevo cliente en el sistema.

    - Utiliza ClienteForm para validar datos.
    - Muestra mensajes de éxito o error.
    """
    form = ClienteForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente guardado correctamente.")
            return redirect('lista_clientes')
        else:
            for error in form.errors.values():
                messages.error(request, error)

    return render(request, './views/clientes/crear_cliente.html', {'form': form})


def editar_cliente(request, cliente_id):
    """
    Vista para editar la información de un cliente existente.

    Args:
        cliente_id (int): ID del cliente a modificar.
    """
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    form = ClienteForm(request.POST or None, instance=cliente)

    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente actualizado correctamente.")
            return redirect('lista_clientes')
        else:
            for error in form.errors.values():
                messages.error(request, error)

    return render(request, './views/clientes/editar_cliente.html', {
        'form': form,
        'cliente': cliente
    })


# ------------------------------------------------------------------
# Asignación de precios por cliente
# ------------------------------------------------------------------

IVA_TAX = Decimal('0.19')   # 19% Chile
DOS_DEC = Decimal('0.01')

def _round2(x: Decimal) -> Decimal:
    return x.quantize(DOS_DEC, rounding=ROUND_HALF_UP)

def _calc_iva_total(neto: Decimal):
    iva   = _round2(neto * IVA_TAX)
    total = _round2(neto + iva)
    return iva, total


def _date_input_value(value) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _fecha_requiere_actualizacion(fecha_desde):
    if not fecha_desde:
        return None
    return fecha_desde + relativedelta(months=MESES_ALERTA_ACTUALIZACION)


def _precio_esta_desactualizado(fecha_desde, today=None) -> bool:
    fecha_alerta = _fecha_requiere_actualizacion(fecha_desde)
    if not fecha_alerta:
        return False
    return fecha_alerta <= (today or timezone.localdate())


def asignar_precios(request, cliente_id):
    """
    Asignar precios personalizados a un cliente:
    - Guardar un precio puntual (usa ListaPreciosForm).
    - Importar todos los precios desde una Lista de Precios Predeterminada.
    """
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    precio_id = request.GET.get('precio_id') or request.POST.get('precio_id') or ''
    precio_en_edicion = None
    today = timezone.localdate()
    if str(precio_id).isdigit():
        precio_en_edicion = get_object_or_404(
            ListaPrecios.objects.select_related('nombre_producto', 'nombre_cliente'),
            pk=int(precio_id),
            nombre_cliente=cliente,
        )

    precios = list(
        ListaPrecios.objects
        .filter(nombre_cliente=cliente)
        .select_related(
            'nombre_producto',
            'nombre_producto__empaque_primario',
            'nombre_producto__empaque_secundario',
            'nombre_producto__empaque_terciario',
        )
        .order_by('nombre_producto__nombre_producto', 'empaque')
    )
    productos = Producto.objects.all().order_by('nombre_producto')

    # Listas predeterminadas activas para el selector
    from Apps.Pedidos.models import ListaPreciosPredeterminada  # evitar import circular si lo hubiera
    listas_pred = list(
        ListaPreciosPredeterminada.objects
        .filter(activa=True)
        .annotate(default_desde=Max('items__vigencia'))
        .order_by('nombre_listaprecios')
    )
    listas_pred_map = {lp.id: lp for lp in listas_pred}
    lista_predeterminada_actual = cliente.lista_precios_predeterminada
    costos_unitarios_por_producto: dict[int, Decimal] = {}

    precios_desactualizados_count = 0
    for item in precios:
        producto = item.nombre_producto
        if producto.id not in costos_unitarios_por_producto:
            costos_unitarios_por_producto[producto.id] = _costo_unitario_desde_stock(producto)
        precio_compra_unitario = costos_unitarios_por_producto[producto.id]

        if precio_compra_unitario and precio_compra_unitario > 0:
            producto = item.nombre_producto
            qty_secundario = Decimal(1 if es_pack(producto) else (producto.qty_secundario or 1))
            qty_terciario = Decimal(1 if es_pack(producto) else (producto.qty_terciario or 1))
            item.precio_compra_referencial = _round2(
                _costo_por_empaque(
                    Decimal(precio_compra_unitario),
                    item.empaque,
                    qty_secundario,
                    qty_terciario,
                )
            )
            item.diferencia_compra_venta = _round2(
                Decimal(item.precio_venta or 0) - item.precio_compra_referencial
            )
        else:
            item.precio_compra_referencial = None
            item.diferencia_compra_venta = None

        item.tiene_precio_compra_referencial = item.precio_compra_referencial is not None
        item.tiene_diferencia_compra_venta = item.diferencia_compra_venta is not None
        item.alerta_bajo_costo = (
            item.diferencia_compra_venta is not None and item.diferencia_compra_venta < 0
        )
        item.fecha_requiere_actualizacion = _fecha_requiere_actualizacion(item.vigencia)
        item.precio_desactualizado = _precio_esta_desactualizado(item.vigencia, today=today)
        if item.precio_desactualizado:
            precios_desactualizados_count += 1

    ultima_fecha_cliente = max((item.vigencia for item in precios if item.vigencia), default=None) or today
    default_desde_lista_actual = None
    if lista_predeterminada_actual:
        lista_actual = listas_pred_map.get(lista_predeterminada_actual.id)
        if lista_actual:
            default_desde_lista_actual = lista_actual.default_desde
        if default_desde_lista_actual is None:
            default_desde_lista_actual = (
                lista_predeterminada_actual.items.aggregate(max_vigencia=Max('vigencia'))["max_vigencia"]
            )
    vigencia_default = precio_en_edicion.vigencia if precio_en_edicion else ultima_fecha_cliente
    vigencia_import_default = default_desde_lista_actual or ultima_fecha_cliente

    if request.method == 'POST':
        accion = request.POST.get('accion')

        # --------------------------
        # 1) Importar desde lista
        # --------------------------
        if accion == 'importar_lista':
            lista_pred_id = request.POST.get('lista_predeterminada_id') or ''
            vig_override  = request.POST.get('vigencia_import') or None
            if not lista_pred_id.isdigit():
                messages.error(request, "Selecciona una Lista de Precios Predeterminada.")
                return redirect('asignar_precios', cliente_id=cliente.id)

            try:
                importar_desde_predeterminada(
                    cliente_id=cliente.id,
                    lista_pred_id=int(lista_pred_id),
                    vig_override=vig_override
                )
                messages.success(request, "Precios importados y lista asociada al cliente.")
            except Exception as e:
                messages.error(request, f"No se pudo importar: {e}")
            return redirect('asignar_precios', cliente_id=cliente.id)

        # --------------------------
        # 2) Guardar un precio puntual (tu flujo con Form)
        # --------------------------
        if accion == 'guardar_uno' or not accion:
            form = ListaPreciosForm(request.POST, cliente=cliente, instance=precio_en_edicion)
            if form.is_valid():
                # Aseguramos que IVA/TOTAL queden calculados y persistidos
                obj: ListaPrecios = form.save(commit=False)
                obj.nombre_cliente = cliente
                neto = _round2(Decimal(obj.precio_venta or 0))
                iva, total = _calc_iva_total(neto)
                obj.precio_venta = neto
                obj.precio_iva   = iva
                obj.precio_total = total
                obj.lista_predeterminada_origen = None
                obj.save()
                messages.success(
                    request,
                    "Precio actualizado correctamente." if precio_en_edicion else "Precio asignado correctamente."
                )
                return redirect('asignar_precios', cliente_id=cliente.id)
            else:
                for error in form.errors.values():
                    messages.error(request, error)
        else:
            messages.error(request, "Acción no reconocida.")
            return redirect('asignar_precios', cliente_id=cliente.id)

    else:
        form = ListaPreciosForm(cliente=cliente, instance=precio_en_edicion)

    producto_form_value = request.POST.get('nombre_producto') if request.method == 'POST' else (
        str(precio_en_edicion.nombre_producto_id) if precio_en_edicion else ''
    )
    empaque_form_value = request.POST.get('empaque') if request.method == 'POST' else (
        precio_en_edicion.empaque if precio_en_edicion else ''
    )
    precio_venta_form_value = request.POST.get('precio_venta') if request.method == 'POST' else (
        str(precio_en_edicion.precio_venta) if precio_en_edicion else ''
    )
    vigencia_form_value = request.POST.get('vigencia') if request.method == 'POST' else _date_input_value(vigencia_default)

    lista_predeterminada_id_form_value = request.POST.get('lista_predeterminada_id') if request.method == 'POST' else (
        str(lista_predeterminada_actual.id) if lista_predeterminada_actual else ''
    )
    vigencia_import_form_value = request.POST.get('vigencia_import') if request.method == 'POST' else _date_input_value(vigencia_import_default)

    return render(request, './views/clientes/asignar_precios.html', {
        'form': form,
        'cliente': cliente,
        'precios': precios,
        'productos': productos,
        'listas_predeterminadas': listas_pred,
        'lista_predeterminada_actual': lista_predeterminada_actual,
        'precio_en_edicion': precio_en_edicion,
        'producto_form_value': producto_form_value or '',
        'empaque_form_value': empaque_form_value or '',
        'precio_venta_form_value': precio_venta_form_value or '',
        'vigencia_form_value': vigencia_form_value or _date_input_value(vigencia_default),
        'lista_predeterminada_id_form_value': lista_predeterminada_id_form_value or '',
        'vigencia_import_form_value': vigencia_import_form_value or _date_input_value(vigencia_import_default),
        'vigencia_import_fallback': _date_input_value(vigencia_import_default),
        'precios_desactualizados_count': precios_desactualizados_count,
    })


@transaction.atomic
def importar_desde_predeterminada(cliente_id: int, lista_pred_id: int, vig_override: str | None = None):
    """
    Sincroniza una lista predeterminada a un cliente y la deja asociada.
    """
    from Apps.Pedidos.models import ListaPreciosPredeterminada

    cliente = Cliente.objects.get(pk=cliente_id)
    lista = ListaPreciosPredeterminada.objects.get(pk=lista_pred_id)
    return sincronizar_lista_predeterminada_a_cliente(
        cliente,
        lista,
        vig_override=vig_override,
        asociar=True,
        limpiar_huerfanos=True,
    )


@require_POST
def eliminar_precio(request, precio_id):
    """
    Elimina un precio asignado a un cliente para un producto específico.

    Args:
        precio_id (int): ID del precio a eliminar.

    Returns:
        HttpResponseRedirect: Redirección a la página de precios del cliente.
    """
    precio = get_object_or_404(ListaPrecios, id=precio_id)
    cliente_id = precio.nombre_cliente.id
    precio.delete()
    return redirect('asignar_precios', cliente_id=cliente_id)


# ------------------------------------------------------------------
# API - Obtener precio base de compra
# ------------------------------------------------------------------

def obtener_precio_base_compra(request, producto_id):
    """
    API: Retorna el precio de compra unitario más alto del producto normalizado por tipo de empaque.

    Este endpoint es utilizado por la calculadora de precios para clientes.

    Args:
        producto_id (int): ID del producto.

    Returns:
        JsonResponse: Resultado de la consulta con éxito o error.
    """
    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Producto no encontrado'})

    precio_max_unitario = costo_maximo_unitario(producto)
    if precio_max_unitario <= 0:
        return JsonResponse({'success': False, 'error': 'Sin registros de compra'})

    return JsonResponse({
        'success': True,
        'precio_unitario': float(precio_max_unitario),  # para JSON
        'qty_secundario': 1 if es_pack(producto) else int(producto.qty_secundario or 1),
        'qty_terciario': 1 if es_pack(producto) else int(producto.qty_terciario or 1),
    })


# Apps/Pedidos/views/cliente.py
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from Apps.Pedidos.models import Cliente, Producto, ListaPrecios, Categoria, Stock

MARGEN  = Decimal('25')     # 25% utilidad
IVA_TAX = Decimal('0.19')   # 19% IVA Chile
DOS_DEC = Decimal('0.01')

def _round2(x: Decimal) -> Decimal:
    return x.quantize(DOS_DEC, rounding=ROUND_HALF_UP)

def _costo_unitario_desde_stock(producto: Producto) -> Decimal:
    """
    Devuelve el costo unitario neto MÁXIMO normalizado a PRIMARIO desde Stock,
    usando la misma lógica que tu endpoint obtener_precio_base_compra.
    """
    return costo_maximo_unitario(producto)

def _costo_por_empaque(c_unit: Decimal, emp: str, qs: Decimal, qt: Decimal) -> Decimal:
    """
    Calcula el costo según el tipo de empaque.
    - PRIMARIO: costo unitario tal cual.
    - SECUNDARIO: costo unitario x cantidad secundaria.
    - TERCIARIO: costo unitario x (cantidad secundaria * cantidad terciaria).
    """
    if emp == 'PRIMARIO':
        return c_unit
    if emp == 'SECUNDARIO':
        return c_unit * (qs or 1)
    if emp == 'TERCIARIO':
        return c_unit * ((qs or 1) * (qt or 1))
    return c_unit


@transaction.atomic
def bulk_25_por_categoria(request, cliente_id: int, categoria_id: int):
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    productos = Producto.objects.filter(
        categoria_producto_id=categoria_id
    ).only('id', 'qty_secundario', 'qty_terciario')

    vigencia_date = date(date.today().year, 12, 31)
    margen = Decimal(request.GET.get('margen', '25')) 

    creados = actualizados = omitidos = 0

    for p in productos:
        c_unit = _costo_unitario_desde_stock(p)
        if c_unit <= 0:
            omitidos += 1
            continue

        qs = Decimal(p.qty_secundario or 1)
        qt = Decimal(p.qty_terciario  or 1)

        for emp in ('PRIMARIO', 'SECUNDARIO', 'TERCIARIO'):
            costo = _costo_por_empaque(c_unit, emp, qs, qt)
            precio_neto = _round2(costo * (Decimal('1') + margen / Decimal('100')))
            precio_iva  = _round2(precio_neto * IVA_TAX)
            precio_total= _round2(precio_neto + precio_iva)

            lp, created = ListaPrecios.objects.get_or_create(
                nombre_cliente=cliente,
                nombre_producto=p,
                empaque=emp,
                defaults={
                    'precio_venta': precio_neto,
                    'precio_iva':   precio_iva,      # <-- NUEVO
                    'precio_total': precio_total,    # <-- NUEVO
                    'vigencia':     vigencia_date,
                }
            )
            if created:
                creados += 1
            else:
                # Si no quieres pisar existentes, comenta este bloque.
                lp.precio_venta = precio_neto
                lp.precio_iva   = precio_iva      # <-- NUEVO
                lp.precio_total = precio_total    # <-- NUEVO
                lp.vigencia     = vigencia_date
                lp.save(update_fields=['precio_venta', 'precio_iva', 'precio_total', 'vigencia'])
                actualizados += 1

    messages.success(
        request,
        f'Bulk 25%: {creados} creados, {actualizados} actualizados, {omitidos} omitidos.'
    )
    # Quedarse en la misma pantalla:
    return redirect('asignar_precios', cliente_id=cliente.id)
