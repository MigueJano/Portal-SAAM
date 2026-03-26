from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from Apps.indicadores.services.contabilidad import (
    COMPRAS_FIELDS,
    STOCK_FIELDS,
    VENTAS_FIELDS,
    csv_bytes,
    filas_libro_compras,
    filas_libro_ventas,
    filas_stock_contable,
    normalizar_periodo,
    obtener_compras_periodo,
    obtener_ventas_periodo,
    zip_libros_bytes,
)


class Command(BaseCommand):
    help = "Exporta libros electronicos Pro Pyme (ventas, compras, inventario) a CSV y ZIP."

    def add_arguments(self, parser):
        hoy = timezone.localdate()
        parser.add_argument("--year", type=int, default=hoy.year, help="Año del periodo contable.")
        parser.add_argument("--month", type=int, default=hoy.month, help="Mes del periodo contable (1-12).")
        parser.add_argument(
            "--output-dir",
            type=str,
            default="logs/contabilidad",
            help="Directorio destino para archivos exportados.",
        )

    def handle(self, *args, **options):
        periodo = normalizar_periodo(options["year"], options["month"], hoy=timezone.localdate())
        output_dir = Path(options["output_dir"]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        ventas_rows = filas_libro_ventas(periodo, obtener_ventas_periodo(periodo))
        compras_rows = filas_libro_compras(periodo, obtener_compras_periodo(periodo))
        stock_rows = filas_stock_contable(periodo)

        sufijo = f"{periodo.year:04d}{periodo.month:02d}"
        f_ventas = output_dir / f"libro_ventas_propyme_{sufijo}.csv"
        f_compras = output_dir / f"libro_compras_propyme_{sufijo}.csv"
        f_stock = output_dir / f"inventario_propyme_{sufijo}.csv"
        f_zip = output_dir / f"libros_propyme_{sufijo}.zip"

        f_ventas.write_bytes(csv_bytes(VENTAS_FIELDS, ventas_rows))
        f_compras.write_bytes(csv_bytes(COMPRAS_FIELDS, compras_rows))
        f_stock.write_bytes(csv_bytes(STOCK_FIELDS, stock_rows))
        f_zip.write_bytes(zip_libros_bytes(periodo, ventas_rows, compras_rows, stock_rows))

        self.stdout.write(self.style.SUCCESS("Exportacion Pro Pyme completada:"))
        self.stdout.write(f"- {f_ventas}")
        self.stdout.write(f"- {f_compras}")
        self.stdout.write(f"- {f_stock}")
        self.stdout.write(f"- {f_zip}")
