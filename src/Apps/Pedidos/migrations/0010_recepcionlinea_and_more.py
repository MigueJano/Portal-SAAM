from datetime import datetime, time

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def _solo_fecha(valor):
    if valor is None:
        return None
    return valor.date() if hasattr(valor, "date") else valor


def _a_datetime_aware(valor):
    fecha = _solo_fecha(valor)
    if fecha is None:
        return None
    naive = datetime.combine(fecha, time.min)
    return django.utils.timezone.make_aware(naive, django.utils.timezone.get_current_timezone())


def consolidar_stock_y_recepciones(apps, schema_editor):
    Stock = apps.get_model("Pedidos", "Stock")
    Recepcion = apps.get_model("Pedidos", "Recepcion")
    RecepcionLinea = apps.get_model("Pedidos", "RecepcionLinea")
    EntregaPedido = apps.get_model("Pedidos", "EntregaPedido")
    MovimientoStockHistorico = apps.get_model("Pedidos", "MovimientoStockHistorico")

    recepciones = Recepcion.objects.in_bulk()

    entregas_por_pedido = {}
    for entrega in EntregaPedido.objects.order_by("pedido_id", "-fecha_entrega", "-id"):
        entregas_por_pedido.setdefault(entrega.pedido_id, entrega)

    historicos_por_stock = {}
    for movimiento in MovimientoStockHistorico.objects.order_by("stock_id", "fecha_movimiento", "id"):
        historicos_por_stock.setdefault(movimiento.stock_id, []).append(movimiento)

    stocks_a_eliminar = []
    stocks_a_actualizar = []

    for stock in Stock.objects.all().iterator():
        historicos = historicos_por_stock.get(stock.id, [])

        def ultimo_evento(tipo):
            for evento in reversed(historicos):
                if evento.tipo_movimiento == tipo:
                    return evento
            return None

        if stock.recepcion_id:
            RecepcionLinea.objects.create(
                recepcion_id=stock.recepcion_id,
                producto_id=stock.producto_id,
                qty=stock.qty,
                empaque=stock.empaque,
                precio_unitario=stock.precio_unitario,
                creado=stock.fecha_movimiento,
                actualizado=stock.fecha_movimiento,
            )

            recepcion = recepciones.get(stock.recepcion_id)
            fecha_disponible = None
            if recepcion and recepcion.fecha_recepcion:
                fecha_disponible = recepcion.fecha_recepcion
            elif stock.fecha_movimiento:
                fecha_disponible = _solo_fecha(stock.fecha_movimiento)

            evento_recepcion = ultimo_evento("RECEPCION") or ultimo_evento("DISPONIBLE")

            if stock.tipo_movimiento == "RECEPCION":
                if recepcion and recepcion.estado_recepcion == "Finalizado":
                    stock.tipo_movimiento = "DISPONIBLE"
                    stock.fecha_movimiento = _a_datetime_aware(fecha_disponible)
                    stock.responsable_id = getattr(evento_recepcion, "responsable_id", None)
                    stocks_a_actualizar.append(stock)
                else:
                    stocks_a_eliminar.append(stock.id)
                continue

            if stock.tipo_movimiento == "DISPONIBLE":
                stock.fecha_movimiento = _a_datetime_aware(fecha_disponible)
                stock.responsable_id = getattr(evento_recepcion, "responsable_id", None)
                stocks_a_actualizar.append(stock)
                continue

        if stock.tipo_movimiento == "RESERVA":
            evento_reserva = ultimo_evento("RESERVA")
            stock.fecha_movimiento = _a_datetime_aware(
                getattr(evento_reserva, "fecha_movimiento", None) or stock.fecha_movimiento
            )
            stock.responsable_id = getattr(evento_reserva, "responsable_id", None)
            stocks_a_actualizar.append(stock)
            continue

        if stock.tipo_movimiento == "DESPACHO":
            evento_reserva = ultimo_evento("RESERVA")
            evento_despacho = ultimo_evento("DESPACHO")
            entrega = entregas_por_pedido.get(stock.pedido_id)

            stock.fecha_reserva = _solo_fecha(
                getattr(evento_reserva, "fecha_movimiento", None) or stock.fecha_movimiento
            )
            stock.fecha_movimiento = _a_datetime_aware(
                getattr(evento_despacho, "fecha_movimiento", None)
                or getattr(entrega, "fecha_entrega", None)
                or stock.fecha_movimiento
            )
            stock.responsable_id = (
                getattr(evento_despacho, "responsable_id", None)
                or getattr(evento_reserva, "responsable_id", None)
            )
            stocks_a_actualizar.append(stock)
            continue

        if stock.fecha_movimiento:
            stock.fecha_movimiento = _a_datetime_aware(stock.fecha_movimiento)
            stocks_a_actualizar.append(stock)

    if stocks_a_eliminar:
        Stock.objects.filter(id__in=stocks_a_eliminar).delete()

    if stocks_a_actualizar:
        Stock.objects.bulk_update(
            stocks_a_actualizar,
            ["tipo_movimiento", "fecha_movimiento", "fecha_reserva", "responsable"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("Pedidos", "0009_cliente_lista_precios_predeterminada_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecepcionLinea",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("qty", models.IntegerField()),
                (
                    "empaque",
                    models.CharField(
                        choices=[("PRIMARIO", "Primario"), ("SECUNDARIO", "Secundario"), ("TERCIARIO", "Terciario")],
                        max_length=10,
                    ),
                ),
                (
                    "precio_unitario",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=12,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("actualizado", models.DateTimeField(auto_now=True)),
                ("producto", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="Pedidos.producto")),
                (
                    "recepcion",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lineas",
                        to="Pedidos.recepcion",
                    ),
                ),
            ],
            options={"ordering": ("id",)},
        ),
        migrations.AlterModelOptions(
            name="stock",
            options={"ordering": ("fecha_movimiento", "id")},
        ),
        migrations.AddField(
            model_name="stock",
            name="fecha_reserva",
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="stock",
            name="responsable",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="movimientos_stock",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(consolidar_stock_y_recepciones, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="stock",
            name="fecha_movimiento",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.AlterField(
            model_name="stock",
            name="tipo_movimiento",
            field=models.CharField(
                choices=[("DISPONIBLE", "Disponible"), ("RESERVA", "Reserva"), ("DESPACHO", "Despacho")],
                max_length=10,
            ),
        ),
        migrations.AddIndex(
            model_name="stock",
            index=models.Index(fields=["fecha_movimiento"], name="Pedidos_sto_fecha_m_2b1a52_idx"),
        ),
        migrations.AddIndex(
            model_name="stock",
            index=models.Index(fields=["tipo_movimiento", "fecha_movimiento"], name="Pedidos_sto_tipo_mo_e29058_idx"),
        ),
        migrations.DeleteModel(
            name="MovimientoStockHistorico",
        ),
        migrations.AddIndex(
            model_name="recepcionlinea",
            index=models.Index(fields=["recepcion"], name="Pedidos_rec_recepci_609862_idx"),
        ),
        migrations.AddIndex(
            model_name="recepcionlinea",
            index=models.Index(fields=["producto"], name="Pedidos_rec_product_c8ce37_idx"),
        ),
    ]
