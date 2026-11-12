"""
Name:           test_webagent_split.py
Description:    Structural/behavioral regression for the webagent.py decomposition
                 (audit item 6): the blueprints expose the same route map, the
                 auth gate and security headers still apply, the token is
                 injected into the served page, and webagent.py stays a thin shell.
                 Uses a stub `term` so no keys, logs or config are touched.
Version:        1.0
Date:           2026-10-17
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  0d3c9b7e-52a1-4f6b-9e08-7b2f4a6c1d95
"""
import _libpath  # noqa: F401
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

flask = pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_routes import (  # noqa: E402
    security, ui_routes, api_exec_routes, api_config_routes, api_chat_routes, api_jobs_routes,
)

TOKEN = "unit-test-token-0123456789"

EXPECTED_ROUTES = {
    ("/", "GET"), ("/api/exec", "POST"), ("/api/config", "GET"), ("/api/config", "POST"),
    ("/api/files/quickjumps", "GET"), ("/api/files/browse", "GET"), ("/api/chat", "POST"),
    ("/api/models", "GET"), ("/api/models", "POST"), ("/api/status", "GET"),
    ("/api/jobs", "GET"), ("/api/jobs/start", "POST"), ("/api/jobs/stop", "POST"),
    ("/api/notes", "GET"), ("/api/notes", "POST"), ("/api/amnesia", "POST"), ("/api/rebirth", "POST"),
}


@pytest.fixture()
def app():
    term = SimpleNamespace(web_token=TOKEN)
    flask_app = flask.Flask("webagent_test", root_path=str(ROOT))
    security.register_security(flask_app, term)
    for module in (ui_routes, api_exec_routes, api_config_routes, api_chat_routes, api_jobs_routes):
        flask_app.register_blueprint(module.create_blueprint(term))
    return flask_app


def test_route_map_unchanged(app):
    got = {(r.rule, m) for r in app.url_map.iter_rules() if r.endpoint != "static"
           for m in r.methods if m not in ("HEAD", "OPTIONS")}
    assert got == EXPECTED_ROUTES


def test_root_without_token_is_html_401(app):
    resp = app.test_client().get("/")
    assert resp.status_code == 401 and b"auth token" in resp.data


def test_api_without_token_is_json_401(app):
    resp = app.test_client().get("/api/status")
    assert resp.status_code == 401 and resp.get_json()["error"].startswith("Unauthorized")


def test_index_serves_template_with_token_shim_and_headers(app):
    resp = app.test_client().get(f"/?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert body.index("X-Auth-Token") < body.index("<script", body.index("</script>") + 1)  # shim precedes page JS
    assert TOKEN in body and "window.fetch" in body
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_template_and_shell_layout():
    assert (ROOT / "templates" / "webagent_terminal.html").is_file()
    shell_lines = (ROOT / "webagent.py").read_text(encoding="utf-8").count("\n")
    assert shell_lines < 400, f"webagent.py has grown back to {shell_lines} lines"
    assert '"""\n<!DOCTYPE' not in (ROOT / "webagent.py").read_text(encoding="utf-8")
