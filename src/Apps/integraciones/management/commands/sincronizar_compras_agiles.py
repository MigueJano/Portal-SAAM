from django.core.management.base import BaseCommand, CommandError

from Apps.integraciones.services.mercado_publico import (
    MercadoPublicoError,
    sincronizar_compras_agiles,
)


class Command(BaseCommand):
    help = "Sincroniza Compras Ágiles de Mercado Público usando los filtros activos."

    def handle(self, *args, **options):
        try:
            resultado = sincronizar_compras_agiles()
        except MercadoPublicoError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Sincronización completada: "
                f"{resultado['coincidentes']} coincidencias, "
                f"{resultado['creadas']} nuevas y {resultado['actualizadas']} actualizadas."
            )
        )
