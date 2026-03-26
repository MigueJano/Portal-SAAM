from django.utils import timezone

from Apps.Pedidos.models import MovimientoStockHistorico, Stock


def registrar_movimiento_stock(
    stock: Stock,
    *,
    tipo_movimiento: str | None = None,
    responsable=None,
    fecha_movimiento=None,
):
    return MovimientoStockHistorico.objects.create(
        stock=stock,
        tipo_movimiento=tipo_movimiento or stock.tipo_movimiento,
        qty=stock.qty,
        empaque=stock.empaque,
        precio_unitario=stock.precio_unitario,
        fecha_movimiento=fecha_movimiento or stock.fecha_movimiento or timezone.now(),
        responsable=responsable,
    )


def registrar_movimientos_stock(
    stocks,
    *,
    tipo_movimiento: str | None = None,
    responsable=None,
    fecha_movimiento=None,
):
    momento = fecha_movimiento or timezone.now()
    eventos = [
        MovimientoStockHistorico(
            stock=stock,
            tipo_movimiento=tipo_movimiento or stock.tipo_movimiento,
            qty=stock.qty,
            empaque=stock.empaque,
            precio_unitario=stock.precio_unitario,
            fecha_movimiento=momento,
            responsable=responsable,
        )
        for stock in stocks
    ]
    if eventos:
        MovimientoStockHistorico.objects.bulk_create(eventos)
    return eventos
