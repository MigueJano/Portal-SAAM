from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from Apps.Pedidos.models import Producto, Recepcion, Stock, UtilidadProducto, Venta
from Apps.integraciones.models import ConciliacionPago, SaldoBancario
from Apps.indicadores.services.contabilidad import _cantidad_unidad_primaria, _valuacion_fifo_por_producto


ZERO = Decimal("0.00")
DOS_DEC = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _sum(qs, field: str) -> Decimal:
    return _q2(qs.aggregate(total=Sum(field))["total"])


def _bucket_antiguedad(dias: int) -> str:
    if dias <= 30:
        return "0-30 días"
    if dias <= 60:
        return "31-60 días"
    if dias <= 90:
        return "61-90 días"
    return "Más de 90 días"


def informe_resultados(desde: date, hasta: date) -> dict:
    ventas = Venta.objects.filter(fecha_venta__range=(desde, hasta))
    ventas_netas = _sum(ventas, "venta_neto_pedido")
    ventas_con_costo = ventas.filter(ganancia_total__isnull=False)
    ventas_netas_con_costo = _sum(ventas_con_costo, "venta_neto_pedido")
    utilidad_bruta = _sum(ventas_con_costo, "ganancia_total")
    costo_ventas = _q2(ventas_netas_con_costo - utilidad_bruta)
    margen = _q2((utilidad_bruta / ventas_netas_con_costo) * 100) if ventas_netas_con_costo else ZERO
    return {
        "ventas_netas": ventas_netas,
        "ventas_netas_con_costo": ventas_netas_con_costo,
        "costo_ventas": costo_ventas,
        "utilidad_bruta": utilidad_bruta,
        "margen_bruto": margen,
        "ventas_total": _sum(ventas, "venta_total_pedido"),
        "documentos": ventas.count(),
        "documentos_con_costo": ventas_con_costo.count(),
        "documentos_sin_costo": ventas.filter(ganancia_total__isnull=True).count(),
        "utilidad_neta_disponible": False,
    }


def informe_balance(hasta: date) -> dict:
    snapshots = SaldoBancario.objects.filter(moneda="CLP").order_by("-consultado_en", "-id")
    saldos = []
    cuentas_vistas = set()
    for saldo in snapshots:
        clave = (saldo.proveedor_api, saldo.cuenta_enmascarada, saldo.moneda)
        if clave in cuentas_vistas:
            continue
        if saldo.periodo_hasta and saldo.periodo_hasta > hasta:
            continue
        if not saldo.periodo_hasta and saldo.consultado_en.date() > hasta:
            continue
        cuentas_vistas.add(clave)
        saldos.append(saldo)

    efectivo = _q2(sum((s.saldo_disponible for s in saldos), start=ZERO))
    valuacion = _valuacion_fifo_por_producto(fecha_corte=hasta)
    inventario = _q2(sum((fila["valor"] for fila in valuacion.values()), start=ZERO))
    cxc = informe_cuentas_por_cobrar(hasta)
    activos_identificados = _q2(efectivo + inventario + cxc["total_pendiente"])
    return {
        "saldos": saldos,
        "efectivo": efectivo,
        "inventario": inventario,
        "cuentas_por_cobrar": cxc["total_pendiente"],
        "activos_identificados": activos_identificados,
        "fecha_corte": hasta,
        "completo": False,
    }


def informe_flujo_efectivo(desde: date, hasta: date) -> dict:
    ventas_pagadas = (
        Venta.objects.filter(
            fecha_venta__range=(desde, hasta),
            documento_pedido__in=("Factura", "Boleta"),
        )
        .select_related("pedidoid__nombre_cliente")
        .order_by("-fecha_venta", "-id")
    )
    compras_pagadas = (
        Recepcion.objects.filter(fecha_recepcion__range=(desde, hasta))
        .exclude(estado_recepcion="Rechazado")
        .exclude(documento_recepcion="Credito")
        .select_related("proveedor")
        .order_by("-fecha_recepcion", "-id")
    )

    entradas = _sum(ventas_pagadas, "venta_total_pedido")
    salidas = _sum(compras_pagadas, "total_recepcion")
    movimientos = [
        {
            "fecha": venta.fecha_venta,
            "tipo": "Entrada",
            "documento": f"{venta.get_documento_pedido_display()} #{venta.num_documento}",
            "contraparte": venta.pedidoid.nombre_cliente.nombre_cliente,
            "monto": _q2(venta.venta_total_pedido),
            "orden": venta.id,
        }
        for venta in ventas_pagadas
    ]
    movimientos.extend(
        {
            "fecha": compra.fecha_recepcion,
            "tipo": "Salida",
            "documento": f"{compra.get_documento_recepcion_display()} #{compra.num_documento_recepcion}",
            "contraparte": compra.proveedor.nombre_proveedor,
            "monto": _q2(compra.total_recepcion),
            "orden": compra.id,
        }
        for compra in compras_pagadas
    )
    movimientos.sort(key=lambda fila: (fila["fecha"], fila["orden"]), reverse=True)
    return {
        "entradas": entradas,
        "salidas": salidas,
        "flujo_neto": _q2(entradas - salidas),
        "movimientos": movimientos[:100],
        "cantidad": len(movimientos),
        "disponible": bool(movimientos),
        "clasificacion_disponible": False,
    }


