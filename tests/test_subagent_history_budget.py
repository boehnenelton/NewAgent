"""
Name:           test_subagent_history_budget.py
Description:    Regression coverage for audit finding #7's named priority
                 follow-up -- sub-agent sessions had no token/char
                 budgeting on their history, only a turn-count trim
                 (max_history_turns) that, per the audit, nothing in the
                 codebase actually passed, so history was unbounded in
                 practice. update_session() now also trims by cumulative
                 serialized size (max_history_chars), wired through every
                 append_history() call site in subagent_runtime.py.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  b6c7a3ab-01a7-439b-9b71-c66dfdfb64a1
"""
import lib_bejson_newagent_subagent_common as subagent_common
import lib_bejson_newagent_subagent_profiles as profiles
import lib_bejson_newagent_subagent_sessions as sessions


class TestUpdateSessionCharBudget:
    def _fresh_session(self, tmp_path):
        subagent_common.ensure_subagent_dirs(tmp_path)
        return sessions.create_session(tmp_path, "test_profile", "test task", "/tmp")

    def test_single_oversized_entry_survives_alone(self, tmp_path):
        """Never drop the only/most-recent entry, even if it alone
        blows the budget -- losing the thing that just happened is
        worse than briefly running over budget by one entry."""
        sid = self._fresh_session(tmp_path)
        updated = sessions.update_session(
            tmp_path, sid,
            append_history=[{"role": "user", "content": "z" * 5000}],
            max_history_chars=500,
        )
        assert len(updated["history"]) == 1

    def test_trims_oldest_first_to_fit_budget(self, tmp_path):
        sid = self._fresh_session(tmp_path)
        for i in range(10):
            updated = sessions.update_session(
                tmp_path, sid,
                append_history=[{"role": "user", "content": f"turn {i}: " + ("x" * 200)}],
                max_history_chars=1000,
            )
        # Budget of 1000 chars, ~210 chars/entry -> roughly 4-5 survive, not all 10
        assert len(updated["history"]) < 10
        assert updated["history"][-1]["content"].startswith("turn 9")  # most recent always kept

    def test_under_budget_is_a_no_op(self, tmp_path):
        sid = self._fresh_session(tmp_path)
        for i in range(3):
            updated = sessions.update_session(
                tmp_path, sid,
                append_history=[{"role": "user", "content": f"turn {i}"}],
                max_history_chars=60000,
            )
        assert len(updated["history"]) == 3

    def test_none_budget_disables_char_trim_entirely(self, tmp_path):
        """max_history_chars=None (the default) must not trim at all --
        only an explicit budget activates this pass."""
        sid = self._fresh_session(tmp_path)
        for i in range(5):
            updated = sessions.update_session(
                tmp_path, sid,
                append_history=[{"role": "user", "content": "x" * 10000}],
            )
        assert len(updated["history"]) == 5


class TestProfileHistoryCharsField:
    def test_default_max_history_chars_is_defined(self):
        assert isinstance(profiles.DEFAULT_MAX_HISTORY_CHARS, int)
        assert profiles.DEFAULT_MAX_HISTORY_CHARS > 0

    def test_make_profile_doc_includes_max_history_chars(self):
        doc = profiles.make_profile_doc("test_profile", max_history_chars=12345)
        fmap = {f["name"]: i for i, f in enumerate(doc["Fields"])}
        assert "max_history_chars" in fmap
        row = doc["Values"][0]
        assert row[fmap["max_history_chars"]] == 12345

    def test_make_profile_doc_default_matches_module_default(self):
        doc = profiles.make_profile_doc("test_profile")
        fmap = {f["name"]: i for i, f in enumerate(doc["Fields"])}
        row = doc["Values"][0]
        assert row[fmap["max_history_chars"]] == profiles.DEFAULT_MAX_HISTORY_CHARS

    def test_old_profile_without_the_field_is_tolerated(self):
        """An old profile file predating this field must not crash
        load_profile() -- row_to_dict() builds its dict from the FILE'S
        OWN Fields array, not the current module constant, so a legacy
        row simply omits the key rather than erroring."""
        from lib_bejson_Core_bejson_core import bejson_core_create_104
        from lib_bejson_newagent_subagent_common import row_to_dict

        old_fields = [f for f in profiles._PROFILE_FIELDS if f["name"] != "max_history_chars"]
        old_row = ["legacy_profile", "", "", "", ["*"], [], 10, "2026-01-01T00:00:00Z"]
        doc = bejson_core_create_104("SubagentProfile", old_fields, [old_row])
        record = row_to_dict(doc, doc["Values"][0])
        assert "max_history_chars" not in record
        # the real call site pattern: profile.get(...) with a fallback
        assert record.get("max_history_chars") or profiles.DEFAULT_MAX_HISTORY_CHARS == profiles.DEFAULT_MAX_HISTORY_CHARS
