from collections import defaultdict, deque
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from Apps.Pedidos.models import Stock, Venta
from Apps.Pedidos.services import factor_empaque


CENTAVO = Decimal("0.01")
CIEN = Decimal("100")
ZERO = Decimal("0.00")


def q2(valor):
    return Decimal(valor or 0).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def cantidad_primaria(movimiento):
    factor = max(factor_empaque(movimiento.producto, movimiento.empaque), 1)
    return Decimal(movimiento.qty or 0) * Decimal(factor)


def costo_primario(movimiento):
    factor = max(factor_empaque(movimiento.producto, movimiento.empaque), 1)
    return q2(Decimal(movimiento.precio_unitario or 0) / Decimal(factor))


def costos_fifo_por_despacho():
    """Retorna costo FIFO por Stock DESPACHO y sus incidencias históricas."""
    capas = defaultdict(deque)
    costos = {}
    incidencias = defaultdict(list)
    movimientos = (
        Stock.objects.filter(tipo_movimiento__in=("DISPONIBLE", "DESPACHO"))
        .select_related("producto")
        .order_by("producto_id", "fecha_movimiento", "id")
    )

    for movimiento in movimientos:
        cantidad = cantidad_primaria(movimiento)
        if cantidad <= 0:
            continue

        if movimiento.tipo_movimiento == "DISPONIBLE":
            costo = costo_primario(movimiento)
            capas[movimiento.producto_id].append(
                {"cantidad": cantidad, "costo": costo, "stock_id": movimiento.id}
            )
            continue

        pendiente = cantidad
        costo_total = ZERO
        problemas = []
        while pendiente > 0 and capas[movimiento.producto_id]:
            capa = capas[movimiento.producto_id][0]
            consumida = min(pendiente, capa["cantidad"])
            if capa["costo"] <= 0:
                problemas.append(f"entrada #{capa['stock_id']} sin costo")
            costo_total += consumida * capa["costo"]
            capa["cantidad"] -= consumida
            pendiente -= consumida
            if capa["cantidad"] <= 0:
                capas[movimiento.producto_id].popleft()

        if pendiente > 0:
            problemas.append(f"faltan {pendiente} unidades primarias de entrada previa")

        if problemas:
            incidencias[movimiento.id].extend(problemas)
        else:
            costos[movimiento.id] = q2(costo_total)

    return costos, incidencias


class Command(BaseCommand):
    help = "Audita o recalcula Venta.ganancia_total usando el costo FIFO de sus despachos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Guarda los valores calculados. Sin esta opción solo simula.",
        )

    def handle(self, *args, **options):
        aplicar = options["apply"]
        costos_despacho, incidencias_despacho = costos_fifo_por_despacho()
        pedidos_multiventa = set(
            Venta.objects.values("pedidoid")
            .annotate(cantidad=Count("id"))
            .filter(cantidad__gt=1)
            .values_list("pedidoid", flat=True)
        )
        despachos_por_pedido = defaultdict(list)
        for despacho in (
            Stock.objects.filter(tipo_movimiento="DESPACHO", pedido__isnull=False)
            .select_related("producto")
            .order_by("fecha_movimiento", "id")
        ):
            despachos_por_pedido[despacho.pedido_id].append(despacho)

        actualizaciones = []
        omitidas = []
        total_anterior = ZERO
        total_fifo = ZERO

        for venta in Venta.objects.select_related("pedidoid").order_by("fecha_venta", "id"):
            if venta.pedidoid_id in pedidos_multiventa:
                omitidas.append((venta.id, "pedido con más de una venta"))
                continue

            despachos = despachos_por_pedido.get(venta.pedidoid_id, [])
            if not despachos:
                omitidas.append((venta.id, "sin despachos vinculados"))
                continue

            problemas = []
            for despacho in despachos:
                problemas.extend(incidencias_despacho.get(despacho.id, []))
                if despacho.id not in costos_despacho and despacho.id not in incidencias_despacho:
                    problemas.append(f"despacho #{despacho.id} sin costo FIFO")
            if problemas:
                omitidas.append((venta.id, "; ".join(sorted(set(problemas)))))
                continue

            costo_fifo = sum((costos_despacho[d.id] for d in despachos), start=ZERO)
            ganancia_fifo = q2(venta.venta_neto_pedido - costo_fifo)
            porcentaje_fifo = (
                q2((ganancia_fifo / venta.venta_neto_pedido) * CIEN)
                if venta.venta_neto_pedido
                else ZERO
            )
            total_anterior += Decimal(venta.ganancia_total or 0)
            total_fifo += ganancia_fifo
            venta.ganancia_total = ganancia_fifo
            venta.ganancia_porcentaje = porcentaje_fifo
            actualizaciones.append(venta)

        self.stdout.write(f"Modo: {'APLICAR' if aplicar else 'SIMULACION'}")
        self.stdout.write(f"Ventas recalculables: {len(actualizaciones)}")
        self.stdout.write(f"Ventas omitidas: {len(omitidas)}")
        self.stdout.write(f"Utilidad anterior (recalculables): ${q2(total_anterior)}")
        self.stdout.write(f"Utilidad FIFO propuesta (recalculables): ${q2(total_fifo)}")
        self.stdout.write(f"Diferencia: ${q2(total_fifo - total_anterior)}")

        for venta_id, motivo in omitidas:
            self.stdout.write(self.style.WARNING(f"Venta #{venta_id} omitida: {motivo}"))

        if not aplicar:
            self.stdout.write(self.style.WARNING("No se modificó la base de datos."))
            return

        with transaction.atomic():
            Venta.objects.bulk_update(
                actualizaciones,
                ["ganancia_total", "ganancia_porcentaje"],
                batch_size=200,
            )
        self.stdout.write(self.style.SUCCESS(f"Ventas actualizadas: {len(actualizaciones)}"))
