"""
Name:           api_jobs_routes.py
Path:           web_routes/api_jobs_routes.py
Description:    Gated JobMaker lifecycle (/api/jobs, /api/jobs/start, /api/jobs/stop)
                and persistent scratch-notes (/api/notes) endpoints. Delegates all
                domain operations to ServiceGateJobNotesController.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  2a386a6f-f705-4109-be63-059ea31b5644
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from lib_bejson_newagent_service_gates import ServiceGateJobNotesController
from web_routes.web_common import JOBS_DIR, NOTES_DIR, NOTES_FILE

NOTES_MAX_CHARS = 1_000_000


def create_blueprint(terminal_instance) -> Blueprint:
    """Build the `api_jobs` blueprint bound to `terminal_instance` via ServiceGateJobNotesController."""
    jobs_route_blueprint = Blueprint("api_jobs", __name__)

    # Use dynamic getters so monkeypatching module attributes in unit tests continues to work seamlessly
    jobs_notes_service_gate = ServiceGateJobNotesController(
        terminal_state_holder=terminal_instance,
        jobs_dir_path_getter=lambda: JOBS_DIR,
        notes_dir_path_getter=lambda: NOTES_DIR,
        notes_file_path_getter=lambda: NOTES_FILE,
        notes_max_chars_getter=lambda: NOTES_MAX_CHARS,
    )

    @jobs_route_blueprint.route("/api/jobs", methods=["GET"])
    def api_jobs_list():
        gate_envelope = jobs_notes_service_gate.gate_jobs_list_pending()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @jobs_route_blueprint.route("/api/jobs/start", methods=["POST"])
    def api_jobs_start():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = jobs_notes_service_gate.gate_jobs_start_named(
            request_body_map=request_json_payload
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @jobs_route_blueprint.route("/api/jobs/stop", methods=["POST"])
    def api_jobs_stop():
        gate_envelope = jobs_notes_service_gate.gate_jobs_stop_active()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @jobs_route_blueprint.route("/api/notes", methods=["GET"])
    def api_notes_get():
        gate_envelope = jobs_notes_service_gate.gate_notes_read_text()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @jobs_route_blueprint.route("/api/notes", methods=["POST"])
    def api_notes_save():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = jobs_notes_service_gate.gate_notes_save_text(
            request_body_map=request_json_payload
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    return jobs_route_blueprint
