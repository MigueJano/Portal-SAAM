from urllib.parse import unquote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import ObservacionForm, ResolverObservacionForm
from .models import ActualizacionSistema, Observacion, VersionRegistro
from .services import SystemUpdateError, apply_system_update, git_status
from .utils_versionado import calcular_siguiente_version, obtener_version_actual


def _resolver_origen(request):
    raw = request.GET.get("from") or request.POST.get("from")
    host = request.get_host()

    if raw:
        decoded = unquote(raw)

        if decoded.startswith("/"):
            return request.build_absolute_uri(decoded)

        if url_has_allowed_host_and_scheme(
            decoded,
            allowed_hosts={host},
            require_https=request.is_secure(),
        ):
            return decoded

    ref = request.META.get("HTTP_REFERER")
    if ref and url_has_allowed_host_and_scheme(
        ref,
        allowed_hosts={host},
        require_https=request.is_secure(),
    ):
        return ref

    return request.build_absolute_uri("/")


def _version_str(version_tuple):
    return ".".join(str(valor) for valor in version_tuple)


def _obtener_version_registro(observacion):
    try:
        return observacion.version_registro
    except VersionRegistro.DoesNotExist:
        return None


@staff_member_required
def actualizaciones_sistema(request):
    resultado = None
    estado_git = None
    ultima_instalacion = ActualizacionSistema.objects.first()

    if request.method == "POST":
        if not request.user.is_superuser:
            messages.error(request, "Solo un superusuario puede consultar o instalar actualizaciones.")
            return redirect("actualizaciones_sistema")

        accion = request.POST.get("accion")
        if accion == "buscar":
            estado_git = git_status(fetch=True)
            if estado_git.available:
                if estado_git.update_available:
                    messages.info(request, f"Hay {estado_git.behind} cambio(s) disponible(s).")
                elif estado_git.diverged or estado_git.ahead:
                    messages.warning(request, "La copia local contiene cambios que requieren revision manual.")
                else:
                    messages.success(request, "El sistema ya esta actualizado.")
            else:
                messages.error(request, f"No fue posible consultar Git: {estado_git.error}")
        elif accion in {"instalar", "reintentar"}:
            estado_previo = git_status(fetch=False)
            try:
                es_reintento = accion == "reintentar"
                if es_reintento and (ultima_instalacion is None or ultima_instalacion.estado != "FALLIDA"):
                    raise SystemUpdateError("No existe una instalacion fallida pendiente de reintento.")
                resultado = apply_system_update(retry=es_reintento)
                estado_final = resultado["status"]
                ActualizacionSistema.objects.create(
                    estado="EXITOSA" if resultado["changed"] else "SIN_CAMBIOS",
                    commit_anterior=resultado.get("previous_commit", estado_previo.current_commit),
                    commit_nuevo=estado_final.current_commit,
                    respaldo=resultado.get("backup_path", ""),
                    detalle=resultado.get("log", "")[-12000:],
                    creado_por=request.user,
                )
                if resultado.get("retried"):
                    messages.success(request, "Instalacion pendiente completada. Reinicia el servicio si no se recarga automaticamente.")
                elif resultado["changed"]:
                    messages.success(request, "Actualizacion aplicada. Reinicia el servicio si no se recarga automaticamente.")
                else:
                    messages.info(request, "No habia cambios pendientes de instalacion.")
            except SystemUpdateError as exc:
                ActualizacionSistema.objects.create(
                    estado="FALLIDA",
                    commit_anterior=estado_previo.current_commit,
                    commit_nuevo=estado_previo.current_commit,
                    detalle=str(exc)[-12000:],
                    creado_por=request.user,
                )
                messages.error(request, f"La actualizacion no pudo completarse: {exc}")
        else:
            messages.error(request, "Accion de actualizacion no reconocida.")

    ultima_instalacion = ActualizacionSistema.objects.first()
    if estado_git is None:
        estado_git = git_status(fetch=False)
    return render(
        request,
        "observaciones/actualizaciones.html",
        {
            "estado_git": estado_git,
            "version_actual": _version_str(obtener_version_actual()),
            "versiones": VersionRegistro.objects.select_related("creado_por")[:10],
            "actualizaciones": ActualizacionSistema.objects.select_related("creado_por")[:10],
            "puede_reintentar": ultima_instalacion is not None and ultima_instalacion.estado == "FALLIDA",
            "resultado": resultado,
        },
    )


