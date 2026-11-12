"""
Library:        lib_bejson_AI_gemini_standard_profiles.py
Family:         AI
Description:    AI Profile manager for the BEJSON ecosystem.
                Implements the canonical AI_Profile 104a schema using
                This_Case_Fields (no CrammedFieldNames). All reads and
                writes go through the Field Map Cache; positional
                look-ups are strictly prohibited.
Version:        3.1.0
Date:           2026-10-02
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  9d12ac56-5465-4ce0-bde7-409115edbb4d

Changelog:
  3.1.0 (2026-10-02) -- Added the OPTIONAL "Mode" profile field (string).
          Mode is a free-form hint a custom client may read to switch on a
          feature for that profile (e.g. "structured_output",
          "profile_generator"); the library assigns it no meaning and
          enforces no value list, and a client is free to ignore it.
          Completely optional: gemini_profiles_validate() accepts a profile
          with or without a Mode column, and a null/blank Mode is the same
          as no Mode. If a Mode column IS present it must be declared
          "string". The canonical PROFILE_FIELDS list and the required-
          field set are UNCHANGED, so every existing profile stays valid
          and no existing file needs migration. New: PROFILE_MODE_FIELD,
          OPTIONAL_PROFILE_FIELDS, gemini_profiles_get_mode(),
          gemini_profiles_set_mode(); gemini_profiles_create() accepts an
          optional Mode= kwarg (column is added only when a Mode is given).
          set_mode() appends the column at the END of Fields (positional
          integrity), null-pads existing rows, and drops the stale
          in-document field-map cache so the Field Map Cache is rebuilt.
          Also fixed: gemini_profiles_validate() now ignores the runtime-
          only _bejson_field_map cache key that Core injects into a doc
          after any field-map lookup (previously a profile that had been
          read via gemini_profiles_get_value() failed validation in
          memory, because 104 forbids custom top-level keys).
  3.0.0 (2026-09-04) -- Renamed from lib_bejson_AI_bejson_gemprofiles.py.
          Migrated all field names to This_Case convention
          (System_Instruction, Forbidden_Topics, Avatar_Source_Url,
          Max_Response_Tokens, Emotional_Expression_Enabled,
          Emotional_Expression_Intensity, Google_Search_Enabled,
          Code_Interpreter_Enabled, Ephemeral_Memory, Code_Parsing_Mode,
          Code_Parsing_Languages, Code_Parsing_Structure_Validation,
          Code_Parsing_Version_Control, Thinking_Supported).
          Eliminated legacy fallback positional constant _PROFILES_LEGACY.
          All operations now exclusively use bejson_core_get_field_map
          via the mandatory Field Map Cache.
  2.1.1 -- AI-family audit fix: added missing module-level VERSION var.
  2.1.0 -- Initial creation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys
import os

# ── Sibling resolution ────────────────────────────────────────────────────────
_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_LIB_DIR), "Core")
for _p in (_LIB_DIR, _CORE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib_bejson_Core_bejson_core import (
    bejson_core_get_field_index,
    bejson_core_get_field_map,
    bejson_core_atomic_write,
)
import lib_bejson_Core_bejson_validator

VERSION = "3.1.0"

logger = logging.getLogger(__name__)

# ── Canonical This_Case field definitions ─────────────────────────────────────
# Field Map Cache is mandatory for all reads/writes; these definitions serve
# as the authoritative schema reference and are used when creating new docs.

PROFILE_FIELDS: List[Dict[str, str]] = [
    {"name": "Record_Type_Parent",             "type": "string"},
    {"name": "Name",                            "type": "string"},
    {"name": "Archetype",                       "type": "string"},
    {"name": "Persona",                         "type": "string"},
    {"name": "System_Instruction",              "type": "string"},
    {"name": "Forbidden_Topics",               "type": "array"},
    {"name": "Avatar_Type",                    "type": "string"},
    {"name": "Avatar_Source_Url",              "type": "string"},
    {"name": "Avatar_Data",                    "type": "string"},
    {"name": "Max_Response_Tokens",            "type": "integer"},
    {"name": "Creativity",                     "type": "number"},
    {"name": "Tone",                           "type": "array"},
    {"name": "Formality",                      "type": "string"},
    {"name": "Verbosity",                      "type": "string"},
    {"name": "Emotional_Expression_Enabled",   "type": "boolean"},
    {"name": "Emotional_Expression_Intensity", "type": "number"},
    {"name": "Google_Search_Enabled",          "type": "boolean"},
    {"name": "Code_Interpreter_Enabled",       "type": "boolean"},
    {"name": "Ephemeral_Memory",               "type": "boolean"},
    {"name": "Code_Parsing_Mode",              "type": "string"},
    {"name": "Code_Parsing_Languages",         "type": "array"},
    {"name": "Code_Parsing_Structure_Validation", "type": "boolean"},
    {"name": "Code_Parsing_Version_Control",   "type": "boolean"},
    {"name": "Thinking_Supported",             "type": "boolean"},
]

_REQUIRED_FIELD_NAMES = {f["name"] for f in PROFILE_FIELDS}

# ── Optional fields ───────────────────────────────────────────────────────────
# Optional fields are NOT part of PROFILE_FIELDS / the required set. A profile
# is valid with or without them; when present they are appended at the END of
# Fields. "Mode" is a free-form hint for custom clients (they may act on it,
# e.g. "structured_output" or "profile_generator", or ignore it entirely).
# The library attaches no meaning to Mode and enforces no list of values.
PROFILE_MODE_FIELD = "Mode"

OPTIONAL_PROFILE_FIELDS: List[Dict[str, str]] = [
    {"name": PROFILE_MODE_FIELD, "type": "string"},
]


# ── Public API ────────────────────────────────────────────────────────────────

def gemini_profiles_validate(doc: Dict[str, Any]) -> bool:
    """
    Validates that *doc* conforms to the AI_Profile 104a schema.
    Returns True only if:
      1. The document passes the Core BEJSON structural validator.
      2. Every canonical This_Case field name is present.
      3. Records_Type contains "AI_Profile".
      4. If the optional "Mode" field is present, it is declared "string".
         A missing Mode is fine; so is a null/blank value.
    """
    try:
        # _bejson_field_map is the Core Field Map Cache injected into the doc
        # at runtime by any get_value()/set_mode() call -- it is not file
        # content, and a 104 doc may not carry custom top-level keys, so it
        # is excluded before structural validation.
        lib_bejson_Core_bejson_validator.bejson_validator_validate_string(
            json.dumps({k: v for k, v in doc.items() if k != "_bejson_field_map"})
        )
        fields = doc.get("Fields", [])
        field_names = {f["name"] for f in fields}
        missing = _REQUIRED_FIELD_NAMES - field_names
        if missing:
            logger.debug("Profile validation: missing fields: %s", missing)
            return False
        if "AI_Profile" not in doc.get("Records_Type", []):
            logger.debug("Profile validation: Records_Type does not contain AI_Profile")
            return False
        # Optional fields: absent is valid; present must have the right type.
        for opt in OPTIONAL_PROFILE_FIELDS:
            for f in fields:
                if f["name"] == opt["name"] and f.get("type") != opt["type"]:
                    logger.debug(
                        "Profile validation: optional field %s declared %s, expected %s",
                        opt["name"], f.get("type"), opt["type"],
                    )
                    return False
        return True
    except Exception as exc:
        logger.debug("Profile validation exception: %s", exc)
        return False


def gemini_profiles_create(
    name: str,
    archetype: str,
    persona: str,
    instruction: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Creates a new AI_Profile BEJSON 104a document with This_Case fields.
    All optional parameters use keyword args keyed by This_Case field name.
    Mode (optional): if a non-blank string is given, the optional "Mode"
    column is appended to the end of Fields; otherwise the profile has no
    Mode column at all.
    """
    values = [
        "AI_Profile",
        name,
        archetype,
        persona,
        instruction,
        kwargs.get("Forbidden_Topics", []),
        kwargs.get("Avatar_Type", "Emoji"),
        kwargs.get("Avatar_Source_Url", ""),
        kwargs.get("Avatar_Data", "🤖"),
        kwargs.get("Max_Response_Tokens", 16384),
        kwargs.get("Creativity", 0.7),
        kwargs.get("Tone", ["Professional", "Helpful"]),
        kwargs.get("Formality", "Formal"),
        kwargs.get("Verbosity", "Balanced"),
        kwargs.get("Emotional_Expression_Enabled", False),
        kwargs.get("Emotional_Expression_Intensity", 0.0),
        kwargs.get("Google_Search_Enabled", True),
        kwargs.get("Code_Interpreter_Enabled", True),
        kwargs.get("Ephemeral_Memory", True),
        kwargs.get("Code_Parsing_Mode", "complete"),
        kwargs.get("Code_Parsing_Languages", []),
        kwargs.get("Code_Parsing_Structure_Validation", True),
        kwargs.get("Code_Parsing_Version_Control", False),
        kwargs.get("Thinking_Supported", True),
    ]

    doc = {
        "Format": "BEJSON",
        "Format_Version": "104",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": ["AI_Profile"],
        # Copy so appending optional fields never mutates PROFILE_FIELDS.
        "Fields": [dict(f) for f in PROFILE_FIELDS],
        "Values": [values],
    }
    mode = kwargs.get(PROFILE_MODE_FIELD)
    if mode is not None:
        gemini_profiles_set_mode(doc, mode)
    return doc


