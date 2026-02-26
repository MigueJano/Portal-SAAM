# Apps/Pedidos/views/listaprecios.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from Apps.Pedidos.models import (
    Producto,
    ListaPreciosPredeterminada,     # <-- Asegúrate del nombre real del modelo
    ListaPreciosPredItem,           # <-- Asegúrate del nombre real del modelo de ítem
)

# --- Constantes numéricas ---
DOS_DEC   = Decimal("0.01")
IVA_RATE  = Decimal("0.19")


# =============================================================================
# Utilidades
# =============================================================================
def _to_decimal(val: str | float | Decimal | None) -> Decimal:
    """Convierte a Decimal de forma segura."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")


def _calcular_iva_total(precio_neto: Decimal) -> tuple[Decimal, Decimal]:
    """
    Dado un precio neto (sin IVA), retorna (iva, total) redondeados a 2 decimales (ROUND_HALF_UP).
    """
    precio_neto = _to_decimal(precio_neto).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva   = (precio_neto * IVA_RATE).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    total = (precio_neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    return iva, total


# =============================================================================
# Listar / Crear / Editar listas de precios
# =============================================================================
@require_GET
def lista_listaprecios(request):
    """
    Lista todas las listas de precios predeterminadas.
    Template: lista_listaprecios.html
    Context:
      - listaprecios: queryset con todas las listas
    """
    listas = ListaPreciosPredeterminada.objects.all().order_by("nombre_listaprecios")
    return render(request, "./views/clientes/lista_listaprecios.html", {"listaprecios": listas})

@require_http_methods(["GET", "POST"])
def crear_listaprecios(request):
    if request.method == "POST":
        nombre = (request.POST.get("nombre_listaprecios") or "").strip()
        desc   = (request.POST.get("descripcion_listaprecios") or "").strip()
        if nombre:
            ListaPreciosPredeterminada.objects.create(
                nombre_listaprecios=nombre,
                descripcion_listaprecios=desc,
            )
            messages.success(request, "Lista de precios creada correctamente.")
            return redirect("lista_listaprecios")
        messages.error(request, "El nombre es obligatorio.")

    ctx = {"modo": "crear", "listaprecios": {}}
    return render(request, "./views/clientes/form_listaprecios.html", ctx)


@require_http_methods(["GET", "POST"])
def editar_listaprecios(request, listaprecios_id: int):
    lista = get_object_or_404(ListaPreciosPredeterminada, id=listaprecios_id)

    if request.method == "POST":
        nombre = (request.POST.get("nombre_listaprecios") or "").strip()
        desc   = (request.POST.get("descripcion_listaprecios") or "").strip()
        if nombre:
            lista.nombre_listaprecios = nombre
            lista.descripcion_listaprecios = desc
            lista.save()
            messages.success(request, "Lista de precios actualizada.")
            return redirect("lista_listaprecios")
        messages.error(request, "El nombre es obligatorio.")

    ctx = {"modo": "editar", "listaprecios": lista}
    return render(request, "./views/clientes/form_listaprecios.html", ctx)

# =============================================================================
# Asignar precios a una lista
# =============================================================================
@require_http_methods(["GET", "POST"])
def asignar_precios_listaprecios(request, listaprecios_id: int):
    """
    Asigna productos y precios a una lista predeterminada.
    Template: asignarprecios_listaprecios.html
    GET:
      - productos: para el <select>
      - precios: ítems ya asignados a la lista
    POST:
      - producto (id de Producto)
      - empaque  ('PRIMARIO'|'SECUNDARIO'|'TERCIARIO')
      - precio_venta (neto)
      - vigencia (YYYY-MM-DD)
    Lógica:
      - Calcula y persiste precio_iva y precio_total con Decimal + ROUND_HALF_UP (IVA 19%).
      - Evita duplicados por (lista, producto, empaque). Si existe, actualiza precio + vigencia.
    """
    lista = get_object_or_404(ListaPreciosPredeterminada, id=listaprecios_id)

    if request.method == "POST":
        producto_id  = request.POST.get("producto")
        empaque      = (request.POST.get("empaque") or "").strip().upper()
        precio_neto  = _to_decimal(request.POST.get("precio_venta"))
        vigencia     = request.POST.get("vigencia")

        if not producto_id or not empaque or not vigencia:
            messages.error(request, "Producto, empaque y vigencia son obligatorios.")
            return redirect(reverse("asignar_precios_listaprecios", args=[lista.id]))

        # Redondea neto a 2 decimales
        precio_neto = precio_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva, total  = _calcular_iva_total(precio_neto)

        producto = get_object_or_404(Producto, id=producto_id)

        try:
            with transaction.atomic():
                # Si tienes unique_together = ('listaprecios','nombre_producto','empaque')
                # usamos update-or-create semántico manual.
                item: Optional[ListaPreciosPredItem] = (
                    ListaPreciosPredItem.objects
                    .filter(listaprecios=lista, nombre_producto=producto, empaque=empaque)
                    .first()
                )
                if item:
                    item.precio_venta = precio_neto
                    item.precio_iva   = iva
                    item.precio_total = total
                    item.vigencia     = vigencia
                    item.save()
                    messages.success(request, "Precio actualizado exitosamente.")
                else:
                    ListaPreciosPredItem.objects.create(
                        listaprecios=lista,
                        nombre_producto=producto,
                        empaque=empaque,
                        precio_venta=precio_neto,
                        precio_iva=iva,
                        precio_total=total,
                        vigencia=vigencia,
                    )
                    messages.success(request, "Precio agregado exitosamente.")
        except IntegrityError:
            messages.error(request, "No se pudo guardar el precio. Verifica duplicados o datos.")

        return redirect(reverse("asignar_precios_listaprecios", args=[lista.id]))

    # GET
    productos = Producto.objects.all().order_by("nombre_producto")
    precios   = (
        ListaPreciosPredItem.objects
        .select_related("nombre_producto")
        .filter(listaprecios=lista)
        .order_by("nombre_producto__nombre_producto", "empaque")
    )

    ctx = {
        "listaprecios": lista,
        "productos": productos,
        "precios": precios,
    }
    return render(request, "./views/clientes/asignar_precios_listaprecios.html", ctx)


@require_POST
def eliminar_precio_listaprecios(request, item_id: int):
    """
    Elimina un ítem de lista de precios y redirige a la pantalla de asignación de la lista correspondiente.
    """
    item = get_object_or_404(ListaPreciosPredItem, id=item_id)
    lista_id = item.listaprecios_id
    try:
        item.delete()
        messages.success(request, "Ítem eliminado.")
    except IntegrityError:
        messages.error(request, "No se pudo eliminar el ítem. Intenta nuevamente.")
    return redirect(reverse("asignar_precios_listaprecios", args=[lista_id]))
