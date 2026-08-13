#!/usr/bin/env python3
"""
CLI_Chunker.py
Description:    BEJSON Project Chunker and Rebuilder.
                Chunks a target directory into a flat BEJSON 104a archive using
                the Chunked-104 schema (default), with optional custom
                include/exclude file patterns. The legacy multi-record BEJSON
                104db schema is available as a fallback (--schema 104db, or
                permanently via --toggle-schema, which persists the choice).
                Unchunk supports both schemas and can restore directly to a
                zip file (--zip) instead of loose files on disk.
                Overwrites the previous chunk for the same project — no version folders.
                STANDALONE BUILD: all lib_bejson_* dependency functions are embedded
                directly in this file (see EMBEDDED LIBRARY CODE block below). No
                /lib folder is required to run this script.
Version:        2.5.1
Date:           2026-07-13
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID:  af9c353f-63b4-4a86-ad06-009b858d5a9a
"""

import os
import sys
import json
import time
import base64
import shutil
import hashlib
import logging
import tempfile
import argparse
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

# ── Self-locate ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

# ════════════════════════════════════════════════════════════════════════════
# BEGIN EMBEDDED LIBRARY CODE
# Originally external dependencies loaded from ./lib at runtime. Embedded here
# so this file has zero dependency on the lib/ folder. Original library files
# are left untouched on disk (Library Immutability policy) — this is a merged
# standalone build, not a modification of the source libraries.
#
# Embedded sources:
#   lib_bejson_Core_bejson_env.py        v2.1.2
#   lib_bejson_Core_bejson_errors.py     v2.3.0
#   lib_bejson_Core_bejson_core.py       v2.0.3
#   lib_bejson_Core_bejson_validator.py  v2.0.2
#   lib_bejson_Utility_bejson_utility.py v2.3.2
# ════════════════════════════════════════════════════════════════════════════

# ── lib_bejson_Core_bejson_env.py (v2.1.2) ─────────────────────────────────────

def source_env(override_path: str = None) -> bool:
    """
    Mandatory Environment Sourcing (Section 54).
    Priority: 1. override_path, 2. ENV_FILE_PATH, 3. Android Storage, 4. Home
    """
    env_path = override_path or os.environ.get("ENV_FILE_PATH")
    search_paths = [
        Path(env_path) if env_path else None,
        Path("/storage/emulated/0/env_file.py"),
        Path.home() / "env_file.py"
    ]
    for p in search_paths:
        if p and p.exists():
            try:
                exec(p.read_text(), globals())
                return True
            except Exception:
                continue
    return False

def resolve_path(path_str: str) -> str:
    """
    Resolves system placeholders and absolute paths to environment-relative paths.
    Prioritizes environment variables (ADMIN_ROOT, BEJSON_LIB_ROOT, etc).
    """
    if not path_str:
        return path_str

    # Define standard roots with defaults
    home = os.environ.get("HOME", os.path.expanduser("~"))

    # Storage and Admin Roots
    # Fallback to HOME if storage root is unset to avoid hardcodes.
    storage_root = os.environ.get("BEJSON_STORAGE_ROOT", home)
    admin_root   = os.environ.get("ADMIN_ROOT", os.path.join(storage_root, "Admin"))

    # Library Root Resolution (Admin/libraries fallback to ~/libraries)
    lib_root = os.environ.get("BEJSON_LIB_ROOT")
    if not lib_root:
        candidate_admin = os.path.join(admin_root, "libraries")
        candidate_home  = os.path.join(home, "libraries")
        lib_root = candidate_admin if os.path.exists(candidate_admin) else candidate_home

    mappings = {
        "{BEJSON_LIB_ROOT}": lib_root,
        "{ADMIN_ROOT}": admin_root,
        "{INTERNAL_STORAGE}": storage_root,
        "{HOME}": home
    }

    # Legacy absolute paths to be replaced
    # Only replace if storage_root is explicitly set to avoid "Vanishing Data".
    if os.environ.get("BEJSON_STORAGE_ROOT"):
        mappings["/storage/emulated/0"] = storage_root
        mappings["/data/data/com.termux/files/home"] = home

    resolved = str(path_str)

    # Sort keys by length descending to avoid partial matches (e.g. {HOME}_STUFF)
    for placeholder in sorted(mappings.keys(), key=len, reverse=True):
        actual = mappings[placeholder]
        if actual:
            resolved = resolved.replace(placeholder, actual)

    # Handle home expansion
    resolved = os.path.expanduser(resolved)
    # Handle environment variables in path (e.g. $VAR)
    resolved = os.path.expandvars(resolved)

    return os.path.normpath(resolved)

def get_env_path(env_var: str, default: str) -> str:
    """Retrieves an environment variable and resolves it as a path."""
    val = os.getenv(env_var, default)
    return resolve_path(val)

# ── lib_bejson_Core_bejson_errors.py (v2.3.0) ──────────────────────────────────

# BEJSON Validation (1-16)
E_INVALID_JSON                       = 1
E_MISSING_MANDATORY_KEY              = 2
E_INVALID_FORMAT                     = 3
E_INVALID_VERSION                    = 4
E_INVALID_RECORDS_TYPE                = 5
E_INVALID_FIELDS                     = 6
E_INVALID_VALUES                     = 7
E_TYPE_MISMATCH                      = 8
E_RECORD_LENGTH_MISMATCH             = 9
E_RESERVED_KEY_COLLISION             = 10
E_INVALID_RECORD_TYPE_PARENT         = 11
E_NULL_VIOLATION                     = 12
E_FILE_NOT_FOUND                     = 13
E_PERMISSION_DENIED                  = 14
E_ATOMIC_WRITE_FAILED                = 15
E_INVALID_FORMAT_CREATOR             = 16

# BEJSON Core ops (17-29)
E_CORE_PARSE_ERROR                   = 17
E_CORE_SERIALIZATION_ERROR           = 18
E_CORE_NULL_DOCUMENT                 = 19
E_CORE_INVALID_VERSION               = 20
E_CORE_INVALID_OPERATION             = 21
E_CORE_INDEX_OUT_OF_BOUNDS           = 22
E_CORE_FIELD_NOT_FOUND               = 23
E_CORE_TYPE_CONVERSION_FAILED        = 24
E_CORE_BACKUP_FAILED                 = 25
E_CORE_WRITE_FAILED                  = 26
E_CORE_QUERY_FAILED                  = 27
E_CORE_ENCRYPTION_FAILED             = 28
E_CORE_DECRYPTION_FAILED             = 29

# Aliases
E_CORE_UNSUPPORTED_OPERATION         = E_CORE_INVALID_OPERATION
E_CORE_WRITE_TYPE_MISMATCH           = E_TYPE_MISMATCH
E_CORE_WRITE_LENGTH_MISMATCH         = E_RECORD_LENGTH_MISMATCH

