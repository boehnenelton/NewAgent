"""
Library:        lib_bejson_NewAgentCMS_cms_ports.py
Family:         NewAgentCMS
Description:    Reads/creates config.json (BEJSON 104a ScriptConfig, per
                System Development Policy §8.4) at the project root and
                resolves each service's port with precedence:
                env var (if set) > config.json > hardcoded default.
                Auto-generates config.json with defaults on first run if
                it's missing or unreadable.
                REBRAND/STRIP NOTE: trimmed to the two surviving services
                (Admin, Publisher) as part of the NewAgent CMS fork --
                Page Editor V1/V2 and the Profile Manager (Persona Hub)
                were removed, so their port settings were removed too.
Version:        2.1.0
Date:           2026-08-23
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  a1e5f0c4-6b2d-4e8a-9c1f-0d7b3a5e6f2c
"""

import os
import json
import sys
from typing import Dict, Optional

# Mirrors the sys.path assumption lib_bejson_NewAgentCMS_cms_config.py
# already makes in this same package: caller puts the shared lib/ and
# tools_lib/na-cms/ on sys.path before importing anything in here.
import lib_bejson_Core_bejson_core as BEJSONCore

VERSION = "2.1.0"

# setting_name -> (default_port, description)
_PORT_SETTINGS = {
    "admin_port":       (5001, "Port for NewAgent_CMS_Admin.py (main admin dashboard)."),
    "publisher_port":   (5001, "Port for NewAgent_CMS_Publisher.py. Same default as "
                                "admin_port -- the advanced launcher auto-bumps this by "
                                "+10 if both are started at once, to avoid a collision."),
}

# service_key (as used by advanced_launcher.py) -> (setting_name, env_var)
SERVICE_PORT_MAP = {
    "admin":      ("admin_port", "CMS_ADMIN_PORT"),
    "publisher":  ("publisher_port", "CMS_PUBLISHER_PORT"),
}


def _default_doc() -> dict:
    return {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": ["ScriptConfig"],
        "Fields": [
            {"name": "setting_name", "type": "string"},
            # FIX (2026-08-27, audit F-16): "any" is not in BEJSON's valid
            # type vocabulary (string/integer/number/boolean/array/object)
            # -- validate_bejson (post-2.1.0) rejects this file outright.
            # The main NewAgent project's own config.json had this exact
            # bug, fixed in pkg084 by declaring "string" and storing every
            # value stringified; this NA-CMS copy was never updated to
            # match. int(row[1]) in get_port()/get_all_ports() below
            # already coerces via Python's own int(), which accepts a
            # numeric string ("5001") exactly the same as a real int
            # (5001) -- no separate coercion helper needed here the way
            # the main project's more varied config values required one.
            {"name": "setting_value", "type": "string"},
            {"name": "description", "type": "string"},
        ],
        "Values": [[name, str(default), desc] for name, (default, desc) in _PORT_SETTINGS.items()],
    }


def ensure_config(config_path: str) -> dict:
    """Loads config.json if present and valid; otherwise (re)creates it with
    defaults via an atomic write. Always returns a usable doc."""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and "Values" in doc:
                return doc
        except Exception:
            pass  # fall through and regenerate a corrupt/unreadable file

    doc = _default_doc()
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp_path, config_path)  # atomic on POSIX
    return doc


def get_port(config_path: str, setting_name: str, env_var: Optional[str] = None) -> int:
    """Resolves one service's port: env var (if set and valid) > config.json
    value > hardcoded default. Never raises -- falls back safely at each step."""
    if env_var:
        raw = os.environ.get(env_var)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass

    doc = ensure_config(config_path)
    # FIX (2026-09-11, audit V106-11): row[0]/row[1] bare positional reads
    # against a file this same module's docstring/ensure_config() rewrites
    # on every regeneration -- a Core Mandate violation (field-map-by-name
    # required for all BEJSON reads) even though the schema here is
    # file-local and low-risk in practice.
    fmap = BEJSONCore.bejson_core_get_field_map(doc)
    name_idx = fmap.get("setting_name", 0)
    value_idx = fmap.get("setting_value", 1)
    for row in doc.get("Values", []):
        if row and len(row) > max(name_idx, value_idx) and row[name_idx] == setting_name:
            try:
                return int(row[value_idx])
            except (TypeError, ValueError):
                break

    return _PORT_SETTINGS.get(setting_name, (5000, ""))[0]


def get_all_ports(config_path: str) -> Dict[str, int]:
    """Returns every configured port as {setting_name: port}, config.json
    values layered over defaults (does not apply env var overrides -- callers
    needing the fully-resolved value for one service should use get_port())."""
    result = {name: default for name, (default, _desc) in _PORT_SETTINGS.items()}
    doc = ensure_config(config_path)
    fmap = BEJSONCore.bejson_core_get_field_map(doc)
    name_idx = fmap.get("setting_name", 0)
    value_idx = fmap.get("setting_value", 1)
    for row in doc.get("Values", []):
        if row and len(row) > max(name_idx, value_idx) and row[name_idx] in result:
            try:
                result[row[name_idx]] = int(row[value_idx])
            except (TypeError, ValueError):
                pass
    return result
