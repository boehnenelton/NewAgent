"""
Name:           test_hardening_20261017.py
Description:    Regression coverage for the 2026-10-17 audit/hardening pass: web auth
                 edge cases (non-ASCII token, Host allow-list, failed-auth throttle),
                 request/notes limits, protected config keys, response headers,
                 job-name path containment and http_get redirect/link-local guards.
Version:        1.0
Date:           2026-10-17
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  4e9a1c37-8b52-4d0f-a6e3-91c7d2b5f018
"""
import _libpath  # noqa: F401
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

flask = pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_routes import security, api_config_routes, api_jobs_routes  # noqa: E402
import lib_bejson_newagent_actions as actions  # noqa: E402
import lib_bejson_newagent_jobs as jobs  # noqa: E402

TOKEN = "hardening-test-token-0123456789"


def make_app(tmp_path, allowed_hosts=None, config=None):
    term = SimpleNamespace(web_token=TOKEN, allowed_hosts=allowed_hosts,
                           config=config if config is not None else {}, _active_job_path=None)
    app = flask.Flask("hardening_test", root_path=str(ROOT))
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    security.register_security(app, term)
    app.register_blueprint(api_config_routes.create_blueprint(term))
    app.register_blueprint(api_jobs_routes.create_blueprint(term))

    @app.route("/ping")
    def ping():
        return "pong"
    return app, term


AUTH = {"X-Auth-Token": TOKEN}


class TestWebAuth:
    def test_non_ascii_token_header_is_401_not_500(self, tmp_path):
        app, _ = make_app(tmp_path)
        assert app.test_client().get("/ping", headers={"X-Auth-Token": "t\u00f6k"}).status_code == 401

    def test_non_ascii_token_query_is_401_not_500(self, tmp_path):
        app, _ = make_app(tmp_path)
        assert app.test_client().get("/ping?token=%E2%82%AC").status_code == 401

    def test_host_allowlist(self, tmp_path):
        app, _ = make_app(tmp_path, allowed_hosts={"127.0.0.1", "localhost", "[::1]"})
        c = app.test_client()
        assert c.get("/ping", headers={**AUTH, "Host": "127.0.0.1:5001"}).status_code == 200
        assert c.get("/ping", headers={**AUTH, "Host": "[::1]:5001"}).status_code == 200
        assert c.get("/ping", headers={**AUTH, "Host": "evil.example.com"}).status_code == 400

    def test_no_allowlist_when_exposed_on_purpose(self, tmp_path):
        app, _ = make_app(tmp_path, allowed_hosts=None)
        assert app.test_client().get("/ping", headers={**AUTH, "Host": "anything.lan"}).status_code == 200

    def test_failed_auth_throttle_never_locks_out_valid_token(self, tmp_path):
        app, _ = make_app(tmp_path)
        c = app.test_client()
        codes = [c.get("/ping", headers={"X-Auth-Token": "wrong"}).status_code
                 for _ in range(security.FAIL_LIMIT + 5)]
        assert codes[0] == 401 and codes[-1] == 429
        resp = c.get("/ping", headers={"X-Auth-Token": "wrong"})
        assert resp.headers["Retry-After"].isdigit()
        assert c.get("/ping", headers=AUTH).status_code == 200  # real user unaffected

    def test_headers_no_store_and_no_referrer(self, tmp_path):
        app, _ = make_app(tmp_path)
        r = app.test_client().get("/ping", headers=AUTH)
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["Referrer-Policy"] == "no-referrer"

    def test_oversized_body_is_413_json(self, tmp_path):
        app, _ = make_app(tmp_path)
        big = "x" * (2 * 1024 * 1024 + 10)
        r = app.test_client().post("/api/notes", data=big, headers={**AUTH, "Content-Type": "application/json"})
        assert r.status_code == 413 and "error" in r.get_json()


