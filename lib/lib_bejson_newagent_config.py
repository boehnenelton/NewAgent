"""
Library:        lib_bejson_newagent_config.py
Family:         NewAgent
Description:    BEJSON 104a configuration initialization, loading, and saving.
                Routes reads/writes through the canonical Core BEJSON library
                (lib_bejson_Core_bejson_core) for atomic writes and structural
                validation instead of hand-rolled json.load/dump.
Version:        1.10.0
Date:           2026-08-09
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  0dc439de-7eba-49c4-b385-491a3f719549

CHANGELOG:
- 1.10.0 (2026-08-09): Added auto_amnesia_memory_retrieval (default True)
  for the renamed /amnesia + /rebirth commands -- toggles whether
  /amnesia's compressed recap is fed straight back into history
  ("rebirth") or left on disk until /rebirth is run manually. Auto-
  backfills into existing config.json files via init_config's existing
  backfill path; picked up automatically by the webagent Config tab
  (renders as a checkbox since the default value is a bool).
- 1.9.1 (2026-08-07): Added network_error_auto_retry (default True) and
  network_error_retry_backoff_seconds (default 3.0) config defaults for
  agent.py's network-error auto-resend fix.
"""

import logging
from pathlib import Path
from typing import Any

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_index,
)
from lib_bejson_Core_bejson_validator import validate_bejson

VERSION = "1.10.0"
logger = logging.getLogger(__name__)

DEFAULT_CONFIG: list[tuple[str, Any, str]] = [
    ("engine_mode", "rest", "Active engine: 'rest' or 'interactions'"),
    ("model_rest", "gemini-2.5-flash", "Model for REST generateContent engine"),
    ("model_interactions", "gemini-2.5-flash", "Model for Interactions API engine"),
    ("key_registry_path", "config/keys.bejson", "API key registry path"),
    ("model_registry_path", "config/models.bejson", "Model registry path"),
    ("key_state_path", "config/key_state.bejson", "Key cooldown state path"),
    ("env_file_path", "/storage/emulated/0/env_file.json", "GlobalEnv BEJSON file synced for API keys on startup"),
    ("log_level", "INFO", "Python logging level"),
    ("send_delay_seconds", 2.0, "Delay before each API request (seconds)"),
    ("max_history_turns", 20, "Max conversation turns kept in memory"),
    ("history_panel_rows", 6, "Rows shown in TUI history panel"),
    ("max_actions_per_turn", 10, "Max action tags executed per model response"),
    ("auto_continue_enabled", True, "Auto-feed action results back to model"),
    ("max_autonomy_turns", 20, "Max consecutive autonomous turns (0=unlimited)"),
    ("exec_timeout_seconds", 60, "Max seconds per shell command"),
    ("exec_denylist", ["rm -rf /", "dd if=", "mkfs", ":(){:|:&};:"], "Command prefixes blocked before execution"),
    ("dryrun_mode", False, "When true: actions shown but not executed"),
    ("confirmation_gate", False, "Pause for Y/n before exec/delete actions"),
    ("input_mode", 0, "0=typed 1=STT 2=dialog+snippets"),
    ("multi_line_mode", False, "Triple-Enter for multi-line typed input"),
    ("live_feed_output", False, "Stream exec stdout/stderr live"),
    ("speak_output_enabled", True, "Print <speak> text to terminal"),
    ("interactions_max_rounds", 10, "Max function-call rounds per Interactions turn"),
    ("native_tools_scope", "all", "Interactions tool scope: 'all' or 'shell_only'"),
    ("resume_mode", "full_history", "Resume strategy: 'full_history' or 'fresh_replay'"),
    ("gen_temperature", 0.7, "Baseline generationConfig.temperature (legacy-profile models only)"),
    ("gen_top_p", 0.95, "Baseline generationConfig.topP (legacy-profile models only)"),
    ("gen_top_k", 40, "Baseline generationConfig.topK (legacy-profile models only)"),
    ("gen_candidate_count", 1, "Baseline generationConfig.candidateCount (legacy-profile models only)"),
    ("gen_thinking_budget", -1, "Baseline thinkingConfig.thinkingBudget (legacy-profile models; -1 = dynamic)"),
    ("gen_thinking_level", "high", "Baseline thinkingConfig.thinkingLevel (v3-profile models: 'low'/'high')"),
    ("debug_mode", True, "When true: write raw REST API request/response pairs to logs/raw_api_debug_*.json and logs/raw_api_error_*.json (rotated, last 5 kept). Defaults True: this being off is why the HTTP 400 issue went undiagnosed through two prior fix attempts."),
    ("health_check_on_startup", True, "When true: fire one minimal REST API call at startup so a bad key/model surfaces immediately instead of mid-conversation"),
    ("network_error_auto_retry", True, "When true: a NETWORK ERROR (dropped connection, no route) auto-resends the same turn instead of waiting for the user to manually retype it"),
    ("network_error_retry_backoff_seconds", 3.0, "Delay before an auto-resend triggered by network_error_auto_retry"),
    ("auto_amnesia_memory_retrieval", True, "When true, /amnesia (agent.py) or the webagent Amnesia button immediately re-feeds the compressed recap back into history ('rebirth') as soon as it wipes memory. When false, /amnesia wipes to a true blank slate and the recap waits on disk until /rebirth is run manually."),
]

