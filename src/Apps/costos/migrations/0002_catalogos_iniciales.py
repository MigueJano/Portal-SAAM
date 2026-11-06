from django.db import migrations


def crear_catalogos(apps, schema_editor):
    Categoria = apps.get_model("costos", "CategoriaGasto")
    Accion = apps.get_model("costos", "AccionOperacional")
    for nombre in ("Despacho externo", "Embalaje externo", "Transporte", "Servicios", "Otros"):
        Categoria.objects.get_or_create(nombre=nombre)
    for nombre, minutos in (
        ("Procesamiento de pedido", 10),
        ("Preparacion y picking", 15),
        ("Embalaje", 10),
        ("Despacho", 15),
        ("Recepcion de mercaderia", 15),
        ("Gestion administrativa", 10),
    ):
        Accion.objects.get_or_create(nombre=nombre, defaults={"minutos_estandar": minutos, "valor_hora": 0})


class Migration(migrations.Migration):
    dependencies = [("costos", "0001_initial")]
    operations = [migrations.RunPython(crear_catalogos, migrations.RunPython.noop)]
