#!/usr/bin/env python3
"""
Name: validate_104_gate.py
Description: Layer 2 deterministic stage-gate validator for Foundational Era BEJSON 104, 104a,
             and 104db documents. Binds dynamically to libraries_104 (Release 300), enforces
             boundary-layer sanitization, O(1) field_map cache checks, POL-002 104a primitive-only
             conformance, and rejects Format 105 documents (redirecting to bejson-105-validator).
Version: 100
Release_Version: 300
Date Created: 2026-10-17
Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID: c014a892-5d31-4b27-9f18-4e6c9a21b304
"""

from __future__ import annotations
import sys

if sys.version_info < (3, 10):
    sys.stderr.write("validate_104_gate requires Python 3.10 or newer.\n")
    sys.exit(20)

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

VERSION: int = 100
RELEASE_VERSION: int = 300
RELATIONAL_ID: str = "c014a892-5d31-4b27-9f18-4e6c9a21b304"

EXIT_OK: int = 0
EXIT_PATH_FAILURE: int = 10
EXIT_ENV_FAILURE: int = 20
EXIT_SCHEMA_FAILURE: int = 30


def get_script_path() -> Path:
    return Path(__file__).resolve().parent


SCRIPT_PATH: Path = get_script_path()
BUNDLE_ROOT: Path = SCRIPT_PATH.parent
CONFIG_PATH: Path = BUNDLE_ROOT / "config" / "config.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
LOG = logging.getLogger("validate_104_gate")


def bejson_boundary_sanitize(raw: Any) -> Any:
    """Enforce Policy §10.9 boundary-layer whitespace stripping on keys and string values."""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        return [bejson_boundary_sanitize(item) for item in raw]
    if isinstance(raw, dict):
        return {str(k).strip(): bejson_boundary_sanitize(v) for k, v in raw.items()}
    return raw


def bejson_get_field_map(doc: dict[str, Any]) -> dict[str, int]:
    """Enforce Policy §6.2 mandatory O(1) Field Map Cache."""
    fields = doc.get("Fields", [])
    return {str(f["name"]).strip(): idx for idx, f in enumerate(fields) if isinstance(f, dict) and "name" in f}


