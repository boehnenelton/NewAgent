"""
Name:           api_chat_routes.py
Path:           web_routes/api_chat_routes.py
Description:    Gated conversational turn loop (/api/chat) and session memory
                management (/api/amnesia, /api/rebirth) endpoints. Delegates all
                domain execution to ServiceGateConversationController.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  ca57b2e8-c904-491a-a227-2a6853ceabbe
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from lib_bejson_newagent_service_gates import ServiceGateConversationController
from web_routes.web_common import (
    BACKUPS_DIR,
    CONFIG_DIR,
    CONTEXT_DIR,
    JOBS_DIR,
    MAX_AUTO_CONTINUE,
    describe_attachment_path,
    run_async,
)


def create_blueprint(terminal_instance) -> Blueprint:
    """Build the `api_chat` blueprint bound to `terminal_instance` via ServiceGateConversationController."""
    chat_route_blueprint = Blueprint("api_chat", __name__)
    chat_service_gate = getattr(terminal_instance, "chat_service_gate", None)
    if chat_service_gate is None:
        chat_service_gate = ServiceGateConversationController(
            terminal_state_holder=terminal_instance,
            config_dir_path=CONFIG_DIR,
            context_dir_path=CONTEXT_DIR,
            backups_dir_path=BACKUPS_DIR,
            jobs_dir_path=JOBS_DIR,
            max_auto_continue_iterations=MAX_AUTO_CONTINUE,
            async_runner_callable=run_async,
            attachment_describer_callable=describe_attachment_path,
        )

    @chat_route_blueprint.route("/api/chat", methods=["POST"])
    def api_chat():
        request_json_payload = request.get_json(force=True, silent=True) or {}
        gate_envelope = chat_service_gate.gate_conversation_execute_turn(
            request_body_map=request_json_payload
        )
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @chat_route_blueprint.route("/api/amnesia", methods=["POST"])
    def api_amnesia():
        gate_envelope = chat_service_gate.gate_conversation_amnesia_compress()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    @chat_route_blueprint.route("/api/rebirth", methods=["POST"])
    def api_rebirth():
        gate_envelope = chat_service_gate.gate_conversation_rebirth_restore()
        return (
            jsonify(gate_envelope.service_gate_response_payload_map),
            gate_envelope.service_gate_response_http_status,
        )

    return chat_route_blueprint
