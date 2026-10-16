"""
Name:         test_autocontinue_guard_pkg128.py
Description:  Regression tests for the pkg128 auto-continue loop guard and the
              OpenRouter payload / reasoning-leak fixes.
Version:      1.0.0
Date:         2026-10-16
Author:       Elton Boehnen — boehnenelton2024@gmail.com
"""
import _libpath  # noqa: F401
import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_engine_rest as rest


def _p(text):
    return actions.parse_actions(text)


def test_announcement_only_detects_logged_loop_messages():
    assert actions.is_announcement_only(_p('<exec>echo "Task completed: Created test folder and physics.html with cool visual physics display."</exec>'))
    assert actions.is_announcement_only(_p('<exec>echo "To view: termux-open test/physics.html"</exec>'))
    assert actions.is_announcement_only(_p("<exec>echo 'done'</exec>"))


def test_announcement_only_rejects_real_work():
    for t in ['<exec>ls</exec>', '<exec>echo hi && rm x</exec>', '<exec>echo "a" > f.txt</exec>',
              '<exec>echo $(whoami)</exec>', '<write_file path="x">y</write_file>']:
        assert not actions.is_announcement_only(_p(t)), t
    assert not actions.is_announcement_only([])


def test_signature_stable_across_whitespace_and_distinguishes_commands():
    a = _p('<exec>echo   "x"</exec>')
    b = _p('<exec>echo "x"</exec>')
    c = _p('<exec>echo "y"</exec>')
    assert actions.actions_signature(a) == actions.actions_signature(b)
    assert actions.actions_signature(a) != actions.actions_signature(c)


def test_openrouter_request_has_no_gemini_only_param():
    _, _, payload = rest._build_openrouter_request(
        "k", "m", [{"role": "user", "content": "x"}], "sys", {}, [{"model_string": "m", "thinking": True}], "openrouter")
    assert "include_thoughts" not in payload
    assert payload["reasoning"] == {"exclude": True}


def test_openrouter_think_leak_stripped():
    data = {"choices": [{"message": {"content": "<think>plan</think>Hi!"}}], "usage": {}}
    assert rest._parse_openrouter_response(data)[0] == "Hi!"
    data = {"choices": [{"message": {"content": "reasoning...</think>\nHi!"}}], "usage": {}}
    assert rest._parse_openrouter_response(data)[0] == "Hi!"
    data = {"choices": [{"message": {"content": "I think so"}}], "usage": {}}
    assert rest._parse_openrouter_response(data)[0] == "I think so"


def test_agent_wires_guard():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "agent.py").read_text()
    assert "is_announcement_only(parsed_actions)" in src
    assert "max_auto_continue_turns" in src


# ── pkg129: secrets never persist under the project directory ──────────────
import json
import re as _re
from pathlib import Path as _P


def _env_doc(tmp_path, pairs):
    f = tmp_path / "secureenv_file.json"
    f.write_text(json.dumps({
        "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
        "Records_Type": ["EnvVar"],
        "Fields": [{"name": "var_name", "type": "string"}, {"name": "var_value", "type": "string"}, {"name": "var_type", "type": "string"}],
        "Values": [[k, v, "secret"] for k, v in pairs.items()],
    }))
    return f


def test_key_cache_never_contains_env_secrets(tmp_path):
    secret = "sk-or-v1-" + "a" * 40
    env = _env_doc(tmp_path, {"OPENROUTER_KEY_1": secret})
    rest._env_source_paths.clear()
    rest._register_env_sources([env])
    keys, state = tmp_path / "keys_openrouter.bejson", tmp_path / "key_state_openrouter.bejson"
    cfg = {"env_secure_file_path": str(env), "env_paths_file_path": ""}
    rest.sync_keys_from_env_sources(keys, cfg, key_prefix="OPENROUTER_KEY_")
    assert secret not in keys.read_text()
    reg = rest.KeyRegistry(keys, state)
    assert reg.keys == [secret]                      # still usable in memory
    reg.deactivate_key(secret, "t")                  # mutation path also writes refs
    assert secret not in keys.read_text()


def test_legacy_plaintext_cache_is_scrubbed_on_load(tmp_path):
    secret = "AQ.Ab" + "b" * 40
    env = _env_doc(tmp_path, {"GEMINI_KEY_1": secret})
    rest._env_source_paths.clear()
    rest._register_env_sources([env])
    keys = tmp_path / "keys.bejson"
    doc = rest.bejson_core_create_104a("ApiKey", list(rest._KEY_FIELDS), [
        [secret, "GEMINI_KEY_1", True, "", "u-1", 1, rest.key_ledger_hash_key(secret)]])
    rest.bejson_core_atomic_write(str(keys), doc)
    assert secret in keys.read_text()
    reg = rest.KeyRegistry(keys, tmp_path / "key_state.bejson")
    assert secret not in keys.read_text()
    assert reg.keys == [secret]


def test_rotated_key_does_not_inherit_old_row(tmp_path):
    old, new = "sk-or-v1-" + "c" * 40, "sk-or-v1-" + "d" * 40
    env = _env_doc(tmp_path, {"OPENROUTER_KEY_1": old})
    rest._env_source_paths.clear()
    rest._register_env_sources([env])
    keys, state = tmp_path / "k.bejson", tmp_path / "s.bejson"
    cfg = {"env_secure_file_path": str(env), "env_paths_file_path": ""}
    rest.sync_keys_from_env_sources(keys, cfg, key_prefix="OPENROUTER_KEY_")
    env = _env_doc(tmp_path, {"OPENROUTER_KEY_1": new})
    assert rest.KeyRegistry(keys, state).keys == []   # old row unusable until sync
    rest.sync_keys_from_env_sources(keys, cfg, key_prefix="OPENROUTER_KEY_")
    assert rest.KeyRegistry(keys, state).keys == [new]


def test_no_secret_shaped_strings_in_shipped_config():
    root = _P(__file__).resolve().parents[1]
    pat = _re.compile(r"gsk_[A-Za-z0-9]{20}|sk-or-v1-[A-Za-z0-9]{20}|AIza[0-9A-Za-z_-]{30}|AQ\.Ab[0-9A-Za-z_-]{20}")
    for sub in ("config", "env_templates", "Context", "dev", "backups", "notes", "jobs"):
        d = root / sub
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    assert not pat.search(f.read_text(errors="ignore")), f
