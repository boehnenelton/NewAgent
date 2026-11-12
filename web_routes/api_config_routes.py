"""
Name:           api_config_routes.py
Path:           web_routes/api_config_routes.py
Description:    Gated configuration, model registry, and runtime telemetry status
                endpoints for webagent.py. Routes all business logic through
                ServiceGateConfigurationController in lib_bejson_newagent_service_gates,
                exposing full 67-option / 7-category / 3-store BEJSON 104a UI control.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  83588c78-782c-4448-a71f-783d540982bc
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

import lib_bejson_newagent_config as config_lib
from lib_bejson_newagent_service_gates import (
    SERVICE_GATE_PROTECTED_CONFIG_KEYS,
    ServiceGateConfigurationController,
)
from web_routes.web_common import (
    BASE_DIR,
    CONFIG_PATH,
    MODEL_CATALOG_PATH,
    VERSION,
)

# Preserved export alias for backward compatibility with security tests
WEB_PROTECTED_CONFIG = SERVICE_GATE_PROTECTED_CONFIG_KEYS


def create_blueprint(terminal_instance) -> Blueprint:
    """Build the `api_config` blueprint bound to `terminal_instance` via ServiceGateConfigurationController."""
    config_route_blueprint = Blueprint("api_config", __name__)
    config_service_gate = getattr(terminal_instance, "config_service_gate", None)
    if config_service_gate is None:
        config_service_gate = ServiceGateConfigurationController(
            terminal_state_holder=terminal_instance,
            project_root_dir_path=BASE_DIR,
            main_config_file_path=CONFIG_PATH,
            model_catalog_file_path=MODEL_CATALOG_PATH,
            runtime_version_string=VERSION,
        )

    @config_route_blueprint.route("/api/config", methods=["GET"])
    def api_config_get():
        category_filter_param = request.args.get("category")
        search_query_param = request.args.get("q")
        gate_envelope = config_service_gate.gate_config_query_catalog(
            category_filter_code=category_filter_param,
            search_query_text=search_query_param,
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @config_route_blueprint.route("/api/config", methods=["POST"])
    def api_config_set():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = config_service_gate.gate_config_mutate_dispatch(
            request_body_map=request_json_payload,
            save_config_callable=config_lib.save_config,
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @config_route_blueprint.route("/api/models", methods=["GET"])
    def api_models_get():
        gate_envelope = config_service_gate.gate_models_list_catalog()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @config_route_blueprint.route("/api/models", methods=["POST"])
    def api_models_set():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = config_service_gate.gate_models_set_active(
            request_body_map=request_json_payload
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @config_route_blueprint.route("/api/status")
    def api_status():
        gate_envelope = config_service_gate.gate_status_snapshot()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    return config_route_blueprint
