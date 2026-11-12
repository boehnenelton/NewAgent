"""
Library:         lib_bejson_MD_md_ops.py
Family:          MD
Module Purpose:  Implements runtime functionality and logic for lib_bejson_MD_md_ops.py.
Architecture:    BEJSON 104 Ecosystem Component maintaining strict schema integrity, field map caching, and standardized runtime contracts.
Version:         1.1.0
Release_Version: 300
Date:            2026-08-08
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   9398b876-6af9-410c-bd83-eb6495f66e4b
"""

import os
import sys
import tempfile
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
        bejson_core_load_file,
        bejson_core_atomic_write,
        bejson_core_get_field_map,
    )
except ImportError as _e:
    raise ImportError(
        "[lib_bejson_MD_md_ops] Cannot import lib_bejson_Core_bejson_core. "
        "Copy your Lib_PY/Core files into Lib_MD/lib/ or add Core to sys.path. "
        f"Original error: {_e}"
    )

from lib_bejson_MD_md_errors import (
    ChunkNotFoundError,
    MdFileNotFoundError,
    IndexNotFoundError,
    ChunkDriftError,
    WriteFailedError,
    InjectRangeInvalidError,
    AssembleEmptyError,
    InvalidDocumentError,
)
from lib_bejson_MD_md_indexer import (
    _checksum,
    _now_iso,
    _CHUNK_LEGACY,
    md_indexer_reindex_file,
    md_indexer_get_chunk_row,
    md_indexer_list_chunks,
    md_indexer_save_index,
    CHUNK_FIELDS,
)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_index(index_path: str) -> Dict[str, Any]:
    """Load and minimally validate a MarkdownChunk index document."""
    p = Path(index_path)
    if not p.exists():
        raise IndexNotFoundError(index_path)
    doc = bejson_core_load_file(index_path)
    if not doc or not isinstance(doc, dict):
        raise InvalidDocumentError(index_path, "bejson_core_load_file returned None or non-dict")
    rt = doc.get("Records_Type", [])
    if not rt or rt[0] != "MarkdownChunk":
        raise InvalidDocumentError(index_path, f"Records_Type must be ['MarkdownChunk'], got {rt}")
    return doc

def _read_file_lines(file_path: str) -> List[str]:
    """Read a file as a list of lines (with line endings preserved)."""
    p = Path(file_path)
    if not p.exists():
        raise MdFileNotFoundError(file_path)
    return p.read_text(encoding="utf-8").splitlines(keepends=True)

def _write_file_atomic(file_path: str, lines: List[str]) -> None:
    """
    Write a list of lines to a file atomically (temp → rename).
    Raises WriteFailedError on any failure.
    """
    target = Path(file_path).resolve()
    target_dir = target.parent
    tmp_path = None  # FIX (LIB-MD-M2): was checked via "tmp_path" in dir(),
                      # a fragile pattern that only worked by accident of
                      # Python's tuple-unpack semantics. Explicit sentinel.

    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), suffix=".md.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    except Exception as e:
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise WriteFailedError(file_path, str(e))

def _get_chunk_fields(doc: Dict[str, Any]):
    """Return field indices for a MarkdownChunk index document."""
    fi = bejson_core_get_field_map(doc)
    return {
        "chunk_id":    fi.get("chunk_id",    _CHUNK_LEGACY["chunk_id"]),
        "file_path":   fi.get("file_path",   _CHUNK_LEGACY["file_path"]),
        "start_line":  fi.get("start_line",  _CHUNK_LEGACY["start_line"]),
        "end_line":    fi.get("end_line",    _CHUNK_LEGACY["end_line"]),
        "chunk_type":  fi.get("chunk_type",  _CHUNK_LEGACY["chunk_type"]),
        "label":       fi.get("label",       _CHUNK_LEGACY["label"]),
        "is_active":   fi.get("is_active",   _CHUNK_LEGACY["is_active"]),
        "tags":        fi.get("tags",        _CHUNK_LEGACY["tags"]),
        "sort_order":  fi.get("sort_order",  _CHUNK_LEGACY["sort_order"]),
        "injected_at": fi.get("injected_at", _CHUNK_LEGACY["injected_at"]),
        "checksum":    fi.get("checksum",    _CHUNK_LEGACY["checksum"]),
    }

