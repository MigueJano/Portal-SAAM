# Apps/indicadores/views/ventas.py
from datetime import date as _date
from datetime import date
from decimal import Decimal
from calendar import monthrange

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Case, When, F, DecimalField, Value, ExpressionWrapper
)
from django.db.models.functions import TruncMonth, Coalesce
from django.shortcuts import render

from Apps.Pedidos.models import (
    Stock, Producto, UtilidadProducto, ListaPrecios,
    CodigoProveedor, Proveedor
)
from Apps.indicadores.forms import FiltroVentasForm

# Meses abreviados en español
MESES_ES = ["", "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
            "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


# ----------------------------
# Utilidades de fechas
# ----------------------------
def primer_dia_mes(d: date) -> date:
    return d.replace(day=1)

def mes_anterior(d: date) -> date:
    y, m = d.year, d.month - 1
    if m == 0:
        y -= 1
        m = 12
    return date(y, m, 1)

def siguiente_mes(d: date) -> date:
    y, m = d.year, d.month + 1
    if m == 13:
        y += 1
        m = 1
    return date(y, m, 1)

def fin_mes(d: date) -> date:
    return date(d.year, d.month, monthrange(d.year, d.month)[1])

def construir_meses_cerrados(hoy: date, n: int):
    """
    Devuelve n meses CERRADOS (excluye el mes actual) en orden ANTIGUO → RECIENTE.
    Ej.: si hoy es 2025-09-07 y n=3 -> JUN 2025, JUL 2025, AGO 2025.
    """
    actual = primer_dia_mes(hoy)
    ultimo_cerrado = mes_anterior(actual)
    meses = []
    cursor = ultimo_cerrado
    for _ in range(n):
        meses.append({"start": cursor, "label": f"{MESES_ES[cursor.month]} {cursor.year}"})
        cursor = mes_anterior(cursor)
    meses.reverse()
    return meses


# ----------------------------
# Normalización de cantidades (VENTAS y STOCK)
# ----------------------------
def _unidades_vendidas_expr():
    """
    Evita doble normalización en ventas:
    UtilidadProducto.cantidad ya está en unidades primarias (según tu models.py).
    Si existieran campos normalizados, se priorizan.
    """
    if hasattr(UtilidadProducto, 'cantidad_unidad'):
        return F('cantidad_unidad')
    if hasattr(UtilidadProducto, 'cantidad_normalizada'):
        return F('cantidad_normalizada')
    return F('cantidad')  # ya está en unidad primaria

def _qty_unidad_stock_expr():
    """
    Stock en unidad primaria:
      PRIMARIO   -> qty
      SECUNDARIO -> qty * producto.qty_secundario
      TERCIARIO  -> qty * producto.qty_terciario * producto.qty_secundario
    """
    return Case(
        When(
            empaque__iexact='TERCIARIO',
            then=F('qty')
                 * Coalesce(F('producto__qty_terciario'), Value(1))
                 * Coalesce(F('producto__qty_secundario'), Value(1))
        ),
        When(
            empaque__iexact='SECUNDARIO',
            then=F('qty') * Coalesce(F('producto__qty_secundario'), Value(1))
        ),
        When(empaque__iexact='PRIMARIO', then=F('qty')),
        default=Value(0),
        output_field=DecimalField(max_digits=18, decimal_places=4),
    )


# ----------------------------
# Productos que se compran a un proveedor
# ----------------------------
def _producto_ids_por_proveedor(proveedor_obj: Proveedor | None):
    """
    Devuelve IDs de productos COMPRADOS a un proveedor:
      1) Por mapeo explícito en CodigoProveedor (FK proveedor↔producto)
      2) Por recepciones (Stock.tipo_movimiento='RECEPCION' con recepcion.proveedor)
    Unión de ambas fuentes. Si no hay proveedor, devuelve None.
    """
    if not proveedor_obj:
        return None

    ids_por_codigo = CodigoProveedor.objects.filter(
        proveedor=proveedor_obj
    ).values_list('producto_id', flat=True)

    ids_por_recepcion = Stock.objects.filter(
        tipo_movimiento='RECEPCION',
        recepcion__proveedor=proveedor_obj
    ).values_list('producto_id', flat=True)

    ids = set(ids_por_codigo) | set(ids_por_recepcion)
    return list(ids)


# ----------------------------
# Vista principal
# ----------------------------
@login_required
def dashboard_ventas(request):
    """
    Dashboard de ventas a MESES CERRADOS.
    - Default: últimos 3 meses cerrados (si hoy es septiembre: JUN, JUL, AGO).
    - Columnas: ANTIGUO → RECIENTE.
    - Filtros: Cliente, Categoría, Proveedor (solo muestra productos COMPRADOS a ese proveedor).
    - Stock = DISPONIBLE - RESERVA - DESPACHO (normalizado).
    - Ventas sin doble normalización (usa campo normalizado si existe).
    - Orden de filas: alfabético por Producto; incluye código interno.
    """
    form = FiltroVentasForm(request.GET or None)

    cliente = categoria = proveedor = None
    meses_n = 3
    hoy = date.today()

    if form.is_valid():
        cliente   = form.cleaned_data.get('cliente')
        categoria = form.cleaned_data.get('categoria')
        proveedor = form.cleaned_data.get('proveedor')
        meses_n   = form.cleaned_data.get('meses') or 3

    # Meses cerrados (antiguo → reciente)
    meses_cols = construir_meses_cerrados(hoy, meses_n)
    min_start = meses_cols[0]["start"]
    max_end_excl = siguiente_mes(meses_cols[-1]["start"])
    inicio = min_start
    fin = fin_mes(meses_cols[-1]["start"])

    # Productos válidos por proveedor (si se seleccionó)
    productos_ids_prov = _producto_ids_por_proveedor(proveedor) if proveedor else None

    # ----------------------------
    # 1) Limitar por Lista de Precios (cliente) y por categoría/proveedor
    # ----------------------------
    productos_ids = None
    if cliente:
        lp_qs = ListaPrecios.objects.filter(nombre_cliente=cliente)
        if categoria:
            lp_qs = lp_qs.filter(nombre_producto__categoria_producto=categoria)
        if productos_ids_prov is not None:
            lp_qs = lp_qs.filter(nombre_producto_id__in=productos_ids_prov)

        productos_ids = list(
            lp_qs.values_list('nombre_producto_id', flat=True).distinct()
        )

        if not productos_ids:
            return render(request, 'indicadores/ventas.html', {
                'form': form,
                'filas': [],
                'inicio': inicio,
                'fin': fin,
                'meses': meses_n,
                'cliente': cliente,
                'categoria': categoria,
                'meses_cols': meses_cols,
                'resumen': {
                    'productos_total': 0,
                    'productos_bajo_minimo': 0,
                    'stock_total': Decimal('0'),
                    'promedio_total': Decimal('0'),
                    'ventas_periodo_total': Decimal('0'),
                },
            })

    # ----------------------------
    # 2) STOCK (DISPONIBLE - RESERVA - DESPACHO) con qty normalizada
    # ----------------------------
    stock_base = Stock.objects.all().select_related('producto')
    if categoria:
        stock_base = stock_base.filter(producto__categoria_producto=categoria)
    if productos_ids_prov is not None:
        stock_base = stock_base.filter(producto_id__in=productos_ids_prov)
    if productos_ids is not None:
        stock_base = stock_base.filter(producto_id__in=productos_ids)

    qty_unidad = _qty_unidad_stock_expr()

    def _total_por_tipo(tipo: str):
        qs = (stock_base.filter(tipo_movimiento=tipo)
              .annotate(qty_unidad=qty_unidad)
              .values('producto')
              .annotate(total=Coalesce(Sum('qty_unidad'),
                                       Value(0, output_field=DecimalField(max_digits=18, decimal_places=4)))))
        return {r['producto']: r['total'] for r in qs}

    disp_map     = _total_por_tipo('DISPONIBLE')
    reserva_map  = _total_por_tipo('RESERVA')
    despacho_map = _total_por_tipo('DESPACHO')

    stock_map = {}
    for pid in set(list(disp_map.keys()) + list(reserva_map.keys()) + list(despacho_map.keys())):
        disponible = (disp_map.get(pid, Decimal('0'))
                      - reserva_map.get(pid, Decimal('0'))
                      - despacho_map.get(pid, Decimal('0')))
        stock_map[pid] = disponible

    # ----------------------------
    # 3) Ventas (UtilidadProducto) a MESES CERRADOS
    # ----------------------------
    util_qs = (
        UtilidadProducto.objects
        .filter(
            venta__fecha_venta__gte=min_start,
            venta__fecha_venta__lt=max_end_excl,
        )
        .select_related('venta', 'producto', 'venta__pedidoid')
    )
    if cliente:
        util_qs = util_qs.filter(venta__pedidoid__nombre_cliente=cliente)
    if categoria:
        util_qs = util_qs.filter(producto__categoria_producto=categoria)
    if productos_ids_prov is not None:
        util_qs = util_qs.filter(producto_id__in=productos_ids_prov)
    if productos_ids is not None:
        util_qs = util_qs.filter(producto_id__in=productos_ids)

    unidades_u = ExpressionWrapper(
        _unidades_vendidas_expr(),
        output_field=DecimalField(max_digits=18, decimal_places=4)
    )

    util_mes = (
        util_qs
        .annotate(mes=TruncMonth('venta__fecha_venta'))
        .values('producto_id', 'mes')
        .annotate(
            unidades=Coalesce(
                Sum(unidades_u),
                Value(0, output_field=DecimalField(max_digits=18, decimal_places=4))
            )
        )
    )

    # ----------------------------
    # 4) Mapear ventas por MES y totales
    # ----------------------------
    ventas_mes_map = {}
    total_periodo_map = {}

    for r in util_mes:
        pid = r['producto_id']
        ms = r['mes']
        mes_start = ms if isinstance(ms, _date) else ms.date()

        u = r['unidades'] or Decimal('0')
        ventas_mes_map.setdefault(pid, {}).setdefault(mes_start, Decimal('0'))
        ventas_mes_map[pid][mes_start] += u
        total_periodo_map[pid] = total_periodo_map.get(pid, Decimal('0')) + u

    meses_n_dec = Decimal(meses_n or 1)
    promedio_map = {pid: (total / meses_n_dec) for pid, total in total_periodo_map.items()}

    # ----------------------------
    # 5) Construir filas (orden alfabético, con código interno)
    # ----------------------------
    producto_ids = set(stock_map.keys()) | set(ventas_mes_map.keys())
    if productos_ids_prov is not None:
        producto_ids = producto_ids & set(productos_ids_prov)
    if productos_ids is not None:
        producto_ids = producto_ids & set(productos_ids)

    productos_qs = (
        Producto.objects
        .filter(id__in=producto_ids)
        .only('id', 'nombre_producto', 'codigo_producto_interno', 'qty_minima')
    )

    filas = []
    for p in productos_qs:
        by_month = ventas_mes_map.get(p.id, {})
        # meses_cols: ANTIGUO → RECIENTE
        meses_vals = [by_month.get(m["start"], Decimal('0')) for m in meses_cols]
        total_periodo = sum(meses_vals, start=Decimal('0'))

        filas.append({
            "producto": p,
            "codigo_interno": getattr(p, 'codigo_producto_interno', '') or '',
            "stock_actual": stock_map.get(p.id, Decimal('0')),
            "promedio_mensual_unidades": promedio_map.get(p.id, Decimal('0')),
            "meses": meses_vals,
            "total_periodo": total_periodo,
        })

    filas.sort(key=lambda x: (x["producto"].nombre_producto or "").lower())

    resumen = {
        'productos_total': len(filas),
        'productos_bajo_minimo': sum(
            1 for f in filas if f["stock_actual"] <= Decimal(f["producto"].qty_minima or 0)
        ),
        'stock_total': sum((f["stock_actual"] for f in filas), start=Decimal('0')),
        'promedio_total': sum((f["promedio_mensual_unidades"] for f in filas), start=Decimal('0')),
        'ventas_periodo_total': sum((f["total_periodo"] for f in filas), start=Decimal('0')),
    }

    return render(request, 'indicadores/ventas.html', {
        'form': form,
        'filas': filas,
        'inicio': inicio,
        'fin': fin,
        'meses': meses_n,
        'cliente': cliente,
        'categoria': categoria,
        'meses_cols': meses_cols,
        'resumen': resumen,
    })
