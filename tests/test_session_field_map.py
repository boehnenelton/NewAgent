"""
Name:           test_session_field_map.py
Description:    Regression coverage for audit finding #3 (MEDIUM-HIGH) --
                 the field-map fallback landmine in
                 lib_bejson_newagent_session.py. 34 fmap.get(name,
                 hardcoded_index) calls previously fell back to a
                 positional literal on a field-map miss, risking a silent
                 miswrite into the wrong column on a drifted/foreign doc.
                 All now route through _require_field(), which raises
                 KeyError instead. Also covers the companion bug found in
                 the same file: `import logging` was missing despite
                 logging.getLogger(__name__) being called in 6 places.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  20159752-cd0b-4e6f-a7cd-70c9c67c20a0
"""
import pytest

import lib_bejson_newagent_session as session


class TestRequireField:
    def test_returns_index_when_field_present(self):
        fmap = {"session_id": 0, "status": 1, "history": 2}
        assert session._require_field(fmap, "status") == 1

    def test_raises_key_error_when_field_missing(self):
        fmap = {"session_id": 0, "status": 1}
        with pytest.raises(KeyError):
            session._require_field(fmap, "nonexistent_field")

    def test_error_message_names_the_missing_field(self):
        fmap = {"session_id": 0}
        with pytest.raises(KeyError) as exc_info:
            session._require_field(fmap, "missing_one")
        assert "missing_one" in str(exc_info.value)

    def test_does_not_silently_fall_back_to_any_index(self):
        """The exact bug: a missing field must never resolve to SOME
        number (right or wrong) -- it must raise, full stop."""
        fmap = {}
        with pytest.raises(KeyError):
            session._require_field(fmap, "anything")


class TestNoBareFmapGetFallbacksRemain:
    """Meta-regression, same shape as the mfdb_core write-check guard:
    greps this module's own source for the exact anti-pattern
    (fmap.get("name", <int>)) so a future edit reintroducing one fails
    immediately instead of waiting for the next audit."""

    def test_source_has_no_fmap_get_with_hardcoded_int_fallback(self):
        import inspect
        import re

        source = inspect.getsource(session)
        pattern = re.compile(r'fmap\.get\("[a-zA-Z_]+",\s*\d+\)')
        matches = pattern.findall(source)
        assert matches == [], (
            f"Found {len(matches)} fmap.get(name, hardcoded_index) fallback "
            f"landmine(s) -- use _require_field(fmap, name) instead (audit "
            f"finding #3)."
        )


class TestLoggingImportPresent:
    """Regression for the bonus bug found while fixing #3: this module
    called logging.getLogger(__name__) in several places with no
    `import logging` at all, so every one of those calls -- mostly
    inside except blocks logging the REAL error -- would itself raise
    NameError and mask it."""

    def test_logging_module_is_imported(self):
        assert hasattr(session, "logging"), (
            "lib_bejson_newagent_session module has no `logging` name bound -- "
            "`import logging` appears to be missing again, which will "
            "NameError every logging.getLogger(__name__) call in this file."
        )

    def test_get_logger_actually_works(self):
        logger = session.logging.getLogger(__name__)
        logger.error("regression smoke check -- must not raise NameError")
