from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Pedidos", "0014_producto_estado_operativo_producto_fecha_estado_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="venta",
            name="ganancia_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="venta",
            name="ganancia_porcentaje",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