# MFDB Validation (30-42)
E_MFDB_NOT_MANIFEST                  = 30
E_MFDB_NOT_ENTITY_FILE               = 31
E_MFDB_MANIFEST_RECORDS_TYPE         = 32
E_MFDB_ENTITY_NOT_FOUND              = 33
E_MFDB_ENTITY_NAME_MISMATCH          = 34
E_MFDB_DUPLICATE_ENTRY               = 35
E_MFDB_NO_PARENT_HIERARCHY           = 36
E_MFDB_MANIFEST_NOT_FOUND            = 37
E_MFDB_BIDIRECTIONAL_FAIL            = 38
E_MFDB_FK_UNRESOLVED                 = 39
E_MFDB_MISSING_REQUIRED_FIELD        = 40
E_MFDB_NULL_REQUIRED                 = 41
E_MFDB_INVALID_ARCHIVE               = 42

# MFDB Core ops (50-72)
E_MFDB_CORE_MANIFEST_NOT_FOUND       = 50
E_MFDB_CORE_ENTITY_NOT_FOUND         = 51
E_MFDB_CORE_WRITE_FAILED             = 52
E_MFDB_CORE_LOCK_FAILED              = 53
E_MFDB_CORE_INVALID_OPERATION        = 54
E_MFDB_CORE_INDEX_OUT_OF_BOUNDS      = 55
E_MFDB_CORE_JOIN_FAILED              = 56
E_MFDB_CORE_DUPLICATE_ENTITY_NAME    = 57
E_MFDB_CORE_RECORD_COUNT_SYNC_FAILED = 58
E_MFDB_CORE_NULL_MANIFEST            = 59
E_MFDB_CORE_ENTITY_NOT_IN_MANIFEST   = 60
E_MFDB_CORE_ARCHIVE_ERROR            = 70
E_MFDB_CORE_MOUNT_CONFLICT           = 71
E_MFDB_CORE_CREATE_FAILED            = 72

# Core_Nesting (130-159)
E_NESTING_INVALID_CELL               = 130
E_NESTING_NOT_BEJSON                 = 131
E_NESTING_DEPTH_EXCEEDED             = 132
E_NESTING_CACHE_MISS                 = 133
E_NESTING_SCHEMA_MISMATCH            = 134
E_NESTING_CIRCULAR_REF               = 135
E_NESTING_VALIDATION_FAILED          = 136
E_NESTING_FIELD_MAP_FAILED           = 137

# Cognition (270-289)
E_COGNITION_INVALID_MATRIX           = 270
E_COGNITION_AGENT_NOT_FOUND          = 271
E_COGNITION_INDEX_MISSING            = 272
E_COGNITION_PATCH_FAILED             = 273
E_COGNITION_SCHEMA_VIOLATION         = 274
E_COGNITION_LOCK_TIMEOUT             = 275

# ── lib_bejson_Core_bejson_core.py (v2.0.3) ────────────────────────────────────

class BEJSONCoreError(Exception):
    """Raised when a BEJSON core operation fails."""
    def __init__(self, message: str, code: int = None):
        super().__init__(message)
        self.code = code

class ResilientPIDLock:
    def __init__(self, target_path: Union[str, Path], timeout_seconds: int = 10):
        self.target    = Path(target_path)
        self.lock_dir  = Path(f"{target_path}.lockdir")
        self.meta_file = self.lock_dir / "lock_meta.json"
        self.timeout   = timeout_seconds

    def acquire(self) -> bool:
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                self.lock_dir.mkdir(exist_ok=False)
                self.meta_file.write_text(json.dumps({
                    "pid":       os.getpid(),
                    "timestamp": int(time.time())
                }))
                return True
            except FileExistsError:
                if self.meta_file.exists():
                    try:
                        meta      = json.loads(self.meta_file.read_text())
                        owner_pid = meta.get("pid")
                        if owner_pid:
                            os.kill(owner_pid, 0)  # Signal 0: check if alive
                    except (ProcessLookupError, OSError):
                        # Owner is dead — safely reclaim
                        self.release()
                        continue
                    except Exception:
                        pass
                time.sleep(0.1)
        return False

    def release(self):
        if self.meta_file.exists():
            try:
                self.meta_file.unlink()
            except OSError:
                pass
        try:
            self.lock_dir.rmdir()
        except OSError:
            pass

    def __enter__(self):
        if not self.acquire():
            raise OSError(53, "Mutex lock timeout expired (E_MFDB_CORE_LOCK_FAILED)")
        return self

    def __exit__(self, *_):
        self.release()

def bejson_core_load_file(path: str) -> Optional[dict]:
    """Loads a BEJSON file and returns the dictionary."""
    path = resolve_path(path)
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"[BEJSON_CORE] Failed to load {path}: {e}")
        return None

