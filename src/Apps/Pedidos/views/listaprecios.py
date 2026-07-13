# Apps/Pedidos/views/listaprecios.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from dateutil.relativedelta import relativedelta

from Apps.Pedidos.models import (
    Producto,
    ListaPreciosPredeterminada,     # <-- Asegúrate del nombre real del modelo
    ListaPreciosPredItem,           # <-- Asegúrate del nombre real del modelo de ítem
)
from Apps.Pedidos.services import (
    costo_maximo_unitario,
    es_pack,
    sincronizar_lista_predeterminada_a_clientes_asociados,
)

# --- Constantes numéricas ---
DOS_DEC   = Decimal("0.01")
IVA_RATE  = Decimal("0.19")
MESES_ALERTA_ACTUALIZACION = 6
MARGEN_ALERTA_ROJA = Decimal("12")
MARGEN_ALERTA_AMARILLA = Decimal("20")


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


def _round2(value: Decimal) -> Decimal:
    return _to_decimal(value).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _date_input_value(value) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _calcular_margen_ganancia(precio_venta: Decimal, precio_compra: Decimal):
    precio_compra = _round2(precio_compra)
    if precio_compra <= 0:
        return None
    precio_venta = _round2(precio_venta)
    return _round2(((precio_venta - precio_compra) / precio_compra) * Decimal("100"))


def _badge_margen_ganancia(margen: Decimal | None) -> str:
    if margen is None:
        return ""
    if margen < MARGEN_ALERTA_ROJA:
        return "bg-danger"
    if margen <= MARGEN_ALERTA_AMARILLA:
        return "bg-warning text-dark"
    return "bg-success"


def _fecha_requiere_actualizacion(fecha_desde):
    if not fecha_desde:
        return None
    return fecha_desde + relativedelta(months=MESES_ALERTA_ACTUALIZACION)


def _precio_esta_desactualizado(fecha_desde, today=None) -> bool:
    fecha_alerta = _fecha_requiere_actualizacion(fecha_desde)
    if not fecha_alerta:
        return False
    return fecha_alerta <= (today or timezone.localdate())


def _costo_por_empaque(costo_unitario: Decimal, producto: Producto, empaque: str) -> Decimal:
    qty_secundario = Decimal(1 if es_pack(producto) else (producto.qty_secundario or 1))
    qty_terciario = Decimal(1 if es_pack(producto) else (producto.qty_terciario or 1))
    nivel = (empaque or "").upper().strip()
    if nivel == "SECUNDARIO":
        return _round2(costo_unitario * qty_secundario)
    if nivel == "TERCIARIO":
        return _round2(costo_unitario * qty_secundario * qty_terciario)
    return _round2(costo_unitario)


def _productos_habilitados_para_precio():
    productos = (
        Producto.objects
        .filter(estado_operativo__in=Producto.estados_precio_habilitados())
        .prefetch_related("componentes_pack__producto")
        .order_by("nombre_producto")
    )
    return [producto for producto in productos if producto.precio_habilitado]


