"""
Dashboard - Vistas para la app Pedidos

Este módulo contiene las vistas relacionadas con la página principal del sistema (inicio)
y funciones de búsqueda general.

Fecha de documentación: 2025-08-08
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from decimal import Decimal, ROUND_HALF_UP
from Apps.Pedidos.models import (
    BoletaElectronica,
    Cliente,
    ConfiguracionBoletaSii,
    Pedido,
    Recepcion,
    Stock,
)
from Apps.Pedidos.forms import ConfiguracionBoletaSiiForm
from Apps.Pedidos.services.listaprecios_alertas import (
    filas_precios_cliente,
)

IVA_RATE = Decimal('0.19')
DOS_DEC = Decimal('0.01')

SII_CONFIG_FIELD_HELP = {
    "nombre": "Nombre interno para distinguir configuraciones, por ejemplo Principal Certificacion o SAAM Produccion. Lo define SAAM.",
    "activa": "Marca esta configuracion como la que SAAM usara para generar DTE. Recomiendo mantener solo una activa.",
    "ambiente": "Usa Certificacion para pruebas SII y Produccion solo cuando SII autorice la salida real.",
    "habilita_boleta": "Activa emision de boleta electronica tipo 39. Debe coincidir con el modelo de emision declarado ante SII.",
    "habilita_factura": "Activa factura electronica tipo 33. Requiere autorizacion SII y CAF tipo 33.",
    "rut_emisor": "RUT de la empresa emisora. Se obtiene desde Mi SII, e-RUT o datos del contribuyente.",
    "razon_social": "Razon social exacta registrada ante SII. Revisar en Mi SII o situacion tributaria.",
    "giro": "Giro registrado ante SII. Usar el texto completo, idealmente sin abreviaciones.",
    "acteco_principal": "Codigo de actividad economica declarado ante SII. Se obtiene desde actividades economicas o Mi SII.",
    "direccion_origen": "Direccion tributaria de casa matriz o sucursal emisora registrada en SII.",
    "comuna_origen": "Comuna asociada a la direccion o sucursal emisora registrada en SII.",
    "ciudad_origen": "Ciudad asociada a la direccion o sucursal emisora registrada en SII.",
    "resolucion_numero": "Numero de resolucion o autorizacion como emisor electronico entregado por SII al certificar/autorizar.",
    "resolucion_fecha": "Fecha de la resolucion o autorizacion SII asociada al emisor electronico.",
    "certificado_alias": "Nombre interno para identificar el certificado digital. No ingresar claves ni contrasenas en este formulario.",
    "correo_intercambio": "Correo tributario/DTE definido por la empresa para intercambio y recepcion de documentos.",
    "ruta_caf_tipo_33": "Ruta o referencia del archivo CAF XML tipo 33 para facturas. Se obtiene en SII, Timbraje electronico.",
    "ruta_caf_tipo_39": "Ruta o referencia del archivo CAF XML tipo 39 para boletas. Se obtiene en SII, Timbraje electronico.",
    "monto_identificacion_receptor_boleta": "Monto en CLP equivalente a 135 UF. Sobre este valor la boleta debe identificar receptor/pagador. Si queda en 0 no fuerza identificacion.",
    "observaciones": "Notas internas: responsable, estado de certificacion, certificado asociado o comentarios operativos.",
}


def _calcular_total_pedido_dashboard(pedido, movimiento_principal):
    if pedido.lineas.exists():
        total_neto = sum(
            (
                Decimal(linea.cantidad or 0) * Decimal(linea.precio_unitario or 0)
                for linea in pedido.lineas.all()
            ),
            start=Decimal('0'),
        )
    else:
        reservas = Stock.objects.filter(
            pedido=pedido,
            precio_unitario__isnull=False,
        )
        if movimiento_principal == 'DESPACHO':
            reservas = list(reservas.filter(tipo_movimiento='DESPACHO'))
            if not reservas:
                reservas = list(
                    Stock.objects.filter(
                        pedido=pedido,
                        precio_unitario__isnull=False,
                        tipo_movimiento__in=['RESERVA', 'DESPACHO'],
                    )
                )
        else:
            reservas = list(reservas.filter(tipo_movimiento='RESERVA'))

        total_neto = sum(
            (Decimal(reserva.qty or 0) * Decimal(reserva.precio_unitario or 0) for reserva in reservas),
            start=Decimal('0'),
        )

    total_neto = Decimal(total_neto).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva = (total_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    return (total_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def home(request):
    """
    Vista principal del sistema (inicio).

    Muestra:
    - Recepciones pendientes
    - Pedidos pendientes con totales
    - Pedidos entregados no pagados (con totales)

    Returns:
        HttpResponse: Renderiza home.html con datos de negocio.
    """
    recepciones_qs = Recepcion.objects.exclude(estado_recepcion='Finalizado').order_by('-fecha_recepcion')
    recepciones = list(recepciones_qs)
    cantidad_recepciones = len(recepciones)

    pedidos_qs = Pedido.objects.filter(estado_pedido='Pendiente').order_by('-fecha_pedido')
    pedidos = list(pedidos_qs)
    cantidad_pedidos_pendiente = len(pedidos)
    monto_pedidos_pendientes = Decimal('0.00')

    # Calcular total de cada pedido pendiente
    for pedido in pedidos:
        pedido.total_pedido_pendiente = _calcular_total_pedido_dashboard(
            pedido,
            movimiento_principal='RESERVA',
        )
        monto_pedidos_pendientes += pedido.total_pedido_pendiente

    pedidos_no_pagados = list(Pedido.objects.filter(estado_pedido='Entregado').order_by('-fecha_pedido'))
    monto_pedidos_no_pagados = Decimal('0.00')

    # Calcular total de cada pedido entregado no pagado
    for pedido in pedidos_no_pagados:
        pedido.total_pedido_no_pagado = _calcular_total_pedido_dashboard(
            pedido,
            movimiento_principal='DESPACHO',
        )
        monto_pedidos_no_pagados += pedido.total_pedido_no_pagado

    cantidad_pedidos_no_pagados = len(pedidos_no_pagados)

    filas_clientes = filas_precios_cliente()
    precios_cliente_bajo_costo = sorted(
        [
            row for row in filas_clientes
            if row["diferencia"] is not None and row["diferencia"] < 0
        ],
        key=lambda row: (row["diferencia"], row["cliente"], row["producto"]),
    )
    cantidad_precios_cliente_bajo_costo = len(precios_cliente_bajo_costo)
    precios_cliente_bajo_costo_preview = precios_cliente_bajo_costo[:5]

    return render(request, './views/dashboard/home.html', {
        'recepciones': recepciones,
        'cantidad_recepciones': cantidad_recepciones,
        'pedidos': pedidos,
        'pedidos_no_pagados': pedidos_no_pagados,
        'cantidad_pedidos_pendiente': cantidad_pedidos_pendiente,
        'cantidad_pedidos_no_pagados': cantidad_pedidos_no_pagados,
        'monto_pedidos_pendientes': monto_pedidos_pendientes,
        'monto_pedidos_no_pagados': monto_pedidos_no_pagados,
        'precios_cliente_bajo_costo': precios_cliente_bajo_costo_preview,
        'cantidad_precios_cliente_bajo_costo': cantidad_precios_cliente_bajo_costo,
        'precios_cliente_bajo_costo_restantes': max(
            cantidad_precios_cliente_bajo_costo - len(precios_cliente_bajo_costo_preview),
            0,
        ),
    })


@staff_member_required
def configuracion(request):
    config_id = request.GET.get("editar") or request.POST.get("config_id")
    config_en_edicion = None
    if str(config_id).isdigit():
        config_en_edicion = get_object_or_404(ConfiguracionBoletaSii, pk=int(config_id))

    if request.method == "POST":
        form = ConfiguracionBoletaSiiForm(request.POST, instance=config_en_edicion)
        if form.is_valid():
            configuracion_guardada = form.save(commit=False)
            configuracion_guardada.save()
            if configuracion_guardada.activa:
                (
                    ConfiguracionBoletaSii.objects
                    .exclude(pk=configuracion_guardada.pk)
                    .filter(activa=True)
                    .update(activa=False)
                )
            messages.success(request, "Configuracion de boleta guardada correctamente.")
            return redirect("configuracion")
        messages.error(request, "Revisa el formulario de configuracion.")
    else:
        form = ConfiguracionBoletaSiiForm(instance=config_en_edicion)

    configuracion_activa = (
        ConfiguracionBoletaSii.objects
        .filter(activa=True)
        .order_by("id")
        .first()
    )
    configuraciones = list(
        ConfiguracionBoletaSii.objects
        .order_by("-activa", "nombre", "id")[:5]
    )
    boletas_pendientes = list(
        BoletaElectronica.objects
        .select_related("venta", "venta__pedidoid", "venta__pedidoid__nombre_cliente")
        .exclude(estado=BoletaElectronica.ESTADO_ENVIADA)
        .order_by("-actualizado", "-id")[:8]
    )
    clientes_incompletos = Cliente.objects.filter(
        Q(razon_social="") |
        Q(giro_cliente="") |
        Q(direccion_cliente="") |
        Q(comuna_cliente="") |
        Q(ciudad_cliente="")
    ).count()

    return render(request, "./views/dashboard/config.html", {
        "form": form,
        "config_en_edicion": config_en_edicion,
        "configuracion_activa": configuracion_activa,
        "configuraciones": configuraciones,
        "boletas_pendientes": boletas_pendientes,
        "clientes_incompletos": clientes_incompletos,
        "sii_field_help": SII_CONFIG_FIELD_HELP,
        "total_configuraciones": ConfiguracionBoletaSii.objects.count(),
        "total_boletas": BoletaElectronica.objects.count(),
        "configuraciones_habilitan_factura": ConfiguracionBoletaSii.objects.filter(habilita_factura=True).count(),
    })