def gemini_profiles_get_mode(
    profile: Dict[str, Any], record_index: int = 0
) -> Optional[str]:
    """
    Returns the profile's Mode as a stripped string, or None when the
    profile has no Mode column, the value is null/blank, or it is not a
    string. Never raises -- "no mode" is the normal case. The library gives
    Mode no meaning; the calling client decides what (if anything) to do
    with it.
    """
    value = gemini_profiles_get_value(profile, PROFILE_MODE_FIELD, record_index)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def gemini_profiles_set_mode(
    profile: Dict[str, Any], mode: Optional[str], record_index: int = 0
) -> bool:
    """
    Sets (or clears) the optional Mode on *profile* in place.

    - mode is a non-blank string: stored stripped. If the profile has no
      Mode column yet, it is appended at the END of Fields and every
      existing row is null-padded (positional integrity preserved).
    - mode is None or blank: clears an existing Mode to null; if there is
      no Mode column, nothing is added (the profile stays Mode-less).

    Returns True on success, False if mode is not a string/None or the
    record index is out of range.
    """
    if mode is not None and not isinstance(mode, str):
        logger.warning("gemini_profiles_set_mode: mode must be a string or None")
        return False
    clean = mode.strip() if isinstance(mode, str) else None
    clean = clean or None

    values = profile.get("Values", [])
    if record_index >= len(values):
        logger.warning("gemini_profiles_set_mode: record %d out of range", record_index)
        return False

    fm = gemini_profiles_get_field_map(profile)
    if PROFILE_MODE_FIELD not in fm:
        if clean is None:
            return True  # nothing to clear, nothing to add
        profile.setdefault("Fields", []).append(dict(OPTIONAL_PROFILE_FIELDS[0]))
        for row in values:
            row.append(None)
        # The Core field-map cache is injected into the doc; the Fields
        # array just changed, so drop the stale copy and rebuild it.
        profile.pop("_bejson_field_map", None)
        bejson_core_get_field_map(profile)
    return gemini_profiles_update_value(profile, PROFILE_MODE_FIELD, clean, record_index)


