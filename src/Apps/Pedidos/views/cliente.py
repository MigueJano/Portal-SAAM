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
from django.db.models import F
from django.db import transaction 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from Apps.Pedidos.models import Cliente, Producto, ListaPrecios, Stock
from Apps.Pedidos.forms import ClienteForm, ListaPreciosForm

# --- Decimal helpers para dinero ---
from decimal import Decimal, ROUND_HALF_UP


DOS_DEC = Decimal('0.01')


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


def asignar_precios(request, cliente_id):
    """
    Asignar precios personalizados a un cliente:
    - Guardar un precio puntual (usa ListaPreciosForm).
    - Importar todos los precios desde una Lista de Precios Predeterminada.
    """
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    precios = ListaPrecios.objects.filter(nombre_cliente=cliente)
    productos = Producto.objects.all().order_by('nombre_producto')

    # Listas predeterminadas activas para el selector
    from Apps.Pedidos.models import ListaPreciosPredeterminada  # evitar import circular si lo hubiera
    listas_pred = ListaPreciosPredeterminada.objects.filter(activa=True).order_by('nombre_listaprecios')

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
                messages.success(request, "Precios importados desde la lista predeterminada.")
            except Exception as e:
                messages.error(request, f"No se pudo importar: {e}")
            return redirect('asignar_precios', cliente_id=cliente.id)

        # --------------------------
        # 2) Guardar un precio puntual (tu flujo con Form)
        # --------------------------
        if accion == 'guardar_uno' or not accion:
            form = ListaPreciosForm(request.POST, cliente=cliente)
            if form.is_valid():
                # Aseguramos que IVA/TOTAL queden calculados y persistidos
                obj: ListaPrecios = form.save(commit=False)
                obj.nombre_cliente = cliente
                neto = _round2(Decimal(obj.precio_venta or 0))
                iva, total = _calc_iva_total(neto)
                obj.precio_venta = neto
                obj.precio_iva   = iva
                obj.precio_total = total
                obj.save()
                messages.success(request, "Precio asignado correctamente.")
                return redirect('asignar_precios', cliente_id=cliente.id)
            else:
                for error in form.errors.values():
                    messages.error(request, error)
        else:
            messages.error(request, "Acción no reconocida.")
            return redirect('asignar_precios', cliente_id=cliente.id)

    else:
        form = ListaPreciosForm(cliente=cliente)

    return render(request, './views/clientes/asignar_precios.html', {
        'form': form,
        'cliente': cliente,
        'precios': precios,
        'productos': productos,
        # 'categorias': ...  # <-- ya NO se envía
        'listas_predeterminadas': listas_pred,   # <-- nuevo
    })


@transaction.atomic
def importar_desde_predeterminada(cliente_id: int, lista_pred_id: int, vig_override: str | None = None):
    """
    Copia todos los ítems de ListaPreciosPredeterminada a ListaPrecios del cliente.
    - Si ya existe (cliente, producto, empaque), se ACTUALIZA.
    - Si vig_override viene, reemplaza la vigencia de todos los ítems.
    """
    from Apps.Pedidos.models import ListaPreciosPredItem  # import local para evitar ciclos

    items = (
        ListaPreciosPredItem.objects
        .select_related("nombre_producto")
        .filter(listaprecios_id=lista_pred_id)
    )

    for it in items:
        producto = it.nombre_producto
        empaque  = it.empaque
        neto     = _round2(Decimal(it.precio_venta or 0))
        iva      = _round2(Decimal(it.precio_iva or 0))
        total    = _round2(Decimal(it.precio_total or 0))
        vigencia = vig_override or it.vigencia

        obj = (
            ListaPrecios.objects
            .filter(nombre_cliente_id=cliente_id, nombre_producto=producto, empaque=empaque)
            .first()
        )
        if obj:
            obj.precio_venta = neto
            obj.precio_iva   = iva
            obj.precio_total = total
            obj.vigencia     = vigencia
            obj.save(update_fields=['precio_venta', 'precio_iva', 'precio_total', 'vigencia'])
        else:
            ListaPrecios.objects.create(
                nombre_cliente_id=cliente_id,
                nombre_producto=producto,
                empaque=empaque,
                precio_venta=neto,
                precio_iva=iva,
                precio_total=total,
                vigencia=vigencia,
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

    # Ajusta 'tipo_movimiento' si en tu modelo real corresponde a 'RECEPCION'
    precios_stock = Stock.objects.filter(
        producto=producto,
        tipo_movimiento='DISPONIBLE',
        precio_unitario__isnull=False,
    )

    precios_normalizados = []
    for item in precios_stock:
        # precio como Decimal
        precio = Decimal(item.precio_unitario)

        # factor por empaque (a unidades primarias)
        q2 = Decimal(producto.qty_secundario or 1)
        q3 = Decimal(producto.qty_terciario or 1)

        if item.empaque == 'SECUNDARIO':
            factor = q2
        elif item.empaque == 'TERCIARIO':
            factor = q2 * q3
        else:  # PRIMARIO u otro
            factor = Decimal(1)

        if factor <= 0:
            factor = Decimal(1)

        # normaliza y guarda (con 2 decimales consistentes)
        precio_unitario = (precio / factor).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        precios_normalizados.append(precio_unitario)

    if not precios_normalizados:
        return JsonResponse({'success': False, 'error': 'Sin registros de compra'})

    precio_max_unitario = max(precios_normalizados)

    return JsonResponse({
        'success': True,
        'precio_unitario': float(precio_max_unitario),  # para JSON
        'qty_secundario': int(producto.qty_secundario or 1),
        'qty_terciario': int(producto.qty_terciario or 1),
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
    qs = Stock.objects.filter(
        producto=producto,
        tipo_movimiento='DISPONIBLE',
        precio_unitario__isnull=False,
    ).only('precio_unitario', 'empaque')

    if not qs.exists():
        return Decimal('0')

    q2 = Decimal(producto.qty_secundario or 1)
    q3 = Decimal(producto.qty_terciario  or 1)
    max_unit = None

    for s in qs:
        precio = Decimal(s.precio_unitario)
        if s.empaque == 'SECUNDARIO':
            factor = q2
        elif s.empaque == 'TERCIARIO':
            factor = q2 * q3
        else:
            factor = Decimal(1)
        if factor <= 0:
            factor = Decimal(1)
        unit = (precio / factor).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        max_unit = unit if (max_unit is None or unit > max_unit) else max_unit

    return max_unit or Decimal('0')

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
