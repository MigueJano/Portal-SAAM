from django.db import migrations


def force_trim_stock_datetime_text(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE Pedidos_stock
            SET fecha_movimiento = SUBSTR(CAST(fecha_movimiento AS TEXT), 1, 10)
            WHERE CAST(fecha_movimiento AS TEXT) LIKE '% %:%:%'
            """
        )
        cursor.execute(
            """
            UPDATE Pedidos_stock
            SET fecha_reserva = SUBSTR(CAST(fecha_reserva AS TEXT), 1, 10)
            WHERE CAST(fecha_reserva AS TEXT) LIKE '% %:%:%'
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("Pedidos", "0012_trim_stock_datetime_text"),
    ]

    operations = [
        migrations.RunPython(force_trim_stock_datetime_text, migrations.RunPython.noop),
    ]