def bejson_core_atomic_write(path: str, data: dict) -> bool:
    """Writes a BEJSON file atomically using a temp file and sync."""
    target_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(target_dir, exist_ok=True)

    # Strip internal metadata keys (starting with _) before write
    clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(clean_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logging.error(f"[BEJSON_CORE] Atomic write failed for {path}: {e}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False

def bejson_core_acquire_lock(file_path: str, timeout: int = 10) -> bool:
    """Acquire a simple directory-based lock."""
    lock_path = file_path + ".lock"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            os.mkdir(lock_path)
            return True
        except FileExistsError:
            time.sleep(0.1)
    return False

def bejson_core_release_lock(file_path: str) -> None:
    """Release the simple directory-based lock."""
    lock_path = file_path + ".lock"
    try:
        os.rmdir(lock_path)
    except OSError:
        pass

# Global Field Map Cache
# Key: tuple of field names (sorted or as-is)
# Value: dict of {name: index}
_FIELD_MAP_CACHE: Dict[tuple, Dict[str, int]] = {}

def bejson_core_get_field_map(doc: dict) -> Dict[str, int]:
    """
    Returns a mapping of field name to index.
    Utilizes both in-document caching and a global cache for performance.
    """
    # High-performance in-document cache check
    if "_bejson_field_map" in doc:
        return doc["_bejson_field_map"]

    fields = doc.get("Fields", [])
    if not fields:
        return {}

    # Create a unique key for this field structure for the global cache
    field_names = tuple(f["name"] for f in fields)
    cache_key = (doc.get("Format_Version"), field_names)

    if cache_key in _FIELD_MAP_CACHE:
        field_map = _FIELD_MAP_CACHE[cache_key]
    else:
        # Build and update global cache
        field_map = {f["name"]: i for i, f in enumerate(fields)}
        _FIELD_MAP_CACHE[cache_key] = field_map

    # Inject into document for subsequent O(1) lookups
    try:
        doc["_bejson_field_map"] = field_map
    except Exception:
        pass # In case doc is immutable or not a dict

    return field_map

def bejson_core_get_field_index(doc: dict, field_name: str) -> int:
    """Returns the positional index of a field name using the cache."""
    field_map = bejson_core_get_field_map(doc)
    return field_map.get(field_name, -1)

def bejson_core_create_104(record_type: str, fields: list, values: list) -> dict:
    return {
        "Format": "BEJSON",
        "Format_Version": "104",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": [record_type],
        "Fields": fields,
        "Values": values
    }

def bejson_core_create_104a(record_type: str, fields: list, values: list, **custom) -> dict:
    doc = {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": [record_type],
        "Fields": fields,
        "Values": values
    }
    doc.update(custom)
    return doc

def bejson_core_create_104db(record_types: list, fields: list, values: list) -> dict:
    return {
        "Format": "BEJSON",
        "Format_Version": "104db",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": record_types,
        "Fields": fields,
        "Values": values
    }

# --- Missing Functions for MFDB and Parser Compatibility ---

def bejson_core_load_string(content: str) -> Optional[dict]:
    try:
        return json.loads(content)
    except Exception as e:
        logging.error(f"[BEJSON_CORE] Failed to load JSON string: {e}")
        return None

def bejson_core_get_record_count(doc: dict) -> int:
    return len(doc.get("Values", []))

def bejson_core_add_record(doc: dict, record: list) -> bool:
    if len(record) != len(doc.get("Fields", [])):
        return False
    doc.setdefault("Values", []).append(record)
    return True

def bejson_core_remove_record(doc: dict, index: int) -> bool:
    values = doc.get("Values", [])
    if 0 <= index < len(values):
        values.pop(index)
        return True
    return False

def bejson_core_update_field(doc: dict, row_index: int, field_name: str, value: Any) -> bool:
    idx = bejson_core_get_field_index(doc, field_name)
    if idx == -1: return False
    values = doc.get("Values", [])
    if 0 <= row_index < len(values):
        values[row_index][idx] = value
        return True
    return False

def bejson_core_filter_rows(doc: dict, field_name: str, value: Any) -> list:
    idx = bejson_core_get_field_index(doc, field_name)
    if idx == -1: return []
    return [row for row in doc.get("Values", []) if row[idx] == value]

def bejson_core_sort_by_field(doc: dict, field_name: str, reverse: bool = False) -> None:
    idx = bejson_core_get_field_index(doc, field_name)
    if idx == -1: return
    doc["Values"].sort(key=lambda x: x[idx] if x[idx] is not None else "", reverse=reverse)

def bejson_core_is_valid(doc: dict) -> bool:
    # Simplified validity check
    required = ["Format", "Format_Version", "Format_Creator", "Records_Type", "Fields", "Values"]
    return all(k in doc for k in required)

def bejson_core_get_version(doc: dict) -> str:
    return doc.get("Format_Version", "unknown")

def bejson_core_get_stats(doc: dict) -> dict:
    return {
        "record_count": bejson_core_get_record_count(doc),
        "field_count": len(doc.get("Fields", [])),
        "version": bejson_core_get_version(doc)
    }

# ── lib_bejson_Core_bejson_validator.py (v2.0.2) ───────────────────────────────

VALID_VERSIONS = {"104", "104a", "104db"}
MANDATORY_KEYS = ("Format", "Format_Version", "Format_Creator", "Records_Type", "Fields", "Values")

@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    current_file: str = ""

    def add_error(self, message: str):
        self.valid = False
        self.errors.append(message)

    def add_warning(self, message: str):
        self.warnings.append(message)

class BEJSONValidationError(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code

def bejson_validator_check_json_syntax(input_, res: ValidationResult, is_file=False):
    if is_file:
        path = Path(input_)
        if not path.exists(): raise BEJSONValidationError(f"File not found: {input_}", E_FILE_NOT_FOUND)
        text = path.read_text(encoding="utf-8")
        res.current_file = str(path)
    else: text = input_
    if isinstance(text, dict): return text
    try: return json.loads(text)
    except Exception as e: raise BEJSONValidationError(f"Invalid JSON: {e}", E_INVALID_JSON)

def bejson_validator_check_mandatory_keys(doc):
    for key in MANDATORY_KEYS:
        if key not in doc: raise BEJSONValidationError(f"Missing key: {key}", E_MISSING_MANDATORY_KEY)
    if doc["Format"] != "BEJSON": raise BEJSONValidationError("Invalid Format", E_INVALID_FORMAT)
    if doc["Format_Creator"] != "Elton Boehnen":
        raise BEJSONValidationError("Invalid Format_Creator: Must be 'Elton Boehnen'", E_INVALID_FORMAT)
    version = doc.get("Format_Version", "")
    if version not in VALID_VERSIONS: raise BEJSONValidationError(f"Invalid version: {version}", E_INVALID_VERSION)
    return version

def bejson_validator_check_records_type(doc, version):
    rt = doc["Records_Type"]
    if not isinstance(rt, list):
        raise BEJSONValidationError("Records_Type must be a list", E_INVALID_RECORDS_TYPE)
    count = len(rt)
    if version in ("104", "104a"):
        if count != 1:
            raise BEJSONValidationError(f"BEJSON {version} must have exactly 1 record type. Found {count}.", E_INVALID_RECORDS_TYPE)
    elif version == "104db":
        if count < 2:
            raise BEJSONValidationError("104db requires 2+ types", E_INVALID_RECORDS_TYPE)

def bejson_validator_check_record_type_parent(doc, version):
    if version != "104db": return True
    fields = doc["Fields"]
    if not fields or fields[0].get("name") != "Record_Type_Parent":
        raise BEJSONValidationError("104db first field must be 'Record_Type_Parent'", E_INVALID_RECORD_TYPE_PARENT)
    valid_types = set(doc["Records_Type"])
    for i, record in enumerate(doc["Values"]):
        if not record: continue
        rtp = record[0]
        if rtp not in valid_types:
            raise BEJSONValidationError(f"Invalid Record_Type_Parent '{rtp}' at row {i}", E_INVALID_RECORD_TYPE_PARENT)
    return True

def bejson_validator_check_fields_structure(doc, version):
    fields = doc["Fields"]
    for i, f in enumerate(fields):
        fname = f.get("name")
        ftype = f.get("type")
        if not fname or not ftype:
            raise BEJSONValidationError(f"Field {i} missing name or type", E_INVALID_FIELDS)
        if version == "104a" and ftype in ("array", "object"):
            raise BEJSONValidationError(f"104a forbids complex type: {ftype}", E_INVALID_FIELDS)
        if version == "104db" and fname != "Record_Type_Parent" and "Record_Type_Parent" not in f:
            raise BEJSONValidationError(f"Field '{fname}' missing Record_Type_Parent in 104db", E_INVALID_RECORD_TYPE_PARENT)
    return len(fields)

def bejson_validator_check_values(doc, version, fields_count):
    fields = doc["Fields"]
    for i, record in enumerate(doc["Values"]):
        if len(record) != fields_count:
            raise BEJSONValidationError(f"Length mismatch at row {i}", E_RECORD_LENGTH_MISMATCH)
        for j, val in enumerate(record):
            ftype = fields[j].get("type")
            if val is None: continue

            # Full type validation including array/object
            if ftype == "string" and not isinstance(val, str):
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected string", E_TYPE_MISMATCH)
            elif ftype == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected integer", E_TYPE_MISMATCH)
            elif ftype == "number" and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                 # bool is a subclass of int in Python, so True/False pass isinstance(int,float).
                 # Explicitly exclude bool — BEJSON "number" means a numeric value, not a boolean.
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected number, got bool", E_TYPE_MISMATCH)
            elif ftype == "boolean" and not isinstance(val, bool):
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected boolean", E_TYPE_MISMATCH)
            elif ftype == "array" and not isinstance(val, list):
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected array", E_TYPE_MISMATCH)
            elif ftype == "object" and not isinstance(val, dict):
                 raise BEJSONValidationError(f"Type mismatch at row {i}, col {j} ({fields[j]['name']}): expected object", E_TYPE_MISMATCH)

def bejson_validator_check_custom_headers(doc, version):
    mandatory_set = set(MANDATORY_KEYS)
    for key in doc:
        if key in mandatory_set or key == "Parent_Hierarchy": continue
        if version in ("104", "104db"):
            raise BEJSONValidationError(f"Custom key '{key}' forbidden in {version}", E_RESERVED_KEY_COLLISION)
        # 104a: Custom headers allowed, no strict PascalCase enforcement
        # Audit 2 Finding: Removed warning to avoid conflict with 104db rigidity.

def validate_bejson(input_data: Union[str, dict], is_file: bool = False) -> ValidationResult:
    """Thread-safe validation. Returns a ValidationResult object."""
    res = ValidationResult()
    try:
        doc = bejson_validator_check_json_syntax(input_data, res, is_file=is_file)
        version = bejson_validator_check_mandatory_keys(doc)
        bejson_validator_check_custom_headers(doc, version)
        bejson_validator_check_records_type(doc, version)
        bejson_validator_check_record_type_parent(doc, version)
        fields_count = bejson_validator_check_fields_structure(doc, version)
        bejson_validator_check_values(doc, version, fields_count)
    except BEJSONValidationError as e:
        res.add_error(str(e))
    except Exception as e:
        res.add_error(f"Unexpected validation error: {e}")
    return res

def bejson_validator_get_report(input_data, is_file: bool = False) -> str:
    """Return a human-readable validation report string."""
    res = validate_bejson(input_data, is_file=is_file)
    lines = ["BEJSON Validation Report"]
    lines.append("  File: " + (res.current_file or "<string>"))
    lines.append("  Valid: " + str(res.valid))
    if res.errors:
        lines.append("  Errors:")
        for e in res.errors:
            lines.append("    - " + e)
    if res.warnings:
        lines.append("  Warnings:")
        for w in res.warnings:
            lines.append("    - " + w)
    return "\n".join(lines)

# Compatibility wrappers (now internal state is gone)
def bejson_validator_validate_string(json_string):
    res = validate_bejson(json_string)
    if not res.valid:
        raise BEJSONValidationError(res.errors[0], E_INVALID_FORMAT)
    return True

def bejson_validator_validate_file(file_path):
    res = validate_bejson(file_path, is_file=True)
    if not res.valid:
        raise BEJSONValidationError(res.errors[0], E_INVALID_FORMAT)
    return True

# ── lib_bejson_Utility_bejson_utility.py (v2.3.2) ──────────────────────────────

DEFAULT_EXTENSIONS = [".py", ".js", ".ts", ".html", ".css", ".md", ".json", ".sh", ".txt", ".bejson", ".tsx", ".jsx"]
DEFAULT_EXCLUDES = [".git", "__pycache__", "node_modules", "lib", "output", ".mfdb_lock", "dist", "build"]

# Text Chunk Separators (Standardized)
SEP_START = "--- FILE: "
SEP_END = " ---"

# Official CLI_CHUNKER Schema (BEJSON 104db)
SCHEMA_CLI_CHUNKER = [
    {"name": "Record_Type_Parent", "type": "string"},
    {"name": "project_name", "type": "string", "Record_Type_Parent": "ProjectMeta"},
    {"name": "version", "type": "string", "Record_Type_Parent": "ProjectMeta"},
    {"name": "root_path", "type": "string", "Record_Type_Parent": "ProjectMeta"},
    {"name": "file_path", "type": "string", "Record_Type_Parent": "FileContent"},
    {"name": "file_name", "type": "string", "Record_Type_Parent": "FileContent"},
    {"name": "content", "type": "string", "Record_Type_Parent": "FileContent"},
    {"name": "is_binary", "type": "boolean", "Record_Type_Parent": "FileContent"}
]

# Official MFDB_V5 Entity Schema (BEJSON 104)
SCHEMA_MFDB_ENTITY = [
    {"name": "version",   "type": "string"},
    {"name": "file_path", "type": "string"},
    {"name": "file_name", "type": "string"},
    {"name": "content",   "type": "string"},
    {"name": "is_binary", "type": "boolean"},
    {"name": "is_base64", "type": "boolean"},
]

def bejson_utility_sanitize_name(name: str) -> str:
    """Sanitizes names for filesystem safety without using regex."""
    invalid = '<>:"/\\|?*'
    sanitized = name
    for char in invalid:
        sanitized = sanitized.replace(char, '_')
    return sanitized

def bejson_utility_slugify(text: str) -> str:
    """Creates a simple lowercase alphanumeric slug without regex."""
    slug = ""
    for char in text.lower():
        if char.isalnum():
            slug += char
        elif char in " -_":
            slug += "_"
    return slug

def bejson_utility_is_binary(file_path: Union[str, Path]) -> bool:
    """Detection logic matching official chunker tools."""
    try:
        with open(file_path, 'tr', encoding='utf-8') as f:
            f.read(1024)
            return False
    except (UnicodeDecodeError, PermissionError):
        return True

def bejson_utility_encode_file(file_path: Union[str, Path], use_base64: bool = False) -> tuple:
    """
    Reads file content and returns (content, is_binary, is_base64).
    Matches MFDB v5 lossless binary logic.
    """
    is_bin = bejson_utility_is_binary(file_path)
    if not is_bin:
        try:
            return Path(file_path).read_text(encoding="utf-8"), False, False
        except Exception:
            return "", True, False

    if use_base64:
        try:
            raw = Path(file_path).read_bytes()
            return base64.b64encode(raw).decode('utf-8'), True, True
        except Exception:
            return "", True, True

    return "", True, False

def bejson_utility_create_cli_chunk(target_dir: str, project_name: str, version: str) -> dict:
    """Generates a BEJSON 104db document compatible with Cli_Chunker."""
    target_path = Path(target_dir).resolve()
    values = []

    # Dynamic Field Mapping for Creation (Phase 7.3.4)
    fm = {f["name"]: i for i, f in enumerate(SCHEMA_CLI_CHUNKER)}
    f_count = len(SCHEMA_CLI_CHUNKER)

    # Meta record
    meta_row = [None] * f_count
    meta_row[fm["Record_Type_Parent"]] = "ProjectMeta"
    meta_row[fm["project_name"]]       = project_name
    meta_row[fm["version"]]            = version
    meta_row[fm["root_path"]]          = str(target_path)
    values.append(meta_row)

    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for file in files:
            f_path = Path(root) / file
            if f_path.suffix.lower() in DEFAULT_EXTENSIONS:
                try:
                    rel_path = f_path.relative_to(target_path)
                    content, binary, _ = bejson_utility_encode_file(f_path, use_base64=False)

                    file_row = [None] * f_count
                    file_row[fm["Record_Type_Parent"]] = "FileContent"
                    file_row[fm["file_path"]]          = str(rel_path)
                    file_row[fm["file_name"]]          = file
                    file_row[fm["content"]]            = content
                    file_row[fm["is_binary"]]          = binary
                    values.append(file_row)
                except Exception: continue

    return bejson_core_create_104db(["ProjectMeta", "FileContent"], SCHEMA_CLI_CHUNKER, values)

def bejson_utility_create_mfdb_version(target_dir: str, version: str, use_base64: bool = True) -> list:
    """
    Generates a list of values for an MFDB v5 Entity file (BEJSON 104).
    """
    target_path = Path(target_dir).resolve()
    rows = []

    fm = {f["name"]: i for i, f in enumerate(SCHEMA_MFDB_ENTITY)}
    f_count = len(SCHEMA_MFDB_ENTITY)

    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for file in files:
            f_path = Path(root) / file
            if f_path.suffix.lower() in DEFAULT_EXTENSIONS:
                try:
                    rel_path = f_path.relative_to(target_path)
                    content, binary, b64 = bejson_utility_encode_file(f_path, use_base64=use_base64)

                    row = [None] * f_count
                    row[fm["version"]]   = version
                    row[fm["file_path"]] = str(rel_path)
                    row[fm["file_name"]] = file
                    row[fm["content"]]   = content
                    row[fm["is_binary"]] = binary
                    row[fm["is_base64"]] = b64
                    rows.append(row)
                except Exception: continue

    return rows

def bejson_utility_chunk_to_text(target_dir: str) -> str:
    """Concatenates files into a single text block with separators."""
    target_path = Path(target_dir).resolve()
    output = []

    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for file in files:
            f_path = Path(root) / file
            if f_path.suffix.lower() in DEFAULT_EXTENSIONS and not bejson_utility_is_binary(f_path):
                try:
                    rel_path = f_path.relative_to(target_path)
                    content = f_path.read_text(encoding="utf-8")
                    output.append(f"{SEP_START}{rel_path}{SEP_END}")
                    output.append(content)
                    output.append("\n")
                except Exception: continue

    return "\n".join(output)

def bejson_utility_unchunk_from_text(text: str, output_dir: str) -> int:
    """Restores files from a text block using strictly string splitting."""
    count = 0
    out_root = Path(output_dir).resolve()

    # Split by the start separator
    parts = text.split(SEP_START)

    for part in parts:
        if not part.strip(): continue

        # Each part starts with: filename --- content
        if SEP_END in part:
            header, content = part.split(SEP_END, 1)
            rel_path = header.strip()

            if rel_path:
                target_file = out_root / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content.lstrip("\n"), encoding="utf-8")
                count += 1

    return count

def bejson_utility_parse_json(text: str) -> Any:
    """Robust JSON parsing using strictly the json module."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Best practice: try to find the actual JSON object in a dirty string
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise

def bejson_utility_save_chunk(path: str, doc: dict) -> bool:
    """Standardized atomic write for all chunking operations."""
    return bejson_core_atomic_write(path, doc)

def bejson_utility_get_timestamp() -> str:
    """ISO 8601 UTC timestamp for manifest consistency."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# ── Chunked-104 schema (optional 104a chunk mode, added 2026-07-10) ────────────
# Matches Chunked-104a_Template.bejson.json — a flat, one-record-per-file BEJSON
# 104a schema, offered as an opt-in alternative to the default 104db schema above.

CHUNKED_104_FIELDS = [
    {"name": "File_Name",      "type": "string"},
    {"name": "File_Extension", "type": "string"},
    {"name": "File_Content",   "type": "string"},
    {"name": "File_Version",   "type": "string"},
    {"name": "File_Hash",      "type": "string"},
    {"name": "Relative_Path",  "type": "string"},
    {"name": "Is_Binary",      "type": "boolean"},
    {"name": "Is_Mounted",     "type": "boolean"},
]

def bejson_utility_hash_file_bytes(raw_bytes: bytes) -> str:
    """SHA-1 hash (hex digest) used for the Chunked-104 schema's File_Hash field."""
    return hashlib.sha1(raw_bytes).hexdigest()

def bejson_utility_create_chunked_104(target_dir: str, version: str = "latest",
                                       extensions: Optional[List[str]] = None,
                                       exclude_dirs: Optional[List[str]] = None) -> dict:
    """
    Generates a BEJSON 104a document matching the Chunked-104 schema template:
    one flat record per file (File_Name/File_Extension/File_Content/File_Version/
    File_Hash/Relative_Path/Is_Binary/Is_Mounted).

    extensions/exclude_dirs let the caller override DEFAULT_EXTENSIONS /
    DEFAULT_EXCLUDES with custom patterns for this run only; pass None to use
    the existing defaults.
    """
    target_path = Path(target_dir).resolve()
    exts = extensions if extensions is not None else DEFAULT_EXTENSIONS
    excl = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDES

    values = []
    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in excl]
        for file in files:
            f_path = Path(root) / file
            if f_path.suffix.lower() in exts:
                try:
                    rel_path = f_path.relative_to(target_path)
                    is_bin   = bejson_utility_is_binary(f_path)
                    if is_bin:
                        raw_bytes = f_path.read_bytes()
                        content   = ""
                    else:
                        raw_bytes = f_path.read_bytes()
                        content   = f_path.read_text(encoding="utf-8")
                    file_hash = bejson_utility_hash_file_bytes(raw_bytes)

                    values.append([
                        f_path.name,      # File_Name
                        f_path.suffix,    # File_Extension
                        content,          # File_Content
                        version,          # File_Version
                        file_hash,        # File_Hash
                        str(rel_path),    # Relative_Path
                        is_bin,           # Is_Binary
                        False,            # Is_Mounted (per-file; not a live mount)
                    ])
                except Exception:
                    continue

    return {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Schema_Name": "Chunked-104a",
        "Schema_Version": "1.0.1",
        "Schema_Description": "Standard schema for chunking single projects.",
        "Chunk_Date-YYYY-MM-DD": bejson_utility_get_timestamp()[:10],
        "Is_Mounted": "False",
        "Mount_Path": "",
        "Records_Type": ["Chunked"],
        "Fields": CHUNKED_104_FIELDS,
        "Values": values,
    }

# ── Namespace shims ─────────────────────────────────────────────────────────────
# The remainder of this file (unchanged from the original CLI_Chunker.py body)
# calls into BEJSONCore.*, Validator.*, and Utility.* exactly as it did when
# these were separate imported modules. These shims preserve that call surface
# without touching the logic below.

BEJSONCore = types.SimpleNamespace(
    BEJSONCoreError=BEJSONCoreError,
    ResilientPIDLock=ResilientPIDLock,
    bejson_core_load_file=bejson_core_load_file,
    bejson_core_atomic_write=bejson_core_atomic_write,
    bejson_core_acquire_lock=bejson_core_acquire_lock,
    bejson_core_release_lock=bejson_core_release_lock,
    bejson_core_get_field_map=bejson_core_get_field_map,
    bejson_core_get_field_index=bejson_core_get_field_index,
    bejson_core_create_104=bejson_core_create_104,
    bejson_core_create_104a=bejson_core_create_104a,
    bejson_core_create_104db=bejson_core_create_104db,
    bejson_core_load_string=bejson_core_load_string,
    bejson_core_get_record_count=bejson_core_get_record_count,
    bejson_core_add_record=bejson_core_add_record,
    bejson_core_remove_record=bejson_core_remove_record,
    bejson_core_update_field=bejson_core_update_field,
    bejson_core_filter_rows=bejson_core_filter_rows,
    bejson_core_sort_by_field=bejson_core_sort_by_field,
    bejson_core_is_valid=bejson_core_is_valid,
    bejson_core_get_version=bejson_core_get_version,
    bejson_core_get_stats=bejson_core_get_stats,
)

Validator = types.SimpleNamespace(
    ValidationResult=ValidationResult,
    BEJSONValidationError=BEJSONValidationError,
    validate_bejson=validate_bejson,
    bejson_validator_get_report=bejson_validator_get_report,
    bejson_validator_validate_string=bejson_validator_validate_string,
    bejson_validator_validate_file=bejson_validator_validate_file,
)

Utility = types.SimpleNamespace(
    DEFAULT_EXTENSIONS=DEFAULT_EXTENSIONS,
    DEFAULT_EXCLUDES=DEFAULT_EXCLUDES,
    SCHEMA_CLI_CHUNKER=SCHEMA_CLI_CHUNKER,
    SCHEMA_MFDB_ENTITY=SCHEMA_MFDB_ENTITY,
    bejson_utility_sanitize_name=bejson_utility_sanitize_name,
    bejson_utility_slugify=bejson_utility_slugify,
    bejson_utility_is_binary=bejson_utility_is_binary,
    bejson_utility_encode_file=bejson_utility_encode_file,
    bejson_utility_create_cli_chunk=bejson_utility_create_cli_chunk,
    bejson_utility_create_mfdb_version=bejson_utility_create_mfdb_version,
    bejson_utility_chunk_to_text=bejson_utility_chunk_to_text,
    bejson_utility_unchunk_from_text=bejson_utility_unchunk_from_text,
    bejson_utility_parse_json=bejson_utility_parse_json,
    bejson_utility_save_chunk=bejson_utility_save_chunk,
    bejson_utility_get_timestamp=bejson_utility_get_timestamp,
    CHUNKED_104_FIELDS=CHUNKED_104_FIELDS,
    bejson_utility_hash_file_bytes=bejson_utility_hash_file_bytes,
    bejson_utility_create_chunked_104=bejson_utility_create_chunked_104,
)

# ════════════════════════════════════════════════════════════════════════════
# END EMBEDDED LIBRARY CODE
# ════════════════════════════════════════════════════════════════════════════

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECTS_DIR  = BASE_DIR / "Projects"
HISTORY_FILE  = BASE_DIR / "data" / "chunk_history.104a.bejson"
REGISTRY_FILE = BASE_DIR / "data" / "project_registry.104a.bejson"
SCHEMA_CONFIG_FILE = BASE_DIR / "data" / "chunker_config.104a.bejson"

# ── Schema ─────────────────────────────────────────────────────────────────────
HISTORY_FIELDS = [
    {"name": "timestamp",    "type": "string"},
    {"name": "project_name", "type": "string"},
    {"name": "file_path",    "type": "string"},
]

REGISTRY_FIELDS = [
    {"name": "project_name",  "type": "string"},
    {"name": "original_path", "type": "string"},
    {"name": "last_chunked",  "type": "string"},
]

DEFAULT_CONFIG = {
    "extensions":  Utility.DEFAULT_EXTENSIONS,
    "exclude_dirs": Utility.DEFAULT_EXCLUDES,
    "evade_mime":  True,
}

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_timestamp():
    return Utility.bejson_utility_get_timestamp()

def _ensure_data_dir():
    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

def _parse_csv_patterns(raw):
    """Splits a comma-separated CLI arg into a clean list, or None if unset."""
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]

