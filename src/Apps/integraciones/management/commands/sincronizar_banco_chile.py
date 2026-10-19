import json
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from Apps.integraciones.services.banco_chile import consultar_movimientos, guardar_resultado


class Command(BaseCommand):
    help = "Importa movimientos de Banco de Chile (API o archivo JSON de homologación)."

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="Fecha inicial YYYY-MM-DD")
        parser.add_argument("--hasta", help="Fecha final YYYY-MM-DD")
        parser.add_argument("--archivo-json", help="Archivo de respuesta para pruebas/homologación")

    def handle(self, *args, **options):
        try:
            if options["archivo_json"]:
                respuesta = json.loads(Path(options["archivo_json"]).read_text(encoding="utf-8"))
                if isinstance(respuesta, list):
                    respuesta = {"movimientos": respuesta}
            else:
                hasta = date.fromisoformat(options["hasta"]) if options["hasta"] else date.today()
                desde = date.fromisoformat(options["desde"]) if options["desde"] else hasta - timedelta(days=7)
                respuesta = consultar_movimientos(desde, hasta)
            if options["archivo_json"]:
                hasta = date.fromisoformat(options["hasta"]) if options["hasta"] else date.today()
                desde = date.fromisoformat(options["desde"]) if options["desde"] else hasta - timedelta(days=7)
            if not isinstance(respuesta, dict) or not isinstance(respuesta.get("movimientos"), list):
                raise ValueError("El origen no contiene una respuesta bancaria con movimientos.")
            creados, existentes, saldo, saldo_creado = guardar_resultado(
                respuesta, desde=desde, hasta=hasta
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Movimientos nuevos: {creados}; ya existentes: {existentes}; "
            f"saldo {'registrado' if saldo_creado else 'ya existente'}: ${saldo.saldo_disponible}."
        ))