def _row_to_dict(row: List, fi: Dict[str, int]) -> Dict[str, Any]:
    """Convert a raw BEJSON row to a named dict using a field-index map."""
    return {name: (row[idx] if idx < len(row) else None) for name, idx in fi.items()}

# ---------------------------------------------------------------------------
# Operation 1 — PULL
# ---------------------------------------------------------------------------

def md_ops_pull(
    index_path: str,
    chunk_id: str,
    verify_checksum: bool = True,
) -> str:
    """
    Pull the raw text content of a chunk from its markdown file.

    Args:
        index_path:       Path to the MarkdownChunk BEJSON 104 index file.
        chunk_id:         The chunk_id to retrieve.
        verify_checksum:  If True, raises ChunkDriftError when checksum mismatches.
                          Set False only when you know the file has changed and
                          are about to call reindex anyway.

    Returns:
        The raw text content of the chunk (including trailing newline if present).

    Raises:
        IndexNotFoundError   — index file missing
        ChunkNotFoundError   — chunk_id not in index
        MdFileNotFoundError  — markdown file missing
        ChunkDriftError      — checksum mismatch (only when verify_checksum=True)
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)

    row = md_indexer_get_chunk_row(doc, chunk_id)
    if row is None:
        raise ChunkNotFoundError(chunk_id)

    chunk = _row_to_dict(row, fi)
    file_path  = chunk["file_path"]
    start_line = chunk["start_line"]
    end_line   = chunk["end_line"]
    stored_cs  = chunk["checksum"]

    lines   = _read_file_lines(file_path)
    segment = "".join(lines[start_line:end_line])

    if verify_checksum:
        actual_cs = _checksum(segment)
        if actual_cs != stored_cs:
            raise ChunkDriftError(chunk_id, file_path, stored_cs, actual_cs)

    return segment

# ---------------------------------------------------------------------------
# Operation 2 — INJECT
# ---------------------------------------------------------------------------

def md_ops_inject(
    index_path: str,
    chunk_id: str,
    new_content: str,
) -> Dict[str, Any]:
    """
    Replace a chunk's content in the markdown file and reindex.

    Sequence (atomic-safe):
        1. Load index → resolve file_path, start_line, end_line
        2. Read file lines
        3. Splice new_content into [start_line:end_line]
        4. Write new file atomically (temp → rename)
        5. Full reindex of that file, preserving other chunk metadata
        6. Write new index atomically

    Args:
        index_path:   Path to the MarkdownChunk index file.
        chunk_id:     The chunk to replace.
        new_content:  New raw text for the chunk. Must end with a newline
                      if you want to preserve normal markdown line structure.

    Returns:
        The new index document (post-reindex).

    Raises:
        IndexNotFoundError, ChunkNotFoundError, MdFileNotFoundError,
        InjectRangeInvalidError, WriteFailedError
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)

    row = md_indexer_get_chunk_row(doc, chunk_id)
    if row is None:
        raise ChunkNotFoundError(chunk_id)

    chunk      = _row_to_dict(row, fi)
    file_path  = chunk["file_path"]
    start_line = chunk["start_line"]
    end_line   = chunk["end_line"]

    lines = _read_file_lines(file_path)

    if start_line < 0 or end_line > len(lines) or start_line > end_line:
        raise InjectRangeInvalidError(chunk_id, start_line, end_line, len(lines))

    # Splice new content
    new_lines = new_content.splitlines(keepends=True)
    # Ensure trailing newline on last injected line
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    updated_lines = lines[:start_line] + new_lines + lines[end_line:]

    # Step 1: write file
    _write_file_atomic(file_path, updated_lines)

    # Step 2: full reindex (always after write, always in same call)
    new_doc = md_indexer_reindex_file(file_path, index_path, preserve_metadata=True)

    return new_doc

# ---------------------------------------------------------------------------
# Operation 3 — TOGGLE
# ---------------------------------------------------------------------------

