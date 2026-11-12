#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      env_loader.py
Description: Simple dotenv parser for NA-WebToolkit.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 8d7e6f5a-4b3c-2d1e-0f9a-8b7c6d5e4f3a
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent
CONFIG_FILE_PATH = SCRIPT_PATH / "config" / "config.json"


def bootstrap_toolkit_library_paths() -> None:
    """Routes NA-WebToolkit to NewAgent's shared lib/ and lib_extensions/ via config/config.json."""
    shared_lib_rel = "../../lib"
    ext_lib_rel = "../../lib_extensions"
    if CONFIG_FILE_PATH.exists():
        try:
            config_doc = json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))
            field_map = {f["name"]: idx for idx, f in enumerate(config_doc.get("Fields", []))}
            name_idx = field_map.get("setting_name", 0)
            val_idx = field_map.get("setting_value", 1)
            for row in config_doc.get("Values", []):
                if len(row) > max(name_idx, val_idx):
                    if row[name_idx] == "shared_lib_directory":
                        shared_lib_rel = str(row[val_idx])
                    elif row[name_idx] == "lib_extensions_directory":
                        ext_lib_rel = str(row[val_idx])
        except Exception:
            pass
    for rel_dir in (shared_lib_rel, ext_lib_rel):
        resolved_dir = (SCRIPT_PATH / rel_dir).resolve()
        if resolved_dir.is_dir() and str(resolved_dir) not in sys.path:
            sys.path.insert(0, str(resolved_dir))


def load_dotenv(dotenv_path=None):
    """Loads environment via shared lib_bejson_Core_bejson_env plus optional local .env file."""
    bootstrap_toolkit_library_paths()
    env_sourced = False
    try:
        from lib_bejson_Core_bejson_env import source_env
        env_sourced = bool(source_env())
    except Exception:
        pass

    if dotenv_path is None:
        dotenv_path = os.path.join(os.getcwd(), '.env')

    if not os.path.isfile(dotenv_path):
        return env_sourced

    try:
        with open(dotenv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
        return True
    except Exception:
        return env_sourced