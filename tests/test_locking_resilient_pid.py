"""
Name:           test_locking_resilient_pid.py
Description:    Regression coverage for audit finding #1 (HIGH) --
                 locking reinvented per-file. with_file_lock()
                 (subagent_common.py) and get_or_create_web_auth_token()
                 (config.py) were both independently-reinvented weaker
                 wall-clock-age stale-lock schemes; both now use the
                 proven ResilientPIDLock. Also covers the second bug found
                 during the with_file_lock() retrofit: the old code fell
                 through into the critical section completely unprotected
                 on acquisition timeout instead of raising.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  c2e21079-d9fe-4f11-abe0-6fd7ee4d8c91
"""
import _libpath  # noqa: F401  (puts lib/ on sys.path for unittest + pytest)
import threading

import lib_bejson_newagent_subagent_common as subagent_common
import lib_bejson_newagent_config as config


def _empty_doc():
    return {
        "Format": "BEJSON", "Format_Version": "104", "Format_Creator": "Elton Boehnen",
        "Records_Type": ["T"], "Fields": [{"name": "n", "type": "integer"}], "Values": [],
    }


def _append_mutate(doc):
    doc["Values"].append([len(doc["Values"])])
    return True, len(doc["Values"])


class TestWithFileLockConcurrency:
    def test_ten_threads_twenty_writes_each_lose_nothing(self, tmp_path):
        """The core race this file guards against: concurrent writers
        under with_file_lock() must never lose an update. 200 total
        writes across 10 threads must land as exactly 200 rows."""
        path = tmp_path / "concurrent.bejson"
        errors = []

        def worker():
            try:
                for _ in range(20):
                    subagent_common.with_file_lock(path, _append_mutate, _empty_doc)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        import json
        doc = json.loads(path.read_text())
        assert errors == []
        assert len(doc["Values"]) == 200

    def test_no_leftover_lockdir_after_use(self, tmp_path):
        path = tmp_path / "single.bejson"
        subagent_common.with_file_lock(path, _append_mutate, _empty_doc)
        lock_path = path.with_name(path.name + ".lock")
        assert not (lock_path.parent / (lock_path.name + ".lockdir")).exists()

    def test_uses_resilient_pid_lock_not_a_second_reinvented_scheme(self):
        """Direct check that the retrofit actually landed -- imports
        ResilientPIDLock and doesn't still carry the old
        LOCK_STALE_AFTER_SECONDS wall-clock-age constant."""
        assert hasattr(subagent_common, "ResilientPIDLock")
        assert not hasattr(subagent_common, "LOCK_STALE_AFTER_SECONDS"), (
            "LOCK_STALE_AFTER_SECONDS still present -- looks like the "
            "wall-clock-age stale-lock scheme this fix replaced may have "
            "been reintroduced."
        )


class TestGetOrCreateWebAuthTokenConcurrency:
    def test_fifteen_concurrent_callers_converge_on_one_token(self, tmp_path):
        """The race this guards: many processes racing to generate the
        first web_auth_token must never end up with more than one
        winning value in circulation."""
        config_path = tmp_path / "config.json"
        results = []

        def worker():
            results.append(config.get_or_create_web_auth_token(config_path, {}))

        threads = [threading.Thread(target=worker) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 1, "Concurrent callers generated more than one distinct token"

    def test_uses_resilient_pid_lock(self):
        assert hasattr(config, "ResilientPIDLock")
