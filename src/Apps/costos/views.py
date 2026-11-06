from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from Apps.Pedidos.models import Pedido, Recepcion
from Apps.indicadores.forms import FiltroFinancieroForm, ultimo_mes_natural

from .forms import AccionOperacionalForm, CategoriaGastoForm, GastoRecepcionForm
from .models import AccionOperacional, CategoriaGasto, GastoRecepcion, RegistroTiempo
from .services import carga_estandar_hitos, costos_configurados_pedido


def _q2(valor):
    return Decimal(valor or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _destino(request):
    destino = request.POST.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino
    return "costos:panel"


@login_required
def panel(request):
    filtros = request.GET.copy()
    desde_default, hasta_default = ultimo_mes_natural(timezone.localdate())
    if not filtros.get("fecha_desde"):
        filtros["fecha_desde"] = desde_default.isoformat()
    if not filtros.get("fecha_hasta"):
        filtros["fecha_hasta"] = hasta_default.isoformat()
    form = FiltroFinancieroForm(filtros)
    if form.is_valid():
        desde = form.cleaned_data["fecha_desde"]
        hasta = form.cleaned_data["fecha_hasta"]
    else:
        desde, hasta = desde_default, hasta_default

    tiempos = RegistroTiempo.objects.filter(
        estado=RegistroTiempo.FINALIZADO,
        iniciado_en__date__range=(desde, hasta),
    ).select_related("accion", "usuario", "pedido", "recepcion")
    gastos = GastoRecepcion.objects.filter(
        recepcion__fecha_recepcion__range=(desde, hasta),
    ).select_related("categoria", "recepcion__proveedor", "pedido")
    por_persona_actividad = list(
        tiempos.values(
            "usuario__username",
            "usuario__first_name",
            "usuario__last_name",
            "accion__nombre",
        )
        .annotate(registros=Count("id"), minutos=Sum("minutos_reales"), estandar=Sum("minutos_estandar"), costo=Sum("costo"))
        .order_by("usuario__username", "accion__nombre")
    )
    for fila in por_persona_actividad:
        fila["diferencia"] = (fila["minutos"] or 0) - (fila["estandar"] or 0)

    carga_estandar = carga_estandar_hitos(desde, hasta)
    total_minutos_estandar = sum((fila["minutos"] for fila in carga_estandar), start=0)
    total_costo_estandar = sum((fila["total"] for fila in carga_estandar), start=Decimal("0"))
    return render(request, "costos/panel.html", {
        "form": form,
        "desde": desde,
        "hasta": hasta,
        "tiempos": tiempos[:100],
        "gastos": gastos[:100],
        "por_persona_actividad": por_persona_actividad,
        "carga_estandar": carga_estandar,
        "total_minutos_estandar": total_minutos_estandar,
        "total_costo_estandar": total_costo_estandar,
        "total_minutos": tiempos.aggregate(v=Sum("minutos_reales"))["v"] or 0,
        "total_costo": tiempos.aggregate(v=Sum("costo"))["v"] or Decimal("0"),
        "total_gastos": gastos.aggregate(v=Sum("monto_neto"))["v"] or Decimal("0"),
        "activo": RegistroTiempo.objects.filter(usuario=request.user).exclude(estado=RegistroTiempo.FINALIZADO).select_related("accion", "pedido", "recepcion").first(),
    })


@login_required
@require_POST
def iniciar_tiempo(request):
    accion = get_object_or_404(AccionOperacional, pk=request.POST.get("accion"), activa=True)
    pedido = get_object_or_404(Pedido, pk=request.POST.get("pedido")) if request.POST.get("pedido") else None
    recepcion = get_object_or_404(Recepcion, pk=request.POST.get("recepcion")) if request.POST.get("recepcion") else None
    if not pedido and not recepcion:
        messages.error(request, "Seleccione un pedido o una recepcion.")
        return redirect(_destino(request))
    try:
        RegistroTiempo.objects.create(
            accion=accion, usuario=request.user, pedido=pedido, recepcion=recepcion,
            minutos_estandar=accion.minutos_estandar, valor_hora=accion.valor_hora,
        )
        messages.success(request, f"Cronometro iniciado: {accion.nombre}.")
    except IntegrityError:
        messages.error(request, "Ya tienes una actividad en curso. Finalizala antes de iniciar otra.")
    return redirect(_destino(request))


@login_required
@require_POST
def cambiar_tiempo(request, registro_id, accion):
    registro = get_object_or_404(RegistroTiempo, pk=registro_id, usuario=request.user)
    ahora = timezone.now()
    if accion == "pausar" and registro.estado == RegistroTiempo.EN_CURSO:
        registro.estado = RegistroTiempo.PAUSADO
        registro.pausa_iniciada_en = ahora
        registro.save(update_fields=("estado", "pausa_iniciada_en"))
    elif accion == "reanudar" and registro.estado == RegistroTiempo.PAUSADO:
        registro.segundos_pausa += max(0, int((ahora - registro.pausa_iniciada_en).total_seconds()))
        registro.pausa_iniciada_en = None
        registro.estado = RegistroTiempo.EN_CURSO
        registro.save(update_fields=("estado", "pausa_iniciada_en", "segundos_pausa"))
    elif accion == "finalizar" and registro.estado != RegistroTiempo.FINALIZADO:
        registro.calcular_y_finalizar(ahora)
        registro.save()
        messages.success(request, f"Actividad finalizada: {registro.minutos_reales} minutos.")
    return redirect(_destino(request))


@user_passes_test(lambda u: u.is_staff)
def configuracion(request):
    accion_id = request.POST.get("accion_id") or request.GET.get("accion_id")
    categoria_id = request.POST.get("categoria_id") or request.GET.get("categoria_id")
    accion_obj = get_object_or_404(AccionOperacional, pk=accion_id) if accion_id else None
    categoria_obj = get_object_or_404(CategoriaGasto, pk=categoria_id) if categoria_id else None
    accion_form = AccionOperacionalForm(prefix="accion", instance=accion_obj)
    categoria_form = CategoriaGastoForm(prefix="categoria", instance=categoria_obj)
    if request.method == "POST":
        if request.POST.get("tipo") == "accion":
            accion_form = AccionOperacionalForm(request.POST, prefix="accion", instance=accion_obj)
            if accion_form.is_valid():
                accion_form.save()
                messages.success(request, "Accion creada.")
                return redirect("costos:configuracion")
        else:
            categoria_form = CategoriaGastoForm(request.POST, prefix="categoria", instance=categoria_obj)
            if categoria_form.is_valid():
                categoria_form.save()
                messages.success(request, "Categoria creada.")
                return redirect("costos:configuracion")
    return render(request, "costos/configuracion.html", {
        "accion_form": accion_form, "categoria_form": categoria_form,
        "acciones": AccionOperacional.objects.all(), "categorias": CategoriaGasto.objects.all(),
        "accion_obj": accion_obj, "categoria_obj": categoria_obj,
    })


@login_required
def pedido_tiempos(request, pedido_id):
    pedido = get_object_or_404(Pedido, pk=pedido_id)
    from Apps.Pedidos.views.pedido import _detalle_lineas_pedido

    _, _, _, _, ganancia_total = _detalle_lineas_pedido(pedido)
    costos_pedido = costos_configurados_pedido(pedido)
    return render(request, "costos/pedido_tiempos.html", {
        "pedido": pedido,
        "ganancia_total": ganancia_total,
        "costos_pedido": costos_pedido,
        "ganancia_real": _q2(ganancia_total - costos_pedido["total"]),
    })


@login_required
@require_POST
def agregar_gasto_recepcion(request, recepcion_id):
    recepcion = get_object_or_404(Recepcion, pk=recepcion_id)
    if recepcion.estado_recepcion == "Finalizado":
        messages.error(request, "La recepcion finalizada no admite nuevos gastos.")
        return redirect("recepcion_productos_historico", documentoid=recepcion.id)
    form = GastoRecepcionForm(request.POST)
    if form.is_valid():
        gasto = form.save(commit=False)
        gasto.recepcion = recepcion
        gasto.creado_por = request.user
        gasto.save()
        from Apps.Pedidos.views.recepcion import _sincronizar_totales_recepcion
        _sincronizar_totales_recepcion(recepcion)
        messages.success(request, "Gasto externo agregado a la factura.")
    else:
        messages.error(request, "No fue posible agregar el gasto: " + "; ".join(
            error for errores in form.errors.values() for error in errores
        ))
    return redirect("crear_recepcion_productos", recepcion_id=recepcion.id)


@login_required
@require_POST
def eliminar_gasto_recepcion(request, gasto_id):
    gasto = get_object_or_404(GastoRecepcion, pk=gasto_id)
    recepcion = gasto.recepcion
    if recepcion.estado_recepcion != "Finalizado":
        gasto.delete()
        from Apps.Pedidos.views.recepcion import _sincronizar_totales_recepcion
        _sincronizar_totales_recepcion(recepcion)
    return redirect("crear_recepcion_productos", recepcion_id=recepcion.id)
