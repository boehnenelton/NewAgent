"""
Name:           test_actions_search_text_cap.py
Description:    Regression coverage for the CRITICAL bug caught live from
                 Elton's own session logs: a `search_text bookwriter` call
                 returned 1,954,412 bytes because do_search_text() had no
                 output cap and no exclusion of logs/ (archived session
                 transcripts, which recursively explode any common word).
                 Also covers the second bug found verifying the first: the
                 ripgrep -g exclusion globs silently didn't work because
                 the subprocess wasn't run with cwd= set to the search
                 root, so the globs never anchored.
Version:        1.0
Date:           2026-10-01
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  a2d0e751-4cce-421d-a2fb-10f3a2dfa06a
"""
import _libpath  # noqa: F401  (puts lib/ on sys.path for unittest + pytest)
import os

import pytest

import lib_bejson_newagent_actions as actions


class TestCapSubprocessOutput:
    def test_small_output_passes_through_unchanged(self):
        assert actions._cap_subprocess_output("hello") == "hello"

    def test_oversized_output_is_truncated_with_notice(self):
        big = "x" * 200000
        capped = actions._cap_subprocess_output(big)
        assert len(capped) < 70000
        assert "truncated" in capped

    def test_cap_boundary_is_64kb(self):
        exactly_at_cap = "y" * actions.SUBPROCESS_OUTPUT_CAP_BYTES
        assert actions._cap_subprocess_output(exactly_at_cap) == exactly_at_cap
        one_over = "y" * (actions.SUBPROCESS_OUTPUT_CAP_BYTES + 1)
        assert "truncated" in actions._cap_subprocess_output(one_over)


@pytest.mark.skipif(
    __import__("shutil").which("rg") is None, reason="ripgrep (rg) not installed"
)
class TestSearchTextExcludesLogsAndCaps:
    def test_logs_directory_is_excluded_from_matches(self, tmp_path):
        """The exact field scenario: a huge file under logs/ must not
        appear in search_text results at all."""
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "huge_session.bejson").write_text("bookwriter " * 500000)
        (tmp_path / "real_code.py").write_text("# bookwriter integration module\n")

        result = actions.do_search_text("bookwriter", ".", str(tmp_path))

        assert "huge_session" not in result
        assert "logs/" not in result
        assert "real_code.py" in result
        assert len(result) < 70000

    def test_backups_and_git_also_excluded(self, tmp_path):
        (tmp_path / "backups").mkdir()
        (tmp_path / "backups" / "snap.bejson").write_text("needle")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "COMMIT_EDITMSG").write_text("needle")
        (tmp_path / "src.py").write_text("needle\n")

        result = actions.do_search_text("needle", ".", str(tmp_path))

        assert "backups/" not in result
        assert ".git/" not in result
        assert "src.py" in result

    def test_oversized_match_outside_excluded_dirs_still_gets_capped(self, tmp_path):
        """Confirms the cap is a real safety net independent of the
        exclusion globs -- a legitimate huge match outside logs/ must
        still be truncated, not just matches inside excluded dirs."""
        (tmp_path / "huge_source.py").write_text("# bookwriter\n" * 500000)

        result = actions.do_search_text("bookwriter", "huge_source.py", str(tmp_path))

        assert len(result) < 70000
        assert "truncated" in result

    def test_normal_small_search_is_unaffected(self, tmp_path):
        (tmp_path / "small.py").write_text("# bookwriter note\n")
        result = actions.do_search_text("bookwriter", "small.py", str(tmp_path))
        assert "small.py" in result or "bookwriter" in result

    def test_exclusion_globs_actually_anchor(self, tmp_path):
        """Direct regression for the SECOND bug (the globs silently not
        working without cwd= set) -- this is the test that would have
        caught it: without the cwd= fix, this assertion fails even
        though the -g flags are present in the command."""
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "noise.txt").write_text("UNIQUEMARKER123")
        result = actions.do_search_text("UNIQUEMARKER123", ".", str(tmp_path))
        assert "UNIQUEMARKER123" not in result
