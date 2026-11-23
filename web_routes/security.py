"""
Name:           security.py
Path:           web_routes/security.py
Description:    Auth-token gate (before_request) and defensive security headers (after_request).
                Split out of webagent.py (audit item 6, 2026-10-17); audited for
                <hierarchy>_<group>_<purpose> taxonomy compliance.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  2a469a65-40ca-4219-952d-4c93a76fce74
"""

import secrets
import threading
import time
from collections import deque

from flask import jsonify, request

FAIL_WINDOW_S = 60
FAIL_LIMIT = 30  # failed auth attempts allowed per window, process-wide


def register_security(flask_application, terminal_instance) -> None:
    """Install the authentication gate and defensive HTTP security headers on `flask_application`."""
    failed_attempt_timestamps: deque = deque()
    failed_attempt_mutex = threading.Lock()

    @flask_application.errorhandler(413)
    def _handle_payload_too_large(_request_entity_error):
        return jsonify({"error": "Request body too large."}), 413

    @flask_application.before_request
    def _require_auth_token():
        allowed_host_set = getattr(terminal_instance, "allowed_hosts", None)
        if allowed_host_set:
            request_host_header = request.host.lower()
            normalized_host = (
                request_host_header[: request_host_header.index("]") + 1]
                if request_host_header.startswith("[")
                else request_host_header.split(":")[0]
            )
            if normalized_host not in allowed_host_set:
                return jsonify({"error": "Bad Host header."}), 400

        supplied_auth_token = (
            request.headers.get("X-Auth-Token")
            or request.args.get("token")
            or request.cookies.get("web_auth_token")
            or ""
        )
        if not secrets.compare_digest(
            supplied_auth_token.encode("utf-8"),
            terminal_instance.web_token.encode("utf-8"),
        ):
            current_monotonic_timestamp = time.monotonic()
            with failed_attempt_mutex:
                while (
                    failed_attempt_timestamps
                    and current_monotonic_timestamp - failed_attempt_timestamps[0]
                    > FAIL_WINDOW_S
                ):
                    failed_attempt_timestamps.popleft()
                exceeded_failure_limit = len(failed_attempt_timestamps) >= FAIL_LIMIT
                failed_attempt_timestamps.append(current_monotonic_timestamp)
                retry_after_seconds = max(
                    1,
                    int(
                        FAIL_WINDOW_S
                        - (current_monotonic_timestamp - failed_attempt_timestamps[0])
                    ),
                )
            if exceeded_failure_limit:
                throttle_response = jsonify(
                    {"error": "Too many failed authentication attempts."}
                )
                throttle_response.status_code = 429
                throttle_response.headers["Retry-After"] = str(retry_after_seconds)
                return throttle_response

            if request.path == "/":
                return (
                    "<!doctype html><meta charset=utf-8><title>NewAgent</title>"
                    "<body style='font-family:monospace;background:#000;color:#fff;padding:2em;display:flex;justify-content:center;align-items:center;min-height:80vh'>"
                    "<div style='background:#111;border:1px solid #333;padding:2em;max-width:500px;width:100%;border-radius:4px'>"
                    "<h3 style='color:#de2626;margin-top:0'>NewAgent web terminal</h3>"
                    "<p style='color:#ccc'>Missing or incorrect auth token. Open the full URL printed in the console:<br>"
                    "<code style='color:#de2626'>http://HOST:PORT/?token=&lt;token&gt;</code></p>"
                    "<form method='GET' action='/' style='margin-top:1.5em;display:flex;flex-direction:column;gap:10px'>"
                    "<input type='text' name='token' placeholder='Paste web_auth_token here...' autofocus required style='background:#222;border:1px solid #555;color:#fff;padding:10px;font-family:monospace;border-radius:2px'>"
                    "<button type='submit' style='background:#de2626;color:#fff;border:none;padding:10px;font-weight:bold;cursor:pointer;font-family:monospace;border-radius:2px'>Authenticate Session</button>"
                    "</form>"
                    "</div></body>"
                ), 401
            return (
                jsonify({"error": "Unauthorized -- missing or incorrect auth token."}),
                401,
            )

    @flask_application.after_request
    def _set_security_headers(http_response):
        http_response.headers["X-Content-Type-Options"] = "nosniff"
        http_response.headers["X-Frame-Options"] = "DENY"
        http_response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
            "object-src 'none'; base-uri 'self'"
        )
        http_response.headers["X-XSS-Protection"] = "1; mode=block"
        http_response.headers["Cache-Control"] = "no-store"
        http_response.headers["Referrer-Policy"] = "no-referrer"
        http_response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        supplied_token_for_cookie = (
            request.headers.get("X-Auth-Token")
            or request.args.get("token")
            or request.cookies.get("web_auth_token")
            or ""
        )
        if supplied_token_for_cookie and secrets.compare_digest(
            supplied_token_for_cookie.encode("utf-8"),
            terminal_instance.web_token.encode("utf-8"),
        ):
            http_response.set_cookie(
                "web_auth_token",
                terminal_instance.web_token,
                httponly=True,
                samesite="Lax",
                path="/",
            )
        return http_response
