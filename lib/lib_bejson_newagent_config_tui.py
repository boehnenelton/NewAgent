"""
Library:        lib_bejson_newagent_config_tui.py
Family:         NewAgent
Description:    57-Column BEJSON Positional Telemetry TUI Engine & Hierarchical
                Configuration Manager for NewAgent. Manages all configuration
                options across config/config.json (49 settings),
                Context/constant_config.bejson (12 settings), and
                config/cliagent_config.json (6 settings) organized into 7
                domain categories with zero-typing presets, one-key toggles,
                BEJSON 104a validation, path probing, and snapshot backups.
Version:        1.0.0
Date:           2026-10-24
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Release_Version: 300
RELATIONAL_ID:  9f5e2c14-8a3b-4d72-9c11-6e40b18f3d2a
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_atomic_write,
    bejson_core_create_104a,
    bejson_core_get_field_map,
    bejson_core_load_file,
)
from lib_bejson_Core_bejson_validator import validate_bejson
import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_context_bubble as context_bubble

VERSION = "1.0.0"
RELATIONAL_ID = "9f5e2c14-8a3b-4d72-9c11-6e40b18f3d2a"
AUTHOR_CREDIT = (
    "Elton Boehnen · boehnenelton2024@gmail.com · "
    "boehnenelton2024.pages.dev · github.com/boehnenelton"
)

EXIT_CODE_SUCCESS = 0
EXIT_CODE_PICKER_FAILURE = 10
EXIT_CODE_ENV_FAILURE = 20
EXIT_CODE_VALIDATION_FAILURE = 30

TUI_VIEWPORT_MAX_COLUMNS = 57
TUI_DIVIDER_MAIN_LINE = "=" * TUI_VIEWPORT_MAX_COLUMNS
TUI_DIVIDER_SUB_LINE = "-" * TUI_VIEWPORT_MAX_COLUMNS

module_logger = logging.getLogger(__name__)

_ANSI_ESCAPE_REGEX = re.compile(r"\033\[[^m]*m")


def strip_ansi_sequences(raw_terminal_text: str) -> str:
    """Remove ANSI escape sequences to measure visible column width."""
    return _ANSI_ESCAPE_REGEX.sub("", raw_terminal_text)


def clamp_cell_text(raw_cell_value: Any, max_column_width: int) -> str:
    """Deterministic single-line truncation that never exceeds max_column_width."""
    normalized_text = str(raw_cell_value).replace("\n", " ").strip()
    if max_column_width <= 0:
        return ""
    if len(normalized_text) <= max_column_width:
        return normalized_text
    if max_column_width == 1:
        return normalized_text[:1]
    return normalized_text[: max_column_width - 1] + "…"


def compact_display_path(target_file_path: Path | str, max_column_width: int = 27) -> str:
    """Format a file path into a compact ~/... tail that fits within max_column_width."""
    raw_path_text = str(target_file_path)
    home_dir_text = os.path.expanduser("~")
    if raw_path_text.startswith(home_dir_text):
        raw_path_text = "~" + raw_path_text[len(home_dir_text) :]
    if len(raw_path_text) <= max_column_width:
        return raw_path_text
    filename_tail = Path(raw_path_text).name
    parent_tail = Path(raw_path_text).parent.name
    candidate_short = f"~/.../{parent_tail}/{filename_tail}" if parent_tail else f"~/.../{filename_tail}"
    if len(candidate_short) <= max_column_width:
        return candidate_short
    candidate_leaf = f"~/.../{filename_tail}"
    if len(candidate_leaf) <= max_column_width:
        return candidate_leaf
    return clamp_cell_text(filename_tail, max_column_width)


def clamp_tui_line(raw_line_text: str) -> str:
    """Guarantee that a rendered line never exceeds 57 visible columns."""
    clean_line_text = strip_ansi_sequences(raw_line_text).rstrip("\r\n")
    if len(clean_line_text) <= TUI_VIEWPORT_MAX_COLUMNS:
        return clean_line_text
    return clean_line_text[:TUI_VIEWPORT_MAX_COLUMNS]


# ── Canonical CLI Default Config (mirrors cliagent.py CLI_DEFAULT_CONFIG) ──
CLI_AGENT_DEFAULT_SCHEMA: list[tuple[str, Any, str]] = [
    ("json_output_default", False, "Default to --json output even when the flag isn't passed"),
    ("execute_default", False, "Default to --execute (auto-run XML tool actions) even when the flag isn't passed"),
    ("include_persistent_policy", True, "Prepend Context/CLIAgent_Persistent_Policy.md to every call's system instruction unless --no-context is passed"),
    ("log_invocations", True, "Append a one-line record of every call to logs/cliagent_invocations.md"),
    ("cli_max_retries", 3, "REST engine max_retries for cliagent calls specifically"),
    ("cli_timeout_seconds", 90, "REST engine per-request timeout (seconds) for cliagent calls specifically"),
]


@dataclass
class ConfigOptionMetadata:
    """Metadata descriptor for a single configuration option inside a category."""

    option_key_name: str
    category_short_code: str
    store_identifier: str
    value_type_tag: str  # BOOL, INT, FLT, ENUM, PATH, LIST, SEC, STR
    default_python_value: Any
    schema_description_text: str
    preset_choices_list: list[Any] = field(default_factory=list)


@dataclass
class ConfigCategoryDescriptor:
    """Metadata descriptor for one hierarchical configuration category."""

    category_index_number: int
    category_short_code: str
    category_title_label: str
    category_summary_label: str
    store_identifier: str
    store_display_short: str
    option_keys_order: list[str]


# ── Hierarchical Category Definitions ──────────────────────────────────────
HIERARCHICAL_CATEGORY_DESCRIPTORS: list[ConfigCategoryDescriptor] = [
    ConfigCategoryDescriptor(
        category_index_number=1,
        category_short_code="ENG",
        category_title_label="ENGINE & GENERATION",
        category_summary_label="Engine & Generation",
        store_identifier="main_config",
        store_display_short="config.json",
        option_keys_order=[
            "engine_mode",
            "interactions_max_rounds",
            "native_tools_scope",
            "gen_temperature",
            "gen_top_p",
            "gen_top_k",
            "gen_candidate_count",
            "gen_thinking_budget",
            "gen_thinking_level",
            "model_rest",
            "model_interactions",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=2,
        category_short_code="AUT",
        category_title_label="AUTONOMY & EXECUTION",
        category_summary_label="Autonomy & Execution",
        store_identifier="main_config",
        store_display_short="config.json",
        option_keys_order=[
            "auto_continue_enabled",
            "max_autonomy_turns",
            "max_auto_continue_turns",
            "max_actions_per_turn",
            "exec_timeout_seconds",
            "exec_output_cap_bytes",
            "exec_denylist",
            "dryrun_mode",
            "confirmation_gate",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=3,
        category_short_code="MEM",
        category_title_label="MEMORY, POLICY & SUBAGT",
        category_summary_label="Memory, Policy & Subagt",
        store_identifier="main_config",
        store_display_short="config.json",
        option_keys_order=[
            "max_history_turns",
            "resume_mode",
            "auto_amnesia_memory_retrieval",
            "gemini_md_policy_enabled",
            "gemini_md_global_paths",
            "gemini_md_tree_filenames",
            "gemini_md_max_chars",
            "subagents_enabled",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=4,
        category_short_code="EXT",
        category_title_label="SKILLS, LIBS & ENV PATH",
        category_summary_label="Skills, Libs & Env Path",
        store_identifier="main_config",
        store_display_short="config.json",
        option_keys_order=[
            "agy_skills_enabled",
            "agy_skills_directories",
            "lib_extensions_directory",
            "env_secure_file_path",
            "env_paths_file_path",
            "env_file_path",
            "key_registry_path",
            "model_registry_path",
            "key_state_path",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=5,
        category_short_code="SYS",
        category_title_label="TUI, IO, NET & WEB AUTH",
        category_summary_label="TUI, IO, Net & Web Auth",
        store_identifier="main_config",
        store_display_short="config.json",
        option_keys_order=[
            "input_mode",
            "multi_line_mode",
            "live_feed_output",
            "speak_output_enabled",
            "history_panel_rows",
            "log_level",
            "debug_mode",
            "health_check_on_startup",
            "send_delay_seconds",
            "network_error_auto_retry",
            "network_error_retry_backoff_seconds",
            "web_auth_token",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=6,
        category_short_code="BUB",
        category_title_label="CONTEXT BUBBLE & OBSVR",
        category_summary_label="Context Bubble & Obsvr",
        store_identifier="bubble_constants",
        store_display_short="constant.bj",
        option_keys_order=[
            "max_context_tokens",
            "pct_persistent_policy",
            "pct_active_tasks",
            "pct_env_file",
            "pct_keyword_triggers",
            "pct_knowledge_pool",
            "pct_cwd_context",
            "chars_per_token",
            "global_default_cooldown",
            "knowledge_drip_interval",
            "observer_refinement_interval",
            "observer_enabled",
        ],
    ),
    ConfigCategoryDescriptor(
        category_index_number=7,
        category_short_code="CLI",
        category_title_label="HEADLESS CLIAGENT OPTS",
        category_summary_label="Headless CLIAgent Opts",
        store_identifier="cli_config",
        store_display_short="cliagent.js",
        option_keys_order=[
            "json_output_default",
            "execute_default",
            "include_persistent_policy",
            "log_invocations",
            "cli_max_retries",
            "cli_timeout_seconds",
        ],
    ),
]


# ── Explicit Enum & Preset Tables for Zero-Typing Operation ────────────────
ENUM_ALLOWED_CHOICES_MAP: dict[str, list[Any]] = {
    "engine_mode": ["rest", "interactions"],
    "native_tools_scope": ["all", "shell_only"],
    "resume_mode": ["full_history", "fresh_replay"],
    "gen_thinking_level": ["high", "low"],
    "log_level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "input_mode": [0, 1, 2],
}

NUMERIC_AND_PATH_PRESETS_MAP: dict[str, list[Any]] = {
    "interactions_max_rounds": [5, 10, 15, 25, 50],
    "gen_temperature": [0.0, 0.2, 0.5, 0.7, 1.0, 1.2],
    "gen_top_p": [0.80, 0.90, 0.95, 1.00],
    "gen_top_k": [10, 20, 40, 64, 100],
    "gen_candidate_count": [1, 2, 4],
    "gen_thinking_budget": [-1, 0, 1024, 4096, 8192, 16384],
    "model_rest": ["gemini-3.6-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    "model_interactions": ["gemini-3.6-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    "max_autonomy_turns": [0, 5, 10, 20, 50],
    "max_auto_continue_turns": [0, 5, 12, 20, 30],
    "max_actions_per_turn": [5, 10, 15, 25],
    "exec_timeout_seconds": [15, 30, 60, 120, 300],
    "exec_output_cap_bytes": [0, 16384, 32768, 65536, 131072],
    "max_history_turns": [10, 20, 40, 80, 100],
    "gemini_md_max_chars": [0, 16000, 36000, 64000],
    "lib_extensions_directory": ["lib_extensions/", "lib/"],
    "env_secure_file_path": [
        "/storage/emulated/0/.env/secure/secureenv_file.json",
        "/storage/emulated/0/.env/secure/secureenv_file-1.json",
    ],
    "env_paths_file_path": [
        "/storage/emulated/0/.env/user/definitions.json",
        "/storage/emulated/0/.env/user/paths.json",
    ],
    "env_file_path": [
        "/storage/emulated/0/env_file.json",
        "/storage/emulated/0/.env/user/definitions.json",
    ],
    "key_registry_path": ["config/keys.bejson"],
    "model_registry_path": ["config/models.bejson"],
    "key_state_path": ["config/key_state.bejson"],
    "history_panel_rows": [4, 6, 8, 12, 16],
    "send_delay_seconds": [0.0, 0.5, 1.0, 2.0, 5.0],
    "network_error_retry_backoff_seconds": [1.0, 2.0, 3.0, 5.0, 10.0],
    "max_context_tokens": [4000, 8000, 16000, 32000],
    "pct_persistent_policy": [0.10, 0.15, 0.20, 0.25, 0.30],
    "pct_active_tasks": [0.10, 0.15, 0.20, 0.25],
    "pct_env_file": [0.02, 0.05, 0.10],
    "pct_keyword_triggers": [0.15, 0.20, 0.30, 0.40],
    "pct_knowledge_pool": [0.05, 0.10, 0.15, 0.20],
    "pct_cwd_context": [0.05, 0.10, 0.15, 0.20],
    "chars_per_token": [3, 4, 5],
    "global_default_cooldown": [60, 180, 300, 600],
    "knowledge_drip_interval": [1, 3, 5, 10],
    "observer_refinement_interval": [3, 5, 7, 10, 15],
    "cli_max_retries": [1, 3, 5, 10],
    "cli_timeout_seconds": [30, 60, 90, 180, 300],
}

PATH_SETTING_KEYS_SET: set[str] = {
    "lib_extensions_directory",
    "env_secure_file_path",
    "env_paths_file_path",
    "env_file_path",
    "key_registry_path",
    "model_registry_path",
    "key_state_path",
}


def classify_option_type_tag(option_key_name: str, default_val: Any) -> str:
    """Classify a setting into one of BOOL, ENUM, INT, FLT, LIST, PATH, SEC, STR."""
    if option_key_name == "web_auth_token":
        return "SEC"
    if isinstance(default_val, bool):
        return "BOOL"
    if option_key_name in ENUM_ALLOWED_CHOICES_MAP:
        return "ENUM"
    if isinstance(default_val, list):
        return "LIST"
    if option_key_name in PATH_SETTING_KEYS_SET:
        return "PATH"
    if isinstance(default_val, int) and not isinstance(default_val, bool):
        return "INT"
    if isinstance(default_val, float):
        return "FLT"
    return "STR"


def format_positional_value_cell(
    option_meta: ConfigOptionMetadata,
    current_val: Any,
    max_width: int = 17,
) -> str:
    """Format a setting's live value into a compact positional string <= max_width."""
    if option_meta.value_type_tag == "SEC":
        token_str = str(current_val or "")
        if not token_str:
            return "(empty)"
        if len(token_str) <= 6:
            return "***"
        return clamp_cell_text(f"{token_str[:3]}…{token_str[-3:]}({len(token_str)}c)", max_width)
    if option_meta.value_type_tag == "BOOL":
        return "true" if bool(current_val) else "false"
    if option_meta.value_type_tag == "LIST":
        if isinstance(current_val, list):
            if len(current_val) == 0:
                return "[0 items]"
            first_item = Path(str(current_val[0])).name or str(current_val[0])
            summary_cell = f"[{len(current_val)}]{first_item}"
            return clamp_cell_text(summary_cell, max_width)
        return clamp_cell_text(str(current_val), max_width)
    if option_meta.value_type_tag == "PATH":
        return compact_display_path(str(current_val), max_column_width=max_width)
    if option_meta.option_key_name == "input_mode":
        mode_labels = {0: "0(typed)", 1: "1(STT)", 2: "2(dialog)"}
        return mode_labels.get(current_val, str(current_val))
    return clamp_cell_text(str(current_val), max_width)


