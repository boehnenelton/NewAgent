"""
Name:           test_service_gates_and_ui_config.py
Description:    Verification suite for the gated modular service abstraction layers
                (lib_bejson_newagent_service_gates.py), full 67-option / 7-category /
                3-store UI configuration control in webagent.py, and taxonomy /
                identifier compliance across webagent.py, web_routes/*, and agent.py.
Version:        1.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  a17d4c83-9b2e-4f50-8c16-3e90d2a7b418
"""

import _libpath  # noqa: F401
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

flask = pytest.importorskip("flask")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lib_bejson_newagent_service_gates import (  # noqa: E402
    AgentAutonomyGateState,
    ServiceGateAgentRuntimeController,
    ServiceGateConfigurationController,
    ServiceGateExecutionController,
    ServiceGateJobNotesController,
)
from web_routes import (  # noqa: E402
    api_chat_routes,
    api_config_routes,
    api_exec_routes,
    api_jobs_routes,
    security,
    ui_routes,
)

TEST_AUTH_TOKEN = "service-gate-unit-token-9876543210"
AUTH_HEADER = {"X-Auth-Token": TEST_AUTH_TOKEN}


def _build_gated_test_app(tmp_path: Path):
    """Build an isolated Flask test application backed by temporary BEJSON 104a stores."""
    terminal_stub = SimpleNamespace(
        web_token=TEST_AUTH_TOKEN,
        allowed_hosts=None,
        config={"send_delay_seconds": 1.0, "web_auth_token": "SECRET_TOKEN"},
        _cwd=str(tmp_path),
        _shell_env=None,
        _active_job_path=None,
        _active_job_doc=None,
        stats=SimpleNamespace(engine="rest", turns=2, execs=5),
        model_reg=SimpleNamespace(
            active="gemini-2.5-flash",
            set_active=lambda m: setattr(terminal_stub.model_reg, "active", m),
        ),
        key_reg=SimpleNamespace(keys=["k1", "k2"], _is_available=lambda _k: True),
    )
    terminal_stub.config_service_gate = ServiceGateConfigurationController(
        terminal_state_holder=terminal_stub,
        project_root_dir_path=tmp_path,
        main_config_file_path=tmp_path / "config" / "config.json",
        model_catalog_file_path=ROOT_DIR / "config" / "gemini_catalog.bejson",
        runtime_version_string="0.14.0",
    )
    flask_app = flask.Flask("service_gate_test", root_path=str(ROOT_DIR))
    security.register_security(flask_app, terminal_stub)
    for route_module in (
        ui_routes,
        api_exec_routes,
        api_config_routes,
        api_chat_routes,
        api_jobs_routes,
    ):
        flask_app.register_blueprint(route_module.create_blueprint(terminal_stub))
    return flask_app, terminal_stub


def test_full_67_options_7_categories_3_stores_exposed(tmp_path):
    """Verify GET /api/config exposes all 67 options across 7 categories and 3 BEJSON 104a stores."""
    flask_app, _ = _build_gated_test_app(tmp_path)
    test_client = flask_app.test_client()

    response = test_client.get("/api/config", headers=AUTH_HEADER)
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["total_options"] == 67
    assert len(payload["config"]) == 67
    category_codes = [cat_item["code"] for cat_item in payload["categories"]]
    assert category_codes == ["ENG", "AUT", "MEM", "EXT", "SYS", "BUB", "CLI"]

    store_ids = {row_item["store_id"] for row_item in payload["config"]}
    assert store_ids == {"main_config", "bubble_constants", "cli_config"}


def test_category_filter_and_search_query(tmp_path):
    """Verify GET /api/config supports category filtering and keyword search."""
    flask_app, _ = _build_gated_test_app(tmp_path)
    test_client = flask_app.test_client()

    bub_resp = test_client.get("/api/config?category=BUB", headers=AUTH_HEADER)
    assert bub_resp.status_code == 200
    bub_rows = bub_resp.get_json()["config"]
    assert len(bub_rows) == 12
    assert all(row_item["category_code"] == "BUB" for row_item in bub_rows)

    search_resp = test_client.get("/api/config?q=observer_enabled", headers=AUTH_HEADER)
    search_rows = search_resp.get_json()["config"]
    assert any(row_item["name"] == "observer_enabled" for row_item in search_rows)