# ── Persistent schema toggle ────────────────────────────────────────────────────
SCHEMA_CONFIG_FIELDS = [
    {"name": "Default_Schema", "type": "string"},
]

def load_default_schema() -> str:
    """
    Reads the persisted default schema ("104" or "104db"). Falls back to
    "104" (Chunked-104) if the config file doesn't exist yet or is unreadable —
    matches the current out-of-the-box default.
    """
    if not SCHEMA_CONFIG_FILE.exists():
        return "104"
    try:
        doc    = BEJSONCore.bejson_core_load_file(str(SCHEMA_CONFIG_FILE))
        values = doc.get("Values", [])
        if values and values[0][0] in ("104", "104db"):
            return values[0][0]
    except Exception:
        pass
    return "104"

def save_default_schema(schema_value: str) -> None:
    _ensure_data_dir()
    doc = BEJSONCore.bejson_core_create_104a("ChunkerConfig", SCHEMA_CONFIG_FIELDS, [[schema_value]])
    BEJSONCore.bejson_core_atomic_write(str(SCHEMA_CONFIG_FILE), doc)

def toggle_default_schema() -> None:
    """Flips the persisted default schema between '104' and '104db' and reports the new state."""
    current = load_default_schema()
    new_value = "104db" if current == "104" else "104"
    save_default_schema(new_value)
    label = "Chunked-104 (104a)" if new_value == "104" else "legacy 104db"
    print(f"[*] Default chunk schema toggled: {current} -> {new_value}")
    print(f"[*] --chunk will now use {label} by default until toggled again.")

