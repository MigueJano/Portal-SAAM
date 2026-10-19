from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from Apps.Pedidos.models import Pedido, Stock, Venta
from Apps.integraciones.models import ConciliacionPago, MovimientoBancario

IVA = Decimal("0.19")


def total_pedido(pedido: Pedido) -> Decimal:
    total_ventas = Venta.objects.filter(pedidoid=pedido).aggregate(total=Sum("venta_total_pedido"))["total"]
    if total_ventas is not None:
        return Decimal(total_ventas)
    if pedido.lineas.exists():
        neto = sum((linea.precio_unitario * linea.cantidad for linea in pedido.lineas.all()), Decimal("0"))
    else:
        movimientos = Stock.objects.filter(pedido=pedido, precio_unitario__isnull=False)
        despachos = movimientos.filter(tipo_movimiento="DESPACHO")
        movimientos = despachos if despachos.exists() else movimientos.filter(tipo_movimiento__in=("RESERVA", "DESPACHO"))
        neto = sum((Decimal(m.qty or 0) * Decimal(m.precio_unitario or 0) for m in movimientos), Decimal("0"))
    return (neto * (Decimal("1") + IVA)).quantize(Decimal("0.01"))


def proponer_conciliaciones(movimiento: MovimientoBancario) -> int:
    if movimiento.tipo != MovimientoBancario.TIPO_ABONO:
        return 0
    creadas = 0
    for pedido in Pedido.objects.filter(estado_pedido="Entregado").prefetch_related("lineas"):
        total = total_pedido(pedido)
        if total == movimiento.monto:
            _, creada = ConciliacionPago.objects.get_or_create(
                movimiento=movimiento,
                pedido=pedido,
                defaults={"monto_aplicado": movimiento.monto, "criterio": "Coincidencia exacta de monto"},
            )
            creadas += int(creada)
    return creadas


@transaction.atomic
def confirmar_conciliacion(conciliacion: ConciliacionPago, usuario) -> ConciliacionPago:
    if conciliacion.estado != ConciliacionPago.ESTADO_PROPUESTA:
        return conciliacion
    aplicado = (
        ConciliacionPago.objects.filter(
            movimiento=conciliacion.movimiento,
            estado=ConciliacionPago.ESTADO_CONFIRMADA,
        ).aggregate(total=Sum("monto_aplicado"))["total"]
        or Decimal("0")
    )
    if aplicado + conciliacion.monto_aplicado > conciliacion.movimiento.monto:
        raise ValueError("El monto conciliado excede el movimiento bancario.")
    conciliacion.estado = ConciliacionPago.ESTADO_CONFIRMADA
    conciliacion.confirmado_por = usuario
    conciliacion.confirmado_en = timezone.now()
    conciliacion.save(update_fields=("estado", "confirmado_por", "confirmado_en"))

    movimiento = conciliacion.movimiento
    aplicado_total = aplicado + conciliacion.monto_aplicado
    if aplicado_total == movimiento.monto:
        movimiento.estado = MovimientoBancario.ESTADO_CONCILIADO
        movimiento.save(update_fields=("estado",))

    pedido = conciliacion.pedido
    confirmado_pedido = (
        ConciliacionPago.objects.filter(pedido=pedido, estado=ConciliacionPago.ESTADO_CONFIRMADA)
        .aggregate(total=Sum("monto_aplicado"))["total"]
        or Decimal("0")
    )
    if confirmado_pedido >= total_pedido(pedido):
        pedido.estado_pedido = "Pagado"
        pedido.save(update_fields=("estado_pedido",))
    return conciliacion

