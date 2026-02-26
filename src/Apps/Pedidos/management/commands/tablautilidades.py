# nueva migración manual (ejemplo)
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('Pedidos', 'XXXX_ultima_migracion'),
    ]

    operations = [
        migrations.AddField(
            model_name='utilidadproducto',
            name='venta',
            field=models.ForeignKey(
                to='Pedidos.venta',
                on_delete=django.db.models.deletion.CASCADE,
                null=True,
                blank=True,
                related_name='utilidades',
            ),
        ),
    ]
