from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import ExpressionWrapper, Sum, Avg, Value, DecimalField
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render

from Apps.Pedidos.models import Recepcion, Venta
from Apps.indicadores.forms import FiltroFinancieroForm

# Constantes
DEC = Decimal('0.00')
DEC_F = DecimalField(max_digits=12, decimal_places=2)

MESES_ES = ["", "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
            "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]

def _primer_dia_mes(d: date) -> date:
    return d.replace(day=1)

def _siguiente_mes(d: date) -> date:
    y, m = d.year, d.month + 1
    if m == 13:
        y += 1; m = 1
    return date(y, m, 1)

def _rango_meses(inicio: date, fin: date):
    cur = _primer_dia_mes(inicio)
    fin_m = _primer_dia_mes(fin)
    out = []
    while cur <= fin_m:
        out.append(cur)
        cur = _siguiente_mes(cur)
    return out

def _label_mes(d: date) -> str:
    return f"{MESES_ES[d.month]}-{str(d.year)[2:]}"  # p.ej. AGO-25


@login_required
def dashboard_financiero_simple(request):
    """
    ÚNICA TABLA:
    - Todas las cifras mostradas en POSITIVO (proveedores y ventas).
    - En el TOTAL GENERAL: Proveedores RESTAN y Ventas SUMAN.
    """
    form = FiltroFinancieroForm(request.GET or None)
    if form.is_valid():
        desde = form.cleaned_data['fecha_desde']
        hasta = form.cleaned_data['fecha_hasta']
    else:
        hoy = date.today()
        desde = hoy.replace(day=1)
        hasta = hoy

    # Querysets base
    recep_qs = (Recepcion.objects
                .select_related('proveedor')
                .filter(fecha_recepcion__range=(desde, hasta)))
    ventas_qs = Venta.objects.filter(fecha_venta__range=(desde, hasta))

    # === Agregados para tarjetas ===
    r = recep_qs.aggregate(
        neto=Coalesce(Sum('total_neto_recepcion'), Value(DEC, output_field=DEC_F)),
        iva=Coalesce(Sum('iva_recepcion'), Value(DEC, output_field=DEC_F)),
        total=Coalesce(Sum('total_recepcion'), Value(DEC, output_field=DEC_F)),
    )
    v = ventas_qs.aggregate(
        neto=Coalesce(Sum('venta_neto_pedido'), Value(DEC, output_field=DEC_F)),
        iva=Coalesce(Sum('venta_iva_pedido'), Value(DEC, output_field=DEC_F)),
        total=Coalesce(Sum('venta_total_pedido'), Value(DEC, output_field=DEC_F)),
    )

    margen_bruto = v['neto'] - r['neto']
    ganancia_periodo = ventas_qs.aggregate(
        ganancia=Coalesce(Sum('ganancia_total'), Value(DEC, output_field=DEC_F))
    )['ganancia']
    diferencia_iva = r['iva'] - v['iva']

    ganancia_porcentaje_qs = ventas_qs.aggregate(
        ganancia_pct=ExpressionWrapper(
            (Coalesce(Sum('ganancia_total'), Value(0, output_field=DecimalField())) * 100.0) /
            Coalesce(Sum('venta_neto_pedido'), Value(1, output_field=DecimalField())),
            output_field=DecimalField(max_digits=5, decimal_places=2)
        )
    )
    ganancia_porcentaje= ganancia_porcentaje_qs['ganancia_pct']

    # Meses (columnas)
    meses = _rango_meses(desde, hasta)
    meses_labels = [_label_mes(m) for m in meses]

    # ================
    # COMPRAS x PROV
    # ================
    compras_grouped = (
        recep_qs
        .annotate(mes=TruncMonth('fecha_recepcion'))
        .values('proveedor__nombre_proveedor', 'mes')
        .annotate(
            neto=Coalesce(Sum('total_neto_recepcion'), Value(DEC, output_field=DEC_F)),
            iva=Coalesce(Sum('iva_recepcion'), Value(DEC, output_field=DEC_F)),
            total=Coalesce(Sum('total_recepcion'), Value(DEC, output_field=DEC_F)),
        )
        .order_by('proveedor__nombre_proveedor', 'mes')
    )

    # { proveedor: { mes: {neto, iva, total} } }
    datos_compras = {}
    for row in compras_grouped:
        prov = row['proveedor__nombre_proveedor'] or '—'
        mes = row['mes']
        datos_compras.setdefault(prov, {})[mes] = {
            'neto': row['neto'] or DEC,
            'iva':  row['iva']  or DEC,
            'total':row['total']or DEC,
        }

    # Filas para mostrar (positivas) + SUBTOTALES (display positivos)
    filas_proveedores = []
    subtotal_compras_mes_display = [{'neto': DEC, 'iva': DEC, 'total': DEC} for _ in meses]
    subtotal_compras_total_display = {'neto': DEC, 'iva': DEC, 'total': DEC}

    # Acumuladores contables (negativos) SOLO para el TOTAL GENERAL
    subtotal_compras_mes_real = [{'neto': DEC, 'iva': DEC, 'total': DEC} for _ in meses]
    subtotal_compras_total_real = {'neto': DEC, 'iva': DEC, 'total': DEC}

    proveedores_ordenados = sorted(
        datos_compras.keys(),
        key=lambda p: sum(datos_compras[p].get(m, {}).get('total', DEC) for m in meses),
        reverse=True
    )

    for prov in proveedores_ordenados:
        valores = []
        suma_prov_display = {'neto': DEC, 'iva': DEC, 'total': DEC}
        for i, m in enumerate(meses):
            d = datos_compras.get(prov, {}).get(m, {'neto': DEC, 'iva': DEC, 'total': DEC})

            # Mostrar SIEMPRE en positivo
            valores.append({'neto': d['neto'], 'iva': d['iva'], 'total': d['total']})

            # Subtotal mostrado (positivo)
            suma_prov_display['neto']  += d['neto']
            suma_prov_display['iva']   += d['iva']
            suma_prov_display['total'] += d['total']
            subtotal_compras_mes_display[i]['neto']  += d['neto']
            subtotal_compras_mes_display[i]['iva']   += d['iva']
            subtotal_compras_mes_display[i]['total'] += d['total']

            # Subtotal REAL (negativo) para total general
            subtotal_compras_mes_real[i]['neto']  += -d['neto']
            subtotal_compras_mes_real[i]['iva']   += -d['iva']
            subtotal_compras_mes_real[i]['total'] += -d['total']

        subtotal_compras_total_display['neto']  += suma_prov_display['neto']
        subtotal_compras_total_display['iva']   += suma_prov_display['iva']
        subtotal_compras_total_display['total'] += suma_prov_display['total']

        subtotal_compras_total_real['neto']  += -suma_prov_display['neto']
        subtotal_compras_total_real['iva']   += -suma_prov_display['iva']
        subtotal_compras_total_real['total'] += -suma_prov_display['total']

        filas_proveedores.append({
            'proveedor': prov,
            'valores': valores,            # [{neto, iva, total}] POSITIVOS
            'total':   suma_prov_display,  # acumulado POSITIVO del proveedor (display)
        })

    # ================
    # VENTAS x TIPO
    # ================
    tipos_doc = ['Factura', 'Boleta']
    ventas_grouped = (
        ventas_qs
        .filter(documento_pedido__in=tipos_doc)
        .annotate(mes=TruncMonth('fecha_venta'))
        .values('documento_pedido', 'mes')
        .annotate(
            neto=Coalesce(Sum('venta_neto_pedido'), Value(DEC, output_field=DEC_F)),
            iva=Coalesce(Sum('venta_iva_pedido'), Value(DEC, output_field=DEC_F)),
            total=Coalesce(Sum('venta_total_pedido'), Value(DEC, output_field=DEC_F)),
        )
        .order_by('documento_pedido', 'mes')
    )

    datos_ventas = {}
    for row in ventas_grouped:
        tipo = row['documento_pedido']
        mes = row['mes']
        datos_ventas.setdefault(tipo, {})[mes] = {
            'neto': row['neto'] or DEC,
            'iva':  row['iva']  or DEC,
            'total':row['total']or DEC,
        }

    filas_ventas_tipo = []
    subtotal_ventas_mes = [{'neto': DEC, 'iva': DEC, 'total': DEC} for _ in meses]
    subtotal_ventas_total = {'neto': DEC, 'iva': DEC, 'total': DEC}

    tipos_ordenados = [t for t in tipos_doc if t in datos_ventas]
    for tipo in tipos_ordenados:
        valores = []
        suma_tipo = {'neto': DEC, 'iva': DEC, 'total': DEC}
        for i, m in enumerate(meses):
            d = datos_ventas.get(tipo, {}).get(m, {'neto': DEC, 'iva': DEC, 'total': DEC})
            # Ventas en positivo (display y contable)
            valores.append({'neto': d['neto'], 'iva': d['iva'], 'total': d['total']})
            suma_tipo['neto']  += d['neto']
            suma_tipo['iva']   += d['iva']
            suma_tipo['total'] += d['total']
            subtotal_ventas_mes[i]['neto']  += d['neto']
            subtotal_ventas_mes[i]['iva']   += d['iva']
            subtotal_ventas_mes[i]['total'] += d['total']

        subtotal_ventas_total['neto']  += suma_tipo['neto']
        subtotal_ventas_total['iva']   += suma_tipo['iva']
        subtotal_ventas_total['total'] += suma_tipo['total']

        filas_ventas_tipo.append({
            'tipo': tipo,
            'valores': valores,   # POSITIVOS
            'total':   suma_tipo, # POSITIVO
        })

    # =================
    # TOTAL GENERAL
    # =================
    total_general_mes = []
    total_general_total = {'neto': DEC, 'iva': DEC, 'total': DEC}
    for i in range(len(meses)):
        tg = {
            # Ventas (pos) + Compras REAL (neg) => suma algebraica correcta
            'neto':  subtotal_ventas_mes[i]['neto']  + subtotal_compras_mes_real[i]['neto'],
            'iva':   subtotal_ventas_mes[i]['iva']   + subtotal_compras_mes_real[i]['iva'],
            'total': subtotal_ventas_mes[i]['total'] + subtotal_compras_mes_real[i]['total'],
        }
        total_general_mes.append(tg)
        total_general_total['neto']  += tg['neto']
        total_general_total['iva']   += tg['iva']
        total_general_total['total'] += tg['total']

    context = {
        'form': form,
        'desde': desde,
        'hasta': hasta,
        'meses_labels': meses_labels,

        'compras': {'neto': r['neto'], 'iva': r['iva'], 'total': r['total']},
        'ventas':  {'neto': v['neto'], 'iva': v['iva'], 'total': v['total']},
        'margen_bruto': margen_bruto,
        'ganancia_periodo': ganancia_periodo,
        'ganancia_porcentaje_periodo':ganancia_porcentaje,
        'diferencia_iva': diferencia_iva,

        # Compras (mostrar POSITIVO)
        'filas_proveedores': filas_proveedores,
        'subtotal_compras_mes_display': subtotal_compras_mes_display,
        'subtotal_compras_total_display': subtotal_compras_total_display,

        # Ventas (mostrar POSITIVO)
        'filas_ventas_tipo': filas_ventas_tipo,
        'subtotal_ventas_mes': subtotal_ventas_mes,
        'subtotal_ventas_total': subtotal_ventas_total,

        # Total general (ventas suman, proveedores restan)
        'total_general_mes': total_general_mes,
        'total_general_total': total_general_total,
    }
    return render(request, 'indicadores/financieros.html', context)
