from datetime import date, datetime

from django.db import migrations


def _normalize_date_text(value):
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


def trim_stock_datetime_text(apps, schema_editor):
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, fecha_movimiento, fecha_reserva FROM Pedidos_stock"
        )
        rows = cursor.fetchall()

    updates = []
    for stock_id, fecha_movimiento, fecha_reserva in rows:
        fecha_movimiento_norm = _normalize_date_text(fecha_movimiento)
        fecha_reserva_norm = _normalize_date_text(fecha_reserva)
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
        ("Pedidos", "0011_normalize_stock_date_values"),
    ]

    operations = [
        migrations.RunPython(trim_stock_datetime_text, migrations.RunPython.noop),
    ]