def md_ops_toggle(
    index_path: str,
    chunk_id: str,
    active: Optional[bool] = None,
) -> bool:
    """
    Toggle or explicitly set the is_active flag for a chunk.

    Args:
        index_path:   Path to the MarkdownChunk index file.
        chunk_id:     The chunk to toggle.
        active:       If None, flips the current value.
                      If True/False, sets it explicitly.

    Returns:
        The new is_active value.

    Raises:
        IndexNotFoundError, ChunkNotFoundError, WriteFailedError
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)
    id_idx     = fi["chunk_id"]
    active_idx = fi["is_active"]

    found = False
    new_val = None

    for row in doc.get("Values", []):
        if row[id_idx] == chunk_id:
            current = row[active_idx]
            new_val = (not current) if active is None else bool(active)
            row[active_idx] = new_val
            found = True
            break

    if not found:
        raise ChunkNotFoundError(chunk_id)

    if not bejson_core_atomic_write(index_path, doc):
        raise WriteFailedError(index_path, "atomic write failed during toggle")

    return new_val

def md_ops_toggle_by_tag(
    index_path: str,
    tag: str,
    active: bool,
) -> List[str]:
    """
    Set is_active for every chunk with a matching tag.

    Args:
        index_path:   Path to the MarkdownChunk index file.
        tag:          Tag string to match against each chunk's tags array.
        active:       True to activate, False to deactivate.

    Returns:
        List of chunk_ids that were modified.

    Raises:
        IndexNotFoundError, WriteFailedError
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)
    id_idx     = fi["chunk_id"]
    active_idx = fi["is_active"]
    tags_idx   = fi["tags"]

    modified = []

    for row in doc.get("Values", []):
        chunk_tags = row[tags_idx] or []
        if tag in chunk_tags:
            row[active_idx] = active
            modified.append(row[id_idx])

    if not bejson_core_atomic_write(index_path, doc):
        raise WriteFailedError(index_path, "atomic write failed during tag toggle")

    return modified

def md_ops_set_tags(
    index_path: str,
    chunk_id: str,
    tags: List[str],
) -> None:
    """
    Set the tags array for a specific chunk.

    Raises:
        IndexNotFoundError, ChunkNotFoundError, WriteFailedError
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)
    id_idx   = fi["chunk_id"]
    tags_idx = fi["tags"]

    found = False
    for row in doc.get("Values", []):
        if row[id_idx] == chunk_id:
            row[tags_idx] = list(tags)
            found = True
            break

    if not found:
        raise ChunkNotFoundError(chunk_id)

    if not bejson_core_atomic_write(index_path, doc):
        raise WriteFailedError(index_path, "atomic write failed during set_tags")

def md_ops_set_sort_order(
    index_path: str,
    chunk_id: str,
    sort_order: int,
) -> None:
    """
    Set the sort_order for a specific chunk.

    Raises:
        IndexNotFoundError, ChunkNotFoundError, WriteFailedError
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)
    id_idx    = fi["chunk_id"]
    order_idx = fi["sort_order"]

    found = False
    for row in doc.get("Values", []):
        if row[id_idx] == chunk_id:
            row[order_idx] = int(sort_order)
            found = True
            break

    if not found:
        raise ChunkNotFoundError(chunk_id)

    if not bejson_core_atomic_write(index_path, doc):
        raise WriteFailedError(index_path, "atomic write failed during set_sort_order")

# ---------------------------------------------------------------------------
# Operation 4 — ASSEMBLE
# ---------------------------------------------------------------------------

