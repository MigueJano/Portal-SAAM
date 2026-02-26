from django.core.management.base import BaseCommand
from Apps.Pedidos.models import Venta, Stock

def obtener_factor_normalizacion(producto, empaque):
    """
    Calcula el factor de normalización de precio por unidad para un producto según el empaque.

    Args:
        producto: Instancia del modelo Producto.
        empaque (str): Tipo de empaque ('PRIMARIO', 'SECUNDARIO', 'TERCIARIO').

    Returns:
        int: Factor de conversión a unidad.
    """
    if empaque == 'SECUNDARIO':
        return producto.qty_secundario or 1
    elif empaque == 'TERCIARIO':
        return (producto.qty_secundario or 1) * (producto.qty_terciario or 1)
    return 1


class Command(BaseCommand):
    help = 'Calcula la ganancia en pesos y porcentaje para todas las ventas existentes'

    def handle(self, *args, **kwargs):
        ventas = Venta.objects.select_related('pedidoid').all()
        total_actualizadas = 0

        for venta in ventas:
            pedido = venta.pedidoid
            despachos = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')

            total_venta = 0
            total_costo = 0

            for item in despachos:
                producto = item.producto
                qty = item.qty
                precio_venta = item.precio_unitario

                # Obtener precio de compra normalizado más alto desde movimientos DISPONIBLES
                disponibles = Stock.objects.filter(producto=producto, tipo_movimiento='DISPONIBLE')
                if not disponibles.exists():
                    continue

                mayor_compra = 0
                for d in disponibles:
                    factor = obtener_factor_normalizacion(producto, d.empaque)
                    normalizado = d.precio_unitario / factor
                    mayor_compra = max(mayor_compra, normalizado)

                total_venta += qty * precio_venta
                total_costo += qty * mayor_compra

            # Calcular y guardar ganancias si hay ventas registradas
            if total_venta > 0:
                ganancia = total_venta - total_costo
                ganancia_pct = (ganancia / total_venta) * 100 if total_venta else 0

                venta.ganancia_total = round(ganancia)
                venta.ganancia_porcentaje = round(ganancia_pct, 2)
                venta.save()
                total_actualizadas += 1

        self.stdout.write(self.style.SUCCESS(f'✅ Ganancias calculadas y guardadas para {total_actualizadas} ventas.'))
        self.stdout.write(self.style.NOTICE(f'📦 Total de ventas procesadas: {ventas.count()}'))
