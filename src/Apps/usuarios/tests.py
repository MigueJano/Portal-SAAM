import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from Apps.usuarios.models import ClonacionBaseDatos
from Apps.usuarios.services import (
    clone_sqlite_database,
    database_environment_paths,
    identify_database_environment,
    read_runtime_database_selection,
    sqlite_db_file_info,
    write_runtime_database_selection,
)


class DatabaseCloneServiceTests(TestCase):
    def test_clone_sqlite_database_crea_destino_y_snapshot(self):
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "origen.db"
            target = tmp_path / "pruebas" / "SAAM.db"
            archive = tmp_path / "clones"

            with sqlite3.connect(source) as conn:
                conn.execute("CREATE TABLE ejemplo (id INTEGER PRIMARY KEY, nombre TEXT)")
                conn.execute("INSERT INTO ejemplo (nombre) VALUES ('registro')")
                conn.commit()

            resultado = clone_sqlite_database(source, target, archive)

            self.assertTrue(Path(resultado["target"]["path"]).exists())
            self.assertTrue(Path(resultado["snapshot"]["path"]).exists())
            self.assertEqual(resultado["target"]["size_bytes"], resultado["snapshot"]["size_bytes"])

            with sqlite3.connect(target) as conn:
                row = conn.execute("SELECT nombre FROM ejemplo").fetchone()
            self.assertEqual(row[0], "registro")

    def test_sqlite_db_file_info_informa_archivo_existente(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "info.db"
            db_path.write_bytes(b"contenido")
            info = sqlite_db_file_info(db_path)

            self.assertTrue(info["exists"])
            self.assertEqual(info["size_bytes"], len(b"contenido"))
            self.assertEqual(info["name"], "info.db")

    def test_runtime_database_selection_persiste_entorno(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            seleccion = write_runtime_database_selection("pruebas", base_dir)
            leida = read_runtime_database_selection(base_dir)
            rutas = database_environment_paths(base_dir)

            self.assertEqual(seleccion["environment"], "pruebas")
            self.assertEqual(leida["environment"], "pruebas")
            self.assertEqual(identify_database_environment(rutas["pruebas"], base_dir), "pruebas")


class ClonarBaseDatosViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("adminclone", password="test123", is_staff=True)

    def _crear_sqlite(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE datos (id INTEGER PRIMARY KEY, valor TEXT)")
            conn.execute("INSERT INTO datos (valor) VALUES ('ok')")
            conn.commit()

    def _override_db_settings(self, base_dir: Path, source: Path):
        previous_base_dir = settings.BASE_DIR
        previous_default = settings.DATABASES["default"].copy()
        settings.BASE_DIR = base_dir
        settings.DATABASES["default"]["ENGINE"] = "django.db.backends.sqlite3"
        settings.DATABASES["default"]["NAME"] = str(source)
        return previous_base_dir, previous_default

    def _restore_db_settings(self, previous_base_dir, previous_default):
        settings.BASE_DIR = previous_base_dir
        settings.DATABASES["default"].clear()
        settings.DATABASES["default"].update(previous_default)

    def test_get_muestra_pantalla_de_clonado(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            source = base_dir / "Database" / "SAAM_activa.db"
            self._crear_sqlite(source)

            self.client.force_login(self.staff)
            previous_base_dir, previous_default = self._override_db_settings(base_dir, source)
            try:
                resp = self.client.get(reverse("clonar_base_datos"))
            finally:
                self._restore_db_settings(previous_base_dir, previous_default)

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Clonar Base de Datos")
            self.assertContains(resp, str(source))
            self.assertContains(resp, "Historial de clonaciones")
            self.assertContains(resp, "DJANGO_DB_NAME=Database/pruebas/SAAM.db")
            self.assertContains(resp, "Usar Producción")
            self.assertContains(resp, "Usar Pruebas")

    def test_post_clona_base_y_registra_historial(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            source = base_dir / "Database" / "SAAM_activa.db"
            self._crear_sqlite(source)

            self.client.force_login(self.staff)
            previous_base_dir, previous_default = self._override_db_settings(base_dir, source)
            try:
                resp = self.client.post(reverse("clonar_base_datos"), follow=True)
            finally:
                self._restore_db_settings(previous_base_dir, previous_default)

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Clonación completada")

            target = base_dir / "Database" / "pruebas" / "SAAM.db"
            self.assertTrue(target.exists())
            self.assertTrue((base_dir / "Database" / "clones").exists())

            registro = ClonacionBaseDatos.objects.get()
            self.assertEqual(registro.usuario, self.staff)
            self.assertEqual(Path(registro.origen_path), source.resolve())
            self.assertEqual(Path(registro.destino_path), target.resolve())
