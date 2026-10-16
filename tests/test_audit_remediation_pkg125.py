"""
Name:           test_audit_remediation_pkg121.py
Description:    Regression coverage for the pkg121 re-audit remediation: ledger
                authoritative over active key rows, ~ path semantics in file
                action tags, exec output cap, /help dispatch, shipped-config
                hygiene, policy rules, and the timestamped/divided markdown
                session export.
Version:        1.0
Date:           2026-10-13
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  c3a91e70-5d24-4b8f-9a6e-1f0b7d2e4c58
"""
import _libpath  # noqa: F401
import asyncio
import json
import re
import uuid
from pathlib import Path

import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_commands as commands
import lib_bejson_newagent_engine_rest as engine_rest
import lib_bejson_newagent_session as session
from lib_bejson_Core_bejson_core import bejson_core_create_104a, bejson_core_atomic_write, bejson_core_load_file
from lib_bejson_newagent_key_ledger import KeyLedger, key_ledger_hash_key

ROOT = Path(__file__).resolve().parent.parent
FAKE = "AQ.FAKE-FIXTURE-ONLY-1111111111111111111111111111"


def _run(coro):
    return asyncio.run(coro)


class TestLedgerAuthoritative:
    def _setup(self, tmp_path):
        fields = [{"name": "var_name", "type": "string"}, {"name": "var_value", "type": "string"},
                  {"name": "var_type", "type": "string"}]
        env = bejson_core_create_104a("GlobalEnv", fields, [["GEMINI_KEY_1", FAKE, "secret"]])
        env_path = tmp_path / "secureenv.json"
        assert bejson_core_atomic_write(str(env_path), env)

        idx = {f["name"]: i for i, f in enumerate(engine_rest._KEY_FIELDS)}
        row = [None] * len(engine_rest._KEY_FIELDS)
        row[idx["api_key"]] = FAKE
        row[idx["label"]] = "GEMINI_KEY_1"
        row[idx["is_active"]] = True
        row[idx["key_hash"]] = key_ledger_hash_key(FAKE)
        keys_path = tmp_path / "keys.bejson"
        assert bejson_core_atomic_write(str(keys_path), bejson_core_create_104a("ApiKey", list(engine_rest._KEY_FIELDS), [row]))
        return env_path, keys_path, idx

    def test_flagged_active_row_is_deactivated(self, tmp_path):
        env_path, keys_path, idx = self._setup(tmp_path)
        led = KeyLedger(tmp_path)
        led.set_flags(key_ledger_hash_key(FAKE), ["bad"], "suspended")
        led.save()
        engine_rest.sync_keys_from_env_file(keys_path, env_path)
        doc = bejson_core_load_file(str(keys_path))
        assert doc["Values"][0][idx["is_active"]] is False

    def test_flagged_row_stays_off_across_repeated_syncs(self, tmp_path):
        env_path, keys_path, idx = self._setup(tmp_path)
        led = KeyLedger(tmp_path)
        led.set_flags(key_ledger_hash_key(FAKE), ["bad"], "suspended")
        led.save()
        for _ in range(3):
            engine_rest.sync_keys_from_env_file(keys_path, env_path)
        doc = bejson_core_load_file(str(keys_path))
        assert doc["Values"][0][idx["is_active"]] is False

    def test_unflagged_row_unaffected(self, tmp_path):
        env_path, keys_path, idx = self._setup(tmp_path)
        engine_rest.sync_keys_from_env_file(keys_path, env_path)
        doc = bejson_core_load_file(str(keys_path))
        assert doc["Values"][0][idx["is_active"]] is True


class TestTildePaths:
    def test_read_file_expands_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".gemini").mkdir()
        (tmp_path / ".gemini" / "GEMINI.md").write_text("hello", encoding="utf-8")
        assert actions.do_read_file("~/.gemini/GEMINI.md", "/") == "hello"

    def test_relative_still_joins_cwd(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        assert actions.do_read_file("a.txt", str(tmp_path)) == "x"


class TestExecCap:
    def test_large_output_truncated_with_notice(self, tmp_path):
        code, out, _, _ = _run(actions.do_exec(
            "head -c 50000 /dev/zero | tr '\\0' a; echo", str(tmp_path), timeout=20, output_cap=1000))
        assert code == 0
        assert len(out) < 1500 and "exec cap hit" in out

    def test_cap_zero_disables(self, tmp_path):
        _, out, _, _ = _run(actions.do_exec(
            "head -c 5000 /dev/zero | tr '\\0' a; echo", str(tmp_path), timeout=20, output_cap=0))
        assert len(out) >= 5000 and "cap hit" not in out

    def test_small_output_untouched(self, tmp_path):
        _, out, _, _ = _run(actions.do_exec("echo hi", str(tmp_path), timeout=20))
        assert out.strip() == "hi"


class TestHelp:
    def test_help_lists_commands(self):
        ok, msg = _run(commands.handle_slash_commands("/help", {}))
        assert ok and "/help" in msg

    def test_command_help_suffix(self):
        ok, msg = _run(commands.handle_slash_commands("/help help", {}))
        assert ok and "Usage" in msg


class TestShippedHygiene:
    def test_web_auth_token_blank(self):
        doc = json.loads((ROOT / "config" / "config.json").read_text())
        vals = {r[0]: r[1] for r in doc["Values"]}
        assert vals["web_auth_token"] == ""

    def test_no_key_prefixes_in_shipped_data(self):
        pat = re.compile(r"gsk_[A-Za-z0-9]{20}|sk-or-v1-[A-Za-z0-9]{20}|AIza[0-9A-Za-z_-]{30}")
        for sub in ("config", "env_templates", "Context", "dev"):
            for f in (ROOT / sub).rglob("*"):
                if f.is_file():
                    assert not pat.search(f.read_text(errors="ignore")), f

    def test_env_template_has_eight_openrouter_slots(self):
        doc = json.loads((ROOT / "env_templates" / "secureenv_file.template.json").read_text())
        names = {r[0] for r in doc["Values"]}
        assert {f"OPENROUTER_KEY_{i}" for i in range(1, 9)} <= names

    def test_policy_has_clarify_and_long_running_rules(self):
        text = (ROOT / "Context" / "Persistent_Policy.md").read_text()
        assert "Clarify-first rule" in text and "exec_bg" in text

    def test_exec_cap_in_config(self):
        doc = json.loads((ROOT / "config" / "config.json").read_text())
        assert "exec_output_cap_bytes" in {r[0] for r in doc["Values"]}


class TestMarkdownLogFormat:
    def test_session_export_is_timestamped_and_divided(self):
        rows = [["12:00:00", "user", "hi", "", 0, 0, 0, 0, 0, 0, "", "2026-10-13T12:00:00"],
                ["12:00:05", "model", "yo", "", 0, 0, 0, 0, 0, 0, "", "2026-10-13T12:00:05"]]
        md = session._render_transcript_markdown("s", rows)
        assert "### [2026-10-13T12:00:00] [USER]" in md
        assert "\n\n--------\n\n" in md and "\n---\n" not in md

    def test_dev_ledgers_use_dividers(self):
        for name in ("change-log.md", "dead_code.md", "security-notes.md"):
            text = (ROOT / "dev" / name).read_text()
            assert "\n\n--------\n\n" in text, name
            first = re.search(r"(?m)^## \[(\d{4}-\d\d-\d\d)", text)
            assert first, name
