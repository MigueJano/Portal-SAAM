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
    ListaPrecios, Stock, Proveedor, CodigoProveedor, PackComponente
)
from Apps.Pedidos.forms import (
    CrearProductoForm, CrearPackForm, CategoriaEmpaqueForm, SubCategoriaForm
)
from Apps.Pedidos.services import (
    costo_referencial_pack,
    costo_maximo_unitario,
    es_pack,
    factor_empaque,
    q2,
    snapshot_pack,
    stock_cache_simple,
    stock_disponible_pack,
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
        if not prov_raw and not cod:
            # La fila vacia equivale a no informar codigos del proveedor.
            continue
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


def _parse_componentes_pack(post_data):
    """
    Lee componentes[IDX][producto|empaque|cantidad] y retorna filas válidas.
    """
    items = {}
    for key, value in post_data.items():
        if not key.startswith('componentes['):
            continue
        try:
            idx = key.split('[', 1)[1].split(']', 1)[0]
            campo = key.rsplit('[', 1)[1].rstrip(']')
        except Exception:
            continue
        items.setdefault(idx, {})[campo] = value

    componentes = []
    errores = []
    for idx, data in items.items():
        producto_raw = (data.get('producto') or '').strip()
        empaque = (data.get('empaque') or '').strip().upper()
        cantidad_raw = (data.get('cantidad') or '').strip()

        if not producto_raw and not empaque and not cantidad_raw:
            continue
        if not producto_raw.isdigit():
            errores.append(f"Componente {idx}: debes seleccionar un producto.")
            continue
        if empaque not in {'PRIMARIO', 'SECUNDARIO', 'TERCIARIO'}:
            errores.append(f"Componente {idx}: empaque inválido.")
            continue
        if not cantidad_raw.isdigit() or int(cantidad_raw) <= 0:
            errores.append(f"Componente {idx}: la cantidad debe ser mayor a cero.")
            continue

        componentes.append({
            'orden': int(idx),
            'producto_id': int(producto_raw),
            'empaque': empaque,
            'cantidad': int(cantidad_raw),
        })

    return componentes, errores


def _sync_componentes_pack(pack, componentes):
    PackComponente.objects.filter(pack=pack).delete()
    if not componentes:
        return []

    rows = [
        PackComponente(
            pack=pack,
            producto_id=item['producto_id'],
            empaque=item['empaque'],
            cantidad=item['cantidad'],
            orden=item['orden'],
        )
        for item in componentes
    ]
    return PackComponente.objects.bulk_create(rows)


def _validar_componentes_pack(pack, componentes):
    errores = []
    if len(componentes) < 1:
        errores.append("Debes agregar al menos 1 componente al pack.")
        return errores

    vistos = set()
    for idx, item in enumerate(componentes, start=1):
        if item['producto_id'] == pack.id:
            errores.append(f"Componente {idx}: un pack no puede contenerse a sí mismo.")
            continue

        producto = Producto.objects.filter(pk=item['producto_id']).only('id', 'tipo_producto').first()
        if not producto:
            errores.append(f"Componente {idx}: producto no encontrado.")
            continue
        if es_pack(producto):
            errores.append(f"Componente {idx}: no se permiten packs dentro de packs.")
            continue

        if item['empaque'] == 'PRIMARIO' and not producto.empaque_primario_id:
            errores.append(f"Componente {idx}: el producto no tiene empaque primario configurado.")
            continue
        if item['empaque'] == 'SECUNDARIO' and not producto.empaque_secundario_id:
            errores.append(f"Componente {idx}: el producto no tiene empaque secundario configurado.")
            continue
        if item['empaque'] == 'TERCIARIO' and not producto.empaque_terciario_id:
            errores.append(f"Componente {idx}: el producto no tiene empaque terciario configurado.")
            continue

        clave = (item['producto_id'], item['empaque'])
        if clave in vistos:
            errores.append(
                f"Componente {idx}: el producto ya fue agregado con el mismo empaque; ajusta la cantidad en una sola fila."
            )
            continue
        vistos.add(clave)

    return errores


def _contexto_pack(pack=None):
    stock_actual = stock_cache_simple()
    componente_rows = []
    if pack is not None:
        componente_rows = list(
            PackComponente.objects
            .filter(pack=pack)
            .select_related('producto')
            .order_by('orden', 'id')
        )

    return {
        'categorias': Categoria.objects.all(),
        'subcategorias': Subcategoria.objects.all(),
        'empaques_primarios': CategoriaEmpaque.objects.filter(nivel='PRIMARIO'),
        'productos_componentes': Producto.objects.filter(tipo_producto='SIMPLE').order_by('nombre_producto'),
        'stock_componentes_map': stock_actual,
        'componentes_pack': componente_rows,
        'resumen_pack': snapshot_pack(pack) if pack else [],
        'costo_referencial_pack': costo_referencial_pack(pack) if pack else Decimal('0.00'),
        'stock_pack_disponible': stock_disponible_pack(pack, cache=stock_actual) if pack else 0,
    }



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
    productos = (
        Producto.objects
        .select_related('categoria_producto', 'subcategoria_producto')
        .order_by('tipo_producto', 'nombre_producto')
    )
    return render(request, 'views/producto/lista_productos.html', {'productos': productos})


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
                producto = form.save(commit=False)
                producto.tipo_producto = 'SIMPLE'
                producto.save()
                _sync_codigos_proveedor(producto, codigos)  
            messages.success(request, "Producto creado correctamente.")
            return redirect('lista_productos')
        else:
            messages.error(request, "No fue posible crear el producto. Revisa los datos ingresados.")

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


def crear_pack(request):
    form = CrearPackForm(request.POST or None)
    contexto = _contexto_pack()

    if request.method == 'POST':
        componentes, errores = _parse_componentes_pack(request.POST)

        if form.is_valid():
            pack = form.save(commit=False)
            pack.tipo_producto = 'PACK'
            pack.qty_terciario = 1
            pack.qty_secundario = 1
            pack.qty_primario = 1
            pack.qty_unidad = 1
            pack.medida = 'und'
            pack.qty_minima = 0
            pack.categoria_producto = None
            pack.subcategoria_producto = None
            pack.empaque_primario = None
            errores.extend(_validar_componentes_pack(pack, componentes))

            if not errores:
                with transaction.atomic():
                    pack.save()
                    _sync_componentes_pack(pack, componentes)
                messages.success(request, "Pack creado correctamente.")
                return redirect('lista_productos')

        for error in errores:
            messages.error(request, error)
        messages.error(request, "No fue posible crear el pack. Revisa los datos ingresados.")
        contexto['componentes_pack_post'] = componentes

    contexto.update({
        'form': form,
        'modo_pack': 'crear',
        'pack': None,
    })
    return render(request, 'views/producto/crear_pack.html', contexto)


def editar_producto(request, id):
    producto = get_object_or_404(Producto, pk=id)
    if es_pack(producto):
        return redirect('editar_pack', id=producto.id)
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
                    producto_editado = form.save(commit=False)
                    producto_editado.tipo_producto = 'SIMPLE'
                    producto_editado.save()
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


def editar_pack(request, id):
    pack = get_object_or_404(Producto, pk=id, tipo_producto='PACK')
    form = CrearPackForm(request.POST or None, instance=pack)
    contexto = _contexto_pack(pack)

    if request.method == 'POST':
        componentes, errores = _parse_componentes_pack(request.POST)
        if form.is_valid():
            pack = form.save(commit=False)
            pack.tipo_producto = 'PACK'
            pack.qty_terciario = 1
            pack.qty_secundario = 1
            pack.qty_primario = 1
            pack.qty_unidad = 1
            pack.medida = 'und'
            pack.qty_minima = 0
            pack.categoria_producto = None
            pack.subcategoria_producto = None
            pack.empaque_primario = None
            errores.extend(_validar_componentes_pack(pack, componentes))

            if not errores:
                with transaction.atomic():
                    pack.save()
                    _sync_componentes_pack(pack, componentes)
                messages.success(request, "Pack actualizado correctamente.")
                return redirect('lista_productos')

        for error in errores:
            messages.error(request, error)
        messages.error(request, "No fue posible actualizar el pack. Revisa los datos ingresados.")
        contexto['componentes_pack_post'] = componentes

    contexto.update({
        'form': form,
        'modo_pack': 'editar',
        'pack': pack,
    })
    return render(request, 'views/producto/crear_pack.html', contexto)


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
    Devuelve el costo referencial máximo por unidad de venta.
    Para packs, el valor corresponde a la suma del costo de sus componentes.
    """
    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        return JsonResponse({'error': 'Producto no encontrado'}, status=404)

    if es_pack(producto):
        precio_base = costo_referencial_pack(producto)
        if precio_base <= 0:
            return JsonResponse({'error': 'No hay costos registrados para los componentes de este pack.'}, status=400)

        precio_prom = precio_base
        precio_max = precio_base
        precio_min = precio_base
        qty_secundario = 1
        nombre_empaque_secundario = producto.empaque_primario.nombre if producto.empaque_primario else 'Pack'
    else:
        recepciones = Stock.objects.filter(
            producto_id=producto_id,
            tipo_movimiento='DISPONIBLE',
            precio_unitario__isnull=False
        )
        if not recepciones.exists():
            return JsonResponse({'error': 'No hay precios registrados para este producto.'}, status=400)

        precio_base = costo_maximo_unitario(producto)
        resumen = recepciones.aggregate(
            maximo=Max('precio_unitario'),
            promedio=Avg('precio_unitario'),
            minimo=Min('precio_unitario')
        )
        precio_prom = Decimal(resumen['promedio'] if resumen['promedio'] is not None else precio_base)
        precio_max = Decimal(resumen['maximo'] if resumen['maximo'] is not None else precio_base)
        precio_min = Decimal(resumen['minimo'] if resumen['minimo'] is not None else precio_base)
        qty_secundario = producto.qty_secundario or 1
        nombre_empaque_secundario = producto.empaque_secundario.nombre if producto.empaque_secundario else 'Manga'

    return JsonResponse({
        'precio_base': float(q2(precio_base)),
        'precio_promedio': float(q2(precio_prom)),
        'precio_maximo': float(q2(precio_max)),
        'precio_minimo': float(q2(precio_min)),
        'precio_sugerido': float(q2(precio_base * Decimal('1.40'))),
        'qty_secundario': qty_secundario,
        'nombre_empaque_secundario': nombre_empaque_secundario,
        'nombre_empaque_primario': producto.empaque_primario.nombre if producto.empaque_primario else ('Pack' if es_pack(producto) else 'Unidad')
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
    stock_base = stock_cache_simple()

    def obtener_stock_por_tipo(tipo):
        filas = (
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
        return {item['producto']: int(item['total'] or 0) for item in filas}

    stock_dict = obtener_stock_por_tipo('DISPONIBLE')
    reserva_dict = obtener_stock_por_tipo('RESERVA')
    despachado_dict = obtener_stock_por_tipo('DESPACHO')

    productos_info = []
    for prod in productos:
        if es_pack(prod):
            disponible = stock_disponible_pack(prod, cache=stock_base)
            reserva = 0
            secundario = 0
            empaque_secundario = ''
        else:
            idp = prod.id
            stock = stock_dict.get(idp, 0)
            reserva = reserva_dict.get(idp, 0)
            despacho = despachado_dict.get(idp, 0)
            disponible = stock - reserva - despacho
            secundario = disponible // prod.qty_secundario if prod.qty_secundario else 0
            empaque_secundario = prod.empaque_secundario.nombre if prod.empaque_secundario else ''

        productos_info.append({
            'codigo_interno': prod.codigo_producto_interno,
            'nombre': prod.nombre_producto,
            'qty_minima': prod.qty_minima,
            'tipo_producto': prod.tipo_producto,
            'stock_empaque_primario': disponible,
            'stock_empaque_secundario': secundario,
            'reserva_unidades': reserva,
            'empaque_primario_nombre': prod.empaque_primario.nombre if prod.empaque_primario else ('Pack' if es_pack(prod) else ''),
            'empaque_secundario_nombre': empaque_secundario,
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
    elif es_pack(producto):
        empaques.append({'nivel': 'PRIMARIO', 'nombre': 'Pack'})
    if producto.empaque_secundario:
        empaques.append({'nivel': 'SECUNDARIO', 'nombre': producto.empaque_secundario.nombre})
    if producto.empaque_terciario:
        empaques.append({'nivel': 'TERCIARIO', 'nombre': producto.empaque_terciario.nombre})

    return JsonResponse({'success': True, 'empaques': empaques})
