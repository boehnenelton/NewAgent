"""
Name:           test_mfdb_core_write_checks.py
Description:    Regression coverage for audit finding #2 (HIGH) --
                 discarded write-failure returns in mfdb_core.py. 13 bare
                 bejson_core_atomic_write() calls (the audit cited 4;
                 a full pass found 13) previously discarded the boolean
                 success return, so a disk-full/permission failure was
                 silently swallowed while the caller believed the write
                 succeeded. Every one now routes through _write_entity_doc,
                 _write_manifest_doc, or the new _write_checked, all three
                 of which raise MFDBCoreError on failure. This suite
                 monkeypatches bejson_core_atomic_write to always fail and
                 confirms each helper raises -- the regression this guards
                 against is someone "simplifying" one of these back to a
                 bare call.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  e9f1e253-e223-4f24-a0ac-8f39c209ed18
"""
import _libpath  # noqa: F401  (puts lib/ on sys.path for unittest + pytest)
import pytest

import lib_bejson_Core_mfdb_core as mfdb_core


class TestWriteHelpersRaiseOnFailure:
    def test_write_entity_doc_raises_when_atomic_write_fails(self, monkeypatch):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: False)
        with pytest.raises(mfdb_core.MFDBCoreError):
            mfdb_core._write_entity_doc({"Format": "BEJSON"}, "/fake/entity.bejson")

    def test_write_manifest_doc_raises_when_atomic_write_fails(self, monkeypatch):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: False)
        with pytest.raises(mfdb_core.MFDBCoreError):
            mfdb_core._write_manifest_doc({"Format": "BEJSON"}, "/fake/manifest.bejson")

    def test_write_checked_raises_when_atomic_write_fails(self, monkeypatch):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: False)
        with pytest.raises(mfdb_core.MFDBCoreError):
            mfdb_core._write_checked({"Format": "BEJSON"}, "/fake/meta.bejson", "test doc")

    def test_write_checked_error_message_names_the_path_and_label(self, monkeypatch):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: False)
        with pytest.raises(mfdb_core.MFDBCoreError) as exc_info:
            mfdb_core._write_checked({"x": 1}, "/fake/thing.bejson", "widget log")
        assert "/fake/thing.bejson" in str(exc_info.value)
        assert "widget log" in str(exc_info.value)


class TestWriteHelpersSucceedSilentlyOnSuccess:
    """Confirms the fix didn't flip the happy path -- these must NOT
    raise when the underlying write genuinely succeeds."""

    def test_write_entity_doc_no_raise_on_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: True)
        mfdb_core._write_entity_doc({"Format": "BEJSON"}, str(tmp_path / "e.bejson"))  # must not raise

    def test_write_manifest_doc_no_raise_on_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: True)
        mfdb_core._write_manifest_doc({"Format": "BEJSON"}, str(tmp_path / "m.bejson"))  # must not raise

    def test_write_checked_no_raise_on_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mfdb_core, "bejson_core_atomic_write", lambda path, data: True)
        mfdb_core._write_checked({"Format": "BEJSON"}, str(tmp_path / "c.bejson"))  # must not raise


class TestNoBareAtomicWriteCallsRemain:
    """Meta-regression: greps the module's own source for the exact
    anti-pattern the audit flagged (a bare bejson_core_atomic_write(...)
    call whose return value is discarded) so a future edit that
    reintroduces one anywhere in the file fails CI immediately instead
    of waiting for another audit to find it by hand."""

    def test_source_has_no_bare_unchecked_atomic_write_calls(self):
        import inspect
        import re

        source = inspect.getsource(mfdb_core)
        # A bare call is a line containing "bejson_core_atomic_write(" that
        # is NOT inside the definitions of the checked helpers themselves
        # (those legitimately call it once, checked, right there) and is
        # not the import line.
        bare_call_pattern = re.compile(r"^\s*bejson_core_atomic_write\(", re.MULTILINE)
        offending_lines = [
            i + 1 for i, line in enumerate(source.splitlines())
            if bare_call_pattern.match(line)
        ]
        assert offending_lines == [], (
            f"Found bare, unchecked bejson_core_atomic_write() call(s) at "
            f"line(s) {offending_lines} -- route through _write_entity_doc, "
            f"_write_manifest_doc, or _write_checked instead (see audit "
            f"finding #2)."
        )