def md_ops_assemble(
    index_path: str,
    tags: Optional[List[str]] = None,
    active_only: bool = True,
    separator: str = "\n",
    predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> str:
    """
    Assemble chunks from one or more markdown files into a single string.

    Chunks are sorted by sort_order then by file_path + start_line as tiebreaker.
    Content is verified via checksum before inclusion; drifted chunks log a warning
    but are still included (use predicate to filter them if needed).

    Args:
        index_path:   Path to the MarkdownChunk index file.
        tags:         If provided, only chunks where ANY of these tags is present
                      in the chunk's tags array are included.
        active_only:  If True (default), only is_active=True chunks are included.
        separator:    String inserted between assembled chunks. Default: "\\n".
        predicate:    Optional callable(chunk_dict) -> bool for custom filtering.
                      Called after is_active and tag filters.

    Returns:
        Assembled string content.

    Raises:
        IndexNotFoundError   — index file missing
        AssembleEmptyError   — no chunks matched the filters
    """
    doc = _load_index(index_path)
    fi  = _get_chunk_fields(doc)

    all_chunks = md_indexer_list_chunks(doc)

    # --- Filter: active ---
    if active_only:
        all_chunks = [c for c in all_chunks if c.get("is_active") is True]

    # --- Filter: tags ---
    if tags:
        tag_set = set(tags)
        filtered = []
        for c in all_chunks:
            chunk_tags = set(c.get("tags") or [])
            if chunk_tags & tag_set:
                filtered.append(c)
        all_chunks = filtered

    # --- Filter: predicate ---
    if predicate:
        all_chunks = [c for c in all_chunks if predicate(c)]

    if not all_chunks:
        reason = []
        if active_only:
            reason.append("active_only=True")
        if tags:
            reason.append(f"tags={tags}")
        if predicate:
            reason.append("predicate filter")
        raise AssembleEmptyError(", ".join(reason) if reason else "no chunks in index")

    # --- Sort: sort_order primary, file_path + start_line secondary ---
    all_chunks.sort(key=lambda c: (
        c.get("sort_order") if c.get("sort_order") is not None else 9999,
        c.get("file_path") or "",
        c.get("start_line") or 0,
    ))

    # --- Pull content for each chunk ---
    parts = []
    for chunk in all_chunks:
        cid        = chunk["chunk_id"]
        file_path  = chunk["file_path"]
        start_line = chunk["start_line"]
        end_line   = chunk["end_line"]
        stored_cs  = chunk["checksum"]

        try:
            lines   = _read_file_lines(file_path)
            segment = "".join(lines[start_line:end_line])
        except MdFileNotFoundError as e:
            logging.warning(f"[lib_bejson_MD_md_ops] Assemble skipping chunk '{cid}' — file missing: {e}")
            continue

        actual_cs = _checksum(segment)
        if actual_cs != stored_cs:
            logging.warning(
                f"[lib_bejson_MD_md_ops] Chunk drift for '{cid}' in '{file_path}' "
                f"(stored={stored_cs}, actual={actual_cs}). "
                f"Including stale content. Run reindex to fix."
            )

        parts.append(segment)

    if not parts:
        raise AssembleEmptyError("all matching chunks had missing files")

    return separator.join(parts)

# ---------------------------------------------------------------------------
# Convenience: assemble system prompt from a tag
# ---------------------------------------------------------------------------

def md_ops_assemble_by_tag(
    index_path: str,
    tag: str,
    separator: str = "\n\n",
) -> str:
    """
    Shorthand to assemble all active chunks with a specific tag.
    Most common use case: building system prompts, policy documents, etc.

    Example:
        assembled = md_ops_assemble_by_tag("chunks.bejson", "gemini_context")

    Returns:
        Assembled string of all matching active chunks.
    """
    return md_ops_assemble(index_path, tags=[tag], active_only=True, separator=separator)

# ---------------------------------------------------------------------------
# Convenience: reindex
# ---------------------------------------------------------------------------

def md_ops_reindex(
    file_path: str,
    index_path: str,
) -> Dict[str, Any]:
    """
    Public wrapper for a full reindex that preserves existing chunk metadata.
    Safe to call at any time — idempotent.
    """
    return md_indexer_reindex_file(file_path, index_path, preserve_metadata=True)

# ---------------------------------------------------------------------------
# Convenience: inspect index
# ---------------------------------------------------------------------------

def md_ops_list_chunks(
    index_path: str,
    active_only: bool = False,
    tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return a list of chunk dicts from the index.

    Args:
        index_path:   Path to the MarkdownChunk index file.
        active_only:  If True, only return is_active=True chunks.
        tag:          If provided, only return chunks with this tag.

    Returns:
        List of chunk dicts, sorted by sort_order.
    """
    doc    = _load_index(index_path)
    chunks = md_indexer_list_chunks(doc)

    if active_only:
        chunks = [c for c in chunks if c.get("is_active") is True]

    if tag:
        chunks = [c for c in chunks if tag in (c.get("tags") or [])]

    chunks.sort(key=lambda c: (
        c.get("sort_order") if c.get("sort_order") is not None else 9999,
        c.get("start_line") or 0,
    ))

    return chunks