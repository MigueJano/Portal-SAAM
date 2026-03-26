"""
Configuracion Django para Portal SAAM.
"""

import json
from pathlib import Path
import os
import sys


BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


DB_SELECTION_FILE = BASE_DIR / "Database" / "active_database.json"


def _resolve_db_path(raw_path: str | Path) -> Path:
    db_path = Path(raw_path).expanduser()
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    return db_path.resolve()


def _resolve_db_name(default_name: Path) -> str:
    db_name = os.getenv("DJANGO_DB_NAME")
    if db_name:
        return str(_resolve_db_path(db_name))

    if DB_SELECTION_FILE.exists():
        try:
            data = json.loads(DB_SELECTION_FILE.read_text(encoding="utf-8"))
            selected_path = data.get("path")
            if selected_path:
                return str(_resolve_db_path(selected_path))
        except (OSError, ValueError, TypeError):
            pass

    return str(default_name.resolve())


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-portal-saam")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "Apps.Pedidos.apps.PedidosConfig",
    "Apps.usuarios.apps.UsuariosConfig",
    "Apps.indicadores.apps.IndicadoresConfig",
    "Apps.observaciones.apps.ObservacionesConfig",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "Portal.wsgi.application"
ASGI_APPLICATION = "Portal.asgi.application"


DB_ENGINE = os.getenv("DJANGO_DB_ENGINE", "django.db.backends.sqlite3")

if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": _resolve_db_name(BASE_DIR / "Database" / "SAAM.db"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.getenv("DJANGO_DB_NAME", ""),
            "USER": os.getenv("DJANGO_DB_USER", ""),
            "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", ""),
            "HOST": os.getenv("DJANGO_DB_HOST", ""),
            "PORT": os.getenv("DJANGO_DB_PORT", ""),
        }
    }


AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "src" / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "src" / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/pedidos/inicio/"
LOGOUT_REDIRECT_URL = "/auth/login/"
