# Create your views here.
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from .forms import ObservacionForm, ResolverObservacionForm
from .models import Observacion, VersionRegistro
from .utils_versionado import calcular_siguiente_version
from urllib.parse import unquote
from django.utils.http import url_has_allowed_host_and_scheme

def _resolver_origen(request):
    raw = request.GET.get("from") or request.POST.get("from")
    host = request.get_host()

    if raw:
        # Decodifica %3A -> ":" etc.
        decoded = unquote(raw)

        # Si es relativa, hazla absoluta
        if decoded.startswith("/"):
            return request.build_absolute_uri(decoded)

        # Si es absoluta, valida host y esquema
        if url_has_allowed_host_and_scheme(
            decoded,
            allowed_hosts={host},
            require_https=request.is_secure(),  # http en local, https en prod
        ):
            return decoded

    # Fallbacks
    ref = request.META.get("HTTP_REFERER")
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={host}, require_https=request.is_secure()):
        return ref

    return request.build_absolute_uri("/")  # último recurso

@login_required
def crear_observacion(request):
    # Resolvemos una vez la URL de origen (decodificada y validada)
    src = _resolver_origen(request)

    if request.method == "POST":
        # Asegura que el form reciba 'url' (si el form lo define) y 'from'
        data = request.POST.copy()

        # Si el form tiene un campo 'url', complétalo con la URL de origen resuelta
        try:
            form_fields = ObservacionForm().fields
        except Exception:
            form_fields = {}

        if 'url' in form_fields and not data.get('url'):
            data['url'] = src

        # Mantén también el 'from' en el POST por si lo usas en otra parte
        if not data.get('from'):
            data['from'] = src

        form = ObservacionForm(data, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            # Guarda SIEMPRE el origen real en el modelo dedicado (p.ej. origen_url)
            obj.origen_url = src
            obj.save()
            messages.success(request, "Observación enviada correctamente.")
            return redirect("lista_observaciones")
        else:
            # Muestra errores en página para ver qué está faltando
            messages.error(request, f"Revisa el formulario: {form.errors.as_text()}")

    else:
        # Pre-carga inicial para que el hidden 'url' tenga valor desde el GET
        init = {}
        try:
            if 'url' in ObservacionForm().fields:
                init['url'] = src
        except Exception:
            pass
        form = ObservacionForm(initial=init)

    return render(request, "observaciones/crear_observacion.html", {
        "form": form,
        "from_url": src,  # el template lo usará en action y en el hidden
    })

@staff_member_required
def lista_observaciones(request):
    qs = (
        Observacion.objects
        .select_related('usuario')
        .order_by('-creado_en')
    )

    # Filtros
    tipo = request.GET.get('tipo')  # MEJORA / ERROR / PREGUNTA / None
    q    = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', 'pendientes')  # 'pendientes' (default) | 'listos' | 'todos'

    if tipo in {'MEJORA', 'ERROR', 'PREGUNTA'}:
        qs = qs.filter(tipo=tipo)

    if q:
        qs = qs.filter(observacion__icontains=q)

    # Filtro estado (predefinido: pendientes = lista False)
    if estado == 'listos':
        qs = qs.filter(lista=True)
    elif estado == 'pendientes':
        qs = qs.filter(lista=False)
    # 'todos' no filtra por lista

    return render(request, 'observaciones/lista.html', {
        'observaciones': qs,
        'tipo': tipo or '',
        'q': q,
        'estado': estado,  # <-- para marcar seleccionado en el template
    })

@staff_member_required
def marcar_lista_observacion(request, pk):
    obs = get_object_or_404(Observacion, pk=pk)
    obs.lista = True
    obs.save()
    messages.success(request, f"La observación #{obs.id} fue marcada como lista.")
    return redirect('resolver_observacion', pk=pk)

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

@staff_member_required
def resolver_observacion(request, pk: int):
    """
    Muestra un formulario para registrar la solución de una observación,
    clasificar el impacto y crear el VersionRegistro con la versión incrementada.
    Al confirmar, marca la observación como lista.
    """
    obs = get_object_or_404(Observacion, pk=pk)

    if obs.lista:
        messages.info(request, f"La observación #{obs.id} ya está marcada como lista.")
        return redirect('lista_observaciones')

    if request.method == 'POST':
        form = ResolverObservacionForm(request.POST)
        if form.is_valid():
            impacto = form.cleaned_data['impacto']
            resumen = form.cleaned_data['resumen'].strip()
            detalle = form.cleaned_data['detalle'].strip()

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
                    creado_por=request.user
                )
                obs.lista = True
                obs.save(update_fields=['lista'])

                from django.core.cache import cache
                cache.delete("observaciones:version_str")
                cache.delete("observaciones:ultima_version")

            messages.success(request, f"Observación #{obs.id} resuelta. Versión actualizada a v{ver.version_str}.")
            return redirect('lista_observaciones')
    else:
        # Valor inicial: impacto PATCH y próxima versión calculada
        form = ResolverObservacionForm(initial={'impacto': 'PATCH'})

    # Calcula “en vivo” la próxima versión para mostrarla al cargar
    impacto_inicial = form.initial.get('impacto', 'PATCH')
    x, y, z = calcular_siguiente_version(impacto_inicial)
    form.fields['proxima_version'].initial = f"{x}.{y}.{z}"

    return render(request, 'observaciones/resolver_observacion.html', {
        'form': form,
        'observacion': obs,
    })