class NewAgentConfigManagerState:
    """
    Central state controller for all 3 BEJSON 104a configuration stores:
      1. main_config      -> config/config.json
      2. bubble_constants -> Context/constant_config.bejson
      3. cli_config       -> config/cliagent_config.json
    """

    def __init__(self, project_root_path: Path) -> None:
        self.project_root_path: Path = project_root_path.resolve()
        self.config_dir_path: Path = self.project_root_path / "config"
        self.context_dir_path: Path = self.project_root_path / "Context"
        self.logs_dir_path: Path = self.project_root_path / "logs"
        self.backups_dir_path: Path = self.project_root_path / "backups"

        self.main_config_file_path: Path = self.config_dir_path / "config.json"
        self.bubble_constants_file_path: Path = self.config_dir_path / "constant_config.bejson"
        self.cli_config_file_path: Path = self.config_dir_path / "cliagent_config.json"

        self.categories_list: list[ConfigCategoryDescriptor] = []
        self.option_metadata_registry: dict[str, ConfigOptionMetadata] = {}
        self.store_values_map: dict[str, dict[str, Any]] = {
            "main_config": {},
            "bubble_constants": {},
            "cli_config": {},
        }
        self.last_status_banner_code: str = "READY"

        self._build_metadata_catalog()
        self.reload_all_stores()

    def _build_metadata_catalog(self) -> None:
        """Build option metadata descriptors and ensure 100% of schema keys are categorized."""
        self.categories_list = [
            ConfigCategoryDescriptor(
                category_index_number=cat.category_index_number,
                category_short_code=cat.category_short_code,
                category_title_label=cat.category_title_label,
                category_summary_label=cat.category_summary_label,
                store_identifier=cat.store_identifier,
                store_display_short=cat.store_display_short,
                option_keys_order=list(cat.option_keys_order),
            )
            for cat in HIERARCHICAL_CATEGORY_DESCRIPTORS
        ]

        assigned_main_keys: set[str] = set()
        for cat_desc in self.categories_list:
            if cat_desc.store_identifier == "main_config":
                assigned_main_keys.update(cat_desc.option_keys_order)

        # Dynamically append any newly added DEFAULT_CONFIG keys to SYS (Category 5)
        main_schema_map: dict[str, tuple[Any, str]] = {}
        for setting_name, default_val, desc_text in config_lib.DEFAULT_CONFIG:
            main_schema_map[setting_name] = (default_val, desc_text)
            if setting_name not in assigned_main_keys:
                self.categories_list[4].option_keys_order.append(setting_name)
                assigned_main_keys.add(setting_name)

        bubble_schema_map: dict[str, tuple[Any, str]] = {}
        for const_name, raw_default_str, desc_text in context_bubble._DEFAULT_CONSTANTS:
            coerced_default = context_bubble._coerce_constant_value(raw_default_str)
            bubble_schema_map[const_name] = (coerced_default, desc_text)

        cli_schema_map: dict[str, tuple[Any, str]] = {}
        for cli_name, default_val, desc_text in CLI_AGENT_DEFAULT_SCHEMA:
            cli_schema_map[cli_name] = (default_val, desc_text)

        self.option_metadata_registry.clear()
        for cat_desc in self.categories_list:
            if cat_desc.store_identifier == "main_config":
                source_map = main_schema_map
            elif cat_desc.store_identifier == "bubble_constants":
                source_map = bubble_schema_map
            else:
                source_map = cli_schema_map

            for option_key in cat_desc.option_keys_order:
                if option_key not in source_map:
                    continue
                default_val, desc_text = source_map[option_key]
                type_tag = classify_option_type_tag(option_key, default_val)
                if type_tag == "BOOL":
                    presets = [True, False]
                elif type_tag == "ENUM":
                    presets = list(ENUM_ALLOWED_CHOICES_MAP.get(option_key, [default_val]))
                else:
                    presets = list(NUMERIC_AND_PATH_PRESETS_MAP.get(option_key, [default_val]))
                self.option_metadata_registry[option_key] = ConfigOptionMetadata(
                    option_key_name=option_key,
                    category_short_code=cat_desc.category_short_code,
                    store_identifier=cat_desc.store_identifier,
                    value_type_tag=type_tag,
                    default_python_value=default_val,
                    schema_description_text=desc_text,
                    preset_choices_list=presets,
                )

    def get_store_file_path(self, store_identifier: str) -> Path:
        if store_identifier == "main_config":
            return self.main_config_file_path
        if store_identifier == "bubble_constants":
            return self.bubble_constants_file_path
        return self.cli_config_file_path

    def reload_all_stores(self) -> None:
        """Load or bootstrap all 3 BEJSON 104a configuration stores from disk."""
        self.config_dir_path.mkdir(parents=True, exist_ok=True)
        self.context_dir_path.mkdir(parents=True, exist_ok=True)
        self.logs_dir_path.mkdir(parents=True, exist_ok=True)

        self.store_values_map["main_config"] = config_lib.init_config(
            self.main_config_file_path, schema=config_lib.DEFAULT_CONFIG
        )
        context_bubble.init_context_bubble(
            self.context_dir_path, self.config_dir_path, self.logs_dir_path
        )
        self.store_values_map["bubble_constants"] = context_bubble.load_constants(
            self.config_dir_path
        )
        self.store_values_map["cli_config"] = config_lib.init_config(
            self.cli_config_file_path, schema=CLI_AGENT_DEFAULT_SCHEMA
        )

    def save_store(self, store_identifier: str) -> bool:
        """Atomically persist the specified store back to its BEJSON 104a file."""
        if store_identifier == "main_config":
            config_lib.save_config(
                self.main_config_file_path,
                self.store_values_map["main_config"],
                schema=config_lib.DEFAULT_CONFIG,
            )
            return True
        if store_identifier == "cli_config":
            config_lib.save_config(
                self.cli_config_file_path,
                self.store_values_map["cli_config"],
                schema=CLI_AGENT_DEFAULT_SCHEMA,
            )
            return True
        if store_identifier == "bubble_constants":
            return self._save_bubble_constants_store()
        return False

    def _save_bubble_constants_store(self) -> bool:
        """Persist config/constant_config.bejson using BEJSON 104a atomic write."""
        bubble_dict = self.store_values_map["bubble_constants"]
        rows_list: list[list[Any]] = []
        for const_name, default_str, desc_text in context_bubble._DEFAULT_CONSTANTS:
            default_coerced = context_bubble._coerce_constant_value(default_str)
            live_val = bubble_dict.get(const_name, default_coerced)
            if live_val == default_coerced:
                defined_cell: Optional[str] = None
            elif isinstance(live_val, bool):
                defined_cell = "true" if live_val else "false"
            else:
                defined_cell = str(live_val)
            rows_list.append([const_name, defined_cell, default_str, desc_text])
        bejson_doc = bejson_core_create_104a(
            "Constant",
            list(context_bubble._CONSTANT_FIELDS),
            rows_list,
        )
        ok = bool(bejson_core_atomic_write(str(self.bubble_constants_file_path), bejson_doc))
        with context_bubble._FILE_CACHE_LOCK:
            context_bubble._FILE_CACHE.pop(str(self.bubble_constants_file_path), None)
        return ok

    def save_all_stores(self) -> bool:
        ok_main = self.save_store("main_config")
        ok_bubble = self.save_store("bubble_constants")
        ok_cli = self.save_store("cli_config")
        self.last_status_banner_code = "SAVED_ALL" if (ok_main and ok_bubble and ok_cli) else "SAVE_ERR"
        return ok_main and ok_bubble and ok_cli

    def get_option_value(self, option_key_name: str) -> Any:
        option_meta = self.option_metadata_registry[option_key_name]
        store_dict = self.store_values_map[option_meta.store_identifier]
        return store_dict.get(option_key_name, option_meta.default_python_value)

    def is_option_modified(self, option_key_name: str) -> bool:
        option_meta = self.option_metadata_registry[option_key_name]
        current_val = self.get_option_value(option_key_name)
        if option_meta.value_type_tag == "SEC":
            return bool(current_val)
        if option_meta.value_type_tag == "FLT":
            try:
                return abs(float(current_val) - float(option_meta.default_python_value)) > 1e-9
            except (TypeError, ValueError):
                return current_val != option_meta.default_python_value
        return current_val != option_meta.default_python_value

    def count_category_modifications(self, category_desc: ConfigCategoryDescriptor) -> int:
        return sum(1 for key in category_desc.option_keys_order if self.is_option_modified(key))

    def count_total_options_and_modifications(self) -> tuple[int, int]:
        total_count = len(self.option_metadata_registry)
        modified_count = sum(
            1 for key in self.option_metadata_registry if self.is_option_modified(key)
        )
        return total_count, modified_count

    def set_option_value(self, option_key_name: str, new_raw_value: Any) -> tuple[bool, str]:
        """Coerce, validate, and persist a single configuration setting."""
        if option_key_name not in self.option_metadata_registry:
            return False, "UNKNOWN_KEY"
        option_meta = self.option_metadata_registry[option_key_name]
        vtype = option_meta.value_type_tag

        if vtype == "BOOL":
            if isinstance(new_raw_value, bool):
                coerced_value = new_raw_value
            else:
                lowered = str(new_raw_value).strip().lower()
                if lowered in ("true", "1", "yes", "on", "y"):
                    coerced_value = True
                elif lowered in ("false", "0", "no", "off", "n"):
                    coerced_value = False
                else:
                    return False, "INVALID_BOOL"
        elif vtype == "ENUM":
            allowed_list = ENUM_ALLOWED_CHOICES_MAP.get(option_key_name, [])
            if option_key_name == "input_mode":
                try:
                    coerced_value = int(str(new_raw_value).strip())
                except ValueError:
                    return False, "INVALID_ENUM"
            else:
                coerced_value = str(new_raw_value).strip()
            if allowed_list and coerced_value not in allowed_list:
                return False, "INVALID_ENUM"
        elif vtype == "INT":
            try:
                coerced_value = int(str(new_raw_value).strip())
            except ValueError:
                return False, "INVALID_INT"
        elif vtype == "FLT":
            try:
                coerced_value = float(str(new_raw_value).strip())
            except ValueError:
                return False, "INVALID_FLT"
        elif vtype == "LIST":
            if isinstance(new_raw_value, list):
                coerced_value = [str(item).strip() for item in new_raw_value if str(item).strip()]
            else:
                raw_text = str(new_raw_value).strip()
                if raw_text.startswith("["):
                    try:
                        parsed_list = json.loads(raw_text)
                        if not isinstance(parsed_list, list):
                            return False, "INVALID_LIST"
                        coerced_value = [str(item).strip() for item in parsed_list if str(item).strip()]
                    except ValueError:
                        return False, "INVALID_LIST"
                else:
                    coerced_value = [part.strip() for part in raw_text.split(",") if part.strip()]
        else:
            coerced_value = str(new_raw_value).strip()

        self.store_values_map[option_meta.store_identifier][option_key_name] = coerced_value
        self.save_store(option_meta.store_identifier)
        self.last_status_banner_code = f"SET:{option_key_name[:12]}"
        return True, "UPDATED"

    def toggle_or_cycle_option(self, option_key_name: str) -> tuple[bool, str]:
        """
        Zero-typing one-key mutation:
          - BOOL -> flips True/False
          - ENUM -> cycles to next enum choice
          - SEC  -> generates a fresh URL-safe 24-byte token
          - INT / FLT / PATH / STR with presets -> cycles through preset_choices_list
        """
        if option_key_name not in self.option_metadata_registry:
            return False, "UNKNOWN_KEY"
        option_meta = self.option_metadata_registry[option_key_name]
        current_val = self.get_option_value(option_key_name)

        if option_meta.value_type_tag == "BOOL":
            return self.set_option_value(option_key_name, not bool(current_val))

        if option_meta.value_type_tag == "SEC":
            new_token = secrets.token_urlsafe(24)
            return self.set_option_value(option_key_name, new_token)

        choices = option_meta.preset_choices_list
        if choices:
            try:
                current_idx = choices.index(current_val)
                next_val = choices[(current_idx + 1) % len(choices)]
            except ValueError:
                next_val = choices[0]
            return self.set_option_value(option_key_name, next_val)

        return False, "NO_CYCLE_PRESET"

    def reset_single_option(self, option_key_name: str) -> tuple[bool, str]:
        """Restore a single configuration option to its schema default."""
        if option_key_name not in self.option_metadata_registry:
            return False, "UNKNOWN_KEY"
        option_meta = self.option_metadata_registry[option_key_name]
        default_copy = (
            list(option_meta.default_python_value)
            if isinstance(option_meta.default_python_value, list)
            else option_meta.default_python_value
        )
        self.store_values_map[option_meta.store_identifier][option_key_name] = default_copy
        self.save_store(option_meta.store_identifier)
        self.last_status_banner_code = f"RST:{option_key_name[:12]}"
        return True, "RESET_DEFAULT"

    def reset_category_to_defaults(self, category_desc: ConfigCategoryDescriptor) -> int:
        """Restore all options in a category to their schema defaults."""
        reset_count = 0
        for option_key in category_desc.option_keys_order:
            option_meta = self.option_metadata_registry[option_key]
            default_copy = (
                list(option_meta.default_python_value)
                if isinstance(option_meta.default_python_value, list)
                else option_meta.default_python_value
            )
            self.store_values_map[option_meta.store_identifier][option_key] = default_copy
            reset_count += 1
        self.save_store(category_desc.store_identifier)
        self.last_status_banner_code = f"RST_CAT:{category_desc.category_short_code}"
        return reset_count

    def reset_all_stores_to_defaults(self) -> int:
        """Factory reset all 3 configuration stores to their canonical defaults."""
        total_reset = 0
        for cat_desc in self.categories_list:
            total_reset += self.reset_category_to_defaults(cat_desc)
        self.last_status_banner_code = "FACTORY_RESET"
        return total_reset

    def create_snapshot_backup(self) -> tuple[bool, str]:
        """Create timestamped backups of all 3 BEJSON 104a config files in backups/."""
        try:
            self.backups_dir_path.mkdir(parents=True, exist_ok=True)
            timestamp_tag = time.strftime("%Y%m%d_%H%M%S")
            copied_count = 0
            for store_id in ("main_config", "bubble_constants", "cli_config"):
                src_path = self.get_store_file_path(store_id)
                if src_path.is_file():
                    dst_path = self.backups_dir_path / f"{src_path.stem}.{timestamp_tag}{src_path.suffix}.bak"
                    shutil.copy2(src_path, dst_path)
                    copied_count += 1
            self.last_status_banner_code = f"BAK:{copied_count}_FILES"
            return True, f"{copied_count} files -> backups/*_{timestamp_tag}.bak"
        except OSError as exc_err:
            module_logger.error("Snapshot backup failed: %s", exc_err)
            self.last_status_banner_code = "BAK_ERR"
            return False, str(exc_err)

    def validate_all_bejson_stores(self) -> list[tuple[str, str, int, str]]:
        """
        Validate all 3 BEJSON 104a stores using validate_bejson + Field Map Cache.
        Returns positional rows: (store_code, format_ver, row_count, status_tag).
        """
        validation_rows: list[tuple[str, str, int, str]] = []
        store_specs = [
            ("MAIN", self.main_config_file_path),
            ("BUBL", self.bubble_constants_file_path),
            ("CLIA", self.cli_config_file_path),
        ]
        all_valid = True
        for short_code, file_path in store_specs:
            if not file_path.is_file():
                validation_rows.append((short_code, "104a", 0, "MISSING"))
                all_valid = False
                continue
            loaded_doc = bejson_core_load_file(str(file_path))
            if not isinstance(loaded_doc, dict):
                validation_rows.append((short_code, "104a", 0, "LOAD_ERR"))
                all_valid = False
                continue
            field_map = bejson_core_get_field_map(loaded_doc)
            val_res = validate_bejson(loaded_doc, is_file=False)
            row_count = len(loaded_doc.get("Values", []))
            fmt_ver = str(loaded_doc.get("Format_Version", "104a"))
            status_tag = "VALID_104A" if (val_res.valid and bool(field_map)) else "INVALID"
            if status_tag != "VALID_104A":
                all_valid = False
            validation_rows.append((short_code, fmt_ver, row_count, status_tag))
        self.last_status_banner_code = "VLD_OK" if all_valid else "VLD_FAIL"
        return validation_rows

    def probe_configured_paths(self) -> list[tuple[str, str, str, str]]:
        """
        Probe all configured filesystem paths & directories across main_config.
        Returns positional rows: (id_str, kind_tag, state_tag, compact_target).
        """
        probe_rows: list[tuple[str, str, str, str]] = []
        idx_counter = 1

        for path_key in sorted(PATH_SETTING_KEYS_SET):
            raw_val = str(self.get_option_value(path_key) or "")
            candidate_path = Path(os.path.expandvars(os.path.expanduser(raw_val)))
            if not candidate_path.is_absolute():
                candidate_path = self.project_root_path / candidate_path
            exists_flag = candidate_path.exists()
            kind_tag = "DIR" if candidate_path.is_dir() else "FILE"
            state_tag = "EXISTS" if exists_flag else "MISSING"
            probe_rows.append(
                (f"{idx_counter:02d}", kind_tag, state_tag, compact_display_path(candidate_path, 34))
            )
            idx_counter += 1

        for list_key in ("agy_skills_directories", "gemini_md_global_paths"):
            list_val = self.get_option_value(list_key)
            if isinstance(list_val, list):
                for item_str in list_val:
                    candidate_path = Path(os.path.expandvars(os.path.expanduser(str(item_str))))
                    exists_flag = candidate_path.exists()
                    kind_tag = "SKIL" if "skills" in list_key else "GMMD"
                    state_tag = "EXISTS" if exists_flag else "MISSING"
                    probe_rows.append(
                        (f"{idx_counter:02d}", kind_tag, state_tag, compact_display_path(candidate_path, 34))
                    )
                    idx_counter += 1

        self.last_status_banner_code = f"PROBE:{len(probe_rows)}"
        return probe_rows

    def search_options(self, query_substring: str) -> list[ConfigOptionMetadata]:
        """Search all 67 configuration options by key name, category code, or description."""
        needle = query_substring.strip().lower()
        if not needle:
            return []
        matches: list[ConfigOptionMetadata] = []
        for cat_desc in self.categories_list:
            for key_name in cat_desc.option_keys_order:
                meta = self.option_metadata_registry[key_name]
                if (
                    needle in meta.option_key_name.lower()
                    or needle in meta.category_short_code.lower()
                    or needle in meta.schema_description_text.lower()
                ):
                    matches.append(meta)
        return matches


