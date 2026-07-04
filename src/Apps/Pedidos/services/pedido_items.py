from django.db.models import Min, Sum

from Apps.Pedidos.models import Pedido, Producto, Stock


def _legacy_stock_base_qs(pedido: Pedido):
    qs = Stock.objects.filter(
        pedido=pedido,
        linea_pedido__isnull=True,
    )

    if pedido.estado_pedido in {"Entregado", "Finalizado", "Pagado"}:
        despacho_qs = qs.filter(tipo_movimiento="DESPACHO")
        if despacho_qs.exists():
            return despacho_qs
        return qs.filter(tipo_movimiento__in=["RESERVA", "DESPACHO"])

    return qs.filter(tipo_movimiento="RESERVA")


def lineas_comerciales_pedido(pedido: Pedido):
    return list(
        pedido.lineas.select_related(
            "producto",
            "producto__empaque_primario",
            "producto__empaque_secundario",
            "producto__empaque_terciario",
        ).order_by("creado", "id")
    )


def reservas_legacy_agrupadas_pedido(pedido: Pedido):
    return list(
        _legacy_stock_base_qs(pedido)
        .values(
            "producto",
            "producto__nombre_producto",
            "empaque",
            "precio_unitario",
        )
        .annotate(
            qty_sum=Sum("qty"),
            primera_fecha=Min("fecha_movimiento"),
        )
        .order_by("primera_fecha", "producto", "empaque", "precio_unitario")
    )


def items_comerciales_pedido(pedido: Pedido):
    items = [
        {
            "origen": "linea",
            "sort_date": linea.creado.date(),
            "linea": linea,
        }
        for linea in lineas_comerciales_pedido(pedido)
    ]

    legacy_rows = reservas_legacy_agrupadas_pedido(pedido)
    if legacy_rows:
        productos = Producto.objects.select_related(
            "empaque_primario",
            "empaque_secundario",
            "empaque_terciario",
        ).in_bulk([row["producto"] for row in legacy_rows])

        for row in legacy_rows:
            items.append(
                {
                    "origen": "legacy",
                    "sort_date": row["primera_fecha"],
                    "legacy": row,
                    "producto": productos.get(row["producto"]),
                }
            )

    items.sort(
        key=lambda item: (
            item["sort_date"],
            0 if item["origen"] == "legacy" else 1,
            item["legacy"]["producto"] if item["origen"] == "legacy" else item["linea"].id,
        )
    )
    return items
