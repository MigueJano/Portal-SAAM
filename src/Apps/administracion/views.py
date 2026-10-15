from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import ActaReunionForm
from .html import sanitize_rich_text
from .models import ActaReunion


def _acta_anterior(fecha, acta_actual=None):
    if not fecha:
        return None
    if isinstance(fecha, str):
        fecha = parse_date(fecha)
    if not fecha:
        return None
    if acta_actual:
        queryset = ActaReunion.objects.filter(
            Q(fecha__lt=fecha) | Q(fecha=fecha, id__lt=acta_actual.id)
        ).exclude(pk=acta_actual.pk)
    else:
        queryset = ActaReunion.objects.filter(fecha__lte=fecha)
    return queryset.order_by("-fecha", "-id").first()


@login_required
def lista_actas(request):
    return render(
        request,
        "administracion/actas/lista.html",
        {"actas": ActaReunion.objects.select_related("creado_por")},
    )


@login_required
def crear_acta(request):
    fecha_referencia = request.POST.get("fecha") or request.GET.get("fecha") or timezone.localdate()
    form = ActaReunionForm(request.POST or None, initial={"fecha": fecha_referencia})
    if request.method == "POST" and form.is_valid():
        acta = form.save(commit=False)
        acta.creado_por = request.user
        acta.save()
        messages.success(request, "Acta de reunión guardada correctamente.")
        return redirect("detalle_acta", pk=acta.pk)
    fecha = form["fecha"].value()
    return render(
        request,
        "administracion/actas/formulario.html",
        {
            "form": form,
            "editor_content": sanitize_rich_text(form.data.get("acta", "")),
            "acta_anterior": _acta_anterior(fecha),
            "titulo": "Nueva acta de reunión",
        },
    )


@login_required
def editar_acta(request, pk):
    acta = get_object_or_404(ActaReunion, pk=pk)
    form = ActaReunionForm(request.POST or None, instance=acta)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Acta de reunión actualizada correctamente.")
        return redirect("detalle_acta", pk=acta.pk)
    fecha = form["fecha"].value()
    return render(
        request,
        "administracion/actas/formulario.html",
        {
            "form": form,
            "acta": acta,
            "editor_content": sanitize_rich_text(form.data.get("acta", acta.acta)),
            "acta_anterior": _acta_anterior(fecha, acta),
            "titulo": "Editar acta de reunión",
        },
    )


@login_required
def detalle_acta(request, pk):
    acta = get_object_or_404(ActaReunion.objects.select_related("creado_por"), pk=pk)
    return render(
        request,
        "administracion/actas/detalle.html",
        {"acta": acta, "acta_anterior": _acta_anterior(acta.fecha, acta)},
    )
