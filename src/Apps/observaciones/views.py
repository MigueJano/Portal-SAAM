from urllib.parse import unquote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import ObservacionForm, ResolverObservacionForm
from .models import Observacion, VersionRegistro
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