# ── Termux File/Dialog Picker Integration (Policy §8.5 & §8.7) ──────────────
def invoke_termux_path_picker(prompt_title: str = "Select Path") -> tuple[bool, str]:
    """
    Invoke Android/Termux dialog or storage picker per Policy §8.5.
    Never falls back to manual console path typing on API failure; returns
    (False, error_code) so caller can exit deterministically with code 10.
    """
    termux_dialog_bin = shutil.which("termux-dialog")
    if not termux_dialog_bin:
        module_logger.error("Termux API binary 'termux-dialog' not found in PATH.")
        return False, "TERMUX_API_MISSING"
    try:
        completed = subprocess.run(
            [termux_dialog_bin, "text", "-t", prompt_title],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            module_logger.error("termux-dialog exited with code %s", completed.returncode)
            return False, "TERMUX_API_ERROR"
        payload = json.loads(completed.stdout or "{}")
        if payload.get("code") == -1 and payload.get("text"):
            return True, str(payload["text"]).strip()
        return False, "PICKER_CANCELLED"
    except Exception as exc_err:
        module_logger.error("Termux picker invocation failed: %s", exc_err)
        return False, "TERMUX_API_TIMEOUT"


# ── 57-Column BEJSON Positional Telemetry Rendering Engine ─────────────────
def render_root_dashboard_lines(state: NewAgentConfigManagerState) -> list[str]:
    """
    Render the Root Hierarchy Dashboard strictly following the 57-Column
    BEJSON Positional Telemetry Discipline (Fields -> Positional Values,
    single-source telemetry, decoupled 3-column hotkeys, <= 57 chars/line).
    """
    main_cfg = state.store_values_map["main_config"]
    bubble_cfg = state.store_values_map["bubble_constants"]
    total_opts, mod_opts = state.count_total_options_and_modifications()

    engine_tok = clamp_cell_text(str(main_cfg.get("engine_mode", "rest")), 6)
    skills_tok = "ON" if main_cfg.get("agy_skills_enabled") else "OFF"
    gemmd_tok = "ON" if main_cfg.get("gemini_md_policy_enabled") else "OFF"
    subagt_tok = "ON" if main_cfg.get("subagents_enabled") else "OFF"
    gate_tok = "ON" if main_cfg.get("confirmation_gate") else "OFF"
    dry_tok = "ON" if main_cfg.get("dryrun_mode") else "OFF"
    dbg_tok = "ON" if main_cfg.get("debug_mode") else "OFF"
    mods_tok = f"{mod_opts}/{total_opts}"

    bubble_tok = f"{bubble_cfg.get('max_context_tokens', 8000)}t"
    obsvr_tok = "ON" if bubble_cfg.get("observer_enabled") else "OFF"
    autoc_tok = "ON" if main_cfg.get("auto_continue_enabled") else "OFF"
    turns_tok = f"{main_cfg.get('max_autonomy_turns', 20)}/{main_cfg.get('max_auto_continue_turns', 12)}"
    timeo_tok = f"{main_cfg.get('exec_timeout_seconds', 60)}s"
    retry_tok = "ON" if main_cfg.get("network_error_auto_retry") else "OFF"
    status_tok = clamp_cell_text(state.last_status_banner_code, 9)

    header_path = compact_display_path(state.main_config_file_path, 28)

    lines: list[str] = [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(f" {'NEWAGENT CONFIG [104a]':<26.26} {header_path:>28.28}"),
        TUI_DIVIDER_SUB_LINE,
        # Strip 1: Core Feature Gates & Mode Telemetry (Fields -> Values)
        clamp_tui_line(
            f" {'ENGINE':<6} {'SKILLS':<6} {'GEM_MD':<6} {'SUBAGT':<6} {'GATE':<5} {'DRY':<5} {'DBG':<5} {'MODS':<8}"
        ),
        clamp_tui_line(
            f" {engine_tok:<6.6} {skills_tok:<6.6} {gemmd_tok:<6.6} {subagt_tok:<6.6} {gate_tok:<5.5} {dry_tok:<5.5} {dbg_tok:<5.5} {mods_tok:<8.8}"
        ),
        TUI_DIVIDER_SUB_LINE,
        # Strip 2: Runtime Budgets, Timeouts & State Telemetry (Fields -> Values)
        clamp_tui_line(
            f" {'BUBBLE':<7} {'OBSVR':<6} {'AUTOC':<6} {'TURNS':<7} {'TIMEO':<6} {'RETRY':<6} {'STATE':<10}"
        ),
        clamp_tui_line(
            f" {bubble_tok:<7.7} {obsvr_tok:<6.6} {autoc_tok:<6.6} {turns_tok:<7.7} {timeo_tok:<6.6} {retry_tok:<6.6} {status_tok:<10.10}"
        ),
        TUI_DIVIDER_SUB_LINE,
        # Strip 3: Hierarchical Category Table (Fields -> Positional Values)
        clamp_tui_line(
            f" {'ID':<2} {'CAT':<3} {'STORE':<11} {'ITEMS':<5} {'MOD':<3} {'CATEGORY_DOMAIN':<25}"
        ),
    ]

    for cat_desc in state.categories_list:
        item_count = len(cat_desc.option_keys_order)
        mod_count = state.count_category_modifications(cat_desc)
        lines.append(
            clamp_tui_line(
                f" {cat_desc.category_index_number:02d} {cat_desc.category_short_code:<3.3} "
                f"{cat_desc.store_display_short:<11.11} {item_count:02d}    {mod_count:<3d} "
                f"{cat_desc.category_summary_label:<25.25}"
            )
        )

    lines.extend(
        [
            TUI_DIVIDER_MAIN_LINE,
            # Strip 4: Decoupled 3-Column Action Grid (18 + 18 + 18 + spaces <= 57)
            clamp_tui_line(f" {'[1-7] Open Cat':<18.18} {'[T] Quick Toggle':<18.18} {'[F] Find Option':<18.18}"),
            clamp_tui_line(f" {'[V] Validate 104a':<18.18} {'[P] Probe Paths':<18.18} {'[K] Snapshot Bak':<18.18}"),
            clamp_tui_line(f" {'[R] Reset All Def':<18.18} {'[A] About Tool':<18.18} {'[Q] Quit & Sync':<18.18}"),
            TUI_DIVIDER_MAIN_LINE,
        ]
    )
    return lines


def render_category_submenu_lines(
    state: NewAgentConfigManagerState,
    category_desc: ConfigCategoryDescriptor,
) -> list[str]:
    """
    Render a Category Submenu strictly adhering to the 57-Column BEJSON
    Positional Telemetry Discipline.
    """
    store_path = state.get_store_file_path(category_desc.store_identifier)
    compact_store = compact_display_path(store_path, 24)
    title_banner = f"CAT {category_desc.category_index_number:02d} [{category_desc.category_short_code}] {category_desc.category_title_label}"

    row_total = len(category_desc.option_keys_order)
    mod_total = state.count_category_modifications(category_desc)
    bool_cnt = 0
    num_cnt = 0
    enum_cnt = 0
    other_cnt = 0
    for key_name in category_desc.option_keys_order:
        vtype = state.option_metadata_registry[key_name].value_type_tag
        if vtype == "BOOL":
            bool_cnt += 1
        elif vtype in ("INT", "FLT"):
            num_cnt += 1
        elif vtype == "ENUM":
            enum_cnt += 1
        else:
            other_cnt += 1

    lines: list[str] = [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(f" {title_banner:<30.30} {compact_store:>24.24}"),
        TUI_DIVIDER_SUB_LINE,
        # Strip 1: Category Telemetry Strip
        clamp_tui_line(
            f" {'CAT':<4} {'STORE':<12} {'ROWS':<5} {'MODS':<5} {'BOOL':<5} {'NUM':<5} {'ENUM':<5} {'PATH/LST':<8}"
        ),
        clamp_tui_line(
            f" {category_desc.category_short_code:<4.4} {category_desc.store_display_short:<12.12} "
            f"{row_total:02d}    {mod_total:<5d} {bool_cnt:<5d} {num_cnt:<5d} {enum_cnt:<5d} {other_cnt:<8d}"
        ),
        TUI_DIVIDER_SUB_LINE,
        # Strip 2: Positional Option Records
        clamp_tui_line(f" {'ID':<2} {'TYPE':<4} {'M':<1} {'SETTING_NAME':<26} {'VALUE':<18}"),
    ]

    for idx_zero, key_name in enumerate(category_desc.option_keys_order, start=1):
        opt_meta = state.option_metadata_registry[key_name]
        live_val = state.get_option_value(key_name)
        mod_flag = "*" if state.is_option_modified(key_name) else "-"
        key_cell = clamp_cell_text(key_name, 26)
        val_cell = format_positional_value_cell(opt_meta, live_val, max_width=18)
        lines.append(
            clamp_tui_line(
                f" {idx_zero:02d} {opt_meta.value_type_tag:<4.4} {mod_flag:<1.1} {key_cell:<26.26} {val_cell:<18.18}"
            )
        )

    lines.extend(
        [
            TUI_DIVIDER_MAIN_LINE,
            clamp_tui_line(f" {'[1-N] Inspect Row':<18.18} {'[T] Toggle/Cycle':<18.18} {'[E] Edit Value':<18.18}"),
            clamp_tui_line(f" {'[R] Reset Row':<18.18} {'[D] Defaults Cat':<18.18} {'[P] Probe Paths':<18.18}"),
            clamp_tui_line(f" {'[N] Next Cat':<18.18} {'[B] Back Root':<18.18} {'[Q] Quit & Sync':<18.18}"),
            TUI_DIVIDER_MAIN_LINE,
        ]
    )
    return lines


def render_option_inspector_lines(
    state: NewAgentConfigManagerState,
    category_desc: ConfigCategoryDescriptor,
    row_one_based_index: int,
) -> list[str]:
    """
    Render the Option Inspector & Zero-Typing Preset Selector view (<= 57 cols).
    """
    option_key = category_desc.option_keys_order[row_one_based_index - 1]
    opt_meta = state.option_metadata_registry[option_key]
    current_val = state.get_option_value(option_key)
    store_path = state.get_store_file_path(opt_meta.store_identifier)
    compact_store = compact_display_path(store_path, 26)

    mod_state_tag = "MODIFIED" if state.is_option_modified(option_key) else "DEFAULT"
    curr_disp = format_positional_value_cell(opt_meta, current_val, max_width=16)
    def_disp = format_positional_value_cell(opt_meta, opt_meta.default_python_value, max_width=15)

    header_left = f"OPT {category_desc.category_index_number:02d}.{row_one_based_index:02d} [{opt_meta.value_type_tag}]"

    lines: list[str] = [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(f" {header_left:<28.28} {compact_store:>26.26}"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(f" {'CAT':<4} {'ID':<3} {'TYPE':<5} {'STATE':<8} {'CURRENT_VAL':<16} {'DEFAULT_VAL':<15}"),
        clamp_tui_line(
            f" {category_desc.category_short_code:<4.4} {row_one_based_index:02d}  "
            f"{opt_meta.value_type_tag:<5.5} {mod_state_tag:<8.8} {curr_disp:<16.16} {def_disp:<15.15}"
        ),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(" SETTING_KEY"),
        clamp_tui_line(f" {clamp_cell_text(option_key, 55)}"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(" SCHEMA_DESCRIPTION"),
    ]

    wrapped_desc = textwrap.wrap(opt_meta.schema_description_text, width=55) or ["(no description)"]
    for desc_line in wrapped_desc[:3]:
        lines.append(clamp_tui_line(f" {desc_line}"))

    lines.append(TUI_DIVIDER_SUB_LINE)

    if opt_meta.value_type_tag == "LIST":
        lines.append(clamp_tui_line(f" {'IDX':<3} {'LIST_ENTRY_VALUE':<38} {'STATE':<12}"))
        items_list = current_val if isinstance(current_val, list) else []
        if not items_list:
            lines.append(clamp_tui_line(" [0 items — press [A] to add or [R] to reset default]"))
        else:
            for item_idx, item_val in enumerate(items_list[:8], start=1):
                disp_item = clamp_cell_text(str(item_val), 38)
                lines.append(clamp_tui_line(f" {item_idx:02d}  {disp_item:<38.38} {'ACTIVE':<12.12}"))
        lines.extend(
            [
                TUI_DIVIDER_MAIN_LINE,
                clamp_tui_line(f" {'[A] Add Entry':<18.18} {'[X] Remove Idx':<18.18} {'[R] Reset Default':<18.18}"),
                clamp_tui_line(f" {'[P] Termux Picker':<18.18} {'[B] Back Category':<18.18} {'[Q] Quit & Sync':<18.18}"),
                TUI_DIVIDER_MAIN_LINE,
            ]
        )
    else:
        lines.append(clamp_tui_line(f" {'IDX':<3} {'PRESET_OPTION':<34} {'STATUS':<16}"))
        presets = opt_meta.preset_choices_list
        if not presets:
            lines.append(clamp_tui_line(" [No static presets — press [T] or [C] to set value]"))
        else:
            for preset_idx, preset_val in enumerate(presets[:9], start=1):
                is_curr = current_val == preset_val
                is_def = opt_meta.default_python_value == preset_val
                if is_curr and is_def:
                    st_label = "ACTIVE (DEFAULT)"
                elif is_curr:
                    st_label = "ACTIVE"
                elif is_def:
                    st_label = "DEFAULT"
                else:
                    st_label = "--"
                preset_disp = clamp_cell_text(
                    compact_display_path(str(preset_val), 34)
                    if opt_meta.value_type_tag == "PATH"
                    else str(preset_val),
                    34,
                )
                lines.append(clamp_tui_line(f" {preset_idx:02d}  {preset_disp:<34.34} {st_label:<16.16}"))
        lines.extend(
            [
                TUI_DIVIDER_MAIN_LINE,
                clamp_tui_line(f" {'[1-9] Pick Preset':<18.18} {'[T] Toggle/Cycle':<18.18} {'[R] Reset Default':<18.18}"),
                clamp_tui_line(f" {'[C] Custom Value':<18.18} {'[P] Termux Picker':<18.18} {'[B] Back Category':<18.18}"),
                TUI_DIVIDER_MAIN_LINE,
            ]
        )
    return lines


def render_validation_and_probe_lines(state: NewAgentConfigManagerState, mode: str = "validate") -> list[str]:
    """
    Render the BEJSON 104a Schema Validation or Path Probe view (<= 57 cols).
    """
    lines: list[str] = [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(
            f" {'BEJSON 104a VALIDATOR & PATH PROBE':<36.36} {'[104a/300]':>18.18}"
        ),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(f" {'STORE':<6} {'FORMAT':<8} {'ROWS':<6} {'FIELD_MAP':<11} {'VALIDATION':<20}"),
    ]

    for store_code, fmt_ver, row_cnt, status_tag in state.validate_all_bejson_stores():
        fmap_state = "O(1)_CACHED" if status_tag == "VALID_104A" else "ERR"
        lines.append(
            clamp_tui_line(
                f" {store_code:<6.6} {fmt_ver:<8.8} {row_cnt:<6d} {fmap_state:<11.11} {status_tag:<20.20}"
            )
        )

    if mode == "probe":
        lines.extend(
            [
                TUI_DIVIDER_SUB_LINE,
                clamp_tui_line(f" {'ID':<2} {'KIND':<4} {'STATE':<7} {'RESOLVED_PATH':<40}"),
            ]
        )
        for pid, kind_tag, state_tag, target_disp in state.probe_configured_paths():
            lines.append(
                clamp_tui_line(
                    f" {pid:<2.2} {kind_tag:<4.4} {state_tag:<7.7} {target_disp:<40.40}"
                )
            )

    lines.extend(
        [
            TUI_DIVIDER_MAIN_LINE,
            clamp_tui_line(f" {'[V] Re-Validate':<18.18} {'[P] Probe Paths':<18.18} {'[B] Back Menu':<18.18}"),
            TUI_DIVIDER_MAIN_LINE,
        ]
    )
    return lines


def render_search_results_lines(
    state: NewAgentConfigManagerState,
    query_string: str,
    matched_options: list[ConfigOptionMetadata],
) -> list[str]:
    """Render positional search results across all 67 configuration options (<= 57 cols)."""
    lines: list[str] = [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(
            f" {'SEARCH OPTIONS [104a]':<24.24} {clamp_cell_text(f'Q:{query_string}', 30):>30.30}"
        ),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(f" {'ID':<2} {'CAT':<3} {'TYPE':<4} {'SETTING_NAME':<26} {'VALUE':<17}"),
    ]
    if not matched_options:
        lines.append(clamp_tui_line(" [0 matches — press [F] to search again or [B] to return]"))
    else:
        for idx_num, meta in enumerate(matched_options[:12], start=1):
            val_str = format_positional_value_cell(meta, state.get_option_value(meta.option_key_name), 17)
            lines.append(
                clamp_tui_line(
                    f" {idx_num:02d} {meta.category_short_code:<3.3} {meta.value_type_tag:<4.4} "
                    f"{clamp_cell_text(meta.option_key_name, 26):<26.26} {val_str:<17.17}"
                )
            )
    lines.extend(
        [
            TUI_DIVIDER_MAIN_LINE,
            clamp_tui_line(f" {'[1-N] Open Match':<18.18} {'[T] Toggle Match':<18.18} {'[B] Back Root':<18.18}"),
            TUI_DIVIDER_MAIN_LINE,
        ]
    )
    return lines


def render_about_screen_lines() -> list[str]:
    """Render the Policy §9.2 About/Info screen within the 57-column ceiling."""
    return [
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(f" {'ABOUT NEWAGENT CONFIG MANAGER':<36.36} {'v' + VERSION:>18.18}"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(f" {'NAME':<18} {'VERSION':<8} {'RELEASE':<8} {'FORMAT':<18}"),
        clamp_tui_line(f" {'config_manager.py':<18.18} {VERSION:<8.8} {'300':<8.8} {'BEJSON 104a':<18.18}"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(" AUTHOR_CREDIT"),
        clamp_tui_line(" Elton Boehnen · boehnenelton2024@gmail.com"),
        clamp_tui_line(" boehnenelton2024.pages.dev · github.com/boehnenelton"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(" RELATIONAL_ID"),
        clamp_tui_line(f" {RELATIONAL_ID}"),
        TUI_DIVIDER_SUB_LINE,
        clamp_tui_line(" ARCHITECTURE"),
        clamp_tui_line(" 57-Col BEJSON Positional Telemetry TUI (7 Categories)"),
        TUI_DIVIDER_MAIN_LINE,
        clamp_tui_line(f" {'[B] Back Root':<18.18} {'[V] Validate 104a':<18.18} {'[Q] Quit & Sync':<18.18}"),
        TUI_DIVIDER_MAIN_LINE,
    ]


# ── Interactive TUI Controller Loop ────────────────────────────────────────
class PositionalConfigTUIController:
    """
    Interactive hierarchical menu controller for NewAgentConfigManagerState.
    Supports injected input_provider and output_writer for deterministic testing.
    """

    def __init__(
        self,
        state: NewAgentConfigManagerState,
        input_provider: Callable[[str], str] = input,
        output_writer: Callable[[str], Any] = sys.stdout.write,
        picker_callable: Callable[[str], tuple[bool, str]] = invoke_termux_path_picker,
    ) -> None:
        self.state = state
        self.input_provider = input_provider
        self.output_writer = output_writer
        self.picker_callable = picker_callable

    def _emit_screen(self, screen_lines: list[str]) -> None:
        rendered_block = "\n".join(clamp_tui_line(line) for line in screen_lines) + "\n"
        self.output_writer(rendered_block)

    def run_interactive_loop(self) -> int:
        """Main Root Dashboard loop. Returns deterministic exit code (0, 10, 20, 30)."""
        while True:
            self._emit_screen(render_root_dashboard_lines(self.state))
            try:
                raw_cmd = self.input_provider("Action (1-7 or Hotkey) > ").strip()
            except (EOFError, KeyboardInterrupt):
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS

            if not raw_cmd:
                continue

            upper_cmd = raw_cmd.upper()
            if upper_cmd in ("Q", "QUIT", "EXIT"):
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS

            if raw_cmd.isdigit() and 1 <= int(raw_cmd) <= len(self.state.categories_list):
                cat_idx = int(raw_cmd) - 1
                exit_rc = self._run_category_loop(cat_idx)
                if exit_rc is not None:
                    return exit_rc
                continue

            if upper_cmd.startswith("T"):
                # Quick toggle from root by key name or prompt
                arg_tail = raw_cmd[1:].strip()
                if not arg_tail:
                    try:
                        arg_tail = self.input_provider("Option key to toggle > ").strip()
                    except (EOFError, KeyboardInterrupt):
                        continue
                if arg_tail:
                    self.state.toggle_or_cycle_option(arg_tail)
                continue

            if upper_cmd.startswith("F"):
                query_tail = raw_cmd[1:].strip()
                if not query_tail:
                    try:
                        query_tail = self.input_provider("Search query > ").strip()
                    except (EOFError, KeyboardInterrupt):
                        continue
                if query_tail:
                    exit_rc = self._run_search_loop(query_tail)
                    if exit_rc is not None:
                        return exit_rc
                continue

            if upper_cmd == "V":
                exit_rc = self._run_validation_probe_loop("validate")
                if exit_rc is not None:
                    return exit_rc
                continue

            if upper_cmd == "P":
                exit_rc = self._run_validation_probe_loop("probe")
                if exit_rc is not None:
                    return exit_rc
                continue

            if upper_cmd == "K":
                self.state.create_snapshot_backup()
                continue

            if upper_cmd == "R":
                try:
                    confirm = self.input_provider("Reset ALL 67 options to defaults? (y/N) > ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    continue
                if confirm == "y":
                    self.state.reset_all_stores_to_defaults()
                continue

            if upper_cmd == "A":
                self._emit_screen(render_about_screen_lines())
                try:
                    post_about = self.input_provider("Action ([B] Back / [Q] Quit) > ").strip().upper()
                except (EOFError, KeyboardInterrupt):
                    return EXIT_CODE_SUCCESS
                if post_about == "Q":
                    self.state.save_all_stores()
                    return EXIT_CODE_SUCCESS
                continue

    def _run_category_loop(self, category_zero_idx: int) -> Optional[int]:
        """Submenu loop for a single category. Returns None to go back to root, or exit code."""
        curr_cat_idx = category_zero_idx
        while True:
            cat_desc = self.state.categories_list[curr_cat_idx]
            self._emit_screen(render_category_submenu_lines(self.state, cat_desc))
            try:
                raw_cmd = self.input_provider(
                    f"Select Row (01-{len(cat_desc.option_keys_order):02d}) or Hotkey > "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                return None

            if not raw_cmd:
                continue

            upper_cmd = raw_cmd.upper()
            if upper_cmd in ("B", "BACK", "0"):
                return None
            if upper_cmd in ("Q", "QUIT"):
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS
            if upper_cmd == "N":
                curr_cat_idx = (curr_cat_idx + 1) % len(self.state.categories_list)
                continue
            if upper_cmd == "D":
                self.state.reset_category_to_defaults(cat_desc)
                continue
            if upper_cmd == "P":
                exit_rc = self._run_validation_probe_loop("probe")
                if exit_rc is not None:
                    return exit_rc
                continue

            # Direct row number (1..N) -> open Option Inspector
            if raw_cmd.isdigit():
                row_num = int(raw_cmd)
                if 1 <= row_num <= len(cat_desc.option_keys_order):
                    exit_rc = self._run_option_inspector_loop(cat_desc, row_num)
                    if exit_rc is not None:
                        return exit_rc
                continue

            # T <row>, E <row>, I <row>, R <row>
            cmd_head = upper_cmd[0]
            cmd_tail = raw_cmd[1:].strip()
            if cmd_head in ("T", "E", "I", "R"):
                if not cmd_tail:
                    try:
                        cmd_tail = self.input_provider(
                            f"Row number (01-{len(cat_desc.option_keys_order):02d}) > "
                        ).strip()
                    except (EOFError, KeyboardInterrupt):
                        continue
                if cmd_tail.isdigit():
                    row_num = int(cmd_tail)
                    if 1 <= row_num <= len(cat_desc.option_keys_order):
                        opt_key = cat_desc.option_keys_order[row_num - 1]
                        if cmd_head == "T":
                            self.state.toggle_or_cycle_option(opt_key)
                        elif cmd_head == "R":
                            self.state.reset_single_option(opt_key)
                        else:
                            exit_rc = self._run_option_inspector_loop(cat_desc, row_num)
                            if exit_rc is not None:
                                return exit_rc

    def _run_option_inspector_loop(
        self,
        cat_desc: ConfigCategoryDescriptor,
        row_one_based_index: int,
    ) -> Optional[int]:
        """Inspector & Zero-Typing Preset Editor loop for one option."""
        option_key = cat_desc.option_keys_order[row_one_based_index - 1]
        opt_meta = self.state.option_metadata_registry[option_key]

        while True:
            self._emit_screen(render_option_inspector_lines(self.state, cat_desc, row_one_based_index))
            try:
                raw_cmd = self.input_provider("Pick Preset or Hotkey > ").strip()
            except (EOFError, KeyboardInterrupt):
                return None

            if not raw_cmd:
                continue

            upper_cmd = raw_cmd.upper()
            if upper_cmd in ("B", "BACK", "0"):
                return None
            if upper_cmd in ("Q", "QUIT"):
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS
            if upper_cmd == "T":
                self.state.toggle_or_cycle_option(option_key)
                continue
            if upper_cmd == "R":
                self.state.reset_single_option(option_key)
                continue

            if upper_cmd == "P":
                # Policy §8.5 / §8.7: Use Termux picker; abort with Exit Code 10 on failure
                picker_ok, picker_val = self.picker_callable(f"Select value for {option_key}")
                if not picker_ok:
                    module_logger.error("Termux picker failed (%s) for %s", picker_val, option_key)
                    return EXIT_CODE_PICKER_FAILURE
                if opt_meta.value_type_tag == "LIST":
                    curr_list = list(self.state.get_option_value(option_key) or [])
                    if picker_val not in curr_list:
                        curr_list.append(picker_val)
                    self.state.set_option_value(option_key, curr_list)
                else:
                    self.state.set_option_value(option_key, picker_val)
                continue

            if opt_meta.value_type_tag == "LIST":
                if upper_cmd.startswith("A"):
                    entry_val = raw_cmd[1:].strip()
                    if not entry_val:
                        if option_key in ("agy_skills_directories", "gemini_md_global_paths"):
                            picker_ok, picker_val = self.picker_callable(f"Add path to {option_key}")
                            if not picker_ok:
                                return EXIT_CODE_PICKER_FAILURE
                            entry_val = picker_val
                        else:
                            try:
                                entry_val = self.input_provider("Add list entry > ").strip()
                            except (EOFError, KeyboardInterrupt):
                                continue
                    if entry_val:
                        curr_list = list(self.state.get_option_value(option_key) or [])
                        if entry_val not in curr_list:
                            curr_list.append(entry_val)
                        self.state.set_option_value(option_key, curr_list)
                    continue
                if upper_cmd.startswith("X"):
                    idx_tail = raw_cmd[1:].strip()
                    if not idx_tail:
                        try:
                            idx_tail = self.input_provider("Remove item index (1-N) > ").strip()
                        except (EOFError, KeyboardInterrupt):
                            continue
                    if idx_tail.isdigit():
                        rm_idx = int(idx_tail) - 1
                        curr_list = list(self.state.get_option_value(option_key) or [])
                        if 0 <= rm_idx < len(curr_list):
                            curr_list.pop(rm_idx)
                            self.state.set_option_value(option_key, curr_list)
                    continue
            else:
                if raw_cmd.isdigit():
                    preset_idx = int(raw_cmd) - 1
                    presets = opt_meta.preset_choices_list
                    if 0 <= preset_idx < len(presets):
                        self.state.set_option_value(option_key, presets[preset_idx])
                    continue
                if upper_cmd.startswith("C"):
                    if opt_meta.value_type_tag == "PATH":
                        # Policy §8.5: Path input must use picker or presets, never console path typing
                        picker_ok, picker_val = self.picker_callable(f"Select path for {option_key}")
                        if not picker_ok:
                            return EXIT_CODE_PICKER_FAILURE
                        self.state.set_option_value(option_key, picker_val)
                        continue
                    custom_tail = raw_cmd[1:].strip()
                    if not custom_tail:
                        try:
                            custom_tail = self.input_provider(f"New {opt_meta.value_type_tag} value > ").strip()
                        except (EOFError, KeyboardInterrupt):
                            continue
                    if custom_tail:
                        self.state.set_option_value(option_key, custom_tail)
                    continue

    def _run_validation_probe_loop(self, initial_mode: str = "validate") -> Optional[int]:
        curr_mode = initial_mode
        while True:
            self._emit_screen(render_validation_and_probe_lines(self.state, mode=curr_mode))
            try:
                raw_cmd = self.input_provider("Action ([V] Validate / [P] Probe / [B] Back) > ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                return None
            if raw_cmd in ("B", "BACK", ""):
                return None
            if raw_cmd == "Q":
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS
            if raw_cmd == "V":
                curr_mode = "validate"
            elif raw_cmd == "P":
                curr_mode = "probe"

    def _run_search_loop(self, query_string: str) -> Optional[int]:
        matches = self.state.search_options(query_string)
        while True:
            self._emit_screen(render_search_results_lines(self.state, query_string, matches))
            try:
                raw_cmd = self.input_provider("Select Match (1-N), [T] Toggle, or [B] Back > ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if not raw_cmd or raw_cmd.upper() in ("B", "BACK", "0"):
                return None
            if raw_cmd.upper() == "Q":
                self.state.save_all_stores()
                return EXIT_CODE_SUCCESS
            if raw_cmd.isdigit():
                match_idx = int(raw_cmd) - 1
                if 0 <= match_idx < len(matches):
                    matched_meta = matches[match_idx]
                    for cat_desc in self.state.categories_list:
                        if cat_desc.category_short_code == matched_meta.category_short_code:
                            row_idx = cat_desc.option_keys_order.index(matched_meta.option_key_name) + 1
                            exit_rc = self._run_option_inspector_loop(cat_desc, row_idx)
                            if exit_rc is not None:
                                return exit_rc
                            break
                continue
            if raw_cmd.upper().startswith("T"):
                tail = raw_cmd[1:].strip()
                if tail.isdigit():
                    match_idx = int(tail) - 1
                    if 0 <= match_idx < len(matches):
                        self.state.toggle_or_cycle_option(matches[match_idx].option_key_name)
                continue
