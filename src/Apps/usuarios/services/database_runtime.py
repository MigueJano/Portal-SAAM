from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone


DB_ENVIRONMENTS = {
    "produccion": "Database/SAAM.db",
    "pruebas": "Database/pruebas/SAAM.db",
}


def runtime_selection_file(base_dir: Path | None = None) -> Path:
    base_dir = Path(base_dir or settings.BASE_DIR).resolve()
    return base_dir / "Database" / "active_database.json"


def database_environment_paths(base_dir: Path | None = None) -> dict[str, Path]:
    base_dir = Path(base_dir or settings.BASE_DIR).resolve()
    return {key: (base_dir / rel_path).resolve() for key, rel_path in DB_ENVIRONMENTS.items()}


def identify_database_environment(db_path: Path | str, base_dir: Path | None = None) -> str:
    db_path = Path(db_path).expanduser().resolve()
    for environment, path in database_environment_paths(base_dir).items():
        if db_path == path:
            return environment
    return "personalizado"


def read_runtime_database_selection(base_dir: Path | None = None) -> dict:
    base_dir = Path(base_dir or settings.BASE_DIR).resolve()
    selection_file = runtime_selection_file(base_dir)
    default_path = DB_ENVIRONMENTS["produccion"]

    if not selection_file.exists():
        return {"environment": "produccion", "path": default_path, "updated_at": None}

    try:
        data = json.loads(selection_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"environment": "produccion", "path": default_path, "updated_at": None}

    environment = data.get("environment") or "produccion"
    rel_path = data.get("path") or DB_ENVIRONMENTS.get(environment, default_path)
    return {
        "environment": environment,
        "path": rel_path,
        "updated_at": data.get("updated_at"),
    }


def write_runtime_database_selection(environment: str, base_dir: Path | None = None) -> dict:
    base_dir = Path(base_dir or settings.BASE_DIR).resolve()
    if environment not in DB_ENVIRONMENTS:
        raise ValueError(f"Entorno inválido: {environment}")

    selection_file = runtime_selection_file(base_dir)
    selection_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environment": environment,
        "path": DB_ENVIRONMENTS[environment],
        "updated_at": timezone.localtime().isoformat(),
    }
    selection_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def env_override_active() -> bool:
    return bool(os.getenv("DJANGO_DB_NAME"))


def switch_current_process_database(db_path: Path | str) -> Path:
    db_path = Path(db_path).expanduser().resolve()
    settings.DATABASES["default"]["NAME"] = str(db_path)
    connections.databases["default"]["NAME"] = str(db_path)
    default_conn = connections["default"]
    default_conn.close()
    default_conn.settings_dict["NAME"] = str(db_path)
    return db_path
