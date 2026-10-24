from datetime import datetime, time

from django.db import migrations, models
from django.utils import timezone


def completar_fecha_carga(apps, schema_editor):
    Stock = apps.get_model("Pedidos", "Stock")
    for movimiento in Stock.objects.filter(fecha_carga__isnull=True).iterator():
        fecha = movimiento.fecha_reserva or movimiento.fecha_movimiento
        fecha_carga = timezone.make_aware(
            datetime.combine(fecha, time.min),
            timezone.get_current_timezone(),
        )
        Stock.objects.filter(pk=movimiento.pk).update(fecha_carga=fecha_carga)


class Migration(migrations.Migration):
    dependencies = [
        ("Pedidos", "0015_venta_permite_perdidas"),
    ]

    operations = [
        migrations.AddField(
            model_name="stock",
            name="fecha_carga",
            field=models.DateTimeField(db_index=True, null=True),
        ),
        migrations.RunPython(completar_fecha_carga, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="stock",
            name="fecha_carga",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]