def ensure_config_104a() -> dict[str, Any]:
    """Generate or load BEJSON 104a ScriptConfig per Policy §4.4."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default_cfg = {
            "Format": "BEJSON",
            "Format_Version": "104a",
            "Format_Creator": "Elton Boehnen",
            "Records_Type": ["ScriptConfig"],
            "Fields": [
                {"name": "setting_name", "type": "string"},
                {"name": "setting_value", "type": "string"},
                {"name": "description", "type": "string"},
            ],
            "Values": [
                ["local_lib_directory", "lib/", "Relative path to local dep folder."],
                ["master_lib_source", "$ADMIN_LIBRARIES", "Fallback if local lib missing."],
                ["log_level", "INFO", "Default log level."],
            ],
        }
        CONFIG_PATH.write_text(json.dumps(default_cfg, indent=2) + "\n", encoding="utf-8")
    return bejson_boundary_sanitize(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


def resolve_libraries_104_core() -> Path:
    """Resolve libraries_104/Lib_PY/Core dynamically via environment or relative workspace discovery."""
    env_lib = os.environ.get("ADMIN_LIBRARIES_104") or os.environ.get("ADMIN_LIBRARIES")
    candidates: list[Path] = []
    if env_lib:
        candidates.append(Path(env_lib) / "Lib_PY" / "Core")
        candidates.append(Path(env_lib) / "libraries_104" / "Lib_PY" / "Core")

    # Relative traversal from SCRIPT_PATH up to storage root
    for parent in SCRIPT_PATH.parents:
        candidates.append(parent / "User" / "core" / "libraries" / "libraries_104" / "Lib_PY" / "Core")
        candidates.append(parent / "Admin" / "libraries" / "libraries_104" / "Lib_PY" / "Core")

    for cand in candidates:
        if (cand / "lib_bejson_Core_bejson_validator.py").exists():
            return cand

    raise FileNotFoundError("Unable to locate libraries_104/Lib_PY/Core/lib_bejson_Core_bejson_validator.py")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="validate_104_gate",
        description="Layer 2 black-box stage-gate validator for BEJSON 104, 104a, and 104db documents.",
    )
    parser.add_argument("target", nargs="?", help="Path to .bejson / .104.bejson / .104a.bejson / .104db.bejson file.")
    parser.add_argument("--expected-version", choices=["104", "104a", "104db"], help="Enforce exact 104 sub-variant.")
    parser.add_argument("--version", action="version", version=f"validate_104_gate v{VERSION} (Release {RELEASE_VERSION})")
    parser.add_argument("--register", action="store_true", help="Display project registration command.")
    parser.add_argument("--config", action="store_true", help="Initialize and display 104a ScriptConfig.")
    parser.add_argument("--reset", action="store_true", help="Reset config/config.json to canonical defaults.")

    args = parser.parse_args()
    if args.reset and CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    cfg = ensure_config_104a()
    fmap = bejson_get_field_map(cfg)

    if args.config:
        settings = {row[fmap["setting_name"]]: row[fmap["setting_value"]] for row in cfg.get("Values", [])}
        LOG.info("Active 104a ScriptConfig: %s", json.dumps(settings))
        return EXIT_OK
    if args.register:
        LOG.info("Registration: python3 $PROJECT_INDEX_ROOT/cli_project_register.py --register \"%s\"", BUNDLE_ROOT)
        return EXIT_OK
    if not args.target:
        parser.print_help(sys.stderr)
        return EXIT_PATH_FAILURE

    target_path = Path(args.target).resolve()
    if not target_path.is_file():
        LOG.error("Target file not found: %s", target_path)
        return EXIT_PATH_FAILURE

    try:
        lib_104_core = resolve_libraries_104_core()
    except FileNotFoundError as exc:
        LOG.error("Environment sourcing failure: %s", exc)
        return EXIT_ENV_FAILURE

    sys.path.insert(0, str(lib_104_core))
    from lib_bejson_Core_bejson_validator import validate_bejson  # type: ignore

    try:
        raw_doc = json.loads(target_path.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.error("E01 E_INVALID_JSON in %s: %s", target_path.name, exc)
        return EXIT_SCHEMA_FAILURE

    fmt_ver = str(raw_doc.get("Format_Version", "")).strip()
    if fmt_ver in ("105", "105a", "105db"):
        LOG.error(
            "ERA_BOUNDARY_VIOLATION: '%s' has Format_Version='%s'. Redirect immediately to bejson-105-validator.",
            target_path.name,
            fmt_ver,
        )
        return EXIT_SCHEMA_FAILURE

    if args.expected_version and fmt_ver != args.expected_version:
        LOG.error(
            "DIALECT_MISMATCH: Expected Format_Version='%s', got '%s' in %s.",
            args.expected_version,
            fmt_ver,
            target_path.name,
        )
        return EXIT_SCHEMA_FAILURE

    val_res = validate_bejson(str(target_path), is_file=True)
    doc_fmap = bejson_get_field_map(bejson_boundary_sanitize(raw_doc))

    report = {
        "valid": bool(val_res.is_valid),
        "era": "libraries_104",
        "file_path": str(target_path),
        "format_version": fmt_ver,
        "field_count": len(doc_fmap),
        "record_count": len(raw_doc.get("Values", [])) if isinstance(raw_doc.get("Values"), list) else 0,
        "errors": list(val_res.errors),
        "warnings": list(getattr(val_res, "warnings", [])),
    }
    sys.stdout.write(json.dumps(report, indent=2) + "\n")

    if not val_res.is_valid:
        LOG.error("104 validation FAILED for %s with %d error(s).", target_path.name, len(val_res.errors))
        return EXIT_SCHEMA_FAILURE

    LOG.info("104 validation PASSED for %s (Format_Version=%s, fields=%d).", target_path.name, fmt_ver, len(doc_fmap))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
