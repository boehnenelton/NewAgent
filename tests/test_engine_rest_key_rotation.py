"""
Name:           test_engine_rest_key_rotation.py
Description:    Regression coverage for the CRITICAL fix in
                 lib_bejson_newagent_engine_rest.py 1.17.0 -- KeyRegistry.
                 next_key() firing a doomed request with zero delay
                 whenever every key was simultaneously on cooldown (the
                 root cause of Elton's reported "keys shooting out like a
                 thousand a second" rate-limit storm). Without this suite,
                 a future edit to next_key() or set_cooldown() could
                 silently reintroduce the exact bug this remediation
                 package closed -- audit finding #8 (no regression suite)
                 named this risk directly: "all this session's stress
                 tests were ad hoc and discarded."
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  2f6c544a-f696-4b24-a53c-50db4234c0d2
"""
import _libpath  # noqa: F401  (puts lib/ on sys.path for unittest + pytest)
import time
from pathlib import Path

import pytest

import lib_bejson_newagent_engine_rest as engine_rest
from lib_bejson_Core_bejson_core import bejson_core_create_104a


def make_registry(tmp_path: Path, key_labels: list, cooldowns: dict) -> engine_rest.KeyRegistry:
    """Builds a real KeyRegistry against real temp files (matching actual
    __init__(keys_path, state_path) usage exactly rather than mocking
    internals), then seeds specific cooldown states directly so each
    test controls timing precisely."""
    keys_path = tmp_path / "keys.bejson"
    state_path = tmp_path / "key_state.bejson"
    doc = bejson_core_create_104a(
        "APIKey", list(engine_rest._KEY_FIELDS),
        [[label, label, True] for label in key_labels],
    )
    from lib_bejson_Core_bejson_core import bejson_core_atomic_write
    assert bejson_core_atomic_write(str(keys_path), doc)

    reg = engine_rest.KeyRegistry(keys_path, state_path)
    for key, until in cooldowns.items():
        reg._cooldowns[key] = until
    return reg


class TestNextKeyAllCoolingDown:
    def test_waits_for_soonest_key_then_returns_it(self, tmp_path):
        """Core regression: when every key is on cooldown but the
        soonest expires soon, next_key() must WAIT for it (not return a
        still-doomed key immediately) and then return it once ready."""
        now = time.time()
        reg = make_registry(tmp_path, ["kA", "kB", "kC"], {"kA": now + 0.3, "kB": now + 5, "kC": now + 10})
        t0 = time.time()
        key = reg.next_key()
        elapsed = time.time() - t0
        assert key == "kA"
        assert 0.2 <= elapsed <= 1.5, (
            f"next_key() returned in {elapsed:.2f}s -- should have waited "
            f"~0.3s for kA's cooldown instead of firing immediately"
        )

    def test_never_returns_a_still_cooling_key(self, tmp_path):
        """The bug, stated as directly as possible: next_key() must
        never hand back a key whose cooldown has not actually elapsed."""
        now = time.time()
        reg = make_registry(tmp_path, ["kA"], {"kA": now + 0.2})
        key = reg.next_key()
        assert key is None or time.time() >= reg._cooldowns[key]

    def test_beyond_wait_cap_returns_none_promptly(self, tmp_path):
        """If the soonest key is still far off, next_key() must give up
        and return None quickly rather than blocking for the full
        remaining cooldown (which could be up to COOLDOWN_AUTH=86400s)."""
        reg = make_registry(tmp_path, ["kA"], {"kA": time.time() + 999})
        t0 = time.time()
        key = reg.next_key()
        elapsed = time.time() - t0
        assert key is None
        assert elapsed < 2.0, f"next_key() blocked for {elapsed:.2f}s instead of giving up promptly"


class TestNextKeyHealthyPath:
    def test_immediately_available_key_has_zero_wait(self, tmp_path):
        """Normal, healthy operation must be completely unaffected by
        the cooldown-wait logic -- no regression in the common case."""
        now = time.time()
        reg = make_registry(tmp_path, ["kA", "kB"], {"kA": now + 999, "kB": 0.0})
        t0 = time.time()
        key = reg.next_key()
        elapsed = time.time() - t0
        assert key == "kB"
        assert elapsed < 0.2

    def test_round_robins_across_multiple_available_keys(self, tmp_path):
        reg = make_registry(tmp_path, ["kA", "kB", "kC"], {})
        seen = {reg.next_key() for _ in range(3)}
        assert seen == {"kA", "kB", "kC"}


class TestSetCooldownDoesNotCascadeFailCount:
    def test_auto_deactivate_threshold_needs_real_consecutive_failures(self, tmp_path):
        """Companion regression to the next_key() fix: with next_key()
        no longer handing back doomed keys for free, a healthy key
        should NOT rack up fail_count from being repeatedly forced
        through an all-keys-cooldown window. This test only exercises
        set_cooldown()'s own counting, confirming it still deactivates a
        GENUINELY repeatedly-failing key (the mechanism itself is fine;
        it was next_key() feeding it bogus repeated failures that was
        the bug)."""
        reg = make_registry(tmp_path, ["kA"], {})
        reg.set_cooldown("kA", engine_rest.COOLDOWN_429)
        reg.set_cooldown("kA", engine_rest.COOLDOWN_429)
        assert "kA" in reg.keys  # 2 failures -- not deactivated yet
        reg.set_cooldown("kA", engine_rest.COOLDOWN_429)
        assert "kA" not in reg.keys  # 3rd consecutive failure -- deactivated, as designed


class TestBackoffDelay:
    def test_backoff_grows_with_attempt_number_and_stays_capped(self):
        """Regression for audit finding #6 (fixed delay -> exponential
        backoff+jitter). Full-jitter means each call is randomized, so
        assert on the CEILING per attempt, not an exact value."""
        for attempt in range(6):
            delay = engine_rest._backoff_delay(attempt, base=2, max_delay=30)
            expected_cap = min(30, 2 * (2 ** attempt))
            assert 0 <= delay <= expected_cap

    def test_backoff_never_exceeds_max_delay_even_at_high_attempt_counts(self):
        delay = engine_rest._backoff_delay(20, base=2, max_delay=30)
        assert 0 <= delay <= 30
