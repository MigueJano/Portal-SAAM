from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from Apps.usuarios.services.database_clone import clone_sqlite_database


class SystemUpdateError(RuntimeError):
    pass


@dataclass
class GitStatus:
    available: bool
    branch: str = ""
    current_commit: str = ""
    remote_commit: str = ""
    behind: int = 0
    ahead: int = 0
    dirty: bool = False
    error: str = ""

    @property
    def update_available(self) -> bool:
        return self.available and self.behind > 0 and self.ahead == 0

    @property
    def diverged(self) -> bool:
        return self.available and self.behind > 0 and self.ahead > 0


def _run(command: list[str], timeout: int = 120) -> str:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            command,
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemUpdateError(f"No se pudo ejecutar {' '.join(command)}: {exc}") from exc

    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode != 0:
        raise SystemUpdateError(output or f"El comando {' '.join(command)} finalizo con error.")
    return output


def git_status(fetch: bool = False) -> GitStatus:
    try:
        if fetch:
            _run(["git", "fetch", "--prune", "origin", "main"])
        branch = _run(["git", "branch", "--show-current"])
        current = _run(["git", "rev-parse", "--short", "HEAD"])
        dirty = bool(_run(["git", "status", "--porcelain"]))
        remote = _run(["git", "rev-parse", "--short", "origin/main"])
        counts = _run(["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"])
        ahead, behind = (int(value) for value in counts.split())
        return GitStatus(
            available=True,
            branch=branch,
            current_commit=current,
            remote_commit=remote,
            behind=behind,
            ahead=ahead,
            dirty=dirty,
        )
    except (SystemUpdateError, ValueError) as exc:
        return GitStatus(available=False, error=str(exc))


def apply_system_update() -> dict:
    status = git_status(fetch=True)
    if not status.available:
        raise SystemUpdateError(status.error)
    if status.branch != "main":
        raise SystemUpdateError(f"La rama activa es {status.branch or 'desconocida'}; se requiere main.")
    if status.dirty:
        raise SystemUpdateError("Existen cambios locales. La actualizacion fue cancelada para no sobrescribirlos.")
    if status.diverged or status.ahead:
        raise SystemUpdateError("La rama local contiene cambios no publicados o esta divergida de origin/main.")
    if not status.update_available:
        return {"changed": False, "status": status, "log": "El sistema ya esta actualizado."}

    backup_path = ""
    if connection.vendor == "sqlite":
        source = Path(connection.settings_dict["NAME"]).resolve()
        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        destination = Path(settings.BASE_DIR) / "Respaldos" / "actualizaciones" / f"{source.stem}_{timestamp}{source.suffix}"
        try:
            clone_sqlite_database(source, destination)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise SystemUpdateError(f"No se pudo respaldar la base activa: {exc}") from exc
        backup_path = str(destination)

    log_parts = []
    log_parts.append(_run(["git", "merge", "--ff-only", "origin/main"]))
    log_parts.append(_run([sys.executable, "manage.py", "migrate", "--noinput"], timeout=300))
    log_parts.append(_run([sys.executable, "manage.py", "collectstatic", "--noinput"], timeout=300))
    log_parts.append(_run([sys.executable, "manage.py", "check"], timeout=180))
    final_status = git_status(fetch=False)
    return {
        "changed": True,
        "status": final_status,
        "previous_commit": status.current_commit,
        "backup_path": backup_path,
        "log": "\n\n".join(part for part in log_parts if part),
    }
