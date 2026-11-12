"""
Library:         lib_bejson_MD_md_indexer.py
Family:          MD
Module Purpose:  Implements runtime functionality and logic for lib_bejson_MD_md_indexer.py.
Architecture:    BEJSON 104 Ecosystem Component maintaining strict schema integrity, field map caching, and standardized runtime contracts.
Version:         1.1.0
Release_Version: 300
Date:            2026-08-08
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   110f5a6b-28c8-4827-ba3a-41c344324ac2
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Self-locating path resolution (Portability Mandate §7.1)
# ---------------------------------------------------------------------------

def get_script_path() -> Path:
    return Path(__file__).resolve().parent

SCRIPT_PATH = get_script_path()

# ---------------------------------------------------------------------------
# Lib_MD bootstrap — require sibling Core from the user's Lib_PY installation.
# The caller must ensure Core is on sys.path, or pass lib_dir at import time.
# We resolve best-effort here and surface a clear message if it fails.
# ---------------------------------------------------------------------------

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
    )
except ImportError as _e:
    raise ImportError(
        "[lib_bejson_MD_md_indexer] Cannot import lib_bejson_Core_bejson_core. "
        "Copy your Lib_PY/Core files into Lib_MD/lib/ or add Core to sys.path. "
        f"Original error: {_e}"
    )

from lib_bejson_MD_md_errors import (
    MdFileNotFoundError,
    InvalidDocumentError,
    WriteFailedError,
)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# BEJSON 104 schema for MarkdownChunk index documents
#
# Layout of Fields array — positional order matters, append-only.
# ---------------------------------------------------------------------------

CHUNK_FIELDS = [
    {"name": "chunk_id",    "type": "string"},   # 0 — stable UUID slug
    {"name": "file_path",   "type": "string"},   # 1 — absolute path to markdown file
    {"name": "start_line",  "type": "integer"},  # 2 — 0-based inclusive
    {"name": "end_line",    "type": "integer"},  # 3 — 0-based exclusive (Python slice)
    {"name": "chunk_type",  "type": "string"},   # 4 — heading|code_block|policy|raw|frontmatter
    {"name": "label",       "type": "string"},   # 5 — human-readable display name
    {"name": "is_active",   "type": "boolean"},  # 6 — participates in assemble operations
    {"name": "tags",        "type": "array"},    # 7 — list of string tags for filtering
    {"name": "sort_order",  "type": "integer"},  # 8 — assembly sequence, independent of line pos
    {"name": "injected_at", "type": "string"},   # 9 — ISO 8601 UTC timestamp of last injection
    {"name": "checksum",    "type": "string"},   # 10 — sha256[:16] of raw chunk content
]

# Legacy fallback constants — in case a consumer builds its own field map
_CHUNK_LEGACY = {f["name"]: i for i, f in enumerate(CHUNK_FIELDS)}

# ---------------------------------------------------------------------------
# Chunk types
# ---------------------------------------------------------------------------

CHUNK_TYPE_HEADING     = "heading"
CHUNK_TYPE_CODE_BLOCK  = "code_block"
CHUNK_TYPE_FRONTMATTER = "frontmatter"
CHUNK_TYPE_POLICY      = "policy"
CHUNK_TYPE_RAW         = "raw"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _checksum(content: str) -> str:
    """Short SHA-256 fingerprint of chunk text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

def _chunk_id(file_path: str, start_line: int, chunk_type: str, seq: int) -> str:
    """
    Deterministic, stable chunk ID derived from file path + position + type.
    Format: <file_stem>_<path_hash8>_<type>_<start>_<seq>

    LIB-MD-M1 fix (2026-08-08): was <file_stem>_<type>_<start>_<seq> --
    using only Path(file_path).stem (not the full path) meant any two
    files sharing a name in different folders (e.g. every project's
    README.md) with a matching chunk type/start-line/seq would collide,
    in a format explicitly designed for cross-file indexing. Appends an
    8-hex-char SHA-256 prefix of the full resolved file_path, which
    every call site already passes in (see md_indexer_scan_and_index's
    `p = Path(file_path).resolve()`), so this is a real, resolved-path
    collision guard, not a cosmetic one.
    """
    stem = Path(file_path).stem
    safe = ""
    for ch in stem.lower():
        if ch.isalnum() or ch in "-_":
            safe += ch
        elif ch in " .":
            safe += "_"
    path_hash = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{path_hash}_{chunk_type}_{start_line}_{seq}"

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# State machine — structural scanner
# ---------------------------------------------------------------------------