@login_required
def crear_observacion(request):
    src = _resolver_origen(request)

    if request.method == "POST":
        data = request.POST.copy()

        try:
            form_fields = ObservacionForm().fields
        except Exception:
            form_fields = {}

        if "url" in form_fields and not data.get("url"):
            data["url"] = src

        if not data.get("from"):
            data["from"] = src

        form = ObservacionForm(data, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.url = src
            obj.usuario = request.user
            obj.save()
            messages.success(request, "Observacion enviada correctamente.")
            if request.user.is_staff:
                return redirect("lista_observaciones")
            return redirect(src)

        messages.error(request, f"Revisa el formulario: {form.errors.as_text()}")
    else:
        init = {}
        try:
            if "url" in ObservacionForm().fields:
                init["url"] = src
        except Exception:
            pass
        form = ObservacionForm(initial=init)

    return render(
        request,
        "observaciones/crear_observacion.html",
        {
            "form": form,
            "from_url": src,
        },
    )


@staff_member_required
def lista_observaciones(request):
    qs = Observacion.objects.select_related("usuario").order_by("-creado_en")

    tipo = request.GET.get("tipo")
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "pendientes")

    if tipo in {"MEJORA", "ERROR", "PREGUNTA"}:
        qs = qs.filter(tipo=tipo)

    if q:
        qs = qs.filter(observacion__icontains=q)

    if estado == "listos":
        qs = qs.filter(lista=True)
    elif estado == "pendientes":
        qs = qs.filter(lista=False)

    return render(
        request,
        "observaciones/lista.html",
        {
            "observaciones": qs,
            "tipo": tipo or "",
            "q": q,
            "estado": estado,
        },
    )


@staff_member_required
def marcar_lista_observacion(request, pk):
    obs = get_object_or_404(Observacion, pk=pk)
    if _obtener_version_registro(obs) is None:
        messages.info(
            request,
            f"La observacion #{obs.id} necesita una resolucion antes de marcarse como lista.",
        )
        return redirect("resolver_observacion", pk=pk)

    obs.lista = True
    obs.save(update_fields=["lista"])
    messages.success(request, f"La observacion #{obs.id} fue marcada como lista.")
    return redirect("resolver_observacion", pk=pk)


@staff_member_required
def resolver_observacion(request, pk: int):
    """
    Muestra un formulario para registrar la solucion de una observacion,
    clasificar el impacto y crear el VersionRegistro con la version resultante.
    Al confirmar, marca la observacion como lista.
    """
    obs = get_object_or_404(
        Observacion.objects.select_related(
            "usuario",
            "version_registro",
            "version_registro__creado_por",
        ),
        pk=pk,
    )
    version_registro = _obtener_version_registro(obs)
    version_base_str = _version_str(obtener_version_actual())
    form = None

    if request.method == "POST":
        if obs.lista:
            messages.info(
                request,
                f"La observacion #{obs.id} ya esta cerrada y solo permite revision.",
            )
            return redirect("resolver_observacion", pk=pk)

        data = request.POST.copy()
        impacto = data.get("impacto") or "PATCH"
        data["proxima_version"] = _version_str(calcular_siguiente_version(impacto))

        form = ResolverObservacionForm(data)
        if form.is_valid():
            impacto = form.cleaned_data["impacto"]
            resumen = form.cleaned_data["resumen"].strip()
            detalle = form.cleaned_data["detalle"].strip()

            x, y, z = calcular_siguiente_version(impacto)

            with transaction.atomic():
                ver = VersionRegistro.objects.create(
                    version_mayor=x,
                    version_menor=y,
                    version_patch=z,
                    impacto=impacto,
                    resumen=resumen,
                    detalle=detalle,
                    observacion=obs,
                    creado_por=request.user,
                )
                obs.lista = True
                obs.save(update_fields=["lista"])

                from django.core.cache import cache

                cache.delete("observaciones:version_str")
                cache.delete("observaciones:ultima_version")

            messages.success(
                request,
                f"Observacion #{obs.id} resuelta. Version actualizada a v{ver.version_str}.",
            )
            return redirect("lista_observaciones")
    elif not obs.lista:
        impacto_inicial = "PATCH"
        form = ResolverObservacionForm(
            initial={
                "impacto": impacto_inicial,
                "proxima_version": _version_str(
                    calcular_siguiente_version(impacto_inicial)
                ),
            }
        )

    if form is not None:
        form.fields["proxima_version"].widget.attrs["data-version-base"] = version_base_str

    return render(
        request,
        "observaciones/resolver_observacion.html",
        {
            "form": form,
            "observacion": obs,
            "modo_revision": obs.lista,
            "version_registro": version_registro,
            "version_base_str": version_base_str,
        },
    )