def gemini_profiles_save(profile: Dict[str, Any], path: str) -> None:
    """
    Atomically writes *profile* to *path* via bejson_core_atomic_write
    (.tmp → os.replace()) to prevent truncation on crash or OOM kill.

    Raises IOError if the write fails.
    """
    if not bejson_core_atomic_write(path, profile):
        raise IOError(f"Atomic write failed for profile: {path}")
    logger.debug("Profile saved: %s", path)


def gemini_profiles_get_field_map(profile: Dict[str, Any]) -> Dict[str, int]:
    """
    Returns the mandatory Field Map Cache (name → index) for *profile*.
    All field reads/writes must go through this map; positional lookups
    are strictly prohibited.
    """
    return bejson_core_get_field_map(profile)


def gemini_profiles_get_value(
    profile: Dict[str, Any], field_name: str, record_index: int = 0
) -> Any:
    """Queries a specific field value from *profile* via Field Map Cache."""
    fm = gemini_profiles_get_field_map(profile)
    idx = fm.get(field_name, -1)
    values = profile.get("Values", [])
    if idx != -1 and record_index < len(values) and idx < len(values[record_index]):
        return values[record_index][idx]
    return None


def gemini_profiles_update_value(
    profile: Dict[str, Any],
    field_name: str,
    new_value: Any,
    record_index: int = 0,
) -> bool:
    """
    Updates *field_name* in *profile* via Field Map Cache.
    Returns True on success, False if the field or record was not found.
    """
    fm = gemini_profiles_get_field_map(profile)
    idx = fm.get(field_name, -1)
    values = profile.get("Values", [])
    if idx != -1 and record_index < len(values) and idx < len(values[record_index]):
        values[record_index][idx] = new_value
        return True
    logger.warning(
        "gemini_profiles_update_value: field '%s' not found or out of range", field_name
    )
    return False