# ── Registry ───────────────────────────────────────────────────────────────────
def save_to_registry(project_name, original_path):
    _ensure_data_dir()
    registry = []
    if REGISTRY_FILE.exists():
        try:
            doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
            registry = doc.get("Values", [])
        except Exception:
            pass

    found = False
    for i, row in enumerate(registry):
        if row[0] == project_name:
            registry[i][1] = str(original_path)
            registry[i][2] = get_timestamp()
            found = True
            break

    if not found:
        registry.append([project_name, str(original_path), get_timestamp()])

    doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, registry)
    BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)

def save_to_history(project_name, file_path):
    _ensure_data_dir()
    history = []
    if HISTORY_FILE.exists():
        try:
            doc = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
            history = doc.get("Values", [])
        except Exception:
            pass

    history.insert(0, [get_timestamp(), project_name, str(file_path)])
    history = history[:100]

    doc = BEJSONCore.bejson_core_create_104a("ChunkHistory", HISTORY_FIELDS, history)
    BEJSONCore.bejson_core_atomic_write(str(HISTORY_FILE), doc)

# ── Listing ────────────────────────────────────────────────────────────────────
def list_chunk_index():
    if not REGISTRY_FILE.exists():
        print("No project registry found.")
        return
    try:
        doc    = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if not values:
            print("Registry is empty.")
            return
        print(f"\n{'ID':<4} | {'Project Name':<28} | {'Last Chunked':<22} | Source Path")
        print("-" * 110)
        for i, row in enumerate(values, 1):
            name, path, last = row
            print(f"{i:<4} | {name:<28} | {last:<22} | {path}")
    except Exception as e:
        print(f"Error reading registry: {e}")

