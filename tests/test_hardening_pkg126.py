"""
Name:           test_hardening_pkg126.py
Description:    Regression tests for the pkg126 audit/harden/optimize pass: the
                undefined-name bugs (confirmation gate, diff_file), exec stdout
                with no trailing newline, cap applied after cwd/env parsing,
                http_get scheme restriction, fd probe caching, /export format.
Version:        1.0
Date:           2026-10-14
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  5d0e7b94-2c61-4f38-a7d3-9e14b6c80f25
"""
import _libpath  # noqa: F401
import asyncio
import builtins

import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_commands as commands


def _run(coro):
    return asyncio.run(coro)


class TestExecOutput:
    def test_no_trailing_newline_is_kept(self, tmp_path):
        code, out, cwd, _ = _run(actions.do_exec("printf hi", str(tmp_path), timeout=20))
        assert code == 0 and out.strip() == "hi"
        assert cwd == str(tmp_path)

    def test_trailing_newline_not_doubled(self, tmp_path):
        _, out, _, _ = _run(actions.do_exec("echo hi", str(tmp_path), timeout=20))
        assert out == "hi\n"

    def test_cd_still_tracked(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _, _, cwd, env = _run(actions.do_exec("cd sub", str(tmp_path), timeout=20))
        assert cwd == str(sub) and env and "PATH" in env

    def test_cap_does_not_break_cwd_tracking(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _, out, cwd, env = _run(actions.do_exec(
            "cd sub && head -c 30000 /dev/zero | tr '\\0' a", str(tmp_path), timeout=20, output_cap=1000))
        assert cwd == str(sub) and env
        assert "exec cap hit" in out and len(out) < 1500


class TestHttpGet:
    def test_file_scheme_rejected(self):
        assert "only supports http" in actions.do_http_get("file:///etc/hostname")

    def test_no_scheme_rejected(self):
        assert actions.do_http_get("example.com").startswith("[ERROR]")


class TestFdProbe:
    def test_probe_cached(self, monkeypatch):
        calls = []
        monkeypatch.setattr(actions, "_FD_AVAILABLE", None)
        monkeypatch.setattr(actions.shutil, "which", lambda n: calls.append(n) or None)
        assert actions._fd_available() is False
        assert actions._fd_available() is False
        assert calls == ["fd"]

    def test_find_files_works_without_fd(self, tmp_path, monkeypatch):
        (tmp_path / "needle_file.txt").write_text("x")
        monkeypatch.setattr(actions, "_FD_AVAILABLE", False)
        assert "needle_file.txt" in actions.do_find_files("needle", ".", str(tmp_path))


class TestConfirmationGate:
    def test_gate_prompt_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setattr(builtins, "input", lambda *_: "n")
        ctx = {"_cwd": str(tmp_path), "config": {"confirmation_gate": True}}
        res = _run(actions.run_action_queue(
            [{"tag": "exec", "attrs": {}, "content": "echo hi"}], ctx))
        assert res and res[0].exit_code == -2


class TestDiffFile:
    def test_diff_file_no_nameerror(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        out = actions.do_diff_file(str(f), str(tmp_path))
        assert "not defined" not in out


class TestExportFormat:
    def test_export_is_timestamped_and_divided(self, tmp_path):
        ctx = {"_cwd": str(tmp_path), "history": [
            {"role": "user", "content": "hi", "_ts": "2026-10-14T10:00:00"},
            {"role": "model", "content": "yo", "_ts": "2026-10-14T10:00:05"}]}
        ctx_keys = ctx
        ok, msg = _run(commands.handle_slash_commands("/export", ctx_keys))
        assert ok
        files = list(tmp_path.glob("session_export_*.md"))
        assert files
        text = files[0].read_text()
        assert "### [2026-10-14T10:00:00] **YOU**" in text
        assert "\n\n--------\n\n" in text
