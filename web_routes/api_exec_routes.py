"""
Name:           api_exec_routes.py
Path:           web_routes/api_exec_routes.py
Description:    Gated shell execution (/api/exec) and filesystem browser
                (/api/files/quickjumps, /api/files/browse) endpoints. Delegates
                all execution and directory inspection to ServiceGateExecutionController.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  0f86b01d-f287-40da-86ca-667f86c381cf
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from lib_bejson_newagent_service_gates import ServiceGateExecutionController
from web_routes.web_common import BASE_DIR, run_async


def create_blueprint(terminal_instance) -> Blueprint:
    """Build the `api_exec` blueprint bound to `terminal_instance` via ServiceGateExecutionController."""
    exec_route_blueprint = Blueprint("api_exec", __name__)
    exec_service_gate = getattr(terminal_instance, "exec_service_gate", None)
    if exec_service_gate is None:
        exec_service_gate = ServiceGateExecutionController(
            terminal_state_holder=terminal_instance,
            project_root_dir_path=BASE_DIR,
            async_runner_callable=run_async,
        )

    @exec_route_blueprint.route("/api/exec", methods=["POST"])
    def api_exec():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = exec_service_gate.gate_exec_command(
            request_body_map=request_json_payload
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @exec_route_blueprint.route("/api/files/quickjumps", methods=["GET"])
    def api_files_quickjumps():
        gate_envelope = exec_service_gate.gate_filesystem_quickjumps()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @exec_route_blueprint.route("/api/files/browse", methods=["GET"])
    def api_files_browse():
        requested_directory_path = request.args.get("path")
        gate_envelope = exec_service_gate.gate_filesystem_browse_directory(
            requested_raw_path=requested_directory_path
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    return exec_route_blueprint
