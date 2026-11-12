"""
Library:         lib_bejson_MD_md_db.py
Family:          MD
Module Purpose:  Implements runtime functionality and logic for lib_bejson_MD_md_db.py.
Architecture:    MFDB provides multi-file database federation coordinating a 104a central manifest (104a.mfdb.bejson) with dense 104 entity tables, supporting atomic transaction locks and cross-disk relational foreign keys.
Version:         1.1.0
Release_Version: 300
Date:            2026-08-08
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   a4766992-c0a3-40c3-b529-6997e1cde57c
"""

import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Self-locating path resolution (Portability Mandate §7.1)
# ---------------------------------------------------------------------------

def get_script_path() -> Path:
    return Path(__file__).resolve().parent

SCRIPT_PATH = get_script_path()

_LIB_SUBDIR = SCRIPT_PATH / "lib"
if str(_LIB_SUBDIR) not in sys.path:
    sys.path.insert(0, str(_LIB_SUBDIR))

try:
    from lib_bejson_Core_bejson_core import (
        bejson_core_create_104,
        bejson_core_atomic_write,
        bejson_core_load_file,
        bejson_core_get_field_map,
        bejson_core_add_record,
        bejson_core_filter_rows,
        bejson_core_get_field_index,
        ResilientPIDLock,
    )
    from lib_bejson_Core_mfdb_core import mfdb_core_create_database
except ImportError as _e:
    raise ImportError(
        "[lib_bejson_MD_md_db] Cannot import lib_bejson_Core_bejson_core or lib_bejson_Core_mfdb_core. "
        "Copy your Lib_PY/Core files into Lib_MD/lib/ or add Core to sys.path. "
        f"Original error: {_e}"
    )

from lib_bejson_MD_md_errors import (
    MdFileNotFoundError,
    IndexNotFoundError,
    MFDBWrapperError,
    AssembleEmptyError,
)
from lib_bejson_MD_md_indexer import (
    CHUNK_FIELDS,
    md_indexer_build_index_doc,
    md_indexer_reindex_file,
    md_indexer_list_chunks,
    _now_iso,
    _CHUNK_LEGACY,
)
from lib_bejson_MD_md_ops import (
    md_ops_pull,
    md_ops_inject,
    md_ops_toggle,
    md_ops_toggle_by_tag,
    md_ops_set_tags,
    md_ops_set_sort_order,
    md_ops_assemble,
    md_ops_assemble_by_tag,
    md_ops_list_chunks,
)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# BEJSON 104 schema for MarkdownFile entity
# ---------------------------------------------------------------------------

FILE_FIELDS = [
    {"name": "file_id",        "type": "string"},   # 0 — stable slug from file stem
    {"name": "file_path",      "type": "string"},   # 1 — absolute path to markdown file
    {"name": "index_path",     "type": "string"},   # 2 — path to the per-file chunk index
    {"name": "last_indexed",   "type": "string"},   # 3 — ISO 8601 UTC timestamp
    {"name": "line_count",     "type": "integer"},  # 4 — total lines at last index
    {"name": "chunk_count",    "type": "integer"},  # 5 — number of chunks at last index
    {"name": "description",    "type": "string"},   # 6 — optional human label
    {"name": "tags",           "type": "array"},    # 7 — file-level tags
]

_FILE_LEGACY = {f["name"]: i for i, f in enumerate(FILE_FIELDS)}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return _now_iso()

def _file_id(file_path: str) -> str:
    """Derive a stable file_id from the file's stem."""
    stem = Path(file_path).stem
    safe = ""
    for ch in stem.lower():
        if ch.isalnum() or ch in "-_":
            safe += ch
        elif ch in " .":
            safe += "_"
    return safe or "file"

def _get_manifest_path(db_root: str) -> str:
    return str(Path(db_root) / "104a.mfdb.bejson")

def _get_file_entity_path(db_root: str) -> str:
    return str(Path(db_root) / "data" / "markdown_file.bejson")

def _get_chunk_entity_path(db_root: str) -> str:
    return str(Path(db_root) / "data" / "markdown_chunk.bejson")

def _file_entity_lock(db_root: str) -> ResilientPIDLock:
    """FIX (LIB-MD-M3): entity writes had no cross-process locking at all -
    bejson_core_atomic_write() is crash-safe (temp+rename) but does nothing
    to stop two concurrent callers both loading the same doc before either
    saves, silently losing one writer's changes. Same race-condition class
    already fixed in mfdb_core.py's manifest writes. Callers wrap their
    full load-mutate-save cycle in this."""
    return ResilientPIDLock(_get_file_entity_path(db_root), timeout_seconds=10)