def list_unchunk_index():
    if not HISTORY_FILE.exists():
        print("No chunk history found.")
        return
    try:
        doc    = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
        values = doc.get("Values", [])
        if not values:
            print("History is empty.")
            return
        print(f"\n{'ID':<4} | {'Timestamp':<22} | {'Project':<25} | Chunk Path")
        print("-" * 110)
        for i, row in enumerate(values, 1):
            ts, proj, path = row[0], row[1], row[-1]
            print(f"{i:<4} | {ts:<22} | {proj:<25} | {path}")
    except Exception as e:
        print(f"Error reading history: {e}")

# ── Resolution helpers ─────────────────────────────────────────────────────────
def resolve_registry_path(index_str):
    if not REGISTRY_FILE.exists():
        return None
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            return values[idx][1]
    except Exception:
        pass
    return None

def resolve_history_path(index_str):
    if not HISTORY_FILE.exists():
        return None
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            return values[idx][-1]
    except Exception:
        pass
    return None

# ── Registry management ────────────────────────────────────────────────────────
def expell_project(index_str):
    if not REGISTRY_FILE.exists():
        print("Error: No project registry found.")
        return
    try:
        idx    = int(index_str) - 1
        doc    = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            removed = values.pop(idx)
            print(f"[*] Expelled: {removed[0]} (registry entry removed, files on disk preserved)")
            doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, values)
            BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)
        else:
            print(f"Error: Project ID {index_str} not found.")
    except Exception as e:
        print(f"Error expelling project: {e}")

