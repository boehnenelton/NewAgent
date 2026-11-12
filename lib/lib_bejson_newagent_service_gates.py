"""
Library:        lib_bejson_newagent_service_gates.py
Family:         NewAgent
Description:    Gated modular service abstraction layers separating transport and
                UI route handlers (webagent.py / web_routes/*) and interactive
                TUI dispatch (agent.py) from domain logic. Enforces strict
                <hierarchy>_<group>_<purpose> taxonomy naming, O(1) BEJSON 104
                Core library primitives, thread-safe execution locks, security
                boundary gates, and full 67-option / 7-category / 3-store UI
                configuration control.
Version:        1.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Release_Version: 300
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  5c8e2a91-4d7b-4f19-9a30-7b6e1c4d8f23
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_atomic_write,
    bejson_core_create_104a,
    bejson_core_get_field_map,
    bejson_core_load_file,
)
from lib_bejson_Core_bejson_env import get_env_path
from lib_bejson_Core_bejson_validator import validate_bejson

import lib_bejson_newagent_actions as actions_module
import lib_bejson_newagent_backup as backup_module
import lib_bejson_newagent_config as config_module
import lib_bejson_newagent_config_tui as config_tui_module
import lib_bejson_newagent_context_bubble as context_bubble_module
import lib_bejson_newagent_engine_interactions as interactions_module
import lib_bejson_newagent_engine_rest as rest_module
import lib_bejson_newagent_env as env_module
import lib_bejson_newagent_errors as errors_module
import lib_bejson_newagent_input as input_module
import lib_bejson_newagent_jobs as jobs_module
import lib_bejson_newagent_session as session_module
import lib_bejson_newagent_subagent_sessions as subagent_sessions_module
import lib_bejson_newagent_tui as tui_module

VERSION = "1.0.0"
RELATIONAL_ID = "5c8e2a91-4d7b-4f19-9a30-7b6e1c4d8f23"
AUTHOR_CREDIT = (
    "Elton Boehnen · boehnenelton2024@gmail.com · "
    "boehnenelton2024.pages.dev · github.com/boehnenelton"
)

service_module_logger = logging.getLogger(__name__)

# Security boundary: configuration keys protected against HTTP mutation
SERVICE_GATE_PROTECTED_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "web_auth_token",
        "exec_denylist",
        "env_secure_file_path",
        "env_paths_file_path",
    }
)


@dataclass
class ServiceGateResponseEnvelope:
    """Standardized return envelope across all gated service controllers."""

    service_gate_response_ok_flag: bool
    service_gate_response_http_status: int
    service_gate_response_payload_map: dict[str, Any] = field(default_factory=dict)


def _service_gate_resolve_state_lock(terminal_state_holder: Any) -> threading.Lock:
    """Return the instance threading.Lock on terminal_state_holder, creating one if absent."""
    existing_state_lock = getattr(terminal_state_holder, "_state_lock", None)
    if existing_state_lock is None:
        existing_state_lock = threading.Lock()
        try:
            setattr(terminal_state_holder, "_state_lock", existing_state_lock)
        except Exception:
            pass
    return existing_state_lock


# =====================================================================
# 1. CONFIGURATION & MODEL REGISTRY SERVICE GATE
# =====================================================================
class ServiceGateConfigurationController:
    """
    Gated service abstraction layer for configuration, model selection, and
    runtime telemetry status. Bridges WebAgentTerminal (or test stubs) with
    NewAgentConfigManagerState (7 categories, 67 options, 3 BEJSON 104a stores).
    """

    def __init__(
        self,
        terminal_state_holder: Any,
        project_root_dir_path: Path,
        main_config_file_path: Path,
        model_catalog_file_path: Path,
        runtime_version_string: str,
    ) -> None:
        self.terminal_state_holder = terminal_state_holder
        self.project_root_dir_path = project_root_dir_path
        self.main_config_file_path = main_config_file_path
        self.model_catalog_file_path = model_catalog_file_path
        self.runtime_version_string = runtime_version_string
        self._config_manager_instance: Optional[config_tui_module.NewAgentConfigManagerState] = None

    def _is_full_terminal_instance(self) -> bool:
        """Detect whether terminal_state_holder is a full WebAgentTerminal or a unit-test stub."""
        return hasattr(self.terminal_state_holder, "rest_prompter") and hasattr(
            self.terminal_state_holder, "model_reg"
        )

    def _get_or_init_config_manager(self) -> config_tui_module.NewAgentConfigManagerState:
        """Lazily initialize NewAgentConfigManagerState and synchronize live terminal config."""
        if self._config_manager_instance is None:
            self._config_manager_instance = config_tui_module.NewAgentConfigManagerState(
                project_root_path=self.project_root_dir_path
            )
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", None)
        if isinstance(live_terminal_config_map, dict):
            self._config_manager_instance.store_values_map["main_config"].update(
                live_terminal_config_map
            )
        return self._config_manager_instance

    def _sync_manager_to_terminal_config(
        self, config_manager_state: config_tui_module.NewAgentConfigManagerState
    ) -> None:
        """Push updated main_config values back into terminal_state_holder.config."""
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", None)
        if isinstance(live_terminal_config_map, dict):
            for option_key_name, option_value in config_manager_state.store_values_map[
                "main_config"
            ].items():
                live_terminal_config_map[option_key_name] = option_value

    def gate_config_query_catalog(
        self, category_filter_code: Optional[str] = None, search_query_text: Optional[str] = None
    ) -> ServiceGateResponseEnvelope:
        """
        Return both backward-compatible flat `config` rows AND rich 7-category / 3-store
        hierarchical metadata for full UI configuration control.
        """
        config_manager_state = self._get_or_init_config_manager()
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", None) or {}
        default_description_map = {
            setting_name: setting_desc
            for setting_name, _, setting_desc in config_module.DEFAULT_CONFIG
        }

        normalized_category_filter = (category_filter_code or "").strip().upper()
        normalized_search_filter = (search_query_text or "").strip().lower()

        # If running against a lightweight test stub with custom keys not in the 67-option catalog,
        # ensure every key in terminal_state_holder.config is included in `config` rows.
        catalog_rows_list: list[dict[str, Any]] = []
        included_option_keys: set[str] = set()

        for category_descriptor in config_manager_state.categories_list:
            if (
                normalized_category_filter
                and normalized_category_filter != "ALL"
                and category_descriptor.category_short_code != normalized_category_filter
            ):
                continue

            for option_key_name in category_descriptor.option_keys_order:
                if option_key_name not in config_manager_state.option_metadata_registry:
                    continue
                # If running on a minimal unit test stub that only seeded a few keys in term.config,
                # still surface all 67 options while pulling overrides from live_terminal_config_map.
                option_metadata = config_manager_state.option_metadata_registry[option_key_name]
                if (
                    option_metadata.store_identifier == "main_config"
                    and option_key_name in live_terminal_config_map
                ):
                    raw_current_value = live_terminal_config_map[option_key_name]
                else:
                    raw_current_value = config_manager_state.get_option_value(option_key_name)

                is_protected_key = option_key_name in SERVICE_GATE_PROTECTED_CONFIG_KEYS
                masked_or_live_value = "********" if is_protected_key else raw_current_value

                if normalized_search_filter:
                    searchable_haystack = (
                        f"{option_key_name} {option_metadata.schema_description_text} "
                        f"{category_descriptor.category_short_code} {category_descriptor.category_summary_label}"
                    ).lower()
                    if normalized_search_filter not in searchable_haystack:
                        continue

                python_type_name = type(raw_current_value).__name__
                is_modified_flag = config_manager_state.is_option_modified(option_key_name)

                catalog_rows_list.append(
                    {
                        "name": option_key_name,
                        "value": masked_or_live_value,
                        "type": python_type_name,
                        "type_tag": option_metadata.value_type_tag,
                        "category_code": category_descriptor.category_short_code,
                        "category_label": category_descriptor.category_summary_label,
                        "store_id": option_metadata.store_identifier,
                        "store_file": category_descriptor.store_display_short,
                        "default_value": (
                            "********"
                            if is_protected_key
                            else option_metadata.default_python_value
                        ),
                        "presets": (
                            []
                            if is_protected_key
                            else list(option_metadata.preset_choices_list)
                        ),
                        "modified": is_modified_flag,
                        "protected": is_protected_key,
                        "description": option_metadata.schema_description_text
                        or default_description_map.get(option_key_name, ""),
                    }
                )
                included_option_keys.add(option_key_name)

        # Include any extra ad-hoc keys present in live_terminal_config_map (e.g., from unit test stubs)
        if not normalized_category_filter or normalized_category_filter in ("ALL", "SYS"):
            for extra_key_name, extra_key_value in live_terminal_config_map.items():
                if extra_key_name in included_option_keys:
                    continue
                is_protected_key = extra_key_name in SERVICE_GATE_PROTECTED_CONFIG_KEYS
                catalog_rows_list.append(
                    {
                        "name": extra_key_name,
                        "value": "********" if is_protected_key else extra_key_value,
                        "type": type(extra_key_value).__name__,
                        "type_tag": config_tui_module.classify_option_type_tag(
                            extra_key_name, extra_key_value
                        ),
                        "category_code": "SYS",
                        "category_label": "TUI, IO, Net & Web Auth",
                        "store_id": "main_config",
                        "store_file": "config.json",
                        "default_value": extra_key_value,
                        "presets": [],
                        "modified": False,
                        "protected": is_protected_key,
                        "description": default_description_map.get(extra_key_name, ""),
                    }
                )

        categories_summary_list: list[dict[str, Any]] = []
        for category_descriptor in config_manager_state.categories_list:
            categories_summary_list.append(
                {
                    "index": category_descriptor.category_index_number,
                    "code": category_descriptor.category_short_code,
                    "title": category_descriptor.category_title_label,
                    "label": category_descriptor.category_summary_label,
                    "store_id": category_descriptor.store_identifier,
                    "store_file": category_descriptor.store_display_short,
                    "option_count": len(category_descriptor.option_keys_order),
                    "modified_count": config_manager_state.count_category_modifications(
                        category_descriptor
                    ),
                }
            )

        total_options_count, total_modified_count = (
            config_manager_state.count_total_options_and_modifications()
        )

        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "config": catalog_rows_list,
                "categories": categories_summary_list,
                "total_options": total_options_count,
                "modified_options": total_modified_count,
                "protected_keys": sorted(SERVICE_GATE_PROTECTED_CONFIG_KEYS),
            },
        )

    def gate_config_mutate_dispatch(
        self, request_body_map: dict[str, Any], save_config_callable: Callable[..., Any]
    ) -> ServiceGateResponseEnvelope:
        """
        Gated dispatcher for POST /api/config supporting both standard `{name, value}`
        updates and extended configuration actions (`set`, `toggle`, `reset_key`,
        `reset_category`, `reset_all`, `backup`, `validate`, `probe`).
        """
        requested_action_name = (
            str(request_body_map.get("action") or "set").strip().lower()
        )
        config_manager_state = self._get_or_init_config_manager()
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", None)

        if requested_action_name == "validate":
            validation_tuples_list = config_manager_state.validate_all_bejson_stores()
            validation_records_list = [
                {
                    "store_code": store_code,
                    "format_version": format_version,
                    "row_count": row_count,
                    "status": status_tag,
                }
                for store_code, format_version, row_count, status_tag in validation_tuples_list
            ]
            all_stores_valid_flag = all(
                record_item["status"] == "VALID_104A"
                for record_item in validation_records_list
            )
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=all_stores_valid_flag,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": all_stores_valid_flag,
                    "action": "validate",
                    "stores": validation_records_list,
                },
            )

        if requested_action_name == "probe":
            probe_tuples_list = config_manager_state.probe_configured_paths()
            probe_records_list = [
                {
                    "probe_id": probe_id_str,
                    "kind": kind_tag,
                    "state": state_tag,
                    "target_path": compact_path_str,
                }
                for probe_id_str, kind_tag, state_tag, compact_path_str in probe_tuples_list
            ]
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": True,
                    "action": "probe",
                    "paths": probe_records_list,
                },
            )

        if requested_action_name == "backup":
            backup_ok_flag, backup_detail_message = (
                config_manager_state.create_snapshot_backup()
            )
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=backup_ok_flag,
                service_gate_response_http_status=200 if backup_ok_flag else 500,
                service_gate_response_payload_map={
                    "ok": backup_ok_flag,
                    "action": "backup",
                    "detail": backup_detail_message,
                },
            )

        if requested_action_name == "reset_category":
            target_category_code = (
                str(request_body_map.get("category") or "").strip().upper()
            )
            matched_category_descriptor = next(
                (
                    cat_desc
                    for cat_desc in config_manager_state.categories_list
                    if cat_desc.category_short_code == target_category_code
                ),
                None,
            )
            if matched_category_descriptor is None:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={
                        "error": f"Unknown category code: {target_category_code}"
                    },
                )
            # Preserve protected keys in main_config during web category reset
            preserved_protected_values = {
                protected_key: config_manager_state.store_values_map["main_config"].get(
                    protected_key
                )
                for protected_key in SERVICE_GATE_PROTECTED_CONFIG_KEYS
                if protected_key in config_manager_state.store_values_map["main_config"]
            }
            reset_options_count = config_manager_state.reset_category_to_defaults(
                matched_category_descriptor
            )
            for protected_key, protected_val in preserved_protected_values.items():
                if protected_val is not None:
                    config_manager_state.store_values_map["main_config"][
                        protected_key
                    ] = protected_val
            config_manager_state.save_store(matched_category_descriptor.store_identifier)
            self._sync_manager_to_terminal_config(config_manager_state)
            if isinstance(live_terminal_config_map, dict):
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": True,
                    "action": "reset_category",
                    "category": target_category_code,
                    "reset_count": reset_options_count,
                },
            )

        if requested_action_name == "reset_all":
            preserved_protected_values = {
                protected_key: config_manager_state.store_values_map["main_config"].get(
                    protected_key
                )
                for protected_key in SERVICE_GATE_PROTECTED_CONFIG_KEYS
                if protected_key in config_manager_state.store_values_map["main_config"]
            }
            total_reset_count = config_manager_state.reset_all_stores_to_defaults()
            for protected_key, protected_val in preserved_protected_values.items():
                if protected_val is not None:
                    config_manager_state.store_values_map["main_config"][
                        protected_key
                    ] = protected_val
            config_manager_state.save_store("main_config")
            self._sync_manager_to_terminal_config(config_manager_state)
            if isinstance(live_terminal_config_map, dict):
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": True,
                    "action": "reset_all",
                    "reset_count": total_reset_count,
                },
            )

        # Per-option actions: set, toggle, reset_key
        option_key_name = request_body_map.get("name")
        if option_key_name is None:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={
                    "error": f"unknown config key: {option_key_name}"
                },
            )

        if option_key_name in SERVICE_GATE_PROTECTED_CONFIG_KEYS:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=403,
                service_gate_response_payload_map={
                    "error": (
                        f"{option_key_name} is protected and cannot be changed "
                        "from the web terminal"
                    )
                },
            )

        known_in_terminal_dict = (
            isinstance(live_terminal_config_map, dict)
            and option_key_name in live_terminal_config_map
        )
        known_in_catalog_registry = (
            option_key_name in config_manager_state.option_metadata_registry
        )

        # If running against a minimal unit test stub where `term.config` only has a small subset of keys
        # and the test asks for an unknown key not in either, reject with 400.
        if not known_in_terminal_dict and not known_in_catalog_registry:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={
                    "error": f"unknown config key: {option_key_name}"
                },
            )

        if requested_action_name == "toggle" and known_in_catalog_registry:
            mutation_ok_flag, mutation_status_code = (
                config_manager_state.toggle_or_cycle_option(option_key_name)
            )
            if not mutation_ok_flag:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={
                        "error": f"could not cycle {option_key_name}: {mutation_status_code}"
                    },
                )
            updated_option_value = config_manager_state.get_option_value(option_key_name)
            self._sync_manager_to_terminal_config(config_manager_state)
            if isinstance(live_terminal_config_map, dict) and known_in_terminal_dict:
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "name": option_key_name,
                    "value": updated_option_value,
                    "saved": True,
                    "modified": config_manager_state.is_option_modified(option_key_name),
                },
            )

        if requested_action_name == "reset_key" and known_in_catalog_registry:
            mutation_ok_flag, mutation_status_code = (
                config_manager_state.reset_single_option(option_key_name)
            )
            if not mutation_ok_flag:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={
                        "error": f"could not reset {option_key_name}: {mutation_status_code}"
                    },
                )
            updated_option_value = config_manager_state.get_option_value(option_key_name)
            self._sync_manager_to_terminal_config(config_manager_state)
            if isinstance(live_terminal_config_map, dict) and known_in_terminal_dict:
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "name": option_key_name,
                    "value": updated_option_value,
                    "saved": True,
                    "modified": config_manager_state.is_option_modified(option_key_name),
                },
            )

        # Default action: "set"
        supplied_raw_value = request_body_map.get("value")

        # If this is a full catalog option in bubble_constants or cli_config (or main_config when full terminal)
        if known_in_catalog_registry and (
            self._is_full_terminal_instance()
            or config_manager_state.option_metadata_registry[
                option_key_name
            ].store_identifier
            != "main_config"
        ):
            mutation_ok_flag, mutation_status_code = (
                config_manager_state.set_option_value(option_key_name, supplied_raw_value)
            )
            if not mutation_ok_flag:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={
                        "error": (
                            f"could not set {option_key_name}: {mutation_status_code}"
                        )
                    },
                )
            updated_option_value = config_manager_state.get_option_value(option_key_name)
            self._sync_manager_to_terminal_config(config_manager_state)
            if isinstance(live_terminal_config_map, dict):
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "name": option_key_name,
                    "value": updated_option_value,
                    "saved": True,
                    "modified": config_manager_state.is_option_modified(option_key_name),
                },
            )

        # Fallback / stub path for main_config keys on lightweight SimpleNamespace test fixtures
        if not known_in_terminal_dict and known_in_catalog_registry:
            mutation_ok_flag, mutation_status_code = (
                config_manager_state.set_option_value(option_key_name, supplied_raw_value)
            )
            if not mutation_ok_flag:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={
                        "error": f"could not set {option_key_name}: {mutation_status_code}"
                    },
                )
            updated_option_value = config_manager_state.get_option_value(option_key_name)
            if isinstance(live_terminal_config_map, dict):
                live_terminal_config_map[option_key_name] = updated_option_value
                save_config_callable(self.main_config_file_path, live_terminal_config_map)
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "name": option_key_name,
                    "value": updated_option_value,
                    "saved": True,
                    "modified": config_manager_state.is_option_modified(option_key_name),
                },
            )

        existing_python_value = live_terminal_config_map[option_key_name]
        try:
            if isinstance(existing_python_value, bool):
                if isinstance(supplied_raw_value, str):
                    lowered_text = supplied_raw_value.strip().lower()
                    if lowered_text in ("true", "1", "yes", "on"):
                        coerced_python_value: Any = True
                    elif lowered_text in ("false", "0", "no", "off"):
                        coerced_python_value = False
                    else:
                        coerced_python_value = bool(supplied_raw_value)
                else:
                    coerced_python_value = bool(supplied_raw_value)
            elif isinstance(existing_python_value, int):
                coerced_python_value = int(supplied_raw_value)
            elif isinstance(existing_python_value, float):
                coerced_python_value = float(supplied_raw_value)
            elif isinstance(existing_python_value, list):
                if isinstance(supplied_raw_value, list):
                    coerced_python_value = [
                        str(list_item).strip()
                        for list_item in supplied_raw_value
                        if str(list_item).strip()
                    ]
                else:
                    coerced_python_value = [
                        part_item.strip()
                        for part_item in str(supplied_raw_value).split(",")
                        if part_item.strip()
                    ]
            else:
                coerced_python_value = str(supplied_raw_value)
        except (TypeError, ValueError):
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={
                    "error": (
                        f"could not set {option_key_name}: value does not match "
                        f"expected type {type(existing_python_value).__name__}"
                    )
                },
            )

        live_terminal_config_map[option_key_name] = coerced_python_value
        if known_in_catalog_registry:
            config_manager_state.store_values_map["main_config"][
                option_key_name
            ] = coerced_python_value
        save_config_callable(self.main_config_file_path, live_terminal_config_map)
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "name": option_key_name,
                "value": coerced_python_value,
                "saved": True,
            },
        )

    def gate_models_list_catalog(self) -> ServiceGateResponseEnvelope:
        """Return available models from MODEL_CATALOG_PATH and the currently active model."""
        catalog_record_rows = rest_module.load_model_catalog(self.model_catalog_file_path)
        formatted_models_list = [
            {
                "model_string": catalog_row.get("model_string"),
                "display_name": catalog_row.get("display_name")
                or catalog_row.get("model_string"),
            }
            for catalog_row in catalog_record_rows
            if catalog_row.get("model_string")
        ]
        model_registry_instance = getattr(self.terminal_state_holder, "model_reg", None)
        active_model_identifier = (
            getattr(model_registry_instance, "active", None)
            if model_registry_instance is not None
            else None
        )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "models": formatted_models_list,
                "active_model": active_model_identifier,
            },
        )

    def gate_models_set_active(
        self, request_body_map: dict[str, Any]
    ) -> ServiceGateResponseEnvelope:
        """Validate and switch the active model in the model registry."""
        requested_model_string = str(request_body_map.get("model") or "").strip()
        if not requested_model_string:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={"error": "missing 'model'"},
            )
        model_registry_instance = getattr(self.terminal_state_holder, "model_reg", None)
        if model_registry_instance is not None:
            model_registry_instance.set_active(requested_model_string)
            active_model_identifier = model_registry_instance.active
        else:
            active_model_identifier = requested_model_string
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={"active_model": active_model_identifier},
        )

    def gate_status_snapshot(self) -> ServiceGateResponseEnvelope:
        """Assemble runtime telemetry status for `/api/status`."""
        key_registry_instance = getattr(self.terminal_state_holder, "key_reg", None)
        if key_registry_instance is not None and hasattr(key_registry_instance, "keys"):
            total_keys_count = len(key_registry_instance.keys)
            available_keys_count = sum(
                1
                for api_key_value in key_registry_instance.keys
                if key_registry_instance._is_available(api_key_value)
            )
        else:
            total_keys_count = 0
            available_keys_count = 0

        model_registry_instance = getattr(self.terminal_state_holder, "model_reg", None)
        session_stats_instance = getattr(self.terminal_state_holder, "stats", None)
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", {}) or {}

        engine_mode_value = (
            live_terminal_config_map.get("engine_mode")
            or getattr(session_stats_instance, "engine", "rest")
        )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "version": self.runtime_version_string,
                "cwd": getattr(self.terminal_state_holder, "_cwd", str(self.project_root_dir_path)),
                "active_model": getattr(model_registry_instance, "active", "--"),
                "key_count": total_keys_count,
                "keys_available": available_keys_count,
                "engine": engine_mode_value,
                "turns": getattr(session_stats_instance, "turns", 0),
                "execs": getattr(session_stats_instance, "execs", 0),
            },
        )


# =====================================================================
# 2. SHELL EXECUTION & FILESYSTEM BROWSER SERVICE GATE
# =====================================================================
class ServiceGateExecutionController:
    """
    Gated service abstraction layer for shell execution (`do_exec`), environment-driven
    filesystem quickjumps, and directory traversal listing.
    """

    def __init__(
        self,
        terminal_state_holder: Any,
        project_root_dir_path: Path,
        async_runner_callable: Callable[..., Any],
    ) -> None:
        self.terminal_state_holder = terminal_state_holder
        self.project_root_dir_path = project_root_dir_path
        self.async_runner_callable = async_runner_callable

    def gate_exec_command(
        self, request_body_map: dict[str, Any]
    ) -> ServiceGateResponseEnvelope:
        """Execute a shell command under the terminal instance lock via actions.do_exec."""
        command_line_string = str(request_body_map.get("command") or "").strip()
        attachment_paths_list = request_body_map.get("attachments") or []
        current_working_dir = getattr(
            self.terminal_state_holder, "_cwd", str(self.project_root_dir_path)
        )
        if not command_line_string:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "output": "",
                    "cwd": current_working_dir,
                    "exit_code": 0,
                },
            )

        state_mutex_lock = _service_gate_resolve_state_lock(self.terminal_state_holder)
        live_terminal_config_map = getattr(self.terminal_state_holder, "config", {}) or {}

        with state_mutex_lock:
            exit_status_code, command_output_text, updated_cwd_path, updated_shell_env = (
                self.async_runner_callable(
                    actions_module.do_exec(
                        command_line_string,
                        self.terminal_state_holder._cwd,
                        timeout=live_terminal_config_map.get("exec_timeout_seconds", 60),
                        shell_env=self.terminal_state_holder._shell_env,
                        denylist=live_terminal_config_map.get("exec_denylist"),
                    )
                )
            )
            self.terminal_state_holder._cwd = updated_cwd_path
            if updated_shell_env is not None:
                self.terminal_state_holder._shell_env = updated_shell_env
            if hasattr(self.terminal_state_holder, "stats") and hasattr(
                self.terminal_state_holder.stats, "execs"
            ):
                self.terminal_state_holder.stats.execs += 1
            resolved_cwd_after_exec = self.terminal_state_holder._cwd

        if attachment_paths_list:
            attachment_basenames_csv = ", ".join(
                Path(attachment_item).name for attachment_item in attachment_paths_list
            )
            command_output_text = (
                f"[Attached {len(attachment_paths_list)} file(s): {attachment_basenames_csv}]\n"
                + command_output_text
            )

        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "output": command_output_text,
                "cwd": resolved_cwd_after_exec,
                "exit_code": exit_status_code,
                "attachments_received": len(attachment_paths_list),
            },
        )

    def gate_filesystem_quickjumps(self) -> ServiceGateResponseEnvelope:
        """Resolve quick-jump directories from canonical environment variables."""
        candidate_jump_pairs = [
            ("Internal Storage", get_env_path("INTERNAL_STORAGE", "")),
            ("SD Card", get_env_path("SD_CARD", "")),
            ("Project Root", get_env_path("PROJECT_ROOT", "")),
            ("Home", str(Path.home())),
            ("/ (filesystem root)", "/"),
        ]
        resolved_quickjumps_list: list[dict[str, str]] = []
        seen_directory_paths: set[str] = set()
        for jump_label_text, raw_jump_path_text in candidate_jump_pairs:
            if not raw_jump_path_text:
                continue
            candidate_dir_path = Path(raw_jump_path_text)
            if (
                candidate_dir_path.is_dir()
                and str(candidate_dir_path) not in seen_directory_paths
            ):
                resolved_quickjumps_list.append(
                    {"label": jump_label_text, "path": str(candidate_dir_path)}
                )
                seen_directory_paths.add(str(candidate_dir_path))
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={"quickjumps": resolved_quickjumps_list},
        )

    def gate_filesystem_browse_directory(
        self, requested_raw_path: Optional[str]
    ) -> ServiceGateResponseEnvelope:
        """Validate and list directory entries for the UI file browser."""
        effective_raw_path = requested_raw_path or str(self.project_root_dir_path)
        try:
            resolved_target_dir = Path(effective_raw_path).expanduser().resolve()
        except Exception:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={
                    "error": f"invalid path: {effective_raw_path}"
                },
            )

        if not resolved_target_dir.exists():
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=404,
                service_gate_response_payload_map={
                    "error": f"path does not exist: {resolved_target_dir}"
                },
            )
        if not resolved_target_dir.is_dir():
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={
                    "error": f"not a directory: {resolved_target_dir}"
                },
            )

        directory_entries_list: list[dict[str, Any]] = []
        try:
            sorted_children_paths = sorted(
                resolved_target_dir.iterdir(),
                key=lambda child_entry_path: (
                    not child_entry_path.is_dir(),
                    child_entry_path.name.lower(),
                ),
            )
            for child_entry_path in sorted_children_paths:
                try:
                    entry_is_directory = child_entry_path.is_dir()
                    entry_byte_size = (
                        None if entry_is_directory else child_entry_path.stat().st_size
                    )
                    directory_entries_list.append(
                        {
                            "name": child_entry_path.name,
                            "path": str(child_entry_path),
                            "is_dir": entry_is_directory,
                            "size": entry_byte_size,
                        }
                    )
                except OSError:
                    continue
        except PermissionError:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=403,
                service_gate_response_payload_map={
                    "error": f"permission denied: {resolved_target_dir}"
                },
            )

        parent_directory_path = (
            str(resolved_target_dir.parent)
            if resolved_target_dir.parent != resolved_target_dir
            else None
        )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "path": str(resolved_target_dir),
                "parent": parent_directory_path,
                "entries": directory_entries_list,
            },
        )


# =====================================================================
# 3. CONVERSATION TURN, AMNESIA & REBIRTH SERVICE GATE
# =====================================================================
class ServiceGateConversationController:
    """
    Gated service abstraction layer for multi-round conversational turn execution,
    context bubble assembly, action tag execution, session amnesia compression,
    and recap rebirth seeding.
    """

    def __init__(
        self,
        terminal_state_holder: Any,
        config_dir_path: Path,
        context_dir_path: Path,
        backups_dir_path: Path,
        jobs_dir_path: Path,
        max_auto_continue_iterations: int,
        async_runner_callable: Callable[..., Any],
        attachment_describer_callable: Callable[[str], str],
    ) -> None:
        self.terminal_state_holder = terminal_state_holder
        self.config_dir_path = config_dir_path
        self.context_dir_path = context_dir_path
        self.backups_dir_path = backups_dir_path
        self.jobs_dir_path = jobs_dir_path
        self.max_auto_continue_iterations = max_auto_continue_iterations
        self.async_runner_callable = async_runner_callable
        self.attachment_describer_callable = attachment_describer_callable

    def gate_conversation_execute_turn(
        self, request_body_map: dict[str, Any]
    ) -> ServiceGateResponseEnvelope:
        """Execute a complete synchronized NewAgent conversation turn."""
        state_mutex_lock = _service_gate_resolve_state_lock(self.terminal_state_holder)
        with state_mutex_lock:
            user_prompt_message = str(request_body_map.get("message") or "").strip()
            attachment_paths_list = request_body_map.get("attachments") or []
            if not user_prompt_message:
                return ServiceGateResponseEnvelope(
                    service_gate_response_ok_flag=False,
                    service_gate_response_http_status=400,
                    service_gate_response_payload_map={"error": "empty message"},
                )

            if attachment_paths_list:
                formatted_attachment_lines = "\n".join(
                    f"  - {self.attachment_describer_callable(raw_attachment_path)}"
                    for raw_attachment_path in attachment_paths_list
                )
                user_prompt_message = (
                    f"{user_prompt_message}\n\n"
                    "[Attached reference file(s) -- for you to study if relevant, do not alter:\n"
                    f"{formatted_attachment_lines}\n]"
                )

            turn_timestamp_hms = datetime.now().strftime("%H:%M:%S")
            self.terminal_state_holder.history.append(
                {
                    "role": "user",
                    "content": user_prompt_message,
                    "_ts": turn_timestamp_hms,
                }
            )

            turn_execution_context_map: dict[str, Any] = {
                "_cwd": self.terminal_state_holder._cwd,
                "_shell_env": self.terminal_state_holder._shell_env,
                "config": self.terminal_state_holder.config,
                "_backups_dir": self.backups_dir_path,
                "_config_dir": self.config_dir_path,
                "_jobs_dir": self.jobs_dir_path,
                "_active_job_path": self.terminal_state_holder._active_job_path,
                "_active_job_doc": self.terminal_state_holder._active_job_doc,
                "_continue_requested": False,
                "stats": self.terminal_state_holder.stats,
                "key_call_counts": self.terminal_state_holder.key_call_counts,
            }

            turn_event_log_entries: list[dict[str, Any]] = []
            completed_iteration_count = 0

            while completed_iteration_count < self.max_auto_continue_iterations:
                completed_iteration_count += 1

                try:
                    assembled_bubble_payload = context_bubble_module.assemble_bubble(
                        self.context_dir_path,
                        self.config_dir_path,
                        user_prompt_message,
                        turn=self.terminal_state_holder.turn_count + 1,
                        cooldown_state=self.terminal_state_holder.trigger_cooldowns,
                        cwd=turn_execution_context_map["_cwd"],
                        env_file_paths=[
                            str(env_source_path)
                            for env_source_path in env_module.resolve_env_bejson_sources(
                                self.terminal_state_holder.config
                            )
                        ],
                        config=self.terminal_state_holder.config,
                    )
                except errors_module.ContextInjectionError:
                    assembled_bubble_payload = (
                        context_bubble_module.build_minimal_bubble(
                            self.context_dir_path, self.config_dir_path
                        )
                    )

                compiled_system_instruction = actions_module.build_system_prompt(
                    turn_execution_context_map["_cwd"],
                    assembled_bubble_payload["text"],
                    active_job=jobs_module.build_job_context_block(
                        turn_execution_context_map.get("_active_job_doc")
                    ),
                )

                try:
                    model_response_text, _token_usage_metadata = (
                        self.terminal_state_holder.rest_prompter.prompt(
                            self.terminal_state_holder.history,
                            compiled_system_instruction,
                        )
                    )
                except errors_module.NewAgentFatalError as fatal_engine_error:
                    return ServiceGateResponseEnvelope(
                        service_gate_response_ok_flag=False,
                        service_gate_response_http_status=500,
                        service_gate_response_payload_map={
                            "error": f"[FATAL] {fatal_engine_error}",
                            "turn_log": turn_event_log_entries,
                        },
                    )
                except Exception as recoverable_engine_error:
                    return ServiceGateResponseEnvelope(
                        service_gate_response_ok_flag=False,
                        service_gate_response_http_status=502,
                        service_gate_response_payload_map={
                            "error": str(recoverable_engine_error),
                            "turn_log": turn_event_log_entries,
                        },
                    )

                self.terminal_state_holder.turn_count += 1
                self.terminal_state_holder.stats.turns += 1
                self.terminal_state_holder.history.append(
                    {
                        "role": "model",
                        "content": model_response_text,
                        "_ts": turn_timestamp_hms,
                    }
                )
                turn_event_log_entries.append(
                    {"type": "text", "content": model_response_text}
                )

                parsed_action_tags_list = actions_module.parse_actions(
                    model_response_text
                )
                if not parsed_action_tags_list:
                    break

                executed_action_results_list = self.async_runner_callable(
                    actions_module.run_action_queue(
                        parsed_action_tags_list, turn_execution_context_map
                    )
                )
                self.terminal_state_holder._active_job_path = (
                    turn_execution_context_map.get("_active_job_path")
                )
                self.terminal_state_holder._active_job_doc = (
                    turn_execution_context_map.get("_active_job_doc")
                )

                for executed_action_item in executed_action_results_list:
                    turn_event_log_entries.append(
                        {
                            "type": "action",
                            "action_type": executed_action_item.action_type,
                            "source": executed_action_item.source,
                            "output": executed_action_item.output,
                            "exit_code": executed_action_item.exit_code,
                        }
                    )

                action_results_xml_payload = actions_module.assemble_results_payload(
                    executed_action_results_list
                )
                self.terminal_state_holder.history.append(
                    {
                        "role": "user",
                        "content": action_results_xml_payload,
                        "_ts": turn_timestamp_hms,
                    }
                )

                if not self.terminal_state_holder.config.get(
                    "auto_continue_enabled", True
                ):
                    break

            self.terminal_state_holder._cwd = turn_execution_context_map["_cwd"]
            if turn_execution_context_map.get("_shell_env") is not None:
                self.terminal_state_holder._shell_env = turn_execution_context_map[
                    "_shell_env"
                ]

            context_bubble_module.trim_history(
                self.terminal_state_holder.history,
                self.terminal_state_holder.config.get("max_history_turns", 20),
            )

            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "turn_log": turn_event_log_entries,
                    "cwd": self.terminal_state_holder._cwd,
                    "iterations": completed_iteration_count,
                    "hit_iteration_cap": (
                        completed_iteration_count >= self.max_auto_continue_iterations
                    ),
                },
            )

    def gate_conversation_amnesia_compress(self) -> ServiceGateResponseEnvelope:
        """Compress live conversation history into an amnesia recap and optionally rebirth."""
        if not self.terminal_state_holder.history:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": False,
                    "error": "Nothing to compress -- history is already empty.",
                },
            )
        compressed_recap_text = context_bubble_module.run_full_session_compression(
            self.terminal_state_holder.history,
            self.terminal_state_holder.rest_prompter,
        )
        if not compressed_recap_text:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": False,
                    "error": (
                        "Compression call failed or returned nothing -- "
                        "history left untouched."
                    ),
                },
            )
        context_bubble_module.save_amnesia_recap(
            self.context_dir_path, compressed_recap_text
        )
        auto_rebirth_enabled = self.terminal_state_holder.config.get(
            "auto_amnesia_memory_retrieval", True
        )
        if auto_rebirth_enabled:
            context_bubble_module.seed_history_with_recap(
                self.terminal_state_holder.history, compressed_recap_text
            )
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=True,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": True,
                    "reborn": True,
                    "recap_chars": len(compressed_recap_text),
                },
            )
        self.terminal_state_holder.history.clear()
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "ok": True,
                "reborn": False,
                "recap_chars": len(compressed_recap_text),
            },
        )

    def gate_conversation_rebirth_restore(self) -> ServiceGateResponseEnvelope:
        """Restore the last saved amnesia recap into live conversation history."""
        saved_recap_text = context_bubble_module.load_amnesia_recap(
            self.context_dir_path
        )
        if not saved_recap_text:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=200,
                service_gate_response_payload_map={
                    "ok": False,
                    "error": "No compressed recap available -- run Amnesia first.",
                },
            )
        context_bubble_module.seed_history_with_recap(
            self.terminal_state_holder.history, saved_recap_text
        )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "ok": True,
                "recap_chars": len(saved_recap_text),
            },
        )


# =====================================================================
# 4. JOBS & SCRATCH NOTES SERVICE GATE
# =====================================================================
class ServiceGateJobNotesController:
    """
    Gated service abstraction layer for JobMaker BEJSON 104a job lifecycle
    (`list`, `start`, `stop`) and bounded atomic scratch-notes persistence.
    """

    def __init__(
        self,
        terminal_state_holder: Any,
        jobs_dir_path_getter: Callable[[], Path],
        notes_dir_path_getter: Callable[[], Path],
        notes_file_path_getter: Callable[[], Path],
        notes_max_chars_getter: Callable[[], int],
    ) -> None:
        self.terminal_state_holder = terminal_state_holder
        self.jobs_dir_path_getter = jobs_dir_path_getter
        self.notes_dir_path_getter = notes_dir_path_getter
        self.notes_file_path_getter = notes_file_path_getter
        self.notes_max_chars_getter = notes_max_chars_getter

    def gate_jobs_list_pending(self) -> ServiceGateResponseEnvelope:
        """Scan jobs directory and annotate the currently active job."""
        current_jobs_dir = self.jobs_dir_path_getter()
        scanned_jobs_list = jobs_module.scan_jobs(current_jobs_dir)
        active_job_path = getattr(self.terminal_state_holder, "_active_job_path", None)
        active_job_stem_name = Path(active_job_path).stem if active_job_path else None
        for job_summary_entry in scanned_jobs_list:
            job_summary_entry["active"] = (
                job_summary_entry["job_name"] == active_job_stem_name
            )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "jobs": scanned_jobs_list,
                "active": active_job_stem_name,
            },
        )

    def gate_jobs_start_named(
        self, request_body_map: dict[str, Any]
    ) -> ServiceGateResponseEnvelope:
        """Validate path containment, load BEJSON job document, and set active job."""
        requested_job_name = str(request_body_map.get("name") or "").strip()
        if not requested_job_name:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={"error": "missing 'name'"},
            )
        current_jobs_dir = self.jobs_dir_path_getter()
        resolved_job_file_path = jobs_module.get_job_path(
            current_jobs_dir, requested_job_name
        )
        if not resolved_job_file_path:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=404,
                service_gate_response_payload_map={
                    "error": f"No job named '{requested_job_name}' found in jobs/."
                },
            )
        loaded_job_bejson_doc = jobs_module.load_job(resolved_job_file_path)
        if not loaded_job_bejson_doc:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=500,
                service_gate_response_payload_map={
                    "error": (
                        f"Could not load {resolved_job_file_path.name} as BEJSON."
                    )
                },
            )
        self.terminal_state_holder._active_job_path = resolved_job_file_path
        self.terminal_state_holder._active_job_doc = loaded_job_bejson_doc
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={
                "ok": True,
                "active": resolved_job_file_path.stem,
            },
        )

    def gate_jobs_stop_active(self) -> ServiceGateResponseEnvelope:
        """Clear the active job reference on the terminal state holder."""
        self.terminal_state_holder._active_job_path = None
        self.terminal_state_holder._active_job_doc = None
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={"ok": True, "active": None},
        )

    def gate_notes_read_text(self) -> ServiceGateResponseEnvelope:
        """Read persistent scratch notes from disk with OSError boundary protection."""
        target_notes_file = self.notes_file_path_getter()
        try:
            notes_content_text = (
                target_notes_file.read_text(encoding="utf-8")
                if target_notes_file.is_file()
                else ""
            )
        except OSError as filesystem_read_error:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=500,
                service_gate_response_payload_map={
                    "text": "",
                    "error": f"Could not read notes file: {filesystem_read_error}",
                },
            )
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={"text": notes_content_text},
        )

    def gate_notes_save_text(
        self, request_body_map: dict[str, Any]
    ) -> ServiceGateResponseEnvelope:
        """Validate type and character limit, then atomically write scratch notes."""
        supplied_notes_text = request_body_map.get("text", "")
        max_allowed_characters = self.notes_max_chars_getter()
        if not isinstance(supplied_notes_text, str):
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=400,
                service_gate_response_payload_map={"error": "'text' must be a string"},
            )
        if len(supplied_notes_text) > max_allowed_characters:
            return ServiceGateResponseEnvelope(
                service_gate_response_ok_flag=False,
                service_gate_response_http_status=413,
                service_gate_response_payload_map={
                    "error": f"notes exceed {max_allowed_characters} characters"
                },
            )
        target_notes_dir = self.notes_dir_path_getter()
        target_notes_file = self.notes_file_path_getter()
        target_notes_dir.mkdir(parents=True, exist_ok=True)
        temp_staging_file = target_notes_file.with_suffix(".tmp")
        temp_staging_file.write_text(supplied_notes_text, encoding="utf-8")
        temp_staging_file.replace(target_notes_file)
        return ServiceGateResponseEnvelope(
            service_gate_response_ok_flag=True,
            service_gate_response_http_status=200,
            service_gate_response_payload_map={"ok": True},
        )


# =====================================================================
# 5. AGENT.PY RUNTIME ORCHESTRATION SERVICE GATES
# =====================================================================
@dataclass
class AgentAutonomyGateState:
    """Encapsulates autonomy countdown and auto-continue loop-guard state for agent.py."""

    autonomy_mode_active_flag: bool = False
    autonomy_turns_remaining_count: int = 0
    auto_continuing_next_turn_flag: bool = False
    auto_continue_streak_count: int = 0
    last_action_batch_signature: Optional[str] = None
    repeated_action_batch_count: int = 0

    def reset_manual_turn_counters(self) -> None:
        """Reset auto-continue loop counters when a user manually submits input."""
        self.auto_continue_streak_count = 0
        self.last_action_batch_signature = None
        self.repeated_action_batch_count = 0

    def evaluate_auto_continue_guard(
        self,
        parsed_actions_list: list[Any],
        max_auto_continue_turns_cap: int,
    ) -> Optional[str]:
        """
        Evaluate whether an auto-continuing REST turn should stop and return control
        to the user. Returns a human-readable stop reason if stopped, or None to continue.
        """
        if not self.auto_continuing_next_turn_flag:
            return None

        self.auto_continue_streak_count += 1
        current_batch_signature = actions_module.actions_signature(parsed_actions_list)
        if current_batch_signature == self.last_action_batch_signature:
            self.repeated_action_batch_count += 1
        else:
            self.repeated_action_batch_count = 0
        self.last_action_batch_signature = current_batch_signature

        if actions_module.is_announcement_only(parsed_actions_list):
            self.auto_continuing_next_turn_flag = False
            return "model only echoed a status message (nothing left to do)"
        if self.repeated_action_batch_count >= 1:
            self.auto_continuing_next_turn_flag = False
            return "model repeated the identical action batch"
        if (
            max_auto_continue_turns_cap > 0
            and self.auto_continue_streak_count >= max_auto_continue_turns_cap
        ):
            self.auto_continuing_next_turn_flag = False
            return f"reached max_auto_continue_turns ({max_auto_continue_turns_cap})"
        return None


class ServiceGateAgentRuntimeController:
    """
    Gated modular service layer for `agent.py` isolating bootstrap lifecycle,
    native tool dispatch map construction, error classification / circuit-breaker
    evaluation, and context bubble assembly.
    """

    @staticmethod
    def gate_register_sigterm_cancellation(
        running_event_loop: asyncio.AbstractEventLoop,
        current_main_task: Optional[asyncio.Task[Any]],
    ) -> None:
        """Register cooperative SIGTERM cancellation on the running asyncio event loop."""
        if current_main_task is None:
            return
        try:
            running_event_loop.add_signal_handler(
                signal.SIGTERM, current_main_task.cancel
            )
        except NotImplementedError:
            signal.signal(
                signal.SIGTERM,
                lambda _signal_number, _stack_frame: current_main_task.cancel(),
            )

    @staticmethod
    def gate_bootstrap_directories_and_registries(
        config_dir_path: Path,
        logs_dir_path: Path,
        backups_dir_path: Path,
        jobs_dir_path: Path,
        subagents_dir_path: Path,
        keys_file_path: Path,
        models_file_path: Path,
        model_catalog_file_path: Path,
    ) -> None:
        """Ensure runtime directory hierarchy exists, prune stale logs/jobs, and seed BEJSON registries."""
        try:
            config_dir_path.mkdir(parents=True, exist_ok=True)
            logs_dir_path.mkdir(parents=True, exist_ok=True)
            backups_dir_path.mkdir(parents=True, exist_ok=True)
            jobs_module.ensure_job_dirs(jobs_dir_path)
            jobs_module.cleanup_old_completed_jobs(jobs_dir_path)
            session_module.prune_old_logs(logs_dir_path)
            subagent_sessions_module.cleanup_old_sessions(subagents_dir_path)

            rest_module.build_default_keys_bejson(keys_file_path)
            rest_module.build_default_models_bejson(models_file_path)
            rest_module.build_default_model_catalog(model_catalog_file_path)
            rest_module.backfill_model_catalog_api_profile(model_catalog_file_path)
            rest_module.backfill_model_catalog_provider(model_catalog_file_path)
        except errors_module.NewAgentFatalError:
            raise
        except Exception as bootstrap_failure_exception:
            raise errors_module.BootstrapFailureError(
                f"Directory/registry-file setup failed: {bootstrap_failure_exception}"
            ) from bootstrap_failure_exception

    @staticmethod
    def gate_build_interactions_tool_map(
        runtime_context_map: dict[str, Any],
        runtime_config_map: dict[str, Any],
        backups_dir_path: Path,
    ) -> dict[str, Callable[..., Any]]:
        """Construct the gated function-calling dispatch dictionary for InteractionsPrompter."""

        async def _gated_async_run_exec(shell_command_text: str) -> str:
            exit_status_code, command_output_text, updated_cwd_path, updated_shell_env = (
                await actions_module.do_exec(
                    shell_command_text,
                    runtime_context_map["_cwd"],
                    runtime_config_map.get("exec_timeout_seconds", 60),
                    runtime_config_map.get("live_feed_output", False),
                    shell_env=runtime_context_map.get("_shell_env"),
                    denylist=runtime_config_map.get("exec_denylist"),
                )
            )
            runtime_context_map["_cwd"] = updated_cwd_path
            if updated_shell_env is not None:
                runtime_context_map["_shell_env"] = updated_shell_env
            return command_output_text

        return {
            "do_exec": _gated_async_run_exec,
            "do_read_file": lambda target_file_path: actions_module.do_read_file(
                target_file_path, runtime_context_map["_cwd"]
            ),
            "do_write_file": lambda target_file_path, file_content_text: actions_module.do_write_file(
                target_file_path, file_content_text, runtime_context_map["_cwd"]
            ),
            "do_edit_file": lambda target_file_path, old_substring, new_substring: actions_module.do_edit_file(
                target_file_path,
                old_substring,
                new_substring,
                runtime_context_map["_cwd"],
            ),
            "do_list_dir": lambda target_dir_path: actions_module.do_list_dir(
                target_dir_path, runtime_context_map["_cwd"]
            ),
            "do_tree_view": lambda target_dir_path, depth=3: actions_module.do_tree_view(
                target_dir_path, runtime_context_map["_cwd"], depth=depth
            ),
            "do_make_dir": lambda target_dir_path: actions_module.do_make_dir(
                target_dir_path, runtime_context_map["_cwd"]
            ),
            "do_delete_file": lambda target_file_path: actions_module.do_delete_file(
                target_file_path, runtime_context_map["_cwd"]
            ),
            "do_copy_file": lambda source_file_path, destination_file_path: actions_module.do_copy_file(
                source_file_path, destination_file_path, runtime_context_map["_cwd"]
            ),
            "do_diff_file": lambda target_file_path: actions_module.do_diff_file(
                target_file_path, runtime_context_map["_cwd"]
            ),
            "do_restore_file": actions_module.do_restore_file,
            "do_http_get": actions_module.do_http_get,
            "do_find_files": lambda glob_pattern, base=".": actions_module.do_find_files(
                glob_pattern, base, runtime_context_map["_cwd"]
            ),
            "do_search_text": lambda regex_pattern, path=".": actions_module.do_search_text(
                regex_pattern, path, runtime_context_map["_cwd"]
            ),
            "do_fuzzy_find": lambda fuzzy_query: actions_module.do_fuzzy_find(
                fuzzy_query, runtime_context_map["_cwd"]
            ),
            "do_env_get": actions_module.do_env_get,
            "do_speak": actions_module.do_speak,
            "do_checkpoint": lambda checkpoint_label: actions_module.do_checkpoint(
                checkpoint_label, backups_dir_path
            ),
            "do_exec_bg": lambda bg_command_text: (
                "[SUCCESS] Background task spawned with ID: "
                f"{actions_module._GLOBAL_TASK_MANAGER.spawn_task(bg_command_text, runtime_context_map['_cwd'], shell_env=runtime_context_map.get('_shell_env'))}"
            ),
            "do_task_status": lambda background_task_id: actions_module._GLOBAL_TASK_MANAGER.get_status(
                background_task_id
            ),
            "do_task_kill": lambda background_task_id: actions_module._GLOBAL_TASK_MANAGER.kill_task(
                background_task_id
            ),
            "do_task_list": lambda: actions_module._GLOBAL_TASK_MANAGER.list_tasks(),
        }

    @staticmethod
    def gate_classify_turn_exception(
        caught_turn_exception: Exception,
        active_engine_mode: str,
        interactions_prompter_instance: Any,
    ) -> tuple[bool, bool, str]:
        """
        Classify a turn exception into `(is_network_error, mid_turn_mutated, human_failure_reason)`.
        Preserves the exact network/side-effect diagnostic contract required by NewAgent tests.
        """
        exception_message_text = str(caught_turn_exception)
        is_network_error_flag = (
            "No address associated with hostname" in exception_message_text
            or "urlopen error" in exception_message_text
            or "Connection error:" in exception_message_text
            or "Request timed out" in exception_message_text
        )
        mid_turn_mutated_flag = bool(
            active_engine_mode == "interactions"
            and interactions_prompter_instance is not None
            and getattr(interactions_prompter_instance, "turn_had_side_effects", False)
        )
        if "Rate-limited" in exception_message_text or "429" in exception_message_text:
            human_failure_reason = (
                "RATE LIMITED — your message was NOT sent to the model."
            )
        elif is_network_error_flag and mid_turn_mutated_flag:
            human_failure_reason = (
                "NETWORK ERROR mid-turn after mutating tool execution — "
                "auto-retry suppressed to prevent duplicate side effects."
            )
        elif is_network_error_flag:
            human_failure_reason = (
                "NETWORK ERROR — your message was NOT sent (no connection)."
            )
        elif "Auth error" in exception_message_text:
            human_failure_reason = (
                "AUTH ERROR on API key — your message was NOT sent."
            )
        elif "Server error" in exception_message_text:
            human_failure_reason = (
                "SERVER ERROR from provider — your message was NOT sent."
            )
        else:
            human_failure_reason = "your message was NOT sent."

        return is_network_error_flag, mid_turn_mutated_flag, human_failure_reason
