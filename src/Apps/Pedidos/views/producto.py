"""
Productos - Vistas para la gestión de productos, stock, precios y categorías.

Incluye:
- CRUD para productos, categorías y subcategorías.
- Registro de precios por producto y cliente.
- Cálculo dinámico de precios con márgenes sugeridos.
- Cálculo de stock en distintos niveles de empaque.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, Http404
from django.db import transaction, IntegrityError
from django.db.models import Sum, Case, When, Value, IntegerField, F, Avg, Max, Min
from decimal import Decimal, ROUND_HALF_UP

from Apps.Pedidos.models import (
    Producto, Categoria, Subcategoria, CategoriaEmpaque,
    ListaPrecios, Stock, Proveedor, CodigoProveedor
)
from Apps.Pedidos.forms import (
    CrearProductoForm, CategoriaEmpaqueForm, SubCategoriaForm
)
from Apps.Pedidos.utils import lista_generica, eliminar_generica

# --- Constantes Decimal ---
DOS_DEC = Decimal('0.01')
UNO     = Decimal('1')


# =========================
# Helpers Códigos Proveedor
# =========================
def _parse_codigos_proveedor(post_data):
    """
    Lee codigos_proveedor[IDX][proveedor|codigo_proveedor] y devuelve:
    - lista válida: [{'proveedor_id': int, 'codigo': str}, ...]
    - errores: [str, ...]
    Deduplica por (proveedor_id, codigo.lower()).
    """
    items = {}
    for k, v in post_data.items():
        if not k.startswith('codigos_proveedor['):
            continue
        try:
            idx = k.split('[', 1)[1].split(']', 1)[0]
            campo = k.rsplit('[', 1)[1].rstrip(']')
        except Exception:
            continue
        items.setdefault(idx, {})[campo] = v

    out, errores, vistos = [], [], set()
    for idx, d in items.items():
        prov_raw = (d.get('proveedor') or '').strip()
        cod = (d.get('codigo_proveedor') or '').strip()
        if not cod:
            errores.append(f"Fila {idx}: el código es obligatorio.")
            continue
        if not prov_raw.isdigit():
            errores.append(f"Fila {idx}: debes seleccionar un proveedor.")
            continue
        prov_id = int(prov_raw)
        clave = (prov_id, cod.lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        out.append({'proveedor_id': prov_id, 'codigo': cod})
    return out, errores


def _sync_codigos_proveedor(producto, nuevos):
    """
    Sincroniza sin borrar a ciegas:
    - Crea los que faltan
    - Elimina los que ya no están
    - Mantiene los que coinciden
    Retorna (creados, eliminados).
    """
    existentes = list(CodigoProveedor.objects
                      .filter(producto=producto)
                      .values('proveedor_id', 'codigo_proveedor'))
    set_exist = {(e['proveedor_id'], e['codigo_proveedor'].lower()) for e in existentes}
    set_nuevos = {(n['proveedor_id'], n['codigo'].lower()) for n in nuevos}

    to_create = set_nuevos - set_exist
    to_delete = set_exist - set_nuevos

    creados = eliminados = 0

    # Crear
    objs = [
        CodigoProveedor(
            producto=producto,
            proveedor_id=prov_id,
            codigo_proveedor=codigo
        )
        for (prov_id, codigo) in to_create
    ]
    if objs:
        try:
            res = CodigoProveedor.objects.bulk_create(objs, batch_size=500, ignore_conflicts=True)
            creados = len(res)
        except TypeError:
            for o in objs:
                try:
                    o.save()
                    creados += 1
                except IntegrityError:
                    continue

    # Eliminar
    for (prov_id, codigo_lc) in to_delete:
        eliminados += CodigoProveedor.objects.filter(
            producto=producto,
            proveedor_id=prov_id
        ).extra(where=["LOWER(codigo_proveedor) = %s"], params=[codigo_lc]).delete()[0]

    return creados, eliminados



# =========================
# CATEGORÍAS Y SUBCATEGORÍAS
# =========================
def categorias_y_subcategorias(request):
    """
    Muestra y gestiona la creación de categorías y subcategorías de productos.
    """
    if request.method == 'POST':
        # Crear nueva categoría
        if 'crear_categoria' in request.POST:
            nombre = request.POST.get('categoria_nombre', '').strip()
            if nombre and not Categoria.objects.filter(categoria__iexact=nombre).exists():
                Categoria.objects.create(categoria=nombre)
            return redirect('categorias_y_subcategorias')

        # Crear nueva subcategoría asociada a una categoría existente
        elif 'crear_subcategoria' in request.POST:
            nombre = request.POST.get('subcategoria_nombre', '').strip()
            cat_id = request.POST.get('categoria_id')
            if nombre and cat_id:
                categoria = get_object_or_404(Categoria, pk=cat_id)
                if not Subcategoria.objects.filter(subcategoria__iexact=nombre, categoria=categoria).exists():
                    Subcategoria.objects.create(subcategoria=nombre, categoria=categoria)
            return redirect('categorias_y_subcategorias')

    categorias = Categoria.objects.all()
    subcategorias = Subcategoria.objects.all()
    return render(request, 'views/categorias/formulario_categoria.html', {
        'categorias': categorias,
        'subcategorias': subcategorias,
    })


def obtener_subcategorias(request):
    """
    Devuelve las subcategorías asociadas a una categoría (AJAX).
    """
    categoria_id = request.GET.get('categoria_id')
    if categoria_id:
        subcategorias = Subcategoria.objects.filter(categoria_id=categoria_id).values('id', 'subcategoria')
        return JsonResponse(list(subcategorias), safe=False)
    return JsonResponse({'error': 'No se especificó categoría'}, status=400)


def editar_subcategoria(request, id):
    """
    Edita una subcategoría existente.
    """
    subcategoria = get_object_or_404(Subcategoria, id=id)
    categorias = Categoria.objects.all()

    if request.method == 'POST':
        form = SubCategoriaForm(request.POST, instance=subcategoria)
        if form.is_valid():
            form.save()
            messages.success(request, "Subcategoría actualizada correctamente.")
            return redirect('categorias_y_subcategorias')
        else:
            messages.error(request, "Error al actualizar la subcategoría. Revisa los campos.")
    else:
        form = SubCategoriaForm(instance=subcategoria)

    return render(request, './views/categorias/editar_subcategoria.html', {
        'form': form,
        'subcategoria': subcategoria,
        'categorias': categorias
    })


def eliminar_subcategoria(request, id):
    """
    Elimina una subcategoría.
    """
    subcategoria = get_object_or_404(Subcategoria, pk=id)
    subcategoria.delete()
    return redirect('categorias_y_subcategorias')


# ================
# CRUD PRODUCTOS
# ================
def lista_productos(request):
    """
    Lista todos los productos registrados en el sistema.
    """
    return lista_generica(request, Producto, 'views/producto/lista_productos.html', 'productos')


def crear_producto(request):
    """
    Crea un nuevo producto con su estructura de empaques, categorías
    y códigos de proveedor (opcionales).
    """
    form = CrearProductoForm(request.POST or None)
    categorias = Categoria.objects.all()
    # Subcategorías se cargan vía AJAX; puedes traer todas si las necesitas:
    subcategorias = Subcategoria.objects.all()
    medidas = Producto.UNIDAD_CHOICES
    empaques_primarios = CategoriaEmpaque.objects.filter(nivel='PRIMARIO')
    empaques_secundarios = CategoriaEmpaque.objects.filter(nivel='SECUNDARIO')
    empaques_terciarios = CategoriaEmpaque.objects.filter(nivel='TERCIARIO')
    proveedores = Proveedor.objects.all().order_by('nombre_proveedor')

    if request.method == 'POST':
        codigos, errores = _parse_codigos_proveedor(request.POST)

        if errores:
            for e in errores:
                messages.error(request, e)

        if form.is_valid() and not errores:
            with transaction.atomic():
                producto = form.save()
                _sync_codigos_proveedor(producto, codigos)  
            messages.success(request, "Producto creado correctamente.")
            return redirect('lista_productos')
        else:
            print(form.errors)  # 👈 DEBUG (opcional)

    return render(request, 'views/producto/crear_producto.html', {
        'form': form,
        'categorias': categorias,
        'subcategorias': subcategorias,
        'medidas': medidas,
        'empaques_primarios': empaques_primarios,
        'empaques_secundarios': empaques_secundarios,
        'empaques_terciarios': empaques_terciarios,
        'proveedores': proveedores,            # 👈 requerido por el repetidor
    })


def editar_producto(request, id):
    producto = get_object_or_404(Producto, pk=id)
    form = CrearProductoForm(request.POST or None, instance=producto)

    categorias = Categoria.objects.all()
    subcategorias = Subcategoria.objects.all()
    medidas = Producto.UNIDAD_CHOICES
    empaques_primarios = CategoriaEmpaque.objects.filter(nivel='PRIMARIO')
    empaques_secundarios = CategoriaEmpaque.objects.filter(nivel='SECUNDARIO')
    empaques_terciarios = CategoriaEmpaque.objects.filter(nivel='TERCIARIO')
    proveedores = Proveedor.objects.all().order_by('nombre_proveedor')
    codigos_proveedor = CodigoProveedor.objects.filter(producto=producto).select_related('proveedor').order_by('proveedor__nombre_proveedor', 'codigo_proveedor')

    if request.method == 'POST':
        nuevos, errores = _parse_codigos_proveedor(request.POST)
        if errores:
            for e in errores:
                messages.error(request, e)

        if form.is_valid() and not errores:
            try:
                with transaction.atomic():
                    form.save()
                    creados = _sync_codigos_proveedor(producto, nuevos)
                messages.success(request, f"Producto actualizado. Códigos guardados: {creados}.")
                return redirect('lista_productos')
            except IntegrityError as e:
                messages.error(request, f"Error de integridad al guardar códigos: {e}")
        # si el form no es válido o hubo errores, seguimos a render para que se muestren

    return render(request, './views/producto/editar_producto.html', {
        'form': form,
        'producto': producto,
        'categorias': categorias,
        'subcategorias': subcategorias,
        'medidas': medidas,
        'empaques_primarios': empaques_primarios,
        'empaques_secundarios': empaques_secundarios,
        'empaques_terciarios': empaques_terciarios,
        'proveedores': proveedores,
        'codigos_proveedor': codigos_proveedor,
    })


def eliminar_producto(request, id):
    """
    Elimina un producto.
    """
    return eliminar_generica(request, Producto, id, 'lista_productos')


# ======================
# PRECIOS Y CALCULADORA
# ======================
def lista_precios(request):
    """
    Lista todos los precios cargados para productos por cliente.
    """
    precios = ListaPrecios.objects.select_related('nombre_cliente', 'nombre_producto').all()
    return render(request, './views/producto/lista_precios.html', {'precios': precios})


def calculadora_precios(request):
    """
    Vista para simular precios de venta a partir de valores históricos.
    """
    productos = Producto.objects.all().order_by('nombre_producto')
    return render(request, './views/producto/calculadora_precios.html', {'productos': productos})


def obtener_precio_maximo(request, producto_id):
    """
    Devuelve precio base (máximo histórico por unidad), más resumen de precios.
    Todo calculado con Decimal y redondeo HALF_UP.
    """
    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        return JsonResponse({'error': 'Producto no encontrado'}, status=404)

    recepciones = Stock.objects.filter(
        producto_id=producto_id,
        tipo_movimiento='DISPONIBLE',
        precio_unitario__isnull=False
    )

    if not recepciones.exists():
        return JsonResponse({'error': 'No hay precios registrados para este producto.'}, status=400)

    # ✅ Tomar la recepción con mayor precio_unitario
    rec_max = recepciones.order_by('-precio_unitario').first()
    precio_base = Decimal(rec_max.precio_unitario)

    # Normalizar a unidad primaria según empaque
    if rec_max.empaque == 'SECUNDARIO':
        divisor = Decimal(producto.qty_secundario or 1)
        if divisor <= 0:
            divisor = UNO
        precio_base = precio_base / divisor
    elif rec_max.empaque == 'TERCIARIO':
        factor = (producto.qty_secundario or 1) * (producto.qty_terciario or 1)
        divisor = Decimal(factor if factor else 1)
        if divisor <= 0:
            divisor = UNO
        precio_base = precio_base / divisor

    # helper de 2 decimales
    def q2(x: Decimal) -> Decimal:
        return x.quantize(DOS_DEC, rounding=ROUND_HALF_UP)

    # Resumen crudo por registro (no normalizado)
    resumen = recepciones.aggregate(
        maximo=Max('precio_unitario'),
        promedio=Avg('precio_unitario'),
        minimo=Min('precio_unitario')
    )

    precio_prom = Decimal(resumen['promedio'] if resumen['promedio'] is not None else precio_base)
    precio_max = Decimal(resumen['maximo']  if resumen['maximo']  is not None else precio_base)
    precio_min = Decimal(resumen['minimo']  if resumen['minimo']  is not None else precio_base)

    return JsonResponse({
        'precio_base': float(q2(precio_base)),
        'precio_promedio': float(q2(precio_prom)),
        'precio_maximo': float(q2(precio_max)),
        'precio_minimo': float(q2(precio_min)),
        'precio_sugerido': float(q2(precio_base * Decimal('1.40'))),
        'qty_secundario': producto.qty_secundario or 1,
        'nombre_empaque_secundario': producto.empaque_secundario.nombre if producto.empaque_secundario else 'Manga',
        'nombre_empaque_primario': producto.empaque_primario.nombre if producto.empaque_primario else 'Unidad'
    })


# =======
# STOCK
# =======
def stock_productos(request):
    """
    Muestra el stock disponible, reservado y despachado de todos los productos.
    Calcula cantidades en unidades equivalentes, independientemente del tipo de empaque.
    """
    productos = Producto.objects.select_related(
        'empaque_primario', 'empaque_secundario'
    )

    def obtener_stock_por_tipo(tipo):
        return (
            Stock.objects.filter(tipo_movimiento=tipo)
            .annotate(
                qty_unidad=Case(
                    When(empaque__iexact='TERCIARIO', then=F('qty') * F('producto__qty_terciario') * F('producto__qty_secundario')),
                    When(empaque__iexact='SECUNDARIO', then=F('qty') * F('producto__qty_secundario')),
                    When(empaque__iexact='PRIMARIO', then=F('qty')),
                    default=Value(0),
                    output_field=IntegerField()
                )
            )
            .values('producto')
            .annotate(total=Sum('qty_unidad'))
        )

    stock_dict = {i['producto']: i['total'] for i in obtener_stock_por_tipo('DISPONIBLE')}
    reserva_dict = {i['producto']: i['total'] for i in obtener_stock_por_tipo('RESERVA')}
    despachado_dict = {i['producto']: i['total'] for i in obtener_stock_por_tipo('DESPACHO')}

    productos_info = []
    for prod in productos:
        idp = prod.id
        stock = stock_dict.get(idp, 0)
        reserva = reserva_dict.get(idp, 0)
        despacho = despachado_dict.get(idp, 0)
        disponible = stock - reserva - despacho

        productos_info.append({
            'codigo_interno': prod.codigo_producto_interno,
            'nombre': prod.nombre_producto,
            'qty_minima': prod.qty_minima,
            'stock_empaque_primario': disponible,
            'stock_empaque_secundario': disponible // prod.qty_secundario if prod.qty_secundario else 0,
            'reserva_unidades': reserva,
            'empaque_primario_nombre': prod.empaque_primario.nombre if prod.empaque_primario else '',
            'empaque_secundario_nombre': prod.empaque_secundario.nombre if prod.empaque_secundario else '',
        })

    return render(request, './views/producto/stock_productos.html', {'productos_info': productos_info})


# =========
# EMPAQUES
# =========
def categorias_empaque(request):
    """
    Gestiona la creación de categorías de empaque: primario, secundario y terciario.
    """
    empaques = CategoriaEmpaque.objects.all()

    if request.method == 'POST':
        form = CategoriaEmpaqueForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Empaque guardado correctamente.")
            return redirect('categorias_empaque')
    else:
        form = CategoriaEmpaqueForm()

    return render(request, './views/producto/categorias_empaque.html', {
        'form': form,
        'empaques': empaques,
    })

def obtener_empaques_producto(request, producto_id):
    """
    Devuelve los empaques definidos para un producto específico.
    Este endpoint es consumido por AJAX.
    """
    try:
        producto = Producto.objects.get(pk=producto_id)
    except Producto.DoesNotExist:
        raise Http404("Producto no encontrado")

    empaques = []
    if producto.empaque_primario:
        empaques.append({'nivel': 'PRIMARIO', 'nombre': producto.empaque_primario.nombre})
    if producto.empaque_secundario:
        empaques.append({'nivel': 'SECUNDARIO', 'nombre': producto.empaque_secundario.nombre})
    if producto.empaque_terciario:
        empaques.append({'nivel': 'TERCIARIO', 'nombre': producto.empaque_terciario.nombre})

    return JsonResponse({'success': True, 'empaques': empaques})