def _chunk_entity_lock(db_root: str) -> ResilientPIDLock:
    return ResilientPIDLock(_get_chunk_entity_path(db_root), timeout_seconds=10)

def _load_file_entity(db_root: str) -> Dict[str, Any]:
    path = _get_file_entity_path(db_root)
    doc  = bejson_core_load_file(path)
    if not doc:
        raise MFDBWrapperError(f"Cannot load MarkdownFile entity: {path}")
    return doc

def _load_chunk_entity(db_root: str) -> Dict[str, Any]:
    path = _get_chunk_entity_path(db_root)
    doc  = bejson_core_load_file(path)
    if not doc:
        raise MFDBWrapperError(f"Cannot load MarkdownChunk entity: {path}")
    return doc

def _save_file_entity(db_root: str, doc: Dict[str, Any]) -> None:
    path = _get_file_entity_path(db_root)
    if not bejson_core_atomic_write(path, doc):
        raise MFDBWrapperError(f"Atomic write failed for MarkdownFile entity: {path}")

def _save_chunk_entity(db_root: str, doc: Dict[str, Any]) -> None:
    path = _get_chunk_entity_path(db_root)
    if not bejson_core_atomic_write(path, doc):
        raise MFDBWrapperError(f"Atomic write failed for MarkdownChunk entity: {path}")


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------

