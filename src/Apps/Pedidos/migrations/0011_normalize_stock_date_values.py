from datetime import date, datetime

from django.db import migrations


def _normalize_date_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()

    text = str(value).strip()
    if not text:
        return None

    if len(text) >= 10:
        return text[:10]
    return text


def normalize_stock_dates(apps, schema_editor):
    Recepcion = apps.get_model("Pedidos", "Recepcion")
    Pedido = apps.get_model("Pedidos", "Pedido")
    Venta = apps.get_model("Pedidos", "Venta")
    EntregaPedido = apps.get_model("Pedidos", "EntregaPedido")
    connection = schema_editor.connection

    recepciones = Recepcion.objects.in_bulk()
    pedidos = Pedido.objects.in_bulk()

    ventas_por_pedido = {}
    for venta in Venta.objects.order_by("pedidoid_id", "-fecha_venta", "-id"):
        ventas_por_pedido.setdefault(venta.pedidoid_id, venta)

    entregas_por_pedido = {}
    for entrega in EntregaPedido.objects.order_by("pedido_id", "-fecha_entrega", "-id"):
        entregas_por_pedido.setdefault(entrega.pedido_id, entrega)

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, fecha_movimiento, fecha_reserva, recepcion_id, pedido_id FROM Pedidos_stock")
        rows = cursor.fetchall()

    updates = []
    for stock_id, fecha_movimiento, fecha_reserva, recepcion_id, pedido_id in rows:
        fecha_movimiento_norm = _normalize_date_value(fecha_movimiento)
        fecha_reserva_norm = _normalize_date_value(fecha_reserva)

        if not fecha_movimiento_norm:
            if recepcion_id and recepcion_id in recepciones:
                fecha_movimiento_norm = _normalize_date_value(recepciones[recepcion_id].fecha_recepcion)
            elif fecha_reserva_norm:
                fecha_movimiento_norm = fecha_reserva_norm
            elif pedido_id and pedido_id in ventas_por_pedido:
                fecha_movimiento_norm = _normalize_date_value(ventas_por_pedido[pedido_id].fecha_venta)
            elif pedido_id and pedido_id in entregas_por_pedido:
                fecha_movimiento_norm = _normalize_date_value(entregas_por_pedido[pedido_id].fecha_entrega)
            elif pedido_id and pedido_id in pedidos:
                fecha_movimiento_norm = _normalize_date_value(pedidos[pedido_id].fecha_pedido)

        if fecha_movimiento_norm != fecha_movimiento or fecha_reserva_norm != fecha_reserva:
            updates.append((fecha_movimiento_norm, fecha_reserva_norm, stock_id))

    if not updates:
        return

    with connection.cursor() as cursor:
        cursor.executemany(
            "UPDATE Pedidos_stock SET fecha_movimiento = ?, fecha_reserva = ? WHERE id = ?",
            updates,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("Pedidos", "0010_recepcionlinea_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_stock_dates, migrations.RunPython.noop),
    ]
