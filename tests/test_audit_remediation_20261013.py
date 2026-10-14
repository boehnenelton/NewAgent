"""
Name:           test_audit_remediation_20261013.py
Description:    Regression coverage for the 2026-10-13 audit remediation:
                 secret redaction/masking, per-key failure counting and
                 immediate deactivation of suspended keys, strict field-map
                 lookups, and the 3-day auto-prune of logs and finished
                 subagent sessions/signals.
Version:        1.0
Date:           2026-10-13
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  7a0f6d52-3f3e-4b1c-8f55-2c9d1e5b6a44
"""
import _libpath  # noqa: F401
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

import lib_bejson_newagent_errors as errors
import lib_bejson_newagent_engine_rest as engine_rest
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_session as session
import lib_bejson_newagent_subagent_sessions as sessions
import lib_bejson_newagent_subagent_signals as signals
import lib_bejson_newagent_subagent_common as subagent_common
from lib_bejson_Core_bejson_core import bejson_core_create_104a, bejson_core_atomic_write
from test_engine_rest_key_rotation import make_registry

FAKE_KEY = "AQ.DUMMY_KEY_FOR_UNIT_TESTING_ONLY"


class TestRedaction:
    def test_redacts_api_key_in_provider_error(self):
        body = f"Permission denied: Consumer 'api_key:{FAKE_KEY}' has been suspended."
        out = errors.redact_secrets(body)
        assert FAKE_KEY not in out and "[REDACTED]" in out

    def test_redacts_google_aiza_and_bearer(self):
        assert "AIza" not in errors.redact_secrets("k=AIza" + "a" * 35)
        assert "abcdefghijklmnopqrstuvwxyz" not in errors.redact_secrets("Bearer abcdefghijklmnopqrstuvwxyz123")

    def test_non_string_passthrough(self):
        assert errors.redact_secrets(None) is None


class TestEnvDripMasking:
    def _env_file(self, tmp_path):
        doc = bejson_core_create_104a(
            "EnvVar",
            [{"name": "var_name", "type": "string"}, {"name": "var_value", "type": "string"},
             {"name": "var_type", "type": "string"}],
            [["GEMINI_KEY_1", FAKE_KEY, "secret"], ["INTERNAL_STORAGE", "/storage/emulated/0", "path"]],
        )
        p = tmp_path / "env.bejson"
        assert bejson_core_atomic_write(str(p), doc)
        return p

    def test_secret_value_is_masked_paths_untouched(self, tmp_path):
        text, _ = bubble.build_env_file_section([self._env_file(tmp_path)], 0, 1, 10_000)
        assert FAKE_KEY not in text
        assert f"GEMINI_KEY_1={errors.mask_value(FAKE_KEY)}" in text
        assert "INTERNAL_STORAGE=/storage/emulated/0" in text


class TestKeyFailureCounting:
    def test_three_403s_auto_deactivate(self, tmp_path):
        reg = make_registry(tmp_path, ["kA", "kB"], {})
        for _ in range(3):
            reg.set_cooldown("kA", engine_rest.COOLDOWN_AUTH, status=403, reason="forbidden")
        assert "kA" not in reg.keys
        assert "kB" in reg.keys

    def test_suspended_body_detected_as_permanent(self):
        assert engine_rest.KeyRegistry.is_permanent_auth_failure(
            "Permission denied: Consumer 'api_key:[REDACTED]' has been suspended.")
        assert not engine_rest.KeyRegistry.is_permanent_auth_failure("quota exceeded, try later")


class TestStrictFieldMap:
    def test_missing_field_raises_keyerror(self, tmp_path):
        doc = bejson_core_create_104a("EnvVar", [{"name": "var_name", "type": "string"}], [["X"]])
        p = tmp_path / "bad_env.bejson"
        assert bejson_core_atomic_write(str(p), doc)
        with pytest.raises(KeyError):
            bubble.build_env_file_section([p], 0, 1, 1000)


class TestLogPruning:
    def _touch(self, path, age_days):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))

    def test_old_deleted_recent_kept_index_untouched(self, tmp_path):
        logs = tmp_path / "logs"
        self._touch(logs / "session_2026-10-01_00-00-00.bejson", 10)
        self._touch(logs / "session_2026-10-01_00-00-00.md", 10)
        self._touch(logs / "raw_api_debug_old.json", 4)
        self._touch(logs / "archive" / "session_old.zip", 30)
        self._touch(logs / "session_2026-10-12_00-00-00.bejson", 1)
        self._touch(logs / "sessions" / "session_index.bejson", 90)
        deleted = session.prune_old_logs(logs)
        assert set(deleted) == {"session_2026-10-01_00-00-00.bejson", "session_2026-10-01_00-00-00.md",
                                "raw_api_debug_old.json", "session_old.zip"}
        assert (logs / "session_2026-10-12_00-00-00.bejson").exists()
        assert (logs / "sessions" / "session_index.bejson").exists()
        assert not (logs / "archive").exists()

    def test_protected_stem_survives(self, tmp_path):
        logs = tmp_path / "logs"
        self._touch(logs / "session_live.bejson", 10)
        assert session.prune_old_logs(logs, protect_stems=("session_live",)) == []


class TestSubagentCleanup:
    def _backdate(self, subagents_dir, session_id, days):
        old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        sessions.update_session(subagents_dir, session_id)  # ensure row exists
        def mutate(doc):
            for i, row in enumerate(doc["Values"]):
                rec = sessions.row_to_dict(doc, row)
                if rec["session_id"] == session_id:
                    rec["created_at"] = old
                    rec["last_updated"] = old
                    doc["Values"][i] = sessions.dict_to_row(doc, rec)
            return True, None
        sessions.with_file_lock(sessions.sessions_path(subagents_dir), mutate, sessions._empty_doc)

    def test_old_finished_sessions_and_signals_purged(self, tmp_path):
        d = tmp_path / "subagents"
        subagent_common.ensure_subagent_dirs(d)
        old_done = sessions.create_session(d, "p", "old done", "/tmp")
        old_active = sessions.create_session(d, "p", "old active", "/tmp")
        fresh_done = sessions.create_session(d, "p", "fresh done", "/tmp")
        sessions.update_session(d, old_done, status=sessions.STATUS_COMPLETED)
        sessions.update_session(d, fresh_done, status=sessions.STATUS_COMPLETED)
        signals.send_signal(d, old_done, "ping")
        signals.send_signal(d, fresh_done, "ping")
        self._backdate(d, old_done, 10)
        self._backdate(d, old_active, 10)

        stats = sessions.cleanup_old_sessions(d, max_age_days=3)

        ids = {r["session_id"] for r in sessions.list_sessions(d)}
        assert ids == {old_active, fresh_done}      # ACTIVE never pruned, fresh kept
        assert stats["sessions"] == 1
        assert stats["signals"] == 1
        assert signals.poll_signals(d, fresh_done)  # fresh signal intact
