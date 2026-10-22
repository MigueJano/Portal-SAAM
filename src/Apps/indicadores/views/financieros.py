from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render

from Apps.Pedidos.models import Recepcion, Venta
from Apps.indicadores.forms import FiltroFinancieroForm, ultimo_mes_natural
from Apps.indicadores.services.reportes import construir_informe

# Constantes
DEC = Decimal('0.00')
DEC_F = DecimalField(max_digits=12, decimal_places=2)
PPM_RATE = Decimal("0.015")

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


def _ppm_value(monto: Decimal) -> Decimal:
    base = Decimal(monto or DEC)
    return (base * PPM_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@login_required
def dashboard_financiero_simple(request, seccion=None):
    """Concentra los informes por sección y conserva el detalle financiero histórico."""
    filtros = request.GET.copy()
    desde_default, hasta_default = ultimo_mes_natural()
    if not filtros.get('fecha_desde'):
        filtros['fecha_desde'] = desde_default.isoformat()
    if not filtros.get('fecha_hasta'):
        filtros['fecha_hasta'] = hasta_default.isoformat()
    form = FiltroFinancieroForm(filtros)
    if form.is_valid():
        desde = form.cleaned_data['fecha_desde']
        hasta = form.cleaned_data['fecha_hasta']
    else:
        desde, hasta = desde_default, hasta_default

    informes_por_seccion = {
        'financieros': ('resultados', 'balance', 'flujo'),
        'comercial': ('presupuesto', 'rentabilidad', 'ventas_stock'),
        'control': ('cxc', 'cxp', 'inventario'),
    }
    secciones = {
        'financieros': {
            'titulo': 'Indicadores financieros',
            'url_name': 'dashboard_financiero_simple',
        },
        'comercial': {
            'titulo': 'Comercial y gestión',
            'url_name': 'dashboard_comercial_gestion',
        },
        'control': {
            'titulo': 'Control y riesgo',
            'url_name': 'dashboard_control_riesgo',
        },
    }
    informe_solicitado = request.GET.get('informe')
    if seccion not in informes_por_seccion:
        seccion = next(
            (
                clave
                for clave, informes in informes_por_seccion.items()
                if informe_solicitado in informes
            ),
            'financieros',
        )
    informe_activo = informe_solicitado or informes_por_seccion[seccion][0]
    if informe_activo not in informes_por_seccion[seccion]:
        informe_activo = informes_por_seccion[seccion][0]
    try:
        producto_id = int(request.GET.get('producto') or 0) or None
    except (TypeError, ValueError):
        producto_id = None

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

    balance_neto_ventas_compras = v['neto'] - r['neto']
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
            cantidad=Count('pk'),
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
            'cantidad': row['cantidad'],
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
        suma_prov_display = {'cantidad': 0, 'neto': DEC, 'iva': DEC, 'total': DEC}
        for i, m in enumerate(meses):
            d = datos_compras.get(prov, {}).get(
                m,
                {'cantidad': 0, 'neto': DEC, 'iva': DEC, 'total': DEC},
            )

            # Mostrar SIEMPRE en positivo
            valores.append({
                'cantidad': d['cantidad'],
                'neto': d['neto'],
                'iva': d['iva'],
                'total': d['total'],
            })

            # Subtotal mostrado (positivo)
            suma_prov_display['cantidad'] += d['cantidad']
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
    ventas_grouped = (
        ventas_qs
        .annotate(mes=TruncMonth('fecha_venta'))
        .values('documento_pedido', 'mes')
        .annotate(
            cantidad=Count('pk'),
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
            'cantidad': row['cantidad'],
            'neto': row['neto'] or DEC,
            'iva':  row['iva']  or DEC,
            'total':row['total']or DEC,
        }

    filas_ventas_tipo = []
    subtotal_ventas_mes = [{'neto': DEC, 'iva': DEC, 'total': DEC} for _ in meses]
    subtotal_ventas_total = {'neto': DEC, 'iva': DEC, 'total': DEC}

    tipos_modelo = [valor for valor, _etiqueta in Venta.DOCUMENTO_PEDIDO_CHOICES]
    tipos_ordenados = [tipo for tipo in tipos_modelo if tipo in datos_ventas]
    tipos_ordenados.extend(sorted(set(datos_ventas) - set(tipos_modelo)))
    for tipo in tipos_ordenados:
        valores = []
        suma_tipo = {'cantidad': 0, 'neto': DEC, 'iva': DEC, 'total': DEC}
        for i, m in enumerate(meses):
            d = datos_ventas.get(tipo, {}).get(
                m,
                {'cantidad': 0, 'neto': DEC, 'iva': DEC, 'total': DEC},
            )
            # Ventas en positivo (display y contable)
            valores.append({
                'cantidad': d['cantidad'],
                'neto': d['neto'],
                'iva': d['iva'],
                'total': d['total'],
            })
            suma_tipo['cantidad'] += d['cantidad']
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
    # PPM 1,5% s/ ventas netas
    # =================
    ppm_mes = []
    ppm_total = {'neto': DEC, 'iva': DEC, 'total': DEC}
    for t in subtotal_ventas_mes:
        ppm_valor = _ppm_value(t['neto'])
        ppm_mes.append({'neto': ppm_valor, 'iva': DEC, 'total': ppm_valor})
        ppm_total['neto'] += ppm_valor
        ppm_total['total'] += ppm_valor

    ppm_periodo = ppm_total['total']

    # =================
    # RESUMEN REFERENCIAL FORMULARIO 29
    # =================
    # El F29 es mensual. Estos valores se calculan solo con las compras y
    # ventas registradas en Portal SAAM; no incluyen remanentes ni ajustes SII.
    resumen_f29_mensual = []
    f29_totales = {
        'debito_fiscal': DEC,
        'credito_fiscal': DEC,
        'iva_determinado': DEC,
        'remanente_credito': DEC,
        'ppm': DEC,
        'total_estimado': DEC,
    }
    for i, mes in enumerate(meses):
        debito_fiscal = subtotal_ventas_mes[i]['iva']
        credito_fiscal = subtotal_compras_mes_display[i]['iva']
        diferencia = debito_fiscal - credito_fiscal
        iva_determinado = max(diferencia, DEC)
        remanente_credito = max(-diferencia, DEC)
        ppm = ppm_mes[i]['total']
        total_estimado = iva_determinado + ppm

        fila_f29 = {
            'periodo': _label_mes(mes),
            'debito_fiscal': debito_fiscal,
            'credito_fiscal': credito_fiscal,
            'iva_determinado': iva_determinado,
            'remanente_credito': remanente_credito,
            'ppm': ppm,
            'total_estimado': total_estimado,
        }
        resumen_f29_mensual.append(fila_f29)
        for campo in f29_totales:
            f29_totales[campo] += fila_f29[campo]

    # =================
    # TOTAL GENERAL
    # =================
    total_general_mes = []
    total_general_total = {'neto': DEC, 'iva': DEC, 'total': DEC}
    for i in range(len(meses)):
        tg = {
            # Ventas (pos) + Compras REAL (neg) => suma algebraica correcta
            'neto':  subtotal_ventas_mes[i]['neto']  + subtotal_compras_mes_real[i]['neto'] - ppm_mes[i]['neto'],
            'iva':   subtotal_ventas_mes[i]['iva']   + subtotal_compras_mes_real[i]['iva'],
            'total': subtotal_ventas_mes[i]['total'] + subtotal_compras_mes_real[i]['total'] - ppm_mes[i]['total'],
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
        'balance_neto_ventas_compras': balance_neto_ventas_compras,
        'ganancia_periodo': ganancia_periodo,
        'ganancia_porcentaje_periodo':ganancia_porcentaje,
        'diferencia_iva': diferencia_iva,
        'ppm_periodo': ppm_periodo,
        'resumen_f29_mensual': resumen_f29_mensual,
        'f29_totales': f29_totales,

        # Compras (mostrar POSITIVO)
        'filas_proveedores': filas_proveedores,
        'subtotal_compras_mes_display': subtotal_compras_mes_display,
        'subtotal_compras_total_display': subtotal_compras_total_display,

        # Ventas (mostrar POSITIVO)
        'filas_ventas_tipo': filas_ventas_tipo,
        'subtotal_ventas_mes': subtotal_ventas_mes,
        'subtotal_ventas_total': subtotal_ventas_total,
        'ppm_mes': ppm_mes,
        'ppm_total': ppm_total,

        # Total general (ventas suman, proveedores restan)
        'total_general_mes': total_general_mes,
        'total_general_total': total_general_total,
        'informe_activo': informe_activo,
        'informe': construir_informe(informe_activo, desde, hasta, producto_id),
        'seccion_activa': seccion,
        'seccion': secciones[seccion],
    }
    return render(request, 'indicadores/financieros.html', context)
