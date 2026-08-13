"""
Library:        lib_bejson_newagent_input.py
Family:         NewAgent
Description:    Unified input dispatching: typed, speech-to-text, and dialogue snippet selection.
Version:        1.1.1
Date:           2026-07-16
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  96280d1c-8033-45e7-be09-133c89b16c99
"""

import json
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson

VERSION = "1.1.1"

_SNIPPET_FIELDS = [
    {"name": "snippet_id", "type": "string"},
    {"name": "label", "type": "string"},
    {"name": "text", "type": "string"},
    {"name": "is_active", "type": "boolean"},
]
_IDX = {f["name"]: i for i, f in enumerate(_SNIPPET_FIELDS)}

_snippets_path: Optional[Path] = None

def init_input(snippets_path: Path) -> None:
    global _snippets_path
    _snippets_path = snippets_path
    if not snippets_path.exists():
        _write_snippets([])

def _read_snippets() -> list[list]:
    if not _snippets_path or not _snippets_path.exists():
        return []
    doc = bejson_core_load_file(str(_snippets_path))
    if not isinstance(doc, dict):
        return []
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        import logging
        logging.getLogger(__name__).warning(
            "[Input] %s failed structural validation: %s", _snippets_path, result.errors
        )
    fmap = bejson_core_get_field_map(doc)
    # Snippets file may predate the field-map cache injection; fall back to
    # the canonical field order above rather than trusting raw positions.
    if fmap and set(fmap) >= set(_IDX):
        rows = doc.get("Values", [])
        if fmap == _IDX:
            return rows
        reordered = []
        for r in rows:
            reordered.append([r[fmap[name]] if len(r) > fmap[name] else None for name in _IDX])
        return reordered
    if doc.get("Values"):
        # Field map doesn't cover the schema every consumer here assumes
        # (snippet_id/label/text/is_active in that order). Returning the raw
        # rows anyway would let e.g. toggle_snippet() silently misread free
        # text as the is_active flag. Fail safe: log it loudly and treat as
        # no usable snippets rather than risk corrupting one on next write.
        import logging
        logging.getLogger(__name__).error(
            "[Input] %s has %d row(s) but its field map %s doesn't cover the "
            "expected schema %s — refusing to read rows positionally to avoid "
            "misaligned data. Snippets are unavailable until this is fixed.",
            _snippets_path, len(doc["Values"]), sorted(fmap), sorted(_IDX),
        )
    return []

def _write_snippets(rows: list[list]) -> None:
    if not _snippets_path:
        return
    doc = bejson_core_create_104("Snippet", list(_SNIPPET_FIELDS), rows)
    if not bejson_core_atomic_write(str(_snippets_path), doc):
        import logging
        logging.getLogger(__name__).error("[Input] Atomic write failed for %s", _snippets_path)

def list_snippets() -> list[dict]:
    rows = _read_snippets()
    return [
        {"snippet_id": r[_IDX["snippet_id"]], "label": r[_IDX["label"]],
         "text": r[_IDX["text"]], "is_active": r[_IDX["is_active"]]}
        for r in rows
    ]

def add_snippet(label: str, text: str) -> str:
    rows = _read_snippets()
    sid = str(uuid.uuid4())[:8]
    row = [None] * len(_SNIPPET_FIELDS)
    row[_IDX["snippet_id"]] = sid
    row[_IDX["label"]] = label
    row[_IDX["text"]] = text
    row[_IDX["is_active"]] = True
    rows.append(row)
    _write_snippets(rows)
    return sid

def delete_snippet(sid: str) -> bool:
    rows = _read_snippets()
    new = [r for r in rows if r[_IDX["snippet_id"]] != sid]
    if len(new) == len(rows):
        return False
    _write_snippets(new)
    return True

def toggle_snippet(sid: str) -> Optional[bool]:
    rows = _read_snippets()
    for r in rows:
        if r[_IDX["snippet_id"]] == sid:
            r[_IDX["is_active"]] = not r[_IDX["is_active"]]
            _write_snippets(rows)
            return r[_IDX["is_active"]]
    return None

def run_stt() -> Optional[str]:
    try:
        result = subprocess.run(
            ["termux-speech-to-text"],
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout.strip()
        if out.startswith("["):
            try:
                parts = json.loads(out)
                out = " ".join(parts) if isinstance(parts, list) else out
            except json.JSONDecodeError:
                pass
        return out if out else None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None

def _run_dialog(args: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["termux-dialog"] + args,
            capture_output=True, text=True, timeout=120,
        )
        raw = result.stdout.strip()
        data = json.loads(raw)
        if data.get("code", -1) == -1:
            return None
        return data.get("text") or data.get("values", [None])[0]
    except Exception:
        return None

def run_dialog_input() -> Optional[str]:
    rows = [r for r in _read_snippets() if r[_IDX["is_active"]]]
    if rows:
        labels = [r[_IDX["label"]] for r in rows]
        chosen = _run_dialog(["sheet", "-v", ",".join(labels)])
        if chosen:
            for r in rows:
                if r[_IDX["label"]] == chosen:
                    return r[_IDX["text"]]
    return _run_dialog(["text", "-t", "Enter your message"])

def get_input(
    prompt: str,
    mode: int = 0,
    multi_line: bool = False,
) -> str:
    if mode == 1:
        transcript = run_stt()
        if transcript:
            print(f"  > {transcript}")
            return transcript
    elif mode == 2:
        text = run_dialog_input()
        if text:
            print(f"  > {text}")
            return text

    if multi_line:
        print(f"{prompt}(triple-Enter to send)")
        lines, blank_count = [], 0
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == "":
                blank_count += 1
                if blank_count >= 3:
                    break
                lines.append("")
            else:
                blank_count = 0
                lines.append(line)
        return "\n".join(lines).rstrip()
    else:
        try:
            return input(prompt)
        except EOFError:
            return ""

# NOTE: The local _atomic_write(path, data) json.dump helper that used to
# live here was removed 2026-07-16 — snippet I/O now goes through
# bejson_core_atomic_write for validation-aware atomic writes. See
# Docs/Changelogs.md.