_CONFIG_FIELDS = [
    {"name": "setting_name", "type": "string"},
    {"name": "setting_value", "type": "any"},
    {"name": "description", "type": "string"},
]


def make_bejson_structure(values: list[tuple]) -> dict:
    return bejson_core_create_104a(
        "ScriptConfig",
        list(_CONFIG_FIELDS),
        [[name, val, desc] for name, val, desc in values],
    )


def _validate_or_warn(path: Path, doc: dict) -> None:
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        logger.warning("[Config] %s failed structural validation: %s", path, result.errors)


def init_config(config_path: Path, schema: list[tuple] = None) -> dict:
    """Load (or create) a BEJSON 104a ScriptConfig file at config_path.

    schema defaults to DEFAULT_CONFIG (agent.py/webagent.py's shared
    config.json, unchanged behavior) but any caller can pass its own
    (name, default_value, description) triples to get an independently
    persisted config file with its own defaults/backfill -- e.g. cliagent.py
    passing CLI_DEFAULT_CONFIG to get config/cliagent_config.json instead of
    sharing the TUI's config.json.
    """
    active_schema = schema if schema is not None else DEFAULT_CONFIG
    defaults = {name: val for name, val, _ in active_schema}

    if not config_path.exists():
        doc = make_bejson_structure(active_schema)
        if not bejson_core_atomic_write(str(config_path), doc):
            logger.error("[Config] Atomic write failed for %s", config_path)
        return dict(defaults)

    raw = bejson_core_load_file(str(config_path))
    if not isinstance(raw, dict):
        logger.warning("[Config] Could not load %s, falling back to defaults", config_path)
        raw = {}
    else:
        _validate_or_warn(config_path, raw)

    name_idx = bejson_core_get_field_index(raw, "setting_name") if raw.get("Fields") else 0
    value_idx = bejson_core_get_field_index(raw, "setting_value") if raw.get("Fields") else 1
    if name_idx == -1:
        name_idx = 0
    if value_idx == -1:
        value_idx = 1

    rows = raw.get("Values", [])
    cfg = {}
    for row in rows:
        if len(row) > max(name_idx, value_idx):
            cfg[row[name_idx]] = row[value_idx]

    # Backfill newly added keys
    changed = False
    for name, val, desc in active_schema:
        if name not in cfg:
            cfg[name] = val
            rows.append([name, val, desc])
            changed = True

    if changed:
        raw["Values"] = rows
        raw.setdefault("Format", "BEJSON")
        raw.setdefault("Format_Version", "104a")
        raw.setdefault("Format_Creator", "Elton Boehnen")
        raw.setdefault("Records_Type", ["ScriptConfig"])
        raw.setdefault("Fields", list(_CONFIG_FIELDS))
        if not bejson_core_atomic_write(str(config_path), raw):
            logger.error("[Config] Atomic write failed for %s", config_path)

    return {**defaults, **cfg}


def save_config(config_path: Path, cfg: dict, schema: list[tuple] = None) -> None:
    active_schema = schema if schema is not None else DEFAULT_CONFIG
    desc_map = {name: desc for name, _, desc in active_schema}
    values = [[k, v, desc_map.get(k, "")] for k, v in cfg.items()]
    doc = bejson_core_create_104a("ScriptConfig", list(_CONFIG_FIELDS), values)
    if not bejson_core_atomic_write(str(config_path), doc):
        logger.error("[Config] Atomic write failed for %s", config_path)
