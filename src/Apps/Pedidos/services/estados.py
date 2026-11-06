from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from Apps.Pedidos.models import PedidoEstadoEvento


def fecha_pedido_a_datetime(fecha):
    valor = datetime.combine(fecha, time.min)
    return timezone.make_aware(valor, timezone.get_current_timezone())


@transaction.atomic
def registrar_estado_pedido(pedido, estado, usuario=None, ocurrido_en=None, origen=""):
    """Actualiza el estado visible y conserva una sola fecha por hito y pedido."""
    ocurrido_en = ocurrido_en or timezone.now()
    if timezone.is_naive(ocurrido_en):
        ocurrido_en = timezone.make_aware(ocurrido_en, timezone.get_current_timezone())

    pedido.estado_pedido = estado
    pedido.save(update_fields=("estado_pedido",))
    evento, creado = PedidoEstadoEvento.objects.get_or_create(
        pedido=pedido,
        estado=estado,
        defaults={"ocurrido_en": ocurrido_en, "usuario": usuario, "origen": origen},
    )
    return evento, creado
