from django.core.management.base import BaseCommand
from Apps.Pedidos.models import Producto, Stock, UtilidadProducto, Pedido
from Apps.Pedidos.views.pedido import calcular_precio_maximo_normalizado

class Command(BaseCommand):
    help = "Llena la tabla UtilidadProducto con datos históricos de ventas finalizadas."

    def handle(self, *args, **kwargs):
        pedidos_finalizados = Pedido.objects.filter(estado_pedido='Finalizado')
        total_insertados = 0
        total_saltados = 0

        for pedido in pedidos_finalizados:
            reservas = Stock.objects.filter(pedido=pedido, tipo_movimiento='DESPACHO')

            for r in reservas:
                producto = r.producto
                empaque = r.empaque
                qty = r.qty
                precio_venta = r.precio_unitario

                if precio_venta is None:
                    print(f"⚠️ Saltado: {producto} sin precio_unitario en pedido {pedido.id}")
                    total_saltados += 1
                    continue

                if empaque == 'SECUNDARIO':
                    factor = producto.qty_secundario or 1
                elif empaque == 'TERCIARIO':
                    factor = (producto.qty_secundario or 1) * (producto.qty_terciario or 1)
                else:
                    factor = 1

                if factor == 0:
                    print(f"⚠️ Saltado: {producto} con factor 0 en empaque {empaque}")
                    total_saltados += 1
                    continue

                precio_venta_unit = precio_venta / factor
                precio_compra_unit = calcular_precio_maximo_normalizado(producto.id)

                utilidad = (precio_venta_unit - precio_compra_unit) * qty * factor
                utilidad_pct = ((precio_venta_unit - precio_compra_unit) / precio_compra_unit) * 100 if precio_compra_unit else 0

                print(f"🧾 Producto: {producto.nombre_producto} | Empaque: {empaque} | Venta Unit: {precio_venta_unit:.2f} | Compra Unit: {precio_compra_unit:.2f} | Qty: {qty} | Utilidad: {utilidad:.2f} ({utilidad_pct:.2f}%)")

                # Verificamos si ya existe un registro idéntico (opcional)
                UtilidadProducto.objects.create(
                    producto=producto,
                    empaque=empaque,
                    precio_compra_unitario=round(precio_compra_unit, 2),
                    precio_venta_unitario=round(precio_venta_unit, 2),
                    utilidad=round(utilidad, 2),
                    utilidad_porcentaje=round(utilidad_pct, 2),
                    fecha=r.fecha_movimiento
                )
                total_insertados += 1
                print("✅ Insertado\n")

        print(f"✔️ Se insertaron {total_insertados} registros en UtilidadProducto.")
        print(f"⛔ Se saltaron {total_saltados} registros por errores o datos faltantes.")
