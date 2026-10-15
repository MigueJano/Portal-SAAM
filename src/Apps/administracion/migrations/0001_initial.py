import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="ActaReunion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateField(verbose_name="Fecha de reunión")),
                ("acta", models.TextField(verbose_name="Acta")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("creado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actas_reunion_creadas", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Acta de reunión", "verbose_name_plural": "Actas de reuniones", "ordering": ["-fecha", "-id"]},
        ),
    ]
