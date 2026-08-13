"""
Library:        config.py
Project:        Cli_Bookwriter
Description:    SCRIPT_PATH self-location and directory bootstrap. Every
                 path this tool touches is relative to SCRIPT_PATH — no
                 hardcoded paths.
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  7a8b9c0d-1e2f-4a3b-4c5d-6e7f8a9b0c11
"""

import sys
from pathlib import Path


def get_script_path() -> Path:
    return Path(__file__).resolve().parent.parent


SCRIPT_PATH = get_script_path()

DIR_LIB = SCRIPT_PATH / "lib"
DIR_SECURE = SCRIPT_PATH / "secure"
DIR_DATA = SCRIPT_PATH / "data"
DIR_PLANS = DIR_DATA / "plans"
DIR_PERSIST = DIR_DATA / "persist"
DIR_CONTEXT = DIR_DATA / "context"
DIR_CONTEXT_BUBBLE = DIR_CONTEXT / "bubble"
DIR_TEMP = DIR_DATA / "temp"
DIR_BOOKS = SCRIPT_PATH / "books"
DIR_BOOKS_BEJSON = DIR_BOOKS / "BEJSON"
DIR_BOOKS_HTML = DIR_BOOKS / "HTML"

ALL_DIRS = [DIR_SECURE, DIR_PLANS, DIR_PERSIST, DIR_CONTEXT, DIR_CONTEXT_BUBBLE,
            DIR_TEMP, DIR_BOOKS_BEJSON, DIR_BOOKS_HTML]


FILE_CONFIG = SCRIPT_PATH / "config.json"

DEFAULT_CONFIG_DOC = {
    "Format": "BEJSON",
    "Format_Version": "104a",
    "Format_Creator": "Elton Boehnen",
    "Records_Type": ["ScriptConfig"],
    "Fields": [
        {"name": "setting_name", "type": "string"},
        {"name": "setting_value", "type": "any"},
        {"name": "description", "type": "string"}
    ],
    "Values": [
        ["dotenv_path", "secure/.env", "Relative or absolute path to .env file."],
        ["use_external_paths", False, "Toggle to allow script to operate outside of its local ecosystem."],
        ["local_lib_directory", "lib/", "Relative path to local dep folder."],
        ["master_lib_source", "/storage/emulated/0/Admin/libraries", "Fallback if local lib missing."],
        ["log_level", "INFO", "Default log level."]
    ]
}


def bootstrap_dirs():
    for required_dir_path in ALL_DIRS:
        required_dir_path.mkdir(parents=True, exist_ok=True)
    ensure_config_file()


def ensure_config_file() -> dict:
    if not FILE_CONFIG.exists():
        import json
        FILE_CONFIG.write_text(json.dumps(DEFAULT_CONFIG_DOC, indent=2), encoding="utf-8")
        return DEFAULT_CONFIG_DOC
    else:
        import json
        try:
            return json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULT_CONFIG_DOC


def get_config_setting(setting_name: str, default=None):
    cfg = ensure_config_file()
    for row in cfg.get("Values", []):
        if len(row) >= 2 and row[0] == setting_name:
            return row[1]
    return default


def bootstrap_lib_path():
    core_lib_dir = DIR_LIB / "Core"
    core_lib_dir_str = str(core_lib_dir)
    if core_lib_dir.exists() and core_lib_dir_str not in sys.path:
        sys.path.insert(0, core_lib_dir_str)