class TestNotesValidation:
    def test_non_string_rejected(self, tmp_path, monkeypatch):
        app, _ = make_app(tmp_path)
        monkeypatch.setattr(api_jobs_routes, "NOTES_DIR", tmp_path)
        monkeypatch.setattr(api_jobs_routes, "NOTES_FILE", tmp_path / "n.txt")
        assert app.test_client().post("/api/notes", json={"text": ["a"]}, headers=AUTH).status_code == 400

    def test_over_cap_rejected_and_normal_saved(self, tmp_path, monkeypatch):
        app, _ = make_app(tmp_path)
        monkeypatch.setattr(api_jobs_routes, "NOTES_DIR", tmp_path)
        monkeypatch.setattr(api_jobs_routes, "NOTES_FILE", tmp_path / "n.txt")
        c = app.test_client()
        assert c.post("/api/notes", json={"text": "y" * (api_jobs_routes.NOTES_MAX_CHARS + 1)}, headers=AUTH).status_code == 413
        assert c.post("/api/notes", json={"text": "ok"}, headers=AUTH).status_code == 200
        assert (tmp_path / "n.txt").read_text() == "ok"


class TestProtectedConfig:
    def _app(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_config_routes.config_lib, "save_config", lambda *_a, **_k: True)
        return make_app(tmp_path, config={"web_auth_token": "SECRET", "exec_denylist": "rm -rf", "send_delay_seconds": 1.0})

    def test_get_masks_token(self, tmp_path, monkeypatch):
        app, _ = self._app(tmp_path, monkeypatch)
        rows = {r["name"]: r["value"] for r in app.test_client().get("/api/config", headers=AUTH).get_json()["config"]}
        assert rows["web_auth_token"] == "********" and rows["send_delay_seconds"] == 1.0

    @pytest.mark.parametrize("key", ["web_auth_token", "exec_denylist"])
    def test_protected_keys_cannot_be_set(self, tmp_path, monkeypatch, key):
        app, term = self._app(tmp_path, monkeypatch)
        r = app.test_client().post("/api/config", json={"name": key, "value": ""}, headers=AUTH)
        assert r.status_code == 403 and term.config[key] != ""

    def test_normal_key_still_settable(self, tmp_path, monkeypatch):
        app, term = self._app(tmp_path, monkeypatch)
        r = app.test_client().post("/api/config", json={"name": "send_delay_seconds", "value": 2}, headers=AUTH)
        assert r.status_code == 200 and term.config["send_delay_seconds"] == 2.0


class TestJobPathContainment:
    def test_traversal_rejected_normal_resolved(self, tmp_path):
        jobs_dir = tmp_path / "jobs"; jobs_dir.mkdir()
        (tmp_path / "secret.bejson").write_text("{}")
        (jobs_dir / "real.bejson").write_text("{}")
        assert jobs.get_job_path(jobs_dir, "../secret.bejson") is None
        assert jobs.get_job_path(jobs_dir, "../secret") is None
        assert jobs.get_job_path(jobs_dir, "real") == jobs_dir / "real.bejson"
        assert jobs.get_job_path(jobs_dir, "real.bejson") == jobs_dir / "real.bejson"


class TestHttpGetGuards:
    def test_link_local_refused(self):
        assert "link-local" in actions.do_http_get("http://169.254.169.254/latest/meta-data/")

    def test_non_http_scheme_refused(self):
        assert "only supports" in actions.do_http_get("file:///etc/passwd")

    def test_redirect_to_ftp_blocked(self):
        h = actions._HttpOnlyRedirects()
        with pytest.raises(urllib.error.HTTPError):
            h.redirect_request(SimpleNamespace(), None, 302, "Found", {}, "ftp://example.com/x")

    def test_redirect_to_metadata_blocked(self):
        h = actions._HttpOnlyRedirects()
        with pytest.raises(urllib.error.HTTPError):
            h.redirect_request(SimpleNamespace(), None, 302, "Found", {}, "http://169.254.169.254/")
