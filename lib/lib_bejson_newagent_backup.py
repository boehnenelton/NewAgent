"""
Library:        lib_bejson_newagent_backup.py
Family:         NewAgent
Description:    24-hour TTL file backup, snapshot log, and restore recovery.
                Backup log I/O routed through the canonical Core BEJSON library
                (atomic write + validation); row access uses field-map lookups
                instead of positional literals.
Version:        1.1.0
Date:           2026-07-16
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  a3d6c9f1-7e42-4b58-9a01-d4f8c2e6b753
"""

import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson

VERSION = "1.1.0"
BACKUP_TTL_HOURS = 24
_log_path: Optional[Path] = None

_BACKUP_FIELDS = [
    {"name": "backup_id", "type": "string"},
    {"name": "file_path", "type": "string"},
    {"name": "content", "type": "string"},
    {"name": "created_at", "type": "number"},
    {"name": "expires_at", "type": "number"},
    {"name": "label", "type": "string"},
]

# Field-map derived once from the canonical field order above, rather than
# scattering positional literals (row[1], row[4], ...) through consumers.
_IDX = {f["name"]: i for i, f in enumerate(_BACKUP_FIELDS)}


def init_backup(backups_dir: Path) -> None:
    global _log_path
    backups_dir.mkdir(parents=True, exist_ok=True)
    _log_path = backups_dir / "backup_log.bejson"
    if not _log_path.exists():
        _write_log([])


def _read_log() -> list[list]:
    if not _log_path or not _log_path.exists():
        return []
    doc = bejson_core_load_file(str(_log_path))
    if not isinstance(doc, dict):
        return []
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        import logging
        logging.getLogger(__name__).warning(
            "[Backup] %s failed structural validation: %s", _log_path, result.errors
        )
    fmap = bejson_core_get_field_map(doc)
    expires_idx = fmap.get("expires_at", 4)
    rows = doc.get("Values", [])
    now = time.time()
    live = [r for r in rows if len(r) > expires_idx and float(r[expires_idx]) > now]
    if len(live) != len(rows):
        _write_log(live)
    return live


def _write_log(rows: list[list]) -> None:
    if not _log_path:
        return
    doc = bejson_core_create_104a(
        "Backup",
        list(_BACKUP_FIELDS),
        rows,
        TTL_Hours=BACKUP_TTL_HOURS,
    )
    if not bejson_core_atomic_write(str(_log_path), doc):
        import logging
        logging.getLogger(__name__).error("[Backup] Atomic write failed for %s", _log_path)


def record_backup(file_path: str, content: str, label: str = "auto") -> str:
    now = time.time()
    bid = str(uuid.uuid4())[:8]
    rows = _read_log()
    row = [None] * len(_BACKUP_FIELDS)
    row[_IDX["backup_id"]] = bid
    row[_IDX["file_path"]] = file_path
    row[_IDX["content"]] = content
    row[_IDX["created_at"]] = now
    row[_IDX["expires_at"]] = now + BACKUP_TTL_HOURS * 3600
    row[_IDX["label"]] = label
    rows.append(row)
    _write_log(rows)
    return bid


def list_backups(path_filter: Optional[str] = None) -> list[dict]:
    rows = _read_log()
    out = []
    for r in rows:
        if path_filter and r[_IDX["file_path"]] != path_filter:
            continue
        out.append({
            "backup_id": r[_IDX["backup_id"]],
            "file_path": r[_IDX["file_path"]],
            "created_at": r[_IDX["created_at"]],
            "expires_at": r[_IDX["expires_at"]],
            "label": r[_IDX["label"]] if len(r) > _IDX["label"] else "auto",
            "size": len(r[_IDX["content"]]),
        })
    return out


def restore_backup(backup_id: str, skip_snapshot: bool = False) -> tuple[bool, str]:
    rows = _read_log()
    target = next((r for r in rows if r[_IDX["backup_id"]] == backup_id), None)
    if not target:
        return False, f"Backup {backup_id} not found or expired."

    file_path = Path(target[_IDX["file_path"]])
    content = target[_IDX["content"]]

    if not skip_snapshot and file_path.exists():
        try:
            old = file_path.read_text("utf-8", errors="replace")
            record_backup(str(file_path), old, label="pre_restore_snapshot")
        except Exception:
            pass

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, file_path)
        return True, f"Restored {file_path} from backup {backup_id}."
    except Exception as exc:
        return False, f"Restore failed: {exc}"


def get_live_backup_ids() -> list[str]:
    return [r[_IDX["backup_id"]] for r in _read_log()]
