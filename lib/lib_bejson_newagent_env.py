"""
Library:        lib_bejson_newagent_env.py
Family:         NewAgent
Description:    Resolves NewAgent's environment sources against the split
                 env scheme (secure/ + user/ paths files, each with .py/.sh/
                 .json siblings) with the single legacy env_file.* as
                 fallback. Wraps the Core BEJSON env library's source_env()
                 (never modifies it -- Core family is off-limits) and adds
                 the BEJSON-doc-source resolution the key sync and context
                 drip code needs now that there are two files instead of one.
Version:        1.1.0
Date:           2026-08-16
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  f3a7c9d2-8e1b-4f6a-9c3d-2b5e7a1f9d84

CHANGELOG:
- 1.1.0 (2026-08-16): Added describe_env_sources() -- Elton reported 0 keys
  synced ("No API keys available for provider 'gemini'") on a live device
  after the pkg073/074 env migration, even though his real secureenv_file
  content synced correctly (21 keys) when tested directly against the exact
  uploaded file. That rules out a parsing bug and points at either a stale
  config.json (not yet backfilled with the new path fields) or an actual
  path mismatch on-device -- neither of which is diagnosable from a plain
  "No API keys available" error. This function reports every candidate
  path (secure/paths/legacy), whether each exists on disk, and which set
  resolve_env_bejson_sources() actually picked -- sync_keys_from_env_sources
  in lib_bejson_newagent_engine_rest.py logs it automatically whenever a
  sync run adds 0 keys, so the next occurrence is diagnosable from the
  startup log line instead of requiring another round trip.
- 1.0.0 (2026-08-16): Initial version. Added per Elton's environment
  migration request: secure/paths.json + secure/secureenv_file.json are now
  NewAgent's primary env sources, with the old single env_file.* kept as
  fallback only when neither new file is present. Two mechanisms covered:
  (1) OS-environment sourcing (INTERNAL_STORAGE, SD_CARD, PROJECT_ROOT, etc,
  via Core's source_env()/get_env_path()) and (2) BEJSON-doc var_name/
  var_value sourcing (API key sync + the context-bubble env drip section).
"""

import logging
from pathlib import Path

from lib_bejson_Core_bejson_env import source_env

VERSION = "1.1.0"
logger = logging.getLogger(__name__)

# New split-scheme defaults (Policy env_file_paths.txt / config.json defaults
# live in lib_bejson_newagent_config.DEFAULT_CONFIG -- these are only the
# fixed .py-variant paths used for OS-environment sourcing, which has no
# corresponding config field since it must run before config is loaded).
SECURE_ENV_PY = Path("/storage/emulated/0/.env/secure/secureenv_file.py")
PATHS_ENV_PY = Path("/storage/emulated/0/.env/user/paths.py")


def newagent_source_env() -> bool:
    """
    Mandatory environment sourcing, NewAgent-specific ordering: new split
    files (secure, then paths) are primary. If NEITHER new .py file exists,
    falls through to Core's own source_env() default chain (legacy
    /storage/emulated/0/env_file.py, then ~/env_file.py) so a device that
    hasn't been migrated yet still boots correctly.

    Returns True if at least one source was sourced.
    """
    sourced_any = False
    if SECURE_ENV_PY.exists():
        sourced_any = source_env(str(SECURE_ENV_PY)) or sourced_any
    if PATHS_ENV_PY.exists():
        sourced_any = source_env(str(PATHS_ENV_PY)) or sourced_any
    if not sourced_any:
        sourced_any = source_env()
    return sourced_any


def resolve_env_bejson_sources(config: dict) -> list[Path]:
    """
    Returns the ordered list of existing BEJSON 104a env docs (var_name/
    var_value rows) to read for key sync and the context drip. New scheme:
    both env_secure_file_path and env_paths_file_path (whichever exist) are
    used together. Legacy env_file_path is used ONLY as a fallback when
    neither new file is present on disk, so a stale/never-migrated device
    still gets its keys and drip content from somewhere.
    """
    secure_p = Path(config.get("env_secure_file_path", ""))
    paths_p = Path(config.get("env_paths_file_path", ""))
    new_sources = [p for p in (secure_p, paths_p) if str(p) not in ("", ".") and p.exists()]
    if new_sources:
        return new_sources

    legacy_p = Path(config.get("env_file_path", ""))
    if str(legacy_p) not in ("", ".") and legacy_p.exists():
        return [legacy_p]
    return []


def describe_env_sources(config: dict) -> str:
    """
    One-line diagnostic: every candidate path this config resolves to
    (secure, paths, legacy) and whether each exists on disk right now, plus
    which set actually got used by resolve_env_bejson_sources() given the
    same config. Logged automatically by sync_keys_from_env_sources() when
    it syncs 0 keys, so a misconfigured/missing env file shows exactly
    which path was wrong instead of just "no keys" with no further clue.
    """
    secure_p = config.get("env_secure_file_path", "")
    paths_p = config.get("env_paths_file_path", "")
    legacy_p = config.get("env_file_path", "")
    used = [str(p) for p in resolve_env_bejson_sources(config)]

    def _fmt(label: str, p) -> str:
        exists = bool(str(p)) and str(p) not in (".",) and Path(str(p)).exists()
        return f"{label}={p!r} exists={exists}"

    return (
        f"[{_fmt('secure', secure_p)}] [{_fmt('paths', paths_p)}] "
        f"[{_fmt('legacy', legacy_p)}] used={used or '[]'}"
    )
