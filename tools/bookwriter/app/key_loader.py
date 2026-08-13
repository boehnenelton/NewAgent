"""
Library:        key_loader.py
Project:        Cli_Bookwriter
Description:    Gemini API key loading. Checks, in order: secure/.env
                 (plain KEY=VALUE lines, relative to the tool — per the
                 update request's "pull keys from .env/secure"), then the
                 device-wide BEJSON env files (same ENV_FILE_PATHS/
                 GEMINI_KEY_1..21 convention already used by Flask_BookCMS
                 and the rest of Elton's toolkit), then plain OS environment
                 variables (GEMINI_API_KEY / GOOGLE_API_KEY).
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  5e6f7a8b-9c0d-4e1f-2a3b-4c5d6e7f8a99
"""

import json
import os
from pathlib import Path

DEVICE_ENV_FILE_PATHS = [
    "/storage/emulated/0/.env/secure/secureenv_file.json",
    "/storage/emulated/0/env_file_2.json",
    "/storage/emulated/0/env_file.json",
]

ENV_TEMPLATE_TEXT = """# Cli_Bookwriter — Environment Configuration
# API Keys & Runtime Configuration

# Gemini API Keys (List in order of priority)
GEMINI_API_KEY=
GEMINI_KEY_1=
GEMINI_KEY_2=
GEMINI_KEY_3=

# Optional model override
# DEFAULT_MODEL=gemini-2.5-flash
"""


def export_env_template(target_path: Path) -> Path:
    """Exports a clean .env template file to the target path."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(ENV_TEMPLATE_TEXT, encoding="utf-8")
    return target_path


def _parse_dotenv_file(dotenv_path: Path):
    parsed_env_values = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
            continue
        env_key, _, env_value = stripped_line.partition("=")
        parsed_env_values[env_key.strip()] = env_value.strip().strip('"').strip("'")
    return parsed_env_values


def _append_keys_to_template(dotenv_path: Path, discovered_keys: dict):
    """Fallback handler: if .env is missing or empty, generates/updates .env and appends pre-configured keys."""
    if not dotenv_path.exists() or not dotenv_path.read_text(encoding="utf-8").strip():
        export_env_template(dotenv_path)

    existing_content = dotenv_path.read_text(encoding="utf-8")
    existing_values = _parse_dotenv_file(dotenv_path)

    lines_to_append = []
    for k, v in discovered_keys.items():
        if k not in existing_values and v:
            lines_to_append.append(f"{k}={v}")

    if lines_to_append:
        new_content = existing_content.rstrip() + "\n\n# Auto-populated from system fallback environment\n" + "\n".join(lines_to_append) + "\n"
        dotenv_path.write_text(new_content, encoding="utf-8")


def load_gemini_api_key(script_path: Path, dotenv_rel_path: str = "secure/.env") -> str:
    """Returns the first usable Gemini key found, or "" if none. Checks:
    1. Configured .env path (default: secure/.env).
    2. OS environment variables.
    3. Device-wide BEJSON env files (and appends found keys to .env fallback template)."""
    configured_dotenv_path = Path(dotenv_rel_path)
    if not configured_dotenv_path.is_absolute():
        configured_dotenv_path = script_path / configured_dotenv_path

    # Check configured .env file
    if configured_dotenv_path.exists():
        try:
            dotenv_values = _parse_dotenv_file(configured_dotenv_path)
            for env_key, env_value in dotenv_values.items():
                if env_value:
                    os.environ.setdefault(env_key, env_value)
        except OSError:
            pass

    # Check OS env variables
    for indexed_key_number in range(1, 22):
        indexed_key_value = os.environ.get(f"GEMINI_KEY_{indexed_key_number}")
        if indexed_key_value and len(indexed_key_value) > 10:
            return indexed_key_value

    direct_key_value = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if direct_key_value:
        return direct_key_value

    # Fallback to device-wide BEJSON env files
    discovered_fallback_keys = {}
    for device_env_file_path_str in DEVICE_ENV_FILE_PATHS:
        device_env_file_path = Path(device_env_file_path_str)
        if not device_env_file_path.exists():
            continue
        try:
            device_env_doc = json.loads(device_env_file_path.read_text(encoding="utf-8"))
            for env_row in device_env_doc.get("Values", []):
                if len(env_row) >= 2 and env_row[0] and env_row[1]:
                    key_name = str(env_row[0])
                    key_val = str(env_row[1])
                    os.environ.setdefault(key_name, key_val)
                    if key_name.startswith("GEMINI_"):
                        discovered_fallback_keys[key_name] = key_val
        except (OSError, json.JSONDecodeError):
            continue

    # If fallback found keys, append them to the local .env template so it is populated automatically
    if discovered_fallback_keys:
        try:
            _append_keys_to_template(configured_dotenv_path, discovered_fallback_keys)
        except Exception:
            pass

    for indexed_key_number in range(1, 22):
        indexed_key_value = os.environ.get(f"GEMINI_KEY_{indexed_key_number}")
        if indexed_key_value and len(indexed_key_value) > 10:
            return indexed_key_value
    fallback_key_value = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if fallback_key_value:
        return fallback_key_value

    # If no key found anywhere, ensure template file is exported
    if not configured_dotenv_path.exists():
        export_env_template(configured_dotenv_path)

    return ""