def informe_presupuesto(desde: date, hasta: date) -> dict:
    resultados = informe_resultados(desde, hasta)
    compras = Recepcion.objects.filter(fecha_recepcion__range=(desde, hasta)).exclude(
        estado_recepcion="Rechazado"
    )
    return {
        "disponible": False,
        "reales": [
            {"concepto": "Ventas netas", "monto": resultados["ventas_netas"]},
            {"concepto": "Costo de ventas reconocido", "monto": resultados["costo_ventas"]},
            {"concepto": "Compras netas de inventario", "monto": _sum(compras, "total_neto_recepcion")},
        ],
    }


def informe_rentabilidad(desde: date, hasta: date) -> dict:
    ventas = (
        Venta.objects.filter(fecha_venta__range=(desde, hasta))
        .select_related("pedidoid__nombre_cliente")
        .order_by("pedidoid__nombre_cliente__nombre_cliente", "fecha_venta", "id")
    )
    clientes = defaultdict(
        lambda: {"ventas": ZERO, "ventas_con_costo": ZERO, "utilidad": ZERO, "documentos": 0, "sin_costo": 0}
    )
    for venta in ventas:
        nombre = venta.pedidoid.nombre_cliente.nombre_cliente
        fila = clientes[nombre]
        fila["ventas"] += Decimal(venta.venta_neto_pedido or 0)
        fila["documentos"] += 1
        if venta.ganancia_total is None:
            fila["sin_costo"] += 1
        else:
            fila["ventas_con_costo"] += Decimal(venta.venta_neto_pedido or 0)
            fila["utilidad"] += Decimal(venta.ganancia_total)

    clientes_rows = []
    for nombre, fila in clientes.items():
        margen = (
            _q2((fila["utilidad"] / fila["ventas_con_costo"]) * 100)
            if fila["ventas_con_costo"]
            else ZERO
        )
        clientes_rows.append({"nombre": nombre, "margen": margen, **fila})
    clientes_rows.sort(key=lambda row: (row["utilidad"], row["ventas"]), reverse=True)

    monto_expr = ExpressionWrapper(
        F("cantidad") * F("precio_venta_unitario"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    utilidad_expr = ExpressionWrapper(
        F("cantidad") * F("utilidad"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    productos_rows = list(
        UtilidadProducto.objects.filter(venta__fecha_venta__range=(desde, hasta))
        .values("producto__codigo_producto_interno", "producto__nombre_producto")
        .annotate(ventas=Sum(monto_expr), utilidad=Sum(utilidad_expr), unidades=Sum("cantidad"))
        .order_by("-utilidad", "producto__nombre_producto")
    )
    for fila in productos_rows:
        fila["ventas"] = _q2(fila["ventas"])
        fila["utilidad"] = _q2(fila["utilidad"])
        fila["margen"] = _q2((fila["utilidad"] / fila["ventas"]) * 100) if fila["ventas"] else ZERO
    return {"clientes": clientes_rows, "productos": productos_rows}


def informe_ventas_stock_mensual(desde: date, hasta: date, producto_id: int | None = None) -> dict:
    filas_por_clave = defaultdict(
        lambda: {
            "unidades_vendidas": ZERO,
            "venta_neta": ZERO,
            "entradas": ZERO,
            "salidas": ZERO,
        }
    )
    productos = {}

    ventas = (
        UtilidadProducto.objects.filter(
            venta__isnull=False,
            venta__fecha_venta__range=(desde, hasta),
        )
        .select_related("producto", "venta")
        .order_by("venta__fecha_venta", "producto_id", "id")
    )
    if producto_id:
        ventas = ventas.filter(producto_id=producto_id)
    for registro in ventas:
        mes = registro.venta.fecha_venta.replace(day=1)
        clave = (mes, registro.producto_id)
        cantidad = Decimal(registro.cantidad or 0)
        filas_por_clave[clave]["unidades_vendidas"] += cantidad
        filas_por_clave[clave]["venta_neta"] += cantidad * Decimal(registro.precio_venta_unitario or 0)
        productos[registro.producto_id] = registro.producto

    movimientos = (
        Stock.objects.filter(
            tipo_movimiento__in=("DISPONIBLE", "DESPACHO"),
            fecha_movimiento__range=(desde, hasta),
        )
        .select_related("producto")
        .order_by("fecha_movimiento", "producto_id", "id")
    )
    if producto_id:
        movimientos = movimientos.filter(producto_id=producto_id)
    for movimiento in movimientos:
        mes = movimiento.fecha_movimiento.replace(day=1)
        clave = (mes, movimiento.producto_id)
        cantidad = _cantidad_unidad_primaria(movimiento)
        campo = "entradas" if movimiento.tipo_movimiento == "DISPONIBLE" else "salidas"
        filas_por_clave[clave][campo] += cantidad
        productos[movimiento.producto_id] = movimiento.producto

    historial_stock = (
        Stock.objects.filter(
            tipo_movimiento__in=("DISPONIBLE", "DESPACHO"),
            fecha_movimiento__lte=hasta,
        )
        .select_related("producto")
        .order_by("fecha_movimiento", "id")
    )
    if producto_id:
        historial_stock = historial_stock.filter(producto_id=producto_id)

    movimientos_stock_por_mes = defaultdict(list)
    productos_stock = set()
    for movimiento in historial_stock:
        mes_movimiento = movimiento.fecha_movimiento.replace(day=1)
        movimientos_stock_por_mes[mes_movimiento].append(movimiento)
        productos_stock.add(movimiento.producto_id)
        productos[movimiento.producto_id] = movimiento.producto

    saldo_stock = defaultdict(lambda: ZERO)
    primer_mes = desde.replace(day=1)
    for mes_movimiento, movimientos_mes in movimientos_stock_por_mes.items():
        if mes_movimiento >= primer_mes:
            continue
        for movimiento in movimientos_mes:
            cantidad = _cantidad_unidad_primaria(movimiento)
            signo = Decimal(1) if movimiento.tipo_movimiento == "DISPONIBLE" else Decimal(-1)
            saldo_stock[movimiento.producto_id] += signo * cantidad

    filas = []
    serie_por_mes = defaultdict(lambda: {"vendidas": ZERO, "entradas": ZERO, "salidas": ZERO})
    for (mes, producto_id), valores in filas_por_clave.items():
        fila = {
            "mes": mes,
            "producto": productos[producto_id],
            "unidades_vendidas": _q2(valores["unidades_vendidas"]),
            "venta_neta": _q2(valores["venta_neta"]),
            "entradas": _q2(valores["entradas"]),
            "salidas": _q2(valores["salidas"]),
            "movimiento_neto": _q2(valores["entradas"] - valores["salidas"]),
        }
        filas.append(fila)
        serie_por_mes[mes]["vendidas"] += fila["unidades_vendidas"]
        serie_por_mes[mes]["entradas"] += fila["entradas"]
        serie_por_mes[mes]["salidas"] += fila["salidas"]

    filas.sort(key=lambda fila: (fila["mes"], fila["producto"].nombre_producto), reverse=True)
    serie = []
    mes = desde.replace(day=1)
    ultimo_mes = hasta.replace(day=1)
    while mes <= ultimo_mes:
        stock_inicio = sum(saldo_stock.values(), start=ZERO)
        for movimiento in movimientos_stock_por_mes.get(mes, []):
            cantidad = _cantidad_unidad_primaria(movimiento)
            signo = Decimal(1) if movimiento.tipo_movimiento == "DISPONIBLE" else Decimal(-1)
            saldo_stock[movimiento.producto_id] += signo * cantidad
        for producto_stock_id in productos_stock:
            clave = (mes, producto_stock_id)
            if clave in filas_por_clave:
                filas_por_clave[clave]["stock_inicio_siguiente"] = saldo_stock[producto_stock_id]
        valores = serie_por_mes[mes]
        serie.append(
            {
                "mes": mes.strftime("%m-%Y"),
                "vendidas": int(valores["vendidas"]),
                "entradas": int(valores["entradas"]),
                "despachos": int(valores["salidas"]),
                "stock": int(stock_inicio),
            }
        )
        mes = date(mes.year + (1 if mes.month == 12 else 0), 1 if mes.month == 12 else mes.month + 1, 1)

    mes_siguiente = mes
    stock_inicio_siguiente = sum(saldo_stock.values(), start=ZERO)
    serie.append(
        {
            "mes": mes_siguiente.strftime("%m-%Y"),
            "vendidas": None,
            "entradas": None,
            "despachos": None,
            "stock": int(stock_inicio_siguiente),
        }
    )

    for fila in filas:
        fila["stock_inicio_siguiente"] = _q2(
            filas_por_clave[(fila["mes"], fila["producto"].id)].get("stock_inicio_siguiente")
        )
        fila["mes_siguiente"] = date(
            fila["mes"].year + (1 if fila["mes"].month == 12 else 0),
            1 if fila["mes"].month == 12 else fila["mes"].month + 1,
            1,
        )
    return {
        "filas": filas,
        "serie": serie,
        "unidades_vendidas": _q2(sum((fila["unidades_vendidas"] for fila in filas), start=ZERO)),
        "venta_neta": _q2(sum((fila["venta_neta"] for fila in filas), start=ZERO)),
        "entradas": _q2(sum((fila["entradas"] for fila in filas), start=ZERO)),
        "salidas": _q2(sum((fila["salidas"] for fila in filas), start=ZERO)),
        "stock_inicio_siguiente": _q2(stock_inicio_siguiente),
        "mes_siguiente": mes_siguiente,
        "producto_seleccionado": Producto.objects.filter(pk=producto_id).first() if producto_id else None,
    }


def informe_cuentas_por_cobrar(hasta: date) -> dict:
    ventas = (
        Venta.objects.filter(fecha_venta__lte=hasta, documento_pedido="Credito")
        .select_related("pedidoid__nombre_cliente")
        .order_by("fecha_venta", "id")
    )
    por_pedido = {}
    for venta in ventas:
        fila = por_pedido.setdefault(
            venta.pedidoid_id,
            {
                "pedido": venta.pedidoid,
                "cliente": venta.pedidoid.nombre_cliente,
                "fecha": venta.fecha_venta,
                "facturado": ZERO,
            },
        )
        fila["fecha"] = min(fila["fecha"], venta.fecha_venta)
        fila["facturado"] += Decimal(venta.venta_total_pedido or 0)

    pagos = defaultdict(lambda: ZERO)
    conciliaciones = ConciliacionPago.objects.filter(
        estado=ConciliacionPago.ESTADO_CONFIRMADA,
        movimiento__fecha__lte=hasta,
    ).values("pedido_id").annotate(total=Sum("monto_aplicado"))
    for fila in conciliaciones:
        pagos[fila["pedido_id"]] = Decimal(fila["total"] or 0)

    rows = []
    buckets = defaultdict(lambda: ZERO)
    for pedido_id, fila in por_pedido.items():
        pagado = min(pagos[pedido_id], fila["facturado"])
        saldo = _q2(fila["facturado"] - pagado)
        if saldo <= 0:
            continue
        dias = max((hasta - fila["fecha"]).days, 0)
        bucket = _bucket_antiguedad(dias)
        buckets[bucket] += saldo
        rows.append({**fila, "pagado": pagado, "saldo": saldo, "dias": dias, "bucket": bucket})
    rows.sort(key=lambda row: (row["dias"], row["saldo"]), reverse=True)
    return {
        "filas": rows,
        "buckets": [{"label": label, "total": _q2(buckets[label])} for label in ("0-30 días", "31-60 días", "61-90 días", "Más de 90 días")],
        "total_pendiente": _q2(sum((row["saldo"] for row in rows), start=ZERO)),
        "vencimientos_disponibles": False,
    }


def informe_cuentas_por_pagar(hasta: date) -> dict:
    recepciones = (
        Recepcion.objects.filter(fecha_recepcion__lte=hasta, documento_recepcion="Credito")
        .exclude(estado_recepcion="Rechazado")
        .select_related("proveedor")
        .order_by("fecha_recepcion", "id")
    )
    filas = []
    for recepcion in recepciones:
        dias = max((hasta - recepcion.fecha_recepcion).days, 0)
        filas.append(
            {
                "recepcion": recepcion,
                "dias": dias,
                "bucket": _bucket_antiguedad(dias),
            }
        )
    return {
        "disponible": True,
        "documentos": filas,
        "total_pendiente": _sum(recepciones, "total_recepcion"),
    }


def informe_rotacion_inventario(desde: date, hasta: date) -> dict:
    apertura = _valuacion_fifo_por_producto(fecha_corte=desde - timedelta(days=1))
    cierre = _valuacion_fifo_por_producto(fecha_corte=hasta)
    utilidad_rows = (
        UtilidadProducto.objects.filter(venta__fecha_venta__range=(desde, hasta))
        .values("producto_id")
        .annotate(
            costo=Sum(
                ExpressionWrapper(
                    F("cantidad") * F("precio_compra_unitario"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
        )
    )
    costos = {fila["producto_id"]: _q2(fila["costo"]) for fila in utilidad_rows}
    producto_ids = set(apertura) | set(cierre) | set(costos)
    productos = Producto.objects.in_bulk(producto_ids)
    recepcion_ids = {
        capa["recepcion_id"]
        for resultado in cierre.values()
        for capa in resultado.get("capas", [])
        if capa.get("recepcion_id")
    }
    recepciones = Recepcion.objects.in_bulk(recepcion_ids)
    filas = []
    capas_fifo = []
    costo_total = ZERO
    inventario_inicial = ZERO
    inventario_final = ZERO
    for producto_id in producto_ids:
        inicial = _q2(apertura.get(producto_id, {}).get("valor"))
        final = _q2(cierre.get(producto_id, {}).get("valor"))
        costo = costos.get(producto_id, ZERO)
        promedio = _q2((inicial + final) / 2)
        rotacion = _q2(costo / promedio) if promedio > 0 else ZERO
        capas = cierre.get(producto_id, {}).get("capas", [])
        fecha_antigua = min((capa["fecha"] for capa in capas), default=None)
        filas.append(
            {
                "producto": productos.get(producto_id),
                "costo_ventas": costo,
                "inventario_promedio": promedio,
                "stock_final": _q2(cierre.get(producto_id, {}).get("cantidad")),
                "valor_final": final,
                "rotacion": rotacion,
                "dias_stock_antiguo": (hasta - fecha_antigua).days if fecha_antigua else None,
            }
        )
        producto = productos.get(producto_id)
        for capa in capas:
            recepcion = recepciones.get(capa.get("recepcion_id"))
            stock_capa = _q2(capa["cantidad"])
            costo_unitario = _q2(capa["costo_unitario"])
            capas_fifo.append(
                {
                    "producto": producto,
                    "documento": (
                        f"{recepcion.get_documento_recepcion_display()} #{recepcion.num_documento_recepcion}"
                        if recepcion
                        else f"Stock #{capa['stock_id']} sin recepcion"
                    ),
                    "fecha": capa["fecha"],
                    "cantidad_documento": _q2(capa.get("cantidad_documento", capa["cantidad"])),
                    "stock": stock_capa,
                    "valor_unitario": costo_unitario,
                    "valor_total": _q2(stock_capa * costo_unitario),
                }
            )
        costo_total += costo
        inventario_inicial += inicial
        inventario_final += final
    filas.sort(key=lambda row: row["producto"].nombre_producto if row["producto"] else "")
    capas_fifo.sort(
        key=lambda row: (
            row["producto"].nombre_producto if row["producto"] else "",
            row["fecha"],
            row["documento"],
        )
    )
    promedio_total = _q2((inventario_inicial + inventario_final) / 2)
    rotacion_total = _q2(costo_total / promedio_total) if promedio_total > 0 else ZERO
    dias_periodo = max((hasta - desde).days + 1, 1)
    dias_inventario = _q2(dias_periodo / rotacion_total) if rotacion_total > 0 else None
    return {
        "filas": filas,
        "capas_fifo": capas_fifo,
        "costo_ventas": _q2(costo_total),
        "inventario_inicial": _q2(inventario_inicial),
        "inventario_final": _q2(inventario_final),
        "total_stock": _q2(inventario_final),
        "inventario_promedio": promedio_total,
        "rotacion": rotacion_total,
        "dias_inventario": dias_inventario,
    }


def construir_informe(nombre: str, desde: date, hasta: date, producto_id: int | None = None) -> dict:
    constructores = {
        "resultados": lambda: informe_resultados(desde, hasta),
        "balance": lambda: informe_balance(hasta),
        "flujo": lambda: informe_flujo_efectivo(desde, hasta),
        "presupuesto": lambda: informe_presupuesto(desde, hasta),
        "rentabilidad": lambda: informe_rentabilidad(desde, hasta),
        "ventas_stock": lambda: informe_ventas_stock_mensual(desde, hasta, producto_id),
        "cxc": lambda: informe_cuentas_por_cobrar(hasta),
        "cxp": lambda: informe_cuentas_por_pagar(hasta),
        "inventario": lambda: informe_rotacion_inventario(desde, hasta),
    }
    return constructores[nombre]()
