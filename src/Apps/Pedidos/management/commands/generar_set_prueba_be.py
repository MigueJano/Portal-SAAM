from __future__ import annotations

from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from Apps.Pedidos.models import ConfiguracionBoletaSii
from Apps.Pedidos.services import generar_archivos_set_boleta


class Command(BaseCommand):
    help = "Genera XMLs base para el set de prueba de boleta electronica del SII."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, help="Ruta del TXT del set de prueba BE descargado desde SII.")
        parser.add_argument(
            "--output",
            default=".codex-runtime/sii_set_pruebas/boletas",
            help="Carpeta destino para los XMLs generados.",
        )
        parser.add_argument("--config-id", type=int, help="ID de Configuracion SII DTE. Si se omite, usa la activa.")
        parser.add_argument("--folio-inicial", type=int, default=1, help="Primer folio de certificacion a usar.")
        parser.add_argument("--fecha-emision", help="Fecha de emision YYYY-MM-DD. Si se omite, usa la fecha local.")
        parser.add_argument(
            "--rut-envia",
            help="RUT del firmante/enviante del sobre y RCOF. Si se omite, usa el RUT emisor.",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        if not input_path.exists():
            raise CommandError(f"No existe el archivo de entrada: {input_path}")

        folio_inicial = options["folio_inicial"]
        if folio_inicial <= 0:
            raise CommandError("--folio-inicial debe ser mayor a cero.")

        config = self._configuracion(options.get("config_id"))
        if not config.habilita_boleta:
            raise CommandError("La configuracion SII seleccionada no tiene habilitada la boleta electronica.")
        if not config.ruta_caf_tipo_39:
            raise CommandError("La configuracion SII seleccionada no tiene CAF tipo 39 informado.")
        if not config.resolucion_numero or not config.resolucion_fecha:
            raise CommandError("La configuracion SII debe tener numero y fecha de resolucion para generar sobre/RCOF.")

        fecha_emision = self._fecha(options.get("fecha_emision"))
        summary = generar_archivos_set_boleta(
            input_path=input_path,
            output_dir=options["output"],
            config=config,
            folio_inicial=folio_inicial,
            fecha_emision=fecha_emision,
            rut_envia=options.get("rut_envia"),
        )

        self.stdout.write(self.style.SUCCESS(f"XMLs generados: {len(summary['folios'])}"))
        self.stdout.write(f"Destino: {summary['output_dir']}")
        self.stdout.write(f"Sobre unico: {summary['sobre']}")
        self.stdout.write(f"RCOF/RDV: {summary['rcof']}")
        for row in summary["folios"]:
            self.stdout.write(
                f"{row['caso']} | folio {row['folio']} | total {row['monto_total']} | {row['archivo']}"
            )

    def _configuracion(self, config_id: int | None) -> ConfiguracionBoletaSii:
        if config_id:
            config = ConfiguracionBoletaSii.objects.filter(pk=config_id).first()
            if not config:
                raise CommandError(f"No existe Configuracion SII DTE id={config_id}.")
            return config

        config = ConfiguracionBoletaSii.objects.filter(activa=True).order_by("id").first()
        if not config:
            raise CommandError("No existe una Configuracion SII DTE activa.")
        return config

    def _fecha(self, value: str | None) -> date:
        if not value:
            return timezone.localdate()
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError("--fecha-emision debe tener formato YYYY-MM-DD.") from exc
