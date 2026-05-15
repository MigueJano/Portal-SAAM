from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from Apps.Pedidos.models import Cliente, ListaPrecios, ListaPreciosPredItem, ListaPreciosPredeterminada


DOS_DEC = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _source_key(item) -> tuple[int, str]:
    return item.nombre_producto_id, str(item.empaque).upper().strip()


@transaction.atomic
def sincronizar_lista_predeterminada_a_cliente(
    cliente: Cliente,
    lista: ListaPreciosPredeterminada,
    *,
    vig_override=None,
    asociar: bool = True,
    limpiar_huerfanos: bool = True,
) -> dict:
    items = list(
        ListaPreciosPredItem.objects
        .select_related("nombre_producto")
        .filter(listaprecios=lista)
    )

    lista_anterior_id = cliente.lista_precios_predeterminada_id
    if asociar and lista_anterior_id and lista_anterior_id != lista.id:
        ListaPrecios.objects.filter(
            nombre_cliente=cliente,
            lista_predeterminada_origen_id=lista_anterior_id,
        ).delete()

    rows_existentes = {
        (row.nombre_producto_id, str(row.empaque).upper().strip()): row
        for row in ListaPrecios.objects.filter(nombre_cliente=cliente)
    }
    claves_fuente = {_source_key(item) for item in items}

    created = 0
    updated = 0
    for item in items:
        clave = _source_key(item)
        row = rows_existentes.get(clave)
        defaults = {
            "precio_venta": _q2(item.precio_venta),
            "precio_iva": _q2(item.precio_iva),
            "precio_total": _q2(item.precio_total),
            "vigencia": vig_override or item.vigencia,
            "lista_predeterminada_origen": lista,
        }
        if row is None:
            ListaPrecios.objects.create(
                nombre_cliente=cliente,
                nombre_producto=item.nombre_producto,
                empaque=item.empaque,
                **defaults,
            )
            created += 1
            continue

        for field, value in defaults.items():
            setattr(row, field, value)
        row.save(update_fields=["precio_venta", "precio_iva", "precio_total", "vigencia", "lista_predeterminada_origen"])
        updated += 1

    deleted = 0
    if limpiar_huerfanos:
        qs_huerfanos = ListaPrecios.objects.filter(
            nombre_cliente=cliente,
            lista_predeterminada_origen=lista,
        )
        for row in qs_huerfanos:
            if (row.nombre_producto_id, str(row.empaque).upper().strip()) not in claves_fuente:
                row.delete()
                deleted += 1

    if asociar and cliente.lista_precios_predeterminada_id != lista.id:
        cliente.lista_precios_predeterminada = lista
        cliente.save(update_fields=["lista_precios_predeterminada"])

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }


@transaction.atomic
def sincronizar_lista_predeterminada_a_clientes_asociados(
    lista: ListaPreciosPredeterminada,
    *,
    vig_override=None,
) -> dict:
    clientes = list(lista.clientes_asociados.all())
    created = 0
    updated = 0
    deleted = 0

    for cliente in clientes:
        stats = sincronizar_lista_predeterminada_a_cliente(
            cliente,
            lista,
            vig_override=vig_override,
            asociar=False,
            limpiar_huerfanos=True,
        )
        created += stats["created"]
        updated += stats["updated"]
        deleted += stats["deleted"]

    return {
        "clientes": len(clientes),
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }
