from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("observaciones", "0004_versionregistro_sin_cambio"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActualizacionSistema",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("estado", models.CharField(choices=[("EXITOSA", "Exitosa"), ("FALLIDA", "Fallida"), ("SIN_CAMBIOS", "Sin cambios")], max_length=20)),
                ("commit_anterior", models.CharField(blank=True, max_length=40)),
                ("commit_nuevo", models.CharField(blank=True, max_length=40)),
                ("respaldo", models.CharField(blank=True, max_length=500)),
                ("detalle", models.TextField(blank=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("creado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-creado_en", "-id"]},
        ),
    ]
