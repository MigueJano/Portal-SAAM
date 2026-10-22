"""
Configuracion Django para Portal SAAM.
"""

import json
from pathlib import Path
import os
import sys

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _load_local_env(path: Path) -> None:
    """Carga un .env local sencillo sin reemplazar variables del servidor."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_local_env(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


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


DEBUG = _env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY es obligatoria en todos los ambientes.")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
    else:
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS es obligatoria cuando DJANGO_DEBUG esta desactivado."
        )


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
    "Apps.administracion.apps.AdministracionConfig",
    "Apps.integraciones.apps.IntegracionesConfig",
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
        "DIRS": [BASE_DIR / "src" / "templates"],
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


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

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


# Integraciones externas. Las credenciales se leen exclusivamente desde el
# entorno y nunca se guardan en Git ni en la base de datos.
EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_SMTP_USE_TLS", "1") == "1"
EMAIL_HOST_USER = os.getenv("EMAIL_SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "portal-saam@localhost")

EMAIL_IMAP_HOST = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
EMAIL_IMAP_PORT = int(os.getenv("EMAIL_IMAP_PORT", "993"))
EMAIL_IMAP_USER = os.getenv("EMAIL_IMAP_USER", EMAIL_HOST_USER)
EMAIL_IMAP_PASSWORD = os.getenv("EMAIL_IMAP_PASSWORD", EMAIL_HOST_PASSWORD)
EMAIL_IMAP_FOLDER = os.getenv("EMAIL_IMAP_FOLDER", "INBOX")

BANCO_CHILE_MOVIMIENTOS_URL = os.getenv("BANCO_CHILE_MOVIMIENTOS_URL", "")
BANCO_CHILE_AMBIENTE = os.getenv("BANCO_CHILE_AMBIENTE", "").strip().lower()
BANCO_CHILE_CLIENT_ID = os.getenv("BANCO_CHILE_CLIENT_ID", "")
BANCO_CHILE_CLIENT_SECRET = os.getenv("BANCO_CHILE_CLIENT_SECRET", "")
BANCO_CHILE_BEARER_TOKEN = os.getenv("BANCO_CHILE_BEARER_TOKEN", "")
BANCO_CHILE_TOKEN_URL = os.getenv(
    "BANCO_CHILE_TOKEN_URL",
    "https://apistore.bancochile.auth0app.com/oauth/token",
)
BANCO_CHILE_PRIVATE_KEY_PATH = os.getenv("BANCO_CHILE_PRIVATE_KEY_PATH", "")
BANCO_CHILE_PRIVATE_KEY_ID = os.getenv("BANCO_CHILE_PRIVATE_KEY_ID", "")
BANCO_CHILE_AUTH0_ASSERTION_AUDIENCE = os.getenv(
    "BANCO_CHILE_AUTH0_ASSERTION_AUDIENCE",
    "https://apistore.bancochile.auth0app.com/",
)
BANCO_CHILE_API_AUDIENCE = os.getenv("BANCO_CHILE_API_AUDIENCE", "https://openbanking/")
BANCO_CHILE_TIMEOUT = int(os.getenv("BANCO_CHILE_TIMEOUT", "35"))
BANCO_CHILE_RUT_ORIGEN = os.getenv("BANCO_CHILE_RUT_ORIGEN", "")
BANCO_CHILE_PRODUCTO_CUENTA = os.getenv("BANCO_CHILE_PRODUCTO_CUENTA", "CTD")
BANCO_CHILE_CUENTA = os.getenv("BANCO_CHILE_CUENTA", "")
BANCO_CHILE_RUT_APODERADO = os.getenv("BANCO_CHILE_RUT_APODERADO", "")

MERCADO_PUBLICO_API_URL = os.getenv("MERCADO_PUBLICO_API_URL", "https://api2.mercadopublico.cl")
MERCADO_PUBLICO_TICKET = os.getenv("MERCADO_PUBLICO_TICKET", "")
MERCADO_PUBLICO_TIMEOUT = int(os.getenv("MERCADO_PUBLICO_TIMEOUT", "30"))
