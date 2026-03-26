from pathlib import Path
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Clona una base SQLite a otra ruta para preparar ambientes de pruebas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default=None,
            help="Ruta origen del archivo .db. Si no se indica, usa la base configurada actualmente.",
        )
        parser.add_argument(
            "--target",
            type=str,
            default="Database/pruebas/SAAM.db",
            help="Ruta destino del archivo de pruebas.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Sobrescribe el archivo destino si ya existe.",
        )

    def _resolve_path(self, raw_path: str | None) -> Path:
        if not raw_path:
            return Path(settings.DATABASES["default"]["NAME"]).expanduser().resolve()

        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path.resolve()

    def handle(self, *args, **options):
        db_engine = settings.DATABASES["default"]["ENGINE"]
        if options["source"] is None and db_engine != "django.db.backends.sqlite3":
            raise CommandError("Debes indicar --source cuando la base configurada no es SQLite.")

        source = self._resolve_path(options["source"])
        target = self._resolve_path(options["target"])

        if not source.exists():
            raise CommandError(f"No existe la base origen: {source}")
        if source == target:
            raise CommandError("La ruta origen y destino no pueden ser la misma.")
        if target.exists() and not options["overwrite"]:
            raise CommandError(f"El destino ya existe: {target}. Usa --overwrite para reemplazarlo.")

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

        self.stdout.write(self.style.SUCCESS("Base de pruebas clonada correctamente."))
        self.stdout.write(f"Origen : {source}")
        self.stdout.write(f"Destino: {target}")
        self.stdout.write("")
        self.stdout.write("Para usarla temporalmente en este proyecto:")
        self.stdout.write(f"DJANGO_DB_NAME='{target}' python3 manage.py runserver")
