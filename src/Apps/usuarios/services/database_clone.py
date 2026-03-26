from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.utils import timezone


def sqlite_db_file_info(path: Path) -> dict:
    path = Path(path).expanduser().resolve()
    exists = path.exists()
    info = {
        "path": str(path),
        "name": path.name,
        "exists": exists,
        "size_bytes": 0,
        "updated_at": None,
    }
    if not exists:
        return info

    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
    info["size_bytes"] = stat.st_size
    info["updated_at"] = updated_at
    return info


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    source_uri = f"{source.as_uri()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_conn:
        with sqlite3.connect(destination) as target_conn:
            source_conn.backup(target_conn)


def clone_sqlite_database(source: Path, target: Path, archive_dir: Path | None = None) -> dict:
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser().resolve()

    if not source.exists():
        raise FileNotFoundError(f"No existe la base origen: {source}")

    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    snapshot_path = None
    if archive_dir:
        archive_dir = Path(archive_dir).expanduser().resolve()
        snapshot_path = archive_dir / f"{target.stem}_{timestamp}{target.suffix}"
        _backup_sqlite(source, snapshot_path)

    if source != target:
        if snapshot_path:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot_path, target)
        else:
            _backup_sqlite(source, target)
    elif snapshot_path:
        target = source

    return {
        "source": sqlite_db_file_info(source),
        "target": sqlite_db_file_info(target),
        "snapshot": sqlite_db_file_info(snapshot_path) if snapshot_path else None,
    }