def md_db_create(db_root: str, db_name: str = "MarkdownDB", description: str = "") -> str:
    """
    Create a new Markdown MFDB database.

    Creates the directory structure and initializes:
        - 104a.mfdb.bejson (manifest)
        - data/markdown_file.bejson (MarkdownFile entity)
        - data/markdown_chunk.bejson (MarkdownChunk entity)

    Args:
        db_root:      Root directory for the database. Created if it doesn't exist.
        db_name:      Human-readable DB name for the manifest.
        description:  Optional description.

    Returns:
        Absolute path to the manifest file.
    """
    root = Path(db_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    manifest_path = mfdb_core_create_database(
        root_dir=str(root),
        db_name=db_name,
        entities=[
            {
                "name":          "MarkdownFile",
                "file_path":     "data/markdown_file.bejson",
                "description":   "Registry of indexed markdown files",
                "primary_key":   "file_id",
                "schema_version": "1.0",
                "fields":        FILE_FIELDS,
            },
            {
                "name":          "MarkdownChunk",
                "file_path":     "data/markdown_chunk.bejson",
                "description":   "Flat chunk index across all registered files",
                "primary_key":   "chunk_id",
                "schema_version": "1.0",
                "fields":        CHUNK_FIELDS,
            },
        ],
        db_description=description,
        schema_version="1.0.0",
        author="Elton Boehnen",
        mfdb_version="1.31",
    )

    return manifest_path

def md_db_exists(db_root: str) -> bool:
    """Return True if a valid Markdown MFDB exists at db_root."""
    manifest = Path(db_root) / "104a.mfdb.bejson"
    file_e   = Path(db_root) / "data" / "markdown_file.bejson"
    chunk_e  = Path(db_root) / "data" / "markdown_chunk.bejson"
    return manifest.exists() and file_e.exists() and chunk_e.exists()

# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------

def md_db_register_file(
    db_root: str,
    file_path: str,
    description: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    """
    Register a markdown file in the database and perform the initial index.

    If the file is already registered (same absolute path), the entry is
    updated in place and the index is refreshed.

    Args:
        db_root:     Root directory of the Markdown MFDB.
        file_path:   Absolute or relative path to the markdown file.
        description: Optional human-readable description.
        tags:        File-level tags.

    Returns:
        The file_id assigned to this file.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        raise MdFileNotFoundError(str(p))

    fid        = _file_id(str(p))
    index_path = str(Path(db_root) / "data" / f"{fid}.chunk_index.bejson")

    # Build the chunk index for this file
    index_doc = md_indexer_build_index_doc(str(p))
    bejson_core_atomic_write(index_path, index_doc)

    line_count  = sum(1 for _ in p.open(encoding="utf-8"))
    chunk_count = len(index_doc.get("Values", []))

    # Update MarkdownFile entity
    # FIX (LIB-MD-M3): load-mutate-save wrapped in a lock so a concurrent
    # register/reindex/unregister on the same db_root can't read a stale
    # copy and silently overwrite this write when it saves.
    with _file_entity_lock(db_root):
        file_doc = _load_file_entity(db_root)
        fi       = bejson_core_get_field_map(file_doc)

        fid_idx   = fi.get("file_id",   _FILE_LEGACY["file_id"])
        fpath_idx = fi.get("file_path", _FILE_LEGACY["file_path"])

        # Check if already registered
        existing_idx = None
        for i, row in enumerate(file_doc.get("Values", [])):
            if row[fpath_idx] == str(p):
                existing_idx = i
                break

        new_row = [None] * len(FILE_FIELDS)
        new_row[_FILE_LEGACY["file_id"]]      = fid
        new_row[_FILE_LEGACY["file_path"]]    = str(p)
        new_row[_FILE_LEGACY["index_path"]]   = index_path
        new_row[_FILE_LEGACY["last_indexed"]] = _now()
        new_row[_FILE_LEGACY["line_count"]]   = line_count
        new_row[_FILE_LEGACY["chunk_count"]]  = chunk_count
        new_row[_FILE_LEGACY["description"]]  = description or None
        new_row[_FILE_LEGACY["tags"]]         = list(tags) if tags else []

        if existing_idx is not None:
            file_doc["Values"][existing_idx] = new_row
        else:
            file_doc["Values"].append(new_row)

        _save_file_entity(db_root, file_doc)

    # Sync the flat chunk entity
    _sync_chunk_entity(db_root, str(p), fid, index_doc)

    return fid

def md_db_list_files(db_root: str) -> List[Dict[str, Any]]:
    """
    Return all registered files as a list of dicts.
    """
    file_doc = _load_file_entity(db_root)
    fields   = [f["name"] for f in file_doc.get("Fields", [])]
    result   = []
    for row in file_doc.get("Values", []):
        item = {fields[i]: row[i] for i in range(min(len(fields), len(row)))}
        result.append(item)
    return result

def md_db_get_file(db_root: str, file_id: str) -> Optional[Dict[str, Any]]:
    """Return a file record dict by file_id, or None if not found."""
    for f in md_db_list_files(db_root):
        if f.get("file_id") == file_id:
            return f
    return None

def md_db_get_index_path(db_root: str, file_id: str) -> Optional[str]:
    """Return the index_path for a registered file, or None."""
    rec = md_db_get_file(db_root, file_id)
    return rec.get("index_path") if rec else None

def md_db_reindex_file(db_root: str, file_id: str) -> Dict[str, Any]:
    """
    Reindex a registered file, refreshing its chunk index and syncing
    the flat chunk entity.

    Returns the new index document.
    """
    with _file_entity_lock(db_root):
        file_doc = _load_file_entity(db_root)
        fi       = bejson_core_get_field_map(file_doc)

        fid_idx   = fi.get("file_id",   _FILE_LEGACY["file_id"])
        fpath_idx = fi.get("file_path", _FILE_LEGACY["file_path"])
        ipath_idx = fi.get("index_path", _FILE_LEGACY["index_path"])
        ts_idx    = fi.get("last_indexed", _FILE_LEGACY["last_indexed"])
        lc_idx    = fi.get("line_count", _FILE_LEGACY["line_count"])
        cc_idx    = fi.get("chunk_count", _FILE_LEGACY["chunk_count"])

        for row in file_doc.get("Values", []):
            if row[fid_idx] == file_id:
                file_path  = row[fpath_idx]
                index_path = row[ipath_idx]

                new_doc = md_indexer_reindex_file(file_path, index_path, preserve_metadata=True)

                # Update file registry metadata
                row[ts_idx] = _now()
                row[lc_idx] = sum(1 for _ in Path(file_path).open(encoding="utf-8"))
                row[cc_idx] = len(new_doc.get("Values", []))

                _save_file_entity(db_root, file_doc)
                _sync_chunk_entity(db_root, file_path, file_id, new_doc)

                return new_doc

    raise MFDBWrapperError(f"file_id '{file_id}' not found in MarkdownFile registry")

def md_db_reindex_all(db_root: str) -> Dict[str, Dict[str, Any]]:
    """
    Reindex all registered files. Returns dict of {file_id: new_index_doc}.
    """
    files   = md_db_list_files(db_root)
    results = {}
    for f in files:
        try:
            results[f["file_id"]] = md_db_reindex_file(db_root, f["file_id"])
        except Exception as e:
            logging.warning(f"[lib_bejson_MD_md_db] Reindex failed for {f['file_id']}: {e}")
    return results

def md_db_unregister_file(db_root: str, file_id: str) -> bool:
    """
    Remove a file from the registry and clean up its index file.
    Does NOT delete the actual markdown file.

    Returns True if found and removed, False if not found.
    """
    with _file_entity_lock(db_root):
        file_doc = _load_file_entity(db_root)
        fi       = bejson_core_get_field_map(file_doc)

        fid_idx   = fi.get("file_id",   _FILE_LEGACY["file_id"])
        ipath_idx = fi.get("index_path", _FILE_LEGACY["index_path"])
        fpath_idx = fi.get("file_path", _FILE_LEGACY["file_path"])

        new_values = []
        removed    = None

        for row in file_doc.get("Values", []):
            if row[fid_idx] == file_id:
                removed = row
            else:
                new_values.append(row)

        if removed is None:
            return False

        file_doc["Values"] = new_values
        _save_file_entity(db_root, file_doc)

    # Clean up index file
    index_path = removed[ipath_idx]
    if index_path and Path(index_path).exists():
        try:
            Path(index_path).unlink()
        except OSError as e:
            logging.warning(f"[lib_bejson_MD_md_db] Could not remove index file {index_path}: {e}")

    # Remove from flat chunk entity
    file_path = removed[fpath_idx]
    _remove_from_chunk_entity(db_root, file_path)

    return True

# ---------------------------------------------------------------------------
# Flat chunk entity sync
# ---------------------------------------------------------------------------

def _sync_chunk_entity(
    db_root: str,
    file_path: str,
    file_id: str,
    index_doc: Dict[str, Any],
) -> None:
    """
    Sync the flat MarkdownChunk entity with chunks from index_doc.
    Replaces all rows for this file_path, preserving rows for other files.
    """
    with _chunk_entity_lock(db_root):
        chunk_doc = _load_chunk_entity(db_root)
        fi        = bejson_core_get_field_map(chunk_doc)
        fp_idx    = fi.get("file_path", _CHUNK_LEGACY["file_path"])

        # Remove existing rows for this file
        existing = [row for row in chunk_doc.get("Values", []) if row[fp_idx] != file_path]

        # Append new rows from index_doc
        new_rows = list(index_doc.get("Values", []))
        chunk_doc["Values"] = existing + new_rows

        _save_chunk_entity(db_root, chunk_doc)

def _remove_from_chunk_entity(db_root: str, file_path: str) -> None:
    """Remove all chunk rows for a given file_path from the flat entity."""
    with _chunk_entity_lock(db_root):
        chunk_doc = _load_chunk_entity(db_root)
        fi        = bejson_core_get_field_map(chunk_doc)
        fp_idx    = fi.get("file_path", _CHUNK_LEGACY["file_path"])

        chunk_doc["Values"] = [
            row for row in chunk_doc.get("Values", []) if row[fp_idx] != file_path
        ]
        _save_chunk_entity(db_root, chunk_doc)

# ---------------------------------------------------------------------------
# Cross-file query operations (using flat chunk entity)
# ---------------------------------------------------------------------------

def md_db_list_all_chunks(
    db_root: str,
    active_only: bool = False,
    tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return all chunks across all registered files from the flat entity.

    Args:
        db_root:     Root directory of the Markdown MFDB.
        active_only: Filter to is_active=True only.
        tag:         Filter to chunks containing this tag.

    Returns:
        List of chunk dicts sorted by sort_order then file_path + start_line.
    """
    chunk_doc = _load_chunk_entity(db_root)
    chunks    = md_indexer_list_chunks(chunk_doc)

    if active_only:
        chunks = [c for c in chunks if c.get("is_active") is True]

    if tag:
        chunks = [c for c in chunks if tag in (c.get("tags") or [])]

    chunks.sort(key=lambda c: (
        c.get("sort_order") if c.get("sort_order") is not None else 9999,
        c.get("file_path") or "",
        c.get("start_line") or 0,
    ))

    return chunks

def md_db_assemble(
    db_root: str,
    tags: Optional[List[str]] = None,
    active_only: bool = True,
    separator: str = "\n",
    predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> str:
    """
    Assemble content from all registered files matching the filters.
    Uses the flat MarkdownChunk entity for cross-file queries.

    Args:
        db_root:     Root directory of the Markdown MFDB.
        tags:        If provided, include only chunks with ANY of these tags.
        active_only: Include only is_active=True chunks.
        separator:   String between assembled chunks.
        predicate:   Optional callable(chunk_dict) -> bool.

    Returns:
        Assembled string content.
    """
    chunk_doc = _load_chunk_entity(db_root)
    all_chunks = md_indexer_list_chunks(chunk_doc)

    if active_only:
        all_chunks = [c for c in all_chunks if c.get("is_active") is True]

    if tags:
        tag_set    = set(tags)
        all_chunks = [c for c in all_chunks if set(c.get("tags") or []) & tag_set]

    if predicate:
        all_chunks = [c for c in all_chunks if predicate(c)]

    if not all_chunks:
        raise AssembleEmptyError(f"tags={tags}, active_only={active_only}")

    all_chunks.sort(key=lambda c: (
        c.get("sort_order") if c.get("sort_order") is not None else 9999,
        c.get("file_path") or "",
        c.get("start_line") or 0,
    ))

    parts = []
    for chunk in all_chunks:
        try:
            file_path  = chunk["file_path"]
            start_line = chunk["start_line"]
            end_line   = chunk["end_line"]

            p = Path(file_path)
            if not p.exists():
                logging.warning(f"[lib_bejson_MD_md_db] Skipping chunk '{chunk['chunk_id']}' — file missing")
                continue

            lines   = p.read_text(encoding="utf-8").splitlines(keepends=True)
            segment = "".join(lines[start_line:end_line])
            parts.append(segment)
        except Exception as e:
            logging.warning(f"[lib_bejson_MD_md_db] Skipping chunk '{chunk.get('chunk_id')}': {e}")

    if not parts:
        raise AssembleEmptyError("all matching chunks had missing or unreadable files")

    return separator.join(parts)

def md_db_assemble_by_tag(
    db_root: str,
    tag: str,
    separator: str = "\n\n",
) -> str:
    """
    Shorthand: assemble all active chunks with a specific tag from all files.
    Primary use case — building system prompts and policy documents.
    """
    return md_db_assemble(db_root, tags=[tag], active_only=True, separator=separator)

# ---------------------------------------------------------------------------
# Per-file chunk operations (delegates to lib_bejson_MD_md_ops via index_path)
# ---------------------------------------------------------------------------

def md_db_pull(db_root: str, file_id: str, chunk_id: str, verify_checksum: bool = True) -> str:
    """Pull a chunk by file_id + chunk_id."""
    index_path = md_db_get_index_path(db_root, file_id)
    if not index_path:
        raise MFDBWrapperError(f"file_id '{file_id}' not found in registry")
    return md_ops_pull(index_path, chunk_id, verify_checksum=verify_checksum)

def md_db_inject(db_root: str, file_id: str, chunk_id: str, new_content: str) -> Dict[str, Any]:
    """Inject new content into a chunk and reindex."""
    index_path = md_db_get_index_path(db_root, file_id)
    if not index_path:
        raise MFDBWrapperError(f"file_id '{file_id}' not found in registry")
    new_doc = md_ops_inject(index_path, chunk_id, new_content)
    # Re-sync flat entity after inject (index was rewritten by md_ops_inject)
    file_rec = md_db_get_file(db_root, file_id)
    if file_rec:
        _sync_chunk_entity(db_root, file_rec["file_path"], file_id, new_doc)
    return new_doc

def md_db_toggle(db_root: str, file_id: str, chunk_id: str, active: Optional[bool] = None) -> bool:
    """Toggle is_active for a chunk and sync flat entity."""
    index_path = md_db_get_index_path(db_root, file_id)
    if not index_path:
        raise MFDBWrapperError(f"file_id '{file_id}' not found in registry")
    result = md_ops_toggle(index_path, chunk_id, active=active)
    # Re-sync flat entity
    file_rec = md_db_get_file(db_root, file_id)
    if file_rec:
        updated_doc = bejson_core_load_file(index_path)
        if updated_doc:
            _sync_chunk_entity(db_root, file_rec["file_path"], file_id, updated_doc)
    return result

def md_db_set_tags(db_root: str, file_id: str, chunk_id: str, tags: List[str]) -> None:
    """Set tags for a chunk and sync flat entity."""
    index_path = md_db_get_index_path(db_root, file_id)
    if not index_path:
        raise MFDBWrapperError(f"file_id '{file_id}' not found in registry")
    md_ops_set_tags(index_path, chunk_id, tags)
    file_rec = md_db_get_file(db_root, file_id)
    if file_rec:
        updated_doc = bejson_core_load_file(index_path)
        if updated_doc:
            _sync_chunk_entity(db_root, file_rec["file_path"], file_id, updated_doc)

def md_db_list_chunks(
    db_root: str,
    file_id: str,
    active_only: bool = False,
    tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List chunks for a specific registered file."""
    index_path = md_db_get_index_path(db_root, file_id)
    if not index_path:
        raise MFDBWrapperError(f"file_id '{file_id}' not found in registry")
    return md_ops_list_chunks(index_path, active_only=active_only, tag=tag)