def test_config_actions_toggle_reset_validate_probe_backup(tmp_path):
    """Verify POST /api/config extended actions: set (across stores), toggle, reset_key, reset_category, validate, probe, backup."""
    flask_app, terminal_stub = _build_gated_test_app(tmp_path)
    test_client = flask_app.test_client()

    # 1. Mutate a bubble_constants option (Store 2) and a cli_config option (Store 3)
    res_bub = test_client.post(
        "/api/config",
        json={"action": "set", "name": "max_context_tokens", "value": 32000},
        headers=AUTH_HEADER,
    )
    assert res_bub.status_code == 200 and res_bub.get_json()["value"] == 32000

    res_cli = test_client.post(
        "/api/config",
        json={"action": "set", "name": "cli_max_retries", "value": 5},
        headers=AUTH_HEADER,
    )
    assert res_cli.status_code == 200 and res_cli.get_json()["value"] == 5

    # 2. Toggle/cycle an option
    res_toggle = test_client.post(
        "/api/config",
        json={"action": "toggle", "name": "dryrun_mode"},
        headers=AUTH_HEADER,
    )
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()["value"] is True
    assert terminal_stub.config["dryrun_mode"] is True

    # 3. Reset single key
    res_reset_key = test_client.post(
        "/api/config",
        json={"action": "reset_key", "name": "dryrun_mode"},
        headers=AUTH_HEADER,
    )
    assert res_reset_key.status_code == 200
    assert res_reset_key.get_json()["value"] is False

    # 4. Validate all 3 BEJSON 104a stores
    res_val = test_client.post(
        "/api/config",
        json={"action": "validate"},
        headers=AUTH_HEADER,
    )
    assert res_val.status_code == 200
    val_payload = res_val.get_json()
    assert val_payload["ok"] is True
    assert len(val_payload["stores"]) == 3
    assert all(store_item["status"] == "VALID_104A" for store_item in val_payload["stores"])

    # 5. Probe configured paths
    res_probe = test_client.post(
        "/api/config",
        json={"action": "probe"},
        headers=AUTH_HEADER,
    )
    assert res_probe.status_code == 200
    assert len(res_probe.get_json()["paths"]) >= 8

    # 6. Snapshot backup
    res_bak = test_client.post(
        "/api/config",
        json={"action": "backup"},
        headers=AUTH_HEADER,
    )
    assert res_bak.status_code == 200 and res_bak.get_json()["ok"] is True

    # 7. Reset category while preserving protected keys
    res_cat = test_client.post(
        "/api/config",
        json={"action": "reset_category", "category": "BUB"},
        headers=AUTH_HEADER,
    )
    assert res_cat.status_code == 200 and res_cat.get_json()["reset_count"] == 12


def test_agent_runtime_service_gates():
    """Verify ServiceGateAgentRuntimeController and AgentAutonomyGateState behavior."""
    import lib_bejson_newagent_actions as actions_mod
    autonomy_gate = AgentAutonomyGateState(auto_continuing_next_turn_flag=True)
    stop_reason = autonomy_gate.evaluate_auto_continue_guard(
        parsed_actions_list=actions_mod.parse_actions('<exec>echo "Task completed"</exec>'),
        max_auto_continue_turns_cap=12,
    )
    assert stop_reason is not None and "echoed" in stop_reason
    assert autonomy_gate.auto_continuing_next_turn_flag is False

    is_net, mid_mutated, reason = (
        ServiceGateAgentRuntimeController.gate_classify_turn_exception(
            caught_turn_exception=RuntimeError("Connection error: socket dropped"),
            active_engine_mode="interactions",
            interactions_prompter_instance=SimpleNamespace(turn_had_side_effects=True),
        )
    )
    assert is_net is True and mid_mutated is True
    assert "auto-retry suppressed" in reason


def test_ast_identifier_audit_no_single_letter_variables():
    """Verify audited files contain zero forbidden single-letter variable assignments."""
    forbidden_single_letters = {"i", "j", "x", "d", "p"}
    audited_paths = [
        ROOT_DIR / "webagent.py",
        ROOT_DIR / "agent.py",
        ROOT_DIR / "lib" / "lib_bejson_newagent_service_gates.py",
        ROOT_DIR / "web_routes" / "api_config_routes.py",
        ROOT_DIR / "web_routes" / "api_exec_routes.py",
        ROOT_DIR / "web_routes" / "api_chat_routes.py",
        ROOT_DIR / "web_routes" / "api_jobs_routes.py",
        ROOT_DIR / "web_routes" / "security.py",
        ROOT_DIR / "web_routes" / "ui_routes.py",
        ROOT_DIR / "web_routes" / "web_common.py",
    ]
    for source_file_path in audited_paths:
        parsed_tree = ast.parse(source_file_path.read_text(encoding="utf-8"))
        for ast_node in ast.walk(parsed_tree):
            if isinstance(ast_node, ast.Name) and isinstance(ast_node.ctx, ast.Store):
                assert ast_node.id not in forbidden_single_letters, (
                    f"{source_file_path.name} assigns forbidden single-letter identifier '{ast_node.id}'"
                )
