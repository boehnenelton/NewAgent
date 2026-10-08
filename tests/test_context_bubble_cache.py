"""
Name:           test_context_bubble_cache.py
Description:    Regression coverage for audit finding #4 (MEDIUM, the
                 audit's own "highest-value win") -- assemble_bubble() in
                 lib_bejson_newagent_context_bubble.py re-read and
                 re-parsed every static context file from disk on every
                 single turn. _cached_read() now serves unchanged files
                 from an mtime+size-keyed cache.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  82bd8a93-2980-4c1d-ba1c-268fefeeb3ee
"""
import time

import lib_bejson_newagent_context_bubble as context_bubble


class TestCachedRead:
    def test_unchanged_file_is_loaded_only_once(self, tmp_path):
        f = tmp_path / "static.txt"
        f.write_text("hello")
        calls = []

        def loader(p):
            calls.append(1)
            return p.read_text()

        v1 = context_bubble._cached_read(f, loader)
        v2 = context_bubble._cached_read(f, loader)
        v3 = context_bubble._cached_read(f, loader)

        assert len(calls) == 1, "loader was invoked more than once for an unchanged file"
        assert v1 == v2 == v3 == "hello"

    def test_content_change_invalidates_the_cache(self, tmp_path):
        f = tmp_path / "static.txt"
        f.write_text("hello")
        calls = []

        def loader(p):
            calls.append(1)
            return p.read_text()

        context_bubble._cached_read(f, loader)
        time.sleep(0.02)
        f.write_text("hello world")  # size changes -- must invalidate regardless of mtime resolution
        v2 = context_bubble._cached_read(f, loader)

        assert len(calls) == 2, "cache did not invalidate after the file's content actually changed"
        assert v2 == "hello world"

    def test_missing_file_does_not_crash_and_is_not_cached_as_present(self, tmp_path):
        f = tmp_path / "does_not_exist.txt"
        calls = []

        def loader(p):
            calls.append(1)
            if not p.exists():
                raise FileNotFoundError(str(p))
            return p.read_text()

        try:
            context_bubble._cached_read(f, loader)
            assert False, "expected FileNotFoundError to propagate"
        except FileNotFoundError:
            pass
        assert len(calls) == 1

    def test_different_paths_are_cached_independently(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("A")
        f2.write_text("B")
        calls = []

        def loader(p):
            calls.append(p.name)
            return p.read_text()

        assert context_bubble._cached_read(f1, loader) == "A"
        assert context_bubble._cached_read(f2, loader) == "B"
        assert context_bubble._cached_read(f1, loader) == "A"  # still cached
        assert len(calls) == 2  # one load per distinct path, not three
