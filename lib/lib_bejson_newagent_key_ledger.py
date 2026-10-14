"""
Library:        lib_bejson_newagent_key_ledger.py
Family:         NewAgent
Description:    Hash-based API key identity, flag handling, a persistent key
                ledger (remembers leaked/bad keys forever, even after they
                are removed from keys.bejson or the env file), and per-key
                usage/failure tracking. Nothing in this module ever stores or
                logs raw key material -- every record is keyed by the full
                SHA-256 hex digest of the key text.

                Files (all BEJSON 104a, all next to keys.bejson in config/):
                  key_ledger.bejson -- one row per key hash ever seen. Rows are
                                       NEVER deleted. Flags like "leaked" or
                                       "bad" here block the key everywhere.
                  key_usage.bejson  -- one row per key hash: success/failure
                                       counters by category + last status,
                                       last error reason, last-used times.

                Flags are a comma-separated string, case-insensitive, e.g.
                "paid", "paid,primary", "leaked". BLOCKING_FLAGS can never be
                used for rotation regardless of what a program asks for.
Version:        1.0.0
Date:           2026-10-10
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  6d1f0a94-2c7b-4e58-b3a1-9e04c7d2f816

CHANGELOG:
- 1.0.0 (2026-10-10): Initial creation. Extracted from the KeyRegistry
  rework requested by Elton: flag field (paid/bad/leaked), uuid, slot,
  full-hash identity, usage tracking, persistent leak memory.
"""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

KEY_LEDGER_FILENAME = "key_ledger.bejson"
KEY_USAGE_FILENAME = "key_usage.bejson"

# Flags that permanently pull a key out of rotation. A program asking for
# required_flags={"paid"} still never receives a key that is also "leaked".
BLOCKING_FLAGS = frozenset({"leaked", "bad", "revoked"})

# Display length for a hash prefix in logs / UI. Matches the 12-char hashes
# already stored by the earlier partial refactor, so old references still match.
KEY_HASH_DISPLAY_LEN = 12

# ── Schemas (registry for this module's two entities) ───────────────────────

KEY_LEDGER_FIELDS = [
    {"name": "ledger_key_hash", "type": "string"},
    {"name": "ledger_key_uuid_fk", "type": "string"},
    {"name": "ledger_label", "type": "string"},
    {"name": "ledger_flags", "type": "string"},
    {"name": "ledger_note", "type": "string"},
    {"name": "ledger_created_at", "type": "string"},
    {"name": "ledger_last_seen_at", "type": "string"},
    {"name": "ledger_flagged_at", "type": "string"},
]

KEY_USAGE_FIELDS = [
    {"name": "usage_key_hash", "type": "string"},
    {"name": "usage_key_uuid_fk", "type": "string"},
    {"name": "usage_label", "type": "string"},
    {"name": "usage_success_count", "type": "integer"},
    {"name": "usage_failure_count", "type": "integer"},
    {"name": "usage_rate_limit_count", "type": "integer"},
    {"name": "usage_auth_error_count", "type": "integer"},
    {"name": "usage_server_error_count", "type": "integer"},
    {"name": "usage_other_error_count", "type": "integer"},
    {"name": "usage_last_status", "type": "string"},
    {"name": "usage_last_error", "type": "string"},
    {"name": "usage_last_used_at", "type": "string"},
    {"name": "usage_last_success_at", "type": "string"},
    {"name": "usage_last_failure_at", "type": "string"},
    {"name": "usage_created_at", "type": "string"},
]

_LEDGER_FIELD_NAMES = [f["name"] for f in KEY_LEDGER_FIELDS]
_USAGE_FIELD_NAMES = [f["name"] for f in KEY_USAGE_FIELDS]
_USAGE_COUNTER_FIELDS = {
    "rate_limit": "usage_rate_limit_count",
    "auth": "usage_auth_error_count",
    "server": "usage_server_error_count",
    "other": "usage_other_error_count",
}
_MAX_ERROR_CHARS = 300


# ── Small pure helpers ──────────────────────────────────────────────────────

def key_ledger_hash_key(api_key: str) -> str:
    """Full SHA-256 hex digest of the stripped key text."""
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()


