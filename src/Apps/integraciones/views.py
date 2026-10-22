from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    ConsultaBancoForm,
    ConciliacionManualForm,
    CorreoForm,
    FiltroCompraAgilForm,
    destinatarios_disponibles,
)
from .models import (
    CompraAgil,
    ConciliacionPago,
    DocumentoTributarioEntrante,
    FiltroCompraAgil,
    MovimientoBancario,
    SaldoBancario,
)
from .services.conciliacion import confirmar_conciliacion, proponer_conciliaciones
from .services.correo import enviar_correo
from .services.banco_chile import consultar_movimientos, guardar_resultado
from .services.mercado_publico import MercadoPublicoError, sincronizar_compras_agiles


@login_required
def inicio(request):
    return redirect("integraciones:correo")


@login_required
def correo(request):
    return render(
        request,
        "integraciones/correo.html",
        {"documentos_pendientes": DocumentoTributarioEntrante.objects.filter(estado="PENDIENTE").count()},
    )


@login_required
def redactar_correo(request):
    form = CorreoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            enviar_correo(
                usuario=request.user,
                destinatario=form.cleaned_data["destinatario"],
                asunto=form.cleaned_data["asunto"],
                cuerpo=form.cleaned_data["cuerpo"],
                adjunto=form.cleaned_data.get("adjuntos"),
            )
        except Exception as exc:
            messages.error(request, f"No fue posible enviar el correo: {exc}")
        else:
            messages.success(request, "Correo enviado y registrado.")
            return redirect("integraciones:redactar_correo")
    return render(
        request,
        "integraciones/redactar_correo.html",
        {"form": form, "destinatarios": destinatarios_disponibles()},
    )


@login_required
def documentos_tributarios(request):
    documentos = DocumentoTributarioEntrante.objects.select_related("recepcion").all()[:200]
    return render(request, "integraciones/documentos.html", {"documentos": documentos})


@user_passes_test(lambda usuario: usuario.is_staff)
def conciliacion_bancaria(request):
    from Apps.Pedidos.models import Pedido

    movimientos = MovimientoBancario.objects.prefetch_related(
        "conciliaciones__pedido__nombre_cliente"
    ).all()[:200]
    pedidos = Pedido.objects.filter(estado_pedido="Entregado").select_related("nombre_cliente").order_by("fecha_pedido", "id")
    return render(
        request,
        "integraciones/conciliacion.html",
        {
            "movimientos": movimientos,
            "pedidos_entregados": pedidos,
            "ultimo_saldo": SaldoBancario.objects.first(),
            "consulta_form": ConsultaBancoForm(),
        },
    )


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def sincronizar_banco(request):
    form = ConsultaBancoForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Revise el rango de fechas de la consulta bancaria.")
        return redirect("integraciones:conciliacion_bancaria")
    desde = form.cleaned_data["desde"]
    hasta = form.cleaned_data["hasta"]
    try:
        respuesta = consultar_movimientos(desde, hasta)
        creados, existentes, saldo, saldo_creado = guardar_resultado(
            respuesta,
            desde=desde,
            hasta=hasta,
        )
    except Exception as exc:
        messages.error(request, f"No fue posible consultar Banco de Chile: {exc}")
    else:
        estado_saldo = "registrado" if saldo_creado else "ya existente"
        messages.success(
            request,
            f"Consulta completada: {creados} movimientos nuevos, "
            f"{existentes} ya existentes y saldo {estado_saldo} (${saldo.saldo_disponible}).",
        )
    return redirect("integraciones:conciliacion_bancaria")


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def proponer_movimiento(request, movimiento_id):
    movimiento = get_object_or_404(MovimientoBancario, pk=movimiento_id)
    cantidad = proponer_conciliaciones(movimiento)
    messages.success(request, f"Se generaron {cantidad} propuestas por coincidencia exacta de monto.")
    return redirect("integraciones:conciliacion_bancaria")


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def crear_conciliacion_manual(request, movimiento_id):
    movimiento = get_object_or_404(
        MovimientoBancario,
        pk=movimiento_id,
        tipo=MovimientoBancario.TIPO_ABONO,
    )
    form = ConciliacionManualForm(request.POST)
    if form.is_valid():
        conciliacion = form.save(commit=False)
        conciliacion.movimiento = movimiento
        conciliacion.criterio = "Asignación manual pendiente de confirmación"
        try:
            conciliacion.save()
        except Exception:
            messages.error(request, "Ese movimiento ya tiene una propuesta para el pedido seleccionado.")
        else:
            messages.success(request, "Propuesta manual creada; todavía debe confirmarse.")
    else:
        messages.error(request, "Revise el pedido y el monto ingresado.")
    return redirect("integraciones:conciliacion_bancaria")


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def confirmar(request, conciliacion_id):
    conciliacion = get_object_or_404(ConciliacionPago, pk=conciliacion_id)
    try:
        confirmar_conciliacion(conciliacion, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Pago confirmado para el pedido #{conciliacion.pedido_id}.")
    return redirect("integraciones:conciliacion_bancaria")


@user_passes_test(lambda usuario: usuario.is_staff)
def compras_agiles(request):
    compras = CompraAgil.objects.filter(coincide_filtros=True).prefetch_related("filtros")
    gestion = request.GET.get("gestion", "activas")
    if gestion == "activas":
        compras = compras.exclude(estado_gestion=CompraAgil.ESTADO_DESCARTADA)
    elif gestion in dict(CompraAgil.ESTADOS_GESTION):
        compras = compras.filter(estado_gestion=gestion)
    pagina = Paginator(compras, 50).get_page(request.GET.get("pagina"))
    return render(
        request,
        "integraciones/compras_agiles.html",
        {
            "pagina": pagina,
            "gestion": gestion,
            "filtros_activos": FiltroCompraAgil.objects.filter(activo=True).count(),
        },
    )


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def sincronizar_compras_agiles_view(request):
    try:
        resultado = sincronizar_compras_agiles()
    except MercadoPublicoError as exc:
        messages.error(request, f"No fue posible sincronizar Compra Ágil: {exc}")
    else:
        messages.success(
            request,
            "Sincronización completada: "
            f"{resultado['coincidentes']} coincidencias, {resultado['creadas']} nuevas y "
            f"{resultado['actualizadas']} actualizadas con {resultado['filtros']} filtros activos.",
        )
    return redirect("integraciones:compras_agiles")


@require_POST
@user_passes_test(lambda usuario: usuario.is_staff)
def cambiar_estado_compra_agil(request, compra_id):
    compra = get_object_or_404(CompraAgil, pk=compra_id)
    estado = request.POST.get("estado")
    estados_validos = dict(CompraAgil.ESTADOS_GESTION)
    if estado not in estados_validos:
        messages.error(request, "La acción seleccionada no es válida.")
    else:
        compra.estado_gestion = estado
        compra.save(update_fields=("estado_gestion", "sincronizado_en"))
        messages.success(request, f"{compra.codigo}: {estados_validos[estado]}.")
    return redirect("integraciones:compras_agiles")


@user_passes_test(lambda usuario: usuario.is_staff)
def filtros_compras_agiles(request, filtro_id=None):
    filtro = get_object_or_404(FiltroCompraAgil, pk=filtro_id) if filtro_id else None
    form = FiltroCompraAgilForm(request.POST or None, instance=filtro)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Filtro de Compra Ágil guardado.")
        return redirect("integraciones:filtros_compras_agiles")
    return render(
        request,
        "integraciones/filtros_compras_agiles.html",
        {"form": form, "filtro_editado": filtro, "filtros": FiltroCompraAgil.objects.all()},
    )