def delete_project(index_str):
    if not REGISTRY_FILE.exists():
        print("Error: No project registry found.")
        return
    try:
        idx    = int(index_str) - 1
        doc    = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            removed      = values.pop(idx)
            project_name = removed[0]
            print(f"[*] Deleting project: {project_name}")
            doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, values)
            BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)
            project_dir = PROJECTS_DIR / project_name
            if project_dir.exists():
                shutil.rmtree(project_dir)
                print(f"[*] Deleted files at: {project_dir}")
            else:
                print(f"Warning: Project folder not found at {project_dir}")
        else:
            print(f"Error: Project ID {index_str} not found.")
    except Exception as e:
        print(f"Error deleting project: {e}")

# ── Core operations ────────────────────────────────────────────────────────────
def run_chunk(target_dir, schema="104", extensions=None, exclude_dirs=None):
    """
    schema: "104" (default — Chunked-104 flat schema, see Chunked-104a_Template.bejson.json)
            or "104db" (fallback — legacy multi-record archive format).
    extensions/exclude_dirs: optional custom include/exclude pattern lists that
            override DEFAULT_EXTENSIONS/DEFAULT_EXCLUDES for this run only.
            Only honored when schema="104" — the 104db path is unchanged.
    """
    target_path  = Path(target_dir).resolve()
    if not target_path.is_dir():
        print(f"Error: {target_dir} is not a directory.")
        return

    project_name = target_path.name.replace(" ", "_")
    project_dir  = PROJECTS_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    evade_txt = ".txt" if DEFAULT_CONFIG.get("evade_mime") else ""

    if schema == "104":
        ext      = ".104a.bejson" + evade_txt
        out_file = project_dir / f"Chunked_{Utility.bejson_utility_sanitize_name(project_name)}{ext}"

        print(f"[*] Mode: CHUNK (104 — Chunked-104 schema)")
        print(f"[*] Project: {project_name}")
        print(f"[*] Target:  {target_path}")
        print(f"[*] Output:  {out_file}")
        if extensions is not None:
            print(f"[*] Custom extensions: {extensions}")
        if exclude_dirs is not None:
            print(f"[*] Custom excludes:   {exclude_dirs}")

        doc = Utility.bejson_utility_create_chunked_104(
            target_dir=str(target_path),
            version="latest",
            extensions=extensions,
            exclude_dirs=exclude_dirs,
        )
    else:
        ext      = ".104db.bejson" + evade_txt
        out_file = project_dir / f"Chunked_{Utility.bejson_utility_sanitize_name(project_name)}{ext}"

        print(f"[*] Mode: CHUNK (104db)")
        print(f"[*] Project: {project_name}")
        print(f"[*] Target:  {target_path}")
        print(f"[*] Output:  {out_file}")

        doc = Utility.bejson_utility_create_cli_chunk(
            target_dir=str(target_path),
            project_name=project_name,
            version="latest",
        )

    print("[*] Validating BEJSON structure...")
    res = Validator.validate_bejson(doc)
    if not res.valid:
        print("\n[ERROR] BEJSON Validation Failed:")
        for err in res.errors:
            print(f"  - {err}")
        return

    if Utility.bejson_utility_save_chunk(str(out_file), doc):
        print(f"\n[SUCCESS] Chunked → {out_file}")
        print(f"[*] Records: {len(doc['Values'])}")
        save_to_registry(project_name, target_path)
        save_to_history(project_name, out_file)
    else:
        print("[ERROR] Failed to save BEJSON chunk.")

def _derive_project_name_from_chunk_filename(input_path: Path) -> str:
    """
    Chunked-104 (104a) has no project_name field, so the name is derived from
    the chunk filename itself, stripping known suffixes/prefixes.
    """
    name = input_path.name
    known_suffixes = (".txt", ".bejson", ".104a", ".104db")
    changed = True
    while changed:
        changed = False
        for suf in known_suffixes:
            if name.endswith(suf):
                name = name[: -len(suf)]
                changed = True
    if name.startswith("Chunked_"):
        name = name[len("Chunked_"):]
    return name or "RestoredProject"