def key_ledger_short_hash(key_hash: str) -> str:
    return (key_hash or "")[:KEY_HASH_DISPLAY_LEN] or "????????????"


def key_ledger_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_ledger_parse_flags(raw: object) -> set[str]:
    """'paid, Leaked' -> {'paid', 'leaked'}. None/'' -> empty set."""
    if not isinstance(raw, str):
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def key_ledger_format_flags(flags: Iterable[str]) -> str:
    return ",".join(sorted({f.strip().lower() for f in flags if f and f.strip()}))


def key_ledger_is_blocked_flags(flags: Iterable[str]) -> bool:
    return bool(set(flags) & BLOCKING_FLAGS)


def key_ledger_classify_status(status: Optional[int]) -> str:
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    if status is not None and 500 <= status < 600:
        return "server"
    return "other"


# ── Generic 104a table helper ───────────────────────────────────────────────

class _HashKeyedTable:
    """Loads/saves a 104a file whose rows are keyed by its first *_key_hash
    field. Field Map Cache based -- tolerant of older files missing trailing
    fields (they are appended + defaulted on next save)."""

    def __init__(self, path: Path, record_type: str, fields: list[dict], key_field: str) -> None:
        self.path = Path(path)
        self.record_type = record_type
        self.fields = fields
        self.field_names = [f["name"] for f in fields]
        self.key_field = key_field
        self.rows: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        doc = bejson_core_load_file(str(self.path))
        if not isinstance(doc, dict):
            logger.error("[KeyLedger] Could not load %s -- starting empty in memory (file left untouched until next write)", self.path)
            return
        fmap = bejson_core_get_field_map(doc)
        if self.key_field not in fmap:
            logger.error("[KeyLedger] %s has no %s field -- ignoring", self.path, self.key_field)
            return
        for raw_row in doc.get("Values", []):
            record = {}
            for name in self.field_names:
                idx = fmap.get(name)
                value = raw_row[idx] if idx is not None and idx < len(raw_row) else None
                if isinstance(value, str):
                    value = value.strip()  # boundary-layer sanitization
                record[name] = value
            row_key = record.get(self.key_field)
            if row_key:
                self.rows[row_key] = record

    def save(self) -> bool:
        values = [[rec.get(name) for name in self.field_names] for rec in self.rows.values()]
        doc = bejson_core_create_104a(self.record_type, list(self.fields), values)
        ok = bejson_core_atomic_write(str(self.path), doc)
        if not ok:
            logger.error("[KeyLedger] Atomic write failed for %s", self.path)
        return ok


# ── Ledger ──────────────────────────────────────────────────────────────────