def _url_asignar_listaprecios(listaprecios_id: int, *, item_id: int | None = None) -> str:
    url = reverse("asignar_precios_listaprecios", args=[listaprecios_id])
    if item_id:
        return f"{url}?item_id={item_id}"
    return url


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
    listas = (
        ListaPreciosPredeterminada.objects
        .prefetch_related("clientes_asociados")
        .all()
        .order_by("nombre_listaprecios")
    )
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
    today = timezone.localdate()
    item_id = request.GET.get("item_id") or request.POST.get("item_id") or ""
    item_en_edicion = None
    if str(item_id).isdigit():
        item_en_edicion = get_object_or_404(
            ListaPreciosPredItem.objects.select_related(
                "nombre_producto",
                "nombre_producto__empaque_primario",
                "nombre_producto__empaque_secundario",
                "nombre_producto__empaque_terciario",
            ),
            pk=int(item_id),
            listaprecios=lista,
        )

    if request.method == "POST":
        producto_id  = request.POST.get("producto")
        empaque      = (request.POST.get("empaque") or "").strip().upper()
        precio_neto  = _to_decimal(request.POST.get("precio_venta"))
        vigencia     = request.POST.get("vigencia")
        redirect_url = _url_asignar_listaprecios(
            lista.id,
            item_id=item_en_edicion.id if item_en_edicion else None,
        )

        if item_en_edicion:
            producto_id = str(item_en_edicion.nombre_producto_id)
            empaque = item_en_edicion.empaque

        if not producto_id or not empaque or not vigencia:
            messages.error(request, "Producto, empaque y vigencia son obligatorios.")
            return redirect(redirect_url)

        # Redondea neto a 2 decimales
        precio_neto = precio_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva, total  = _calcular_iva_total(precio_neto)

        producto = get_object_or_404(Producto.objects.prefetch_related("componentes_pack__producto"), id=producto_id)
        if not producto.precio_habilitado:
            messages.error(request, "El producto no estÃ¡ habilitado para nuevos precios.")
            return redirect(redirect_url)

        try:
            with transaction.atomic():
                # Si tienes unique_together = ('listaprecios','nombre_producto','empaque')
                # usamos update-or-create semántico manual.
                item: Optional[ListaPreciosPredItem] = item_en_edicion or (
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
                    sync_stats = sincronizar_lista_predeterminada_a_clientes_asociados(lista)
                    messages.success(
                        request,
                        (
                            f"Precio actualizado exitosamente. Sincronizados {sync_stats['clientes']} clientes asociados. "
                            f"Productos omitidos por estado: {sync_stats.get('skipped_disabled', 0)}."
                        ),
                    )
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
                    sync_stats = sincronizar_lista_predeterminada_a_clientes_asociados(lista)
                    messages.success(
                        request,
                        (
                            f"Precio agregado exitosamente. Sincronizados {sync_stats['clientes']} clientes asociados. "
                            f"Productos omitidos por estado: {sync_stats.get('skipped_disabled', 0)}."
                        ),
                    )
        except IntegrityError:
            messages.error(request, "No se pudo guardar el precio. Verifica duplicados o datos.")

        return redirect(_url_asignar_listaprecios(lista.id))

    # GET
    productos = _productos_habilitados_para_precio()
    if (
        item_en_edicion
        and item_en_edicion.nombre_producto_id
        and all(producto.id != item_en_edicion.nombre_producto_id for producto in productos)
    ):
        productos = productos + [item_en_edicion.nombre_producto]
        productos.sort(key=lambda producto: producto.nombre_producto.casefold())
    precios   = list(
        ListaPreciosPredItem.objects
        .select_related(
            "nombre_producto",
            "nombre_producto__empaque_primario",
            "nombre_producto__empaque_secundario",
            "nombre_producto__empaque_terciario",
        )
        .filter(listaprecios=lista)
        .order_by("nombre_producto__nombre_producto", "empaque")
    )
    clientes_asociados = lista.clientes_asociados.order_by("nombre_cliente")
    costos_unitarios_por_producto: dict[int, Decimal] = {}
    precios_desactualizados_count = 0

    for item in precios:
        producto = item.nombre_producto
        if producto.id not in costos_unitarios_por_producto:
            costos_unitarios_por_producto[producto.id] = costo_maximo_unitario(producto)
        precio_compra_unitario = costos_unitarios_por_producto[producto.id]

        if precio_compra_unitario and precio_compra_unitario > 0:
            item.precio_compra_referencial = _costo_por_empaque(
                Decimal(precio_compra_unitario),
                producto,
                item.empaque,
            )
            item.diferencia_compra_venta = _round2(
                Decimal(item.precio_venta or 0) - item.precio_compra_referencial
            )
            item.margen_ganancia = _calcular_margen_ganancia(
                item.precio_venta,
                item.precio_compra_referencial,
            )
        else:
            item.precio_compra_referencial = None
            item.diferencia_compra_venta = None
            item.margen_ganancia = None

        item.tiene_precio_compra_referencial = item.precio_compra_referencial is not None
        item.tiene_diferencia_compra_venta = item.diferencia_compra_venta is not None
        item.tiene_margen_ganancia = item.margen_ganancia is not None
        item.badge_margen_ganancia = _badge_margen_ganancia(item.margen_ganancia)
        item.alerta_bajo_costo = (
            item.diferencia_compra_venta is not None and item.diferencia_compra_venta < 0
        )
        item.precio_desactualizado = _precio_esta_desactualizado(item.vigencia, today=today)
        if item.precio_desactualizado:
            precios_desactualizados_count += 1

    vigencia_default = max((item.vigencia for item in precios if item.vigencia), default=None) or today
    producto_form_value = str(item_en_edicion.nombre_producto_id) if item_en_edicion else ""
    empaque_form_value = item_en_edicion.empaque if item_en_edicion else ""
    precio_venta_form_value = str(item_en_edicion.precio_venta) if item_en_edicion else ""
    vigencia_form_value = _date_input_value(item_en_edicion.vigencia if item_en_edicion else vigencia_default)

    ctx = {
        "listaprecios": lista,
        "productos": productos,
        "precios": precios,
        "clientes_asociados": clientes_asociados,
        "item_en_edicion": item_en_edicion,
        "producto_form_value": producto_form_value,
        "empaque_form_value": empaque_form_value,
        "precio_venta_form_value": precio_venta_form_value,
        "vigencia_form_value": vigencia_form_value,
        "today_input_value": _date_input_value(today),
        "precios_desactualizados_count": precios_desactualizados_count,
    }
    return render(request, "./views/clientes/asignar_precios_listaprecios.html", ctx)


@require_POST
def eliminar_precio_listaprecios(request, item_id: int):
    """
    Elimina un ítem de lista de precios y redirige a la pantalla de asignación de la lista correspondiente.
    """
    item = get_object_or_404(ListaPreciosPredItem, id=item_id)
    lista_id = item.listaprecios_id
    lista = item.listaprecios
    try:
        item.delete()
        sync_stats = sincronizar_lista_predeterminada_a_clientes_asociados(lista)
        messages.success(
            request,
            (
                f"Ítem eliminado. Sincronizados {sync_stats['clientes']} clientes asociados. "
                f"Productos omitidos por estado: {sync_stats.get('skipped_disabled', 0)}."
            ),
        )
    except IntegrityError:
        messages.error(request, "No se pudo eliminar el ítem. Intenta nuevamente.")
    return redirect(reverse("asignar_precios_listaprecios", args=[lista_id]))


@require_POST
def sincronizar_clientes_listaprecios(request, listaprecios_id: int):
    lista = get_object_or_404(ListaPreciosPredeterminada, id=listaprecios_id)
    stats = sincronizar_lista_predeterminada_a_clientes_asociados(lista)
    messages.success(
        request,
        (
            f"Sincronización masiva completada. "
            f"Clientes: {stats['clientes']}, creados: {stats['created']}, "
            f"actualizados: {stats['updated']}, eliminados: {stats['deleted']}, "
            f"omitidos por estado: {stats.get('skipped_disabled', 0)}."
        ),
    )
    return redirect(reverse("asignar_precios_listaprecios", args=[lista.id]))