def run_unchunk(bejson_file, destination=None, zip_output=False):
    input_path = Path(bejson_file).resolve()
    if not input_path.exists():
        print(f"Error: File not found: {bejson_file}")
        return

    print(f"[*] Mode: UNCHUNK")
    print(f"[*] Source: {input_path}")

    try:
        print("[*] Validating BEJSON structure...")
        res = Validator.validate_bejson(str(input_path), is_file=True)
        if not res.valid:
            print("\n[ERROR] BEJSON Validation Failed:")
            for err in res.errors:
                print(f"  - {err}")
            return

        doc     = BEJSONCore.bejson_core_load_file(str(input_path))
        version = doc.get("Format_Version")

        if version == "104db":
            fields    = [f["name"] for f in doc["Fields"]]
            pname_idx = fields.index("project_name")
            fpath_idx = fields.index("file_path")
            cont_idx  = fields.index("content")
            bin_idx   = fields.index("is_binary")

            meta_rows = [r for r in doc["Values"] if r[0] == "ProjectMeta"]
            proj_name = meta_rows[0][pname_idx] if meta_rows else "RestoredProject"
            file_rows = [r for r in doc["Values"] if r[0] == "FileContent"]
            records   = [(r[fpath_idx], r[cont_idx], r[bin_idx]) for r in file_rows]

        elif version == "104a" and doc.get("Schema_Name") in ("Chunked-104a", "Chunked-104"):
            # Accepts both the corrected name ("Chunked-104a") and the old buggy
            # name ("Chunked-104") so chunks already produced before this fix
            # still unchunk cleanly.
            fields    = [f["name"] for f in doc["Fields"]]
            fpath_idx = fields.index("Relative_Path")
            cont_idx  = fields.index("File_Content")
            bin_idx   = fields.index("Is_Binary")

            proj_name = _derive_project_name_from_chunk_filename(input_path)
            records   = [(r[fpath_idx], r[cont_idx], r[bin_idx]) for r in doc["Values"]]

        else:
            print(f"Error: Unrecognized chunk schema (Format_Version={version}, "
                  f"Schema_Name={doc.get('Schema_Name')}). Expected 104db or Chunked-104a.")
            return

        if destination:
            out_dir = Path(destination).resolve()
        else:
            ts_slug = get_timestamp().replace(":", "").replace("-", "")
            out_dir = Path.cwd() / "Restored_Projects" / proj_name / ts_slug

        out_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content, binary in records:
            if rel_path:
                target_file = out_dir / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if binary:
                    target_file.touch()
                else:
                    target_file.write_text(content, encoding="utf-8")
                print(f"  [>] {rel_path}")

        print(f"\n[SUCCESS] Rebuilt at {out_dir}")

        if zip_output:
            zip_path_str = shutil.make_archive(str(out_dir), "zip", root_dir=str(out_dir))
            shutil.rmtree(out_dir)
            print(f"[SUCCESS] Zipped → {zip_path_str}")

    except Exception as e:
        print(f"\n[ERROR] Unchunking failed: {e}")

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="CLI_Chunker",
        description="CLI_Chunker v2.3.0 — BEJSON Project Chunker & Rebuilder (standalone build, Chunked-104 default schema)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chunk",              metavar="DIR",  help="Chunk a directory (overwrites previous)")
    group.add_argument("--chunk-index",        metavar="ID",   help="Chunk a registered project by ID")
    group.add_argument("--unchunk",            metavar="FILE", help="Unchunk a BEJSON 104db file")
    group.add_argument("--unchunk-index",      metavar="ID",   help="Unchunk a historical chunk by ID")
    group.add_argument("--list-chunk-index",   action="store_true", help="List registered projects")
    group.add_argument("--list-project-index", action="store_true", help="Alias for --list-chunk-index")
    group.add_argument("--list-unchunk-index", action="store_true", help="List chunk history")
    group.add_argument("--expell-project",     metavar="ID",   help="Remove project from registry (files kept)")
    group.add_argument("--delete-project",     metavar="ID",   help="Remove project from registry and delete files")
    group.add_argument("--toggle-schema",      action="store_true",
                        help="Toggle the persisted default chunk schema between '104' (Chunked-104) "
                             "and '104db'. Remembered across runs until toggled again.")

    parser.add_argument("--dest", metavar="DIR", help="Custom output directory for --unchunk")
    parser.add_argument("--zip", action="store_true",
                         help="For --unchunk/--unchunk-index: zip the restored output instead of "
                              "leaving loose files on disk (produces <dest>.zip, removes the loose folder).")
    parser.add_argument("--schema", choices=["104db", "104"], default=None,
                         help="One-off override of the schema for this --chunk / --chunk-index run "
                              "(default: uses the persisted toggle set by --toggle-schema, '104' out of the box). "
                              "'104db' is the legacy multi-record format. --patterns/--exclude-patterns apply to '104' only.")
    parser.add_argument("--patterns", metavar="EXT_LIST",
                         help="Comma-separated custom file extensions to include, e.g. '.py,.md' "
                              "(only used with --schema 104; overrides the default extension list).")
    parser.add_argument("--exclude-patterns", metavar="DIR_LIST",
                         help="Comma-separated custom directory names to exclude, e.g. '.git,dist' "
                              "(only used with --schema 104; overrides the default exclude list).")

    args = parser.parse_args()

    custom_extensions   = _parse_csv_patterns(args.patterns)
    custom_exclude_dirs = _parse_csv_patterns(args.exclude_patterns)
    effective_schema     = args.schema if args.schema is not None else load_default_schema()

    if args.toggle_schema:
        toggle_default_schema()
    elif args.list_chunk_index or args.list_project_index:
        list_chunk_index()
    elif args.list_unchunk_index:
        list_unchunk_index()
    elif args.chunk:
        run_chunk(args.chunk, schema=effective_schema, extensions=custom_extensions, exclude_dirs=custom_exclude_dirs)
    elif args.chunk_index:
        source_path = resolve_registry_path(args.chunk_index)
        if source_path:
            run_chunk(source_path, schema=effective_schema, extensions=custom_extensions, exclude_dirs=custom_exclude_dirs)
        else:
            print(f"Error: Project ID {args.chunk_index} not found in registry.")
    elif args.unchunk:
        run_unchunk(args.unchunk, args.dest, zip_output=args.zip)
    elif args.unchunk_index:
        chunk_path = resolve_history_path(args.unchunk_index)
        if chunk_path:
            run_unchunk(chunk_path, args.dest, zip_output=args.zip)
        else:
            print(f"Error: Chunk ID {args.unchunk_index} not found in history.")
    elif args.expell_project:
        expell_project(args.expell_project)
    elif args.delete_project:
        delete_project(args.delete_project)


if __name__ == "__main__":
    main()