def gemini_profiles_query_by_name(
    profiles_dir: str, profile_name: str
) -> Optional[Dict[str, Any]]:
    """
    Scans *profiles_dir* for a .bejson file whose 'Name' field matches
    *profile_name* (case-sensitive). Returns the parsed document, or None.
    """
    path = Path(profiles_dir)
    for file in path.glob("*.bejson"):
        try:
            with open(file, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            if gemini_profiles_get_value(doc, "Name") == profile_name:
                return doc
        except Exception as exc:
            logger.debug("gemini_profiles_query_by_name: skipping %s — %s", file, exc)
    return None


def gemini_profiles_load_config(config_path: str) -> Dict[str, Any]:
    """
    Loads and returns the Profile_Config BEJSON document at *config_path*.
    Returns an empty dict on failure.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("gemini_profiles_load_config: could not load %s — %s", config_path, exc)
        return {}


def gemini_profiles_get_config_value(
    config_doc: Dict[str, Any], key: str
) -> Optional[str]:
    """
    Reads a value from the Profile_Config document by Config_Key via Field
    Map Cache. Returns None if the key is not found.
    """
    fm = bejson_core_get_field_map(config_doc)
    key_idx = fm.get("Config_Key", -1)
    val_idx = fm.get("Config_Value", -1)
    if key_idx == -1 or val_idx == -1:
        return None
    for row in config_doc.get("Values", []):
        if len(row) > max(key_idx, val_idx) and row[key_idx] == key:
            return row[val_idx]
    return None


def gemini_profiles_get_selected(config_path: str) -> str:
    """
    Convenience wrapper: returns the currently selected profile name from
    the Profile_Config file, defaulting to 'default' on any error.
    """
    doc = gemini_profiles_load_config(config_path)
    return gemini_profiles_get_config_value(doc, "Selected_Profile") or "default"


def gemini_profiles_is_enabled(config_path: str) -> bool:
    """
    Convenience wrapper: returns True if Profiles_Enabled is 'true' in
    the Profile_Config file.
    """
    doc = gemini_profiles_load_config(config_path)
    val = gemini_profiles_get_config_value(doc, "Profiles_Enabled") or "false"
    return val.strip().lower() == "true"