class KeyLedger:
    """Permanent memory of every key hash ever seen. Rows are never removed.
    A hash flagged leaked/bad/revoked here is blocked from rotation and from
    env re-sync forever (until explicitly unflagged)."""

    def __init__(self, config_dir: Path) -> None:
        self._table = _HashKeyedTable(
            Path(config_dir) / KEY_LEDGER_FILENAME, "KeyLedgerEntry",
            KEY_LEDGER_FIELDS, "ledger_key_hash",
        )

    @property
    def path(self) -> Path:
        return self._table.path

    def entries(self) -> list[dict]:
        return list(self._table.rows.values())

    def get(self, key_hash: str) -> Optional[dict]:
        return self._table.rows.get(key_hash)

    def flags_for(self, key_hash: str) -> set[str]:
        entry = self.get(key_hash)
        return key_ledger_parse_flags(entry.get("ledger_flags")) if entry else set()

    def is_blocked(self, key_hash: str) -> bool:
        return key_ledger_is_blocked_flags(self.flags_for(key_hash))

    def find_by_prefix(self, prefix: str) -> list[dict]:
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return []
        return [e for h, e in self._table.rows.items() if h.startswith(prefix)]

    def observe(self, key_hash: str, key_uuid: str = "", label: str = "",
                flags: Iterable[str] = (), save: bool = True) -> bool:
        """Record that a key hash exists right now. Merges (never drops)
        flags. Returns True if anything changed."""
        now = key_ledger_now_iso()
        entry = self._table.rows.get(key_hash)
        changed = False
        if entry is None:
            entry = {name: "" for name in _LEDGER_FIELD_NAMES}
            entry.update({
                "ledger_key_hash": key_hash,
                "ledger_created_at": now,
            })
            self._table.rows[key_hash] = entry
            changed = True
        merged_flags = key_ledger_parse_flags(entry.get("ledger_flags")) | set(flags)
        merged_text = key_ledger_format_flags(merged_flags)
        if merged_text != (entry.get("ledger_flags") or ""):
            entry["ledger_flags"] = merged_text
            entry["ledger_flagged_at"] = now
            changed = True
        if key_uuid and not entry.get("ledger_key_uuid_fk"):
            entry["ledger_key_uuid_fk"] = key_uuid
            changed = True
        if label and entry.get("ledger_label") != label:
            entry["ledger_label"] = label
            changed = True
        # last_seen only bumps once per day to avoid rewriting on every boot
        if (entry.get("ledger_last_seen_at") or "")[:10] != now[:10]:
            entry["ledger_last_seen_at"] = now
            changed = True
        if changed and save:
            self._table.save()
        return changed

    def set_flags(self, key_hash: str, flags: Iterable[str], note: str = "") -> None:
        """Replace the flag set for a hash (creating the ledger row if
        needed) and optionally append a note."""
        self.observe(key_hash, save=False)
        entry = self._table.rows[key_hash]
        entry["ledger_flags"] = key_ledger_format_flags(flags)
        entry["ledger_flagged_at"] = key_ledger_now_iso()
        if note:
            stamp = f"[{key_ledger_now_iso()}] {note.strip()}"
            entry["ledger_note"] = f"{entry['ledger_note']} | {stamp}" if entry.get("ledger_note") else stamp
        self._table.save()

    def save(self) -> bool:
        return self._table.save()


# ── Usage tracker ───────────────────────────────────────────────────────────

class KeyUsageTracker:
    """Per-hash success/failure counters + last failure reason, so you can
    see which key is failing and why without ever storing the key itself."""

    def __init__(self, config_dir: Path) -> None:
        self._table = _HashKeyedTable(
            Path(config_dir) / KEY_USAGE_FILENAME, "KeyUsage",
            KEY_USAGE_FIELDS, "usage_key_hash",
        )

    @property
    def path(self) -> Path:
        return self._table.path

    def get(self, key_hash: str) -> Optional[dict]:
        return self._table.rows.get(key_hash)

    def entries(self) -> list[dict]:
        return list(self._table.rows.values())

    def _ensure(self, key_hash: str, key_uuid: str, label: str) -> dict:
        entry = self._table.rows.get(key_hash)
        if entry is None:
            entry = {name: None for name in _USAGE_FIELD_NAMES}
            for name in _USAGE_FIELD_NAMES:
                if name.endswith("_count"):
                    entry[name] = 0
            entry["usage_key_hash"] = key_hash
            entry["usage_created_at"] = key_ledger_now_iso()
            self._table.rows[key_hash] = entry
        for name in _USAGE_FIELD_NAMES:
            if name.endswith("_count") and not isinstance(entry.get(name), int):
                entry[name] = 0
        if key_uuid:
            entry["usage_key_uuid_fk"] = key_uuid
        if label:
            entry["usage_label"] = label
        return entry

    def record_success(self, key_hash: str, key_uuid: str = "", label: str = "") -> None:
        now = key_ledger_now_iso()
        entry = self._ensure(key_hash, key_uuid, label)
        entry["usage_success_count"] += 1
        entry["usage_last_status"] = "ok"
        entry["usage_last_used_at"] = now
        entry["usage_last_success_at"] = now
        self._table.save()

    def record_failure(self, key_hash: str, status: Optional[int], reason: str = "",
                       key_uuid: str = "", label: str = "") -> None:
        now = key_ledger_now_iso()
        entry = self._ensure(key_hash, key_uuid, label)
        category = key_ledger_classify_status(status)
        entry["usage_failure_count"] += 1
        entry[_USAGE_COUNTER_FIELDS[category]] += 1
        entry["usage_last_status"] = str(status) if status is not None else category
        entry["usage_last_error"] = (reason or "")[:_MAX_ERROR_CHARS]
        entry["usage_last_used_at"] = now
        entry["usage_last_failure_at"] = now
        self._table.save()