def _scan_lines(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Walk markdown lines using a two-flag state machine (no regex).
    Returns a list of raw chunk dicts:
        { start, end, chunk_type, label }

    State flags:
        in_frontmatter  — True while inside YAML front matter block
        in_code_block   — True while inside a fenced code block
        fence_char      — '`' or '~' — which fence style opened the block
        fence_width     — how many fence chars opened the block (3+)
    """
    chunks: List[Dict[str, Any]] = []

    in_frontmatter  = False
    in_code_block   = False
    fence_char      = ""
    fence_width     = 0

    # Track the current "raw" prose section between structural elements
    raw_start: Optional[int] = None

    def close_raw(end_line: int):
        nonlocal raw_start
        if raw_start is not None and end_line > raw_start:
            # Only emit if there's non-blank content
            segment = lines[raw_start:end_line]
            if any(l.strip() for l in segment):
                chunks.append({
                    "start":      raw_start,
                    "end":        end_line,
                    "chunk_type": CHUNK_TYPE_RAW,
                    "label":      f"Raw block (lines {raw_start}–{end_line - 1})",
                })
        raw_start = None

    i = 0
    total = len(lines)

    # --- Handle YAML frontmatter (must be first line = "---") ---
    if total > 0 and lines[0].rstrip() == "---":
        in_frontmatter = True
        fm_start = 0
        i = 1
        while i < total:
            stripped = lines[i].rstrip()
            if stripped == "---" or stripped == "...":
                chunks.append({
                    "start":      fm_start,
                    "end":        i + 1,
                    "chunk_type": CHUNK_TYPE_FRONTMATTER,
                    "label":      "Frontmatter",
                })
                in_frontmatter = False
                i += 1
                break
            i += 1
        if in_frontmatter:
            # Unclosed frontmatter — treat rest of file as raw
            chunks.append({
                "start":      0,
                "end":        total,
                "chunk_type": CHUNK_TYPE_RAW,
                "label":      "Unclosed frontmatter (treated as raw)",
            })
            return chunks

    # --- Main scan loop ---
    raw_start = i  # begin tracking raw content from after frontmatter

    while i < total:
        line = lines[i]
        stripped = line.rstrip()

        # ---- Inside a fenced code block ----
        if in_code_block:
            # Detect closing fence: same char, same or greater width, optional trailing spaces
            s = stripped.lstrip()
            if s.startswith(fence_char * fence_width) and s.replace(fence_char, "").strip() == "":
                # Close the code block — end is exclusive so +1
                close_raw(code_block_start)
                chunks.append({
                    "start":      code_block_start,
                    "end":        i + 1,
                    "chunk_type": CHUNK_TYPE_CODE_BLOCK,
                    "label":      f"Code block (lines {code_block_start}–{i})",
                })
                in_code_block = False
                fence_char    = ""
                fence_width   = 0
                raw_start     = i + 1
            i += 1
            continue

        # ---- Detect opening fence ----
        # A fenced code block starts with 3+ backticks or 3+ tildes at line start
        lstripped = stripped.lstrip()
        for fc in ("`", "~"):
            if lstripped.startswith(fc * 3):
                # Count consecutive fence chars
                width = 0
                for ch in lstripped:
                    if ch == fc:
                        width += 1
                    else:
                        break
                if width >= 3:
                    close_raw(i)
                    in_code_block    = True
                    fence_char       = fc
                    fence_width      = width
                    code_block_start = i
                    i += 1
                    break
        else:
            # ---- Detect ATX heading (# / ## / ### etc.) ----
            if stripped.startswith("#"):
                # Count leading #
                level = 0
                for ch in stripped:
                    if ch == "#":
                        level += 1
                    else:
                        break
                # Must be followed by space or end-of-line to be a real heading
                rest = stripped[level:]
                if not rest or rest.startswith(" "):
                    close_raw(i)
                    heading_text = rest.strip() if rest.strip() else f"Heading (level {level})"
                    # A heading chunk spans only that single line
                    chunks.append({
                        "start":      i,
                        "end":        i + 1,
                        "chunk_type": CHUNK_TYPE_HEADING,
                        "label":      heading_text[:80],
                    })
                    raw_start = i + 1
                    i += 1
                    continue

            i += 1
            continue

    # Close any trailing raw block
    close_raw(total)

    # If an unclosed code block exists, emit as raw
    if in_code_block:
        chunks.append({
            "start":      code_block_start,
            "end":        total,
            "chunk_type": CHUNK_TYPE_RAW,
            "label":      f"Unclosed code block (lines {code_block_start}–{total - 1})",
        })

    return chunks

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def md_indexer_scan_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Scan a markdown file and return a list of raw chunk dicts.
    Each dict contains: start, end, chunk_type, label, checksum.

    Does NOT write anything — pure read operation.
    Raises MdFileNotFoundError if the file does not exist.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        raise MdFileNotFoundError(str(p))

    raw_text = p.read_text(encoding="utf-8")
    lines    = raw_text.splitlines(keepends=True)

    raw_chunks = _scan_lines(lines)

    # Attach checksum to each chunk
    for chunk in raw_chunks:
        segment = "".join(lines[chunk["start"]:chunk["end"]])
        chunk["checksum"] = _checksum(segment)

    return raw_chunks

def md_indexer_build_index_doc(file_path: str, default_active: bool = True) -> Dict[str, Any]:
    """
    Scan a markdown file and produce a BEJSON 104 MarkdownChunk index document.

    Args:
        file_path:      Absolute or relative path to the markdown file.
        default_active: Whether newly scanned chunks default to is_active=True.

    Returns:
        A valid BEJSON 104 dict ready for atomic write or further manipulation.
    """
    p = Path(file_path).resolve()
    raw_chunks = md_indexer_scan_file(str(p))

    values = []
    now    = _now_iso()

    for seq, chunk in enumerate(raw_chunks):
        cid   = _chunk_id(str(p), chunk["start"], chunk["chunk_type"], seq)
        label = chunk.get("label") or f"{chunk['chunk_type']} (line {chunk['start']})"

        # Build row in CHUNK_FIELDS positional order
        row = [
            cid,                        # 0  chunk_id
            str(p),                     # 1  file_path
            chunk["start"],             # 2  start_line
            chunk["end"],               # 3  end_line
            chunk["chunk_type"],        # 4  chunk_type
            label,                      # 5  label
            default_active,             # 6  is_active
            [],                         # 7  tags
            seq,                        # 8  sort_order
            now,                        # 9  injected_at
            chunk["checksum"],          # 10 checksum
        ]
        values.append(row)

    doc = bejson_core_create_104("MarkdownChunk", CHUNK_FIELDS, values)
    return doc

def md_indexer_save_index(index_doc: Dict[str, Any], index_path: str) -> bool:
    """
    Atomically write a MarkdownChunk index document to disk.
    Returns True on success, raises WriteFailedError on failure.
    """
    result = bejson_core_atomic_write(index_path, index_doc)
    if not result:
        raise WriteFailedError(index_path, "bejson_core_atomic_write returned False")
    return True

def md_indexer_reindex_file(
    file_path: str,
    index_path: str,
    preserve_metadata: bool = True,
) -> Dict[str, Any]:
    """
    Full reindex of a markdown file.

    If preserve_metadata=True and an existing index exists at index_path,
    it merges per-chunk metadata (tags, is_active, sort_order) from the old
    index into the new one by matching on chunk_type + start_line proximity.
    This is a best-effort match — if the file changed substantially, metadata
    may not carry over cleanly. Checksums are always recomputed from the file.

    Sequence: scan file → build new index → merge metadata → write atomically.
    Returns the new index document.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        raise MdFileNotFoundError(str(p))

    new_doc = md_indexer_build_index_doc(str(p))

    if preserve_metadata and Path(index_path).exists():
        old_doc = bejson_core_load_file(index_path)
        if old_doc:
            new_doc = _merge_metadata(old_doc, new_doc)

    md_indexer_save_index(new_doc, index_path)
    return new_doc

def _merge_metadata(old_doc: Dict[str, Any], new_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort merge of per-chunk metadata from old_doc into new_doc.
    Matches by chunk_id first, falls back to (chunk_type, start_line) proximity.
    """
    old_fi = bejson_core_get_field_map(old_doc)
    new_fi = bejson_core_get_field_map(new_doc)

    old_id_idx    = old_fi.get("chunk_id",   _CHUNK_LEGACY["chunk_id"])
    old_type_idx  = old_fi.get("chunk_type", _CHUNK_LEGACY["chunk_type"])
    old_start_idx = old_fi.get("start_line", _CHUNK_LEGACY["start_line"])
    old_tags_idx  = old_fi.get("tags",       _CHUNK_LEGACY["tags"])
    old_act_idx   = old_fi.get("is_active",  _CHUNK_LEGACY["is_active"])
    old_sort_idx  = old_fi.get("sort_order", _CHUNK_LEGACY["sort_order"])

    new_id_idx    = new_fi.get("chunk_id",   _CHUNK_LEGACY["chunk_id"])
    new_type_idx  = new_fi.get("chunk_type", _CHUNK_LEGACY["chunk_type"])
    new_start_idx = new_fi.get("start_line", _CHUNK_LEGACY["start_line"])
    new_tags_idx  = new_fi.get("tags",       _CHUNK_LEGACY["tags"])
    new_act_idx   = new_fi.get("is_active",  _CHUNK_LEGACY["is_active"])
    new_sort_idx  = new_fi.get("sort_order", _CHUNK_LEGACY["sort_order"])

    # Build lookup: chunk_id -> old row
    old_by_id = {row[old_id_idx]: row for row in old_doc.get("Values", [])}

    # Build lookup: (chunk_type, approx_start) -> old row for proximity matching
    old_by_type_start = {}
    for row in old_doc.get("Values", []):
        key = (row[old_type_idx], row[old_start_idx])
        old_by_type_start[key] = row

    for new_row in new_doc.get("Values", []):
        cid          = new_row[new_id_idx]
        new_type     = new_row[new_type_idx]
        new_start    = new_row[new_start_idx]

        old_row = old_by_id.get(cid)

        if old_row is None:
            # Proximity fallback: same type, closest start line within 5 lines
            best_match = None
            best_dist  = 999
            for (otype, ostart), orow in old_by_type_start.items():
                if otype == new_type:
                    dist = abs(ostart - new_start)
                    if dist < best_dist and dist <= 5:
                        best_dist  = dist
                        best_match = orow
            old_row = best_match

        if old_row is not None:
            # Merge: tags, is_active, sort_order
            if old_row[old_tags_idx] is not None:
                new_row[new_tags_idx] = old_row[old_tags_idx]
            new_row[new_act_idx]  = old_row[old_act_idx]
            new_row[new_sort_idx] = old_row[old_sort_idx]

    return new_doc

def md_indexer_list_chunks(index_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return all chunks from an index document as a list of dicts.
    Convenience for inspection and debugging.
    """
    fi     = bejson_core_get_field_map(index_doc)
    fields = [f["name"] for f in index_doc.get("Fields", [])]
    result = []
    for row in index_doc.get("Values", []):
        item = {}
        for i, name in enumerate(fields):
            item[name] = row[i] if i < len(row) else None
        result.append(item)
    return result

def md_indexer_get_chunk_row(index_doc: Dict[str, Any], chunk_id: str) -> Optional[List]:
    """
    Return the raw row list for a chunk_id, or None if not found.
    """
    fi     = bejson_core_get_field_map(index_doc)
    id_idx = fi.get("chunk_id", _CHUNK_LEGACY["chunk_id"])
    for row in index_doc.get("Values", []):
        if row[id_idx] == chunk_id:
            return row
    return None