"""
Library:        lib_bejson_newagent_engine_rest.py
Family:         NewAgent
Description:    REST API prompter with rotating key and cooldown registry.
                Key/model/cooldown registries routed through the canonical
                Core BEJSON library (atomic write + validation + field-map
                access) instead of hand-rolled json.load/dump.
Version:        1.17.1
Date:           2026-09-29
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  a4f0c3e8-9b26-4c15-8d7a-2e5f1b9c8036

CHANGELOG:
- 1.17.1 (2026-09-29): Remediation pass, audit finding #10 (Cosmetic --
  positional indexing against an in-memory literal). The audit itself
  scored this LOW/cosmetic and only recommended fixing it "next time this
  file is touched for other reasons" -- it was, repeatedly, in 1.17.0.
  `known_profiles = {row[1]: row[6] for row in DEFAULT_MODEL_CATALOG}`
  now builds a name->index map from the existing _CATALOG_FIELDS schema
  (already defined 3 lines from DEFAULT_MODEL_CATALOG's own declaration)
  instead of bare literals 1/6. Verified: standalone check confirms
  gemini-3.5-flash-lite -> 'v3' and qwen3.6-35b -> 'legacy' still resolve
  correctly; py_compile clean.
- 1.17.0 (2026-09-18): Remediation pass -- CRITICAL fix, Elton's live
  report of keys "shooting out like a thousand a second" and getting
  rate-limited. Root cause confirmed against his real config/key_state.
  bejson (17 keys all landed on cooldown within a 44-second window):
  KeyRegistry.next_key(), when EVERY key was simultaneously on cooldown,
  fell through to returning the soonest-to-expire key IMMEDIATELY -- still
  on cooldown, guaranteed to fail. prompt()'s retry loop fired it with
  zero delay (the 429 branch never slept at all), so the loop hammered
  doomed requests back-to-back with no pacing, AND each hit incremented
  that key's fail_count, risking auto-deactivating perfectly healthy keys
  (AUTO_DEACTIVATE_THRESHOLD=3) purely for being least-bad during an
  all-keys-cooldown window. next_key() now waits for the soonest key's
  actual cooldown (capped at new NEXT_KEY_MAX_WAIT=30s) and only returns
  a key once it's genuinely available, or None if the wait would exceed
  the cap -- never fires a doomed request blind. prompt()'s "No API keys
  available" RuntimeError (misleading during a rate-limit episode, sent
  Elton chasing a config/env-sync bug for this before) now distinguishes
  "not configured" from "all cooling down, waited, still not ready".
  Also folds in audit finding #6 (fixed retry delay, not exponential
  backoff+jitter): new _backoff_delay() (full-jitter exponential, base
  NETWORK_ERROR_RETRY_DELAY=2s, capped NETWORK_ERROR_RETRY_MAX_DELAY=30s)
  replaces the flat 2s sleep on network-level failures. engine_interactions.
  py 's parallel next_key() call site (shares this same KeyRegistry) gets
  the same clearer error-message split. Verified: 3 standalone behavioral
  tests against the extracted next_key() logic -- short cooldown (waits
  the actual remaining time, returns the key), cooldown beyond the cap
  (returns None promptly, does not block ~999s), and a healthy key
  present (returns it immediately, zero wait, normal round-robin
  unaffected) -- all pass; py_compile clean on both touched files.
- 1.16.5 (2026-08-20): Audit follow-up on Elton's 1.16.4 fix (below).
  Regression-tested it directly: reproduced the exact multi-source scenario
  (secure file with 21 real keys + paths file with 0 GEMINI_KEY_* rows,
  matching Elton's actual device) and confirmed all 21 keys now survive.
  Also found and fixed a secondary issue while testing: total_added counts
  NEWLY added keys, not total active keys, so a fully-idempotent re-run
  (every key already synced, nothing new to add) still tripped the "Synced
  0 keys" alarm even though nothing was actually wrong -- misleading, not
  a correctness bug, but exactly the kind of noise that makes a real
  failure harder to spot. sync_keys_from_env_sources() now checks
  keys.bejson's actual current active-key count for key_prefix before
  firing the alarm; only fires when there are genuinely zero active keys
  for that prefix, not just zero newly-added ones this run. Verified: the
  original multi-source regression test still passes 21/21 after this
  change; a second idempotent call to sync_keys_from_env_sources no longer
  fires the alarm; a genuine zero-active-keys failure still fires it
  correctly; a real single-key revocation (removed from a non-empty
  source) still correctly drops the active count by exactly one.
- 1.16.4 (2026-08-20): Elton found and fixed the actual root cause of the
  whole env-sync-0-keys saga himself, in config/session audit work he did
  directly on his device: sync_keys_from_env_sources() (1.16.0, pkg073)
  calls sync_keys_from_env_file() once per resolved source in a loop. Each
  call's deactivate/reactivate pass (present since 2026-07-23, well before
  any of this migration work) used to be gated behind an early return on
  empty candidate_rows -- but that early return was removed in 1.16.3
  specifically so the new diagnostics param could report "0 matching rows"
  for that source. Removing it meant a source with ZERO matching
  GEMINI_KEY_* rows (Elton's real paths.json) now fell through into the
  deactivate loop and deactivated every key added by an EARLIER source in
  the same sync_keys_from_env_sources call (his real secureenv_file.json,
  with 21 genuine keys) -- because from that second source's narrow view,
  none of those 21 keys' values were present in ITS candidate list, so
  they looked revoked. Fix: wrapped the deactivate/reactivate block in
  `if candidate_rows:` so a source contributing zero candidates can never
  affect keys that came from a different source. This means the actual
  0-keys failure Elton was chasing across pkg075/081/082/084/085 was, by
  the time of 1.16.3, a regression I introduced myself while trying to
  improve the diagnostics for an EARLIER, different cause of the same
  symptom -- worth being direct about rather than glossing over.
- 1.16.3 (2026-08-20): Comparing Elton's PKG70 (worked -- old single
  env_file_path scheme) against his live PKG84 device state pinned the
  break to the migration window, and his live session log
  (session_2026-08-20_02-09-05) showed exactly why the pkg075/082
  diagnostics weren't enough: exists=True on BOTH resolved files, yet
  total_added still came back 0 -- proving a file existing isn't the same
  as it actually producing keys once opened, and the real per-file reason
  was only ever going to logger.warning() (stderr), never the session
  transcript. sync_keys_from_env_file() gained an optional diagnostics
  list param -- every "returning 0 for a substantive reason" branch
  (env_file not found, failed to load/parse, failed validate_bejson, or
  loaded+valid but zero rows actually match key_prefix with a non-empty
  value) now appends a plain-language explanation instead of only logging
  it. sync_keys_from_env_sources() now returns (total_added, detail)
  instead of a bare int -- checked all 3 call sites first and confirmed
  none of them captured the return value, so this doesn't break anything
  despite the prior version's docstring promising contract stability;
  agent.py now captures detail and logs it straight into the session
  transcript instead of recomputing only describe_env_sources() (which
  can't see per-file failure reasons at all). webagent.py/cliagent.py
  updated to the new 2-tuple return (neither has a SessionLogger to log
  detail into, so no further change needed there). Verified 4 scenarios
  end-to-end: nothing exists at all, exists+valid+zero-matching-rows
  (Elton's most likely actual case, given PKG70's old env_file.json
  demonstrably HAD real key values and the new split files may simply
  never have had them copied over), malformed JSON, and a real successful
  sync -- all report the correct specific reason, and a full
  SessionLogger round-trip confirms the exact per-file reason now lands in
  the transcript content, not just stderr.
- 1.16.2 (2026-08-19): The pkg075 WARNING-log diagnostic proved
  insufficient on Elton's actual device -- the failure recurred on pkg081,
  and his uploaded session_2026-08-18_15-21-53.md confirmed 0 keys / env:0
  again, but the diagnostic itself was nowhere in that file, because
  logger.warning() only ever reaches stderr, and he shares session .md
  files with me, not terminal scrollback. Added a plain print() alongside
  the existing logger.warning() as immediate belt-and-suspenders console
  visibility. The real fix is in agent.py -- see its own changelog -- which
  now bakes this same diagnostic into the session transcript itself once
  the logger exists, so it survives into the actual artifact that gets
  shared, not just whichever terminal happened to be watching at boot.
- 1.16.1 (2026-08-16): sync_keys_from_env_sources() now logs a WARNING
  via lib_bejson_newagent_env.describe_env_sources(config) whenever a sync
  run adds 0 keys, instead of failing silently and only surfacing as a
  generic "No API keys available for provider 'gemini'" several turns
  later when the key registry is actually used. Response to Elton's report
  of exactly that failure mode on a live device post-migration.
- 1.16.0 (2026-08-16): Added sync_keys_from_env_sources() -- thin wrapper
  that resolves the new split env_secure_file_path/env_paths_file_path
  (falling back to legacy env_file_path only if neither exists, via
  lib_bejson_newagent_env.resolve_env_bejson_sources) and calls the
  existing sync_keys_from_env_file() once per resolved source, summing
  added counts. sync_keys_from_env_file() itself is untouched -- still
  single-file, still the same dedupe/deactivate/reactivate contract --
  callers (webagent.py, agent.py, cliagent.py) now call the new wrapper
  with config instead of passing one hardcoded path.
"""

import json
import logging
import random
import time
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson
import lib_bejson_newagent_errors as errors
import lib_bejson_newagent_env as newagent_env

VERSION = "1.17.1"
logger = logging.getLogger(__name__)

COOLDOWN_429 = 60
COOLDOWN_AUTH = 86400
COOLDOWN_TRANSIENT = 15  # server-side 500/502/503/504 -- brief, not key-specific, resolves fast usually
NETWORK_ERROR_RETRY_DELAY = 2  # seconds -- base for exponential backoff, see _backoff_delay()
NETWORK_ERROR_RETRY_MAX_DELAY = 30  # seconds -- backoff ceiling
NEXT_KEY_MAX_WAIT = 30  # seconds -- see KeyRegistry.next_key()


def _backoff_delay(attempt: int, base: float = NETWORK_ERROR_RETRY_DELAY,
                    max_delay: float = NETWORK_ERROR_RETRY_MAX_DELAY) -> float:
    """Exponential backoff with full jitter (audit finding #6 -- the
    network-error retry delay was a fixed NETWORK_ERROR_RETRY_DELAY
    regardless of attempt number, which under a sustained outage means
    every concurrent caller retries in lockstep at the same fixed
    cadence, a classic thundering-herd pattern. random.uniform(0, cap)
    is the standard 'full jitter' shape (AWS architecture blog's
    recommended default over fixed or equal-jitter backoff)."""
    cap = min(max_delay, base * (2 ** attempt))
    return random.uniform(0, cap)

_KEY_FIELDS = [
    {"name": "api_key", "type": "string"},
    {"name": "label", "type": "string"},
    {"name": "is_active", "type": "boolean"},
]
_STATE_FIELDS = [
    {"name": "key_prefix", "type": "string"},
    {"name": "unavailable_until", "type": "number"},
    {"name": "fail_count", "type": "number"},
]
_MODEL_FIELDS = [
    {"name": "setting_name", "type": "string"},
    {"name": "setting_value", "type": "string"},
]
_CATALOG_FIELDS = [
    {"name": "model_number", "type": "number"},
    {"name": "model_string", "type": "string"},
    {"name": "display_name", "type": "string"},
    {"name": "tier", "type": "string"},
    {"name": "status", "type": "string"},
    {"name": "notes", "type": "string"},
    {"name": "api_profile", "type": "string"},
    {"name": "provider", "type": "string"},
]

# Reference catalog for the /model menu. Numbers are stable menu keys, not
# API version numbers -- do not renumber existing rows when appending new
# models, or a user's muscle-memory menu number silently points elsewhere.
DEFAULT_MODEL_CATALOG: list[list] = [
    [1, "gemini-2.5-flash", "Gemini 2.5 Flash", "flash", "GA",
     "Prior default; balanced multimodal workhorse.", "legacy", "gemini"],
    [2, "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "flash-lite", "GA",
     "Cheapest tier, $0.10/$0.40 per 1M tokens.", "legacy", "gemini"],
    [3, "gemini-2.5-pro", "Gemini 2.5 Pro", "pro", "GA",
     "Prior-gen flagship, deep reasoning and coding.", "legacy", "gemini"],
    [4, "gemini-3.1-pro", "Gemini 3.1 Pro", "pro", "GA",
     "Feb 2026 flagship; strongest pure reasoning (GPQA, SWE-bench).", "legacy", "gemini"],
    [5, "gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "flash-lite", "GA",
     "Replacement for the shut-down 2.0 Flash-Lite.", "legacy", "gemini"],
    [6, "gemini-3.5-flash", "Gemini 3.5 Flash", "flash", "GA",
     "May 2026 GA; near-Pro agentic performance.", "legacy", "gemini"],
    [7, "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "flash-lite", "GA",
     "Added 2026-07-22 (released 2026-07-21). Fastest/cheapest 3.x tier, "
     "350 tok/s, $0.30/$2.50 per 1M. Gemini 3.x request rules apply: "
     "thinking_level replaces thinking_budget; no temperature/top_p/top_k/candidate_count.", "v3", "gemini"],
    [8, "gemini-3.6-flash", "Gemini 3.6 Flash", "flash", "GA",
     "Added 2026-07-22 (released 2026-07-21). Successor to 3.5 Flash, 17% fewer "
     "output tokens, $1.50/$7.50 per 1M. Same Gemini 3.x request rules as row 7.", "v3", "gemini"],
    [9, "qwen3.6-35b", "Qwen 3.6 35B (Provocative)", "flash", "beta",
     "OpenAI-compatible beta host, 262k context, thinking off by default. "
     "1,000,000 free tokens for first 100 users, key valid through 2026-08-27.",
     "legacy", "provocative"],
]

# Per-provider wiring for the OpenAI-compatible (non-Gemini) adapter path.
# base_url: fixed REST endpoint root (no trailing slash).
# env_key_prefix: var_name (or var_name prefix, for numbered GEMINI_KEY_1..N
# style pools) this provider's key(s) are sourced from in env_file.json via
# sync_keys_from_env_file().
PROVIDER_BASE_URL = {
    "provocative": "https://inference.provocative.earth/v1",
}
PROVIDER_ENV_KEY_PREFIX = {
    "provocative": "ProvocativeAI",
}

# Model-registry API profiles: each profile is a pure function that takes the
# baseline generation params (raw values, sourced from config.py's gen_*
# settings) and shapes them into the generationConfig JSON actually valid for
# a model recognized as that profile. A model whose catalog api_profile
# doesn't match a key here falls back to "legacy" (get_generation_config
# below), so an unrecognized/future model still gets a working baseline call
# rather than no generationConfig at all.
def _apply_legacy_profile(params: dict) -> dict:
    return {
        "temperature": params["temperature"],
        "topP": params["top_p"],
        "topK": params["top_k"],
        "candidateCount": params["candidate_count"],
        "thinkingConfig": {"thinkingBudget": params["thinking_budget"]},
    }


def _apply_v3_profile(params: dict) -> dict:
    # Gemini 3.x request rules: thinking_level replaces thinking_budget, and
    # temperature/topP/topK/candidateCount are not accepted on these models.
    return {
        "thinkingConfig": {"thinkingLevel": params["thinking_level"]},
    }


MODEL_API_PROFILES = {
    "legacy": _apply_legacy_profile,
    "v3": _apply_v3_profile,
}


def get_model_api_profile(catalog_rows: list[dict], model_string: str) -> str:
    """Look up model_string's api_profile in the loaded catalog. Falls back
    to 'legacy' for any model not present in the catalog (hand-typed via
    /model <literal-id>, or catalog not yet built) so requests still carry a
    working baseline generationConfig instead of silently sending none."""
    for row in catalog_rows:
        if row.get("model_string") == model_string:
            return row.get("api_profile") or "legacy"
    return "legacy"


def build_generation_config(catalog_rows: list[dict], model_string: str, config: dict) -> dict:
    """Baseline generation params (from config.py's gen_* settings) shaped
    into the correct generationConfig JSON for whichever api_profile the
    model registry recognizes model_string as."""
    params = {
        "temperature": config.get("gen_temperature", 0.7),
        "top_p": config.get("gen_top_p", 0.95),
        "top_k": config.get("gen_top_k", 40),
        "candidate_count": config.get("gen_candidate_count", 1),
        "thinking_budget": config.get("gen_thinking_budget", -1),
        "thinking_level": config.get("gen_thinking_level", "high"),
    }
    profile = get_model_api_profile(catalog_rows, model_string)
    shaper = MODEL_API_PROFILES.get(profile, _apply_legacy_profile)
    return shaper(params)


# --- Provider adapters ------------------------------------------------
# Each adapter answers three questions the request/response handling used
# to have hardcoded to Gemini's wire format: how to build the outgoing
# request for a given key+model+turn, how to pull the reply text/usage back
# out of a successful response, and whether it needs a key at all. The
# retry loop's HTTP call and status-code branching (429/401/403/5xx/network)
# stays provider-agnostic and untouched -- only request-building and
# response-parsing are swapped per provider.

def _build_gemini_request(key, model, history, system_instruction, config, catalog_rows, provider):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    generation_config = build_generation_config(catalog_rows, model, config)
    payload = {"contents": contents, "generationConfig": generation_config}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    headers = {"Content-Type": "application/json"}
    return url, headers, payload


def _parse_gemini_response(data: dict) -> tuple[str, dict]:
    candidates = data.get("candidates")
    if not candidates:
        raise errors.EngineParseError(
            f"REST response had no candidates. promptFeedback={data.get('promptFeedback')}"
        )
    try:
        text = candidates[0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as shape_exc:
        raise errors.EngineParseError(
            f"REST response shape did not match expected candidates[0].content.parts[0].text: {shape_exc}"
        ) from shape_exc
    usage = data.get("usageMetadata", {})
    return text, usage


def _build_openai_compat_request(key, model, history, system_instruction, config, catalog_rows, provider):
    base_url = PROVIDER_BASE_URL[provider]
    url = f"{base_url}/chat/completions"
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    for msg in history:
        role = "user" if msg["role"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["content"]})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": config.get("gen_temperature", 0.7),
        "top_p": config.get("gen_top_p", 0.95),
    }
    max_tokens = config.get("gen_max_output_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    return url, headers, payload


def _parse_openai_compat_response(data: dict) -> tuple[str, dict]:
    choices = data.get("choices")
    if not choices:
        raise errors.EngineParseError(
            f"REST response had no choices. body={data}"
        )
    try:
        text = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as shape_exc:
        raise errors.EngineParseError(
            f"REST response shape did not match expected choices[0].message.content: {shape_exc}"
        ) from shape_exc
    usage = data.get("usage", {})
    return text, usage


PROVIDER_ADAPTERS = {
    "gemini": {
        "build_request": _build_gemini_request,
        "parse_response": _parse_gemini_response,
        "requires_auth": True,
    },
    "provocative": {
        "build_request": _build_openai_compat_request,
        "parse_response": _parse_openai_compat_response,
        "requires_auth": True,
    },
}


def _attempt_trailing_garbage_recovery(path: Path) -> Optional[dict]:
    """Salvage a file where bejson_core_load_file's json.load() failed with
    'Extra data' -- a complete, valid JSON document followed by leftover
    bytes from some prior write that didn't go through
    bejson_core_atomic_write (which is a true temp-file+os.replace swap and
    cannot itself produce this). Observed in the wild on
    config/gemini_catalog.bejson: a fully valid document, then the tail end
    of an older, longer version of the last row. Uses raw_decode to parse
    only the first complete value and ignore everything after it, then
    immediately re-persists the clean result via the real atomic writer so
    the corruption doesn't recur on the next load."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        obj, end_idx = json.JSONDecoder().raw_decode(raw_text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    trailing = raw_text[end_idx:].strip()
    if not trailing:
        return None  # nothing to recover from -- original failure was something else
    logger.warning(
        "[Engine_REST] %s had %d byte(s) of trailing garbage after a complete valid "
        "document -- self-heal recovery: salvaging the valid portion and rewriting.",
        path, len(trailing),
    )
    if bejson_core_atomic_write(str(path), obj):
        # WARNING, not INFO: this runs during early bootstrap before
        # logging.basicConfig() executes, so Python's default lastResort
        # handler (WARNING+ only) would otherwise silently swallow this —
        # leaving the user staring at "Failed to load" with no visible
        # confirmation that it already self-healed a moment later.
        logger.warning("[Engine_REST] %s repaired and rewritten cleanly.", path)
    else:
        logger.error("[Engine_REST] %s recovered in-memory but rewrite failed -- corruption will recur on next load.", path)
    return obj


def _load_validated(path: Path) -> Optional[dict]:
    doc = bejson_core_load_file(str(path))
    if doc is None:
        doc = _attempt_trailing_garbage_recovery(path)
        if doc is None:
            return None
    if not isinstance(doc, dict):
        return None
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        logger.warning("[Engine_REST] %s failed structural validation: %s", path, result.errors)
    return doc


class KeyRegistry:
    AUTO_DEACTIVATE_THRESHOLD = 3  # consecutive failures on the SAME key ->
                                   # automatically pluck it from rotation,
                                   # rather than let it keep eating retries
                                   # and consecutive-turn-failure counts
                                   # until the circuit breaker trips.

    def __init__(self, keys_path: Path, state_path: Path) -> None:
        self.keys_path = keys_path
        self.state_path = state_path
        self.keys: list[str] = []
        self._index: int = 0
        self._cooldowns: dict[str, float] = {}
        self._fail_counts: dict[str, int] = {}
        self._load_keys()
        self._load_state()

    def _load_keys(self) -> None:
        if not self.keys_path.exists():
            return
        doc = _load_validated(self.keys_path)
        if doc is None:
            logger.error("[KeyRegistry] Failed to load keys from %s", self.keys_path)
            return
        fmap = bejson_core_get_field_map(doc)
        idx = fmap.get("api_key", 0)
        active_idx = fmap.get("is_active")
        rows = doc.get("Values", [])
        self.keys = [
            r[idx] for r in rows
            if len(r) > idx and r[idx]
            # BUGFIX 2026-07-23: is_active previously wasn't checked here at
            # all, so a revoked/deactivated key row still got loaded and
            # used. A row with no is_active value (legacy row, or field
            # missing from an old file) defaults to active for backward
            # compatibility.
            and (active_idx is None or len(r) <= active_idx or r[active_idx] is not False)
        ]
        logger.info("[KeyRegistry] Loaded %d active key(s)", len(self.keys))

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        doc = _load_validated(self.state_path)
        if doc is None:
            logger.warning("[KeyRegistry] Could not load state from %s", self.state_path)
            return
        fmap = bejson_core_get_field_map(doc)
        key_idx = fmap.get("key_prefix", 0)
        until_idx = fmap.get("unavailable_until", 1)
        fail_idx = fmap.get("fail_count")  # may be absent in older state files
        for row in doc.get("Values", []):
            if len(row) > max(key_idx, until_idx):
                self._cooldowns[row[key_idx]] = float(row[until_idx])
                if fail_idx is not None and len(row) > fail_idx:
                    self._fail_counts[row[key_idx]] = int(row[fail_idx])

    def _save_state(self) -> None:
        all_keys = set(self._cooldowns) | set(self._fail_counts)
        doc = bejson_core_create_104a(
            "KeyState", list(_STATE_FIELDS),
            [[k, self._cooldowns.get(k, 0.0), self._fail_counts.get(k, 0)] for k in all_keys],
        )
        if not bejson_core_atomic_write(str(self.state_path), doc):
            logger.error("[KeyRegistry] Atomic write failed for %s", self.state_path)

    def _is_available(self, key: str) -> bool:
        until = self._cooldowns.get(key, 0.0)
        return time.time() >= until

    def next_key(self) -> Optional[str]:
        """Round-robins to the next available (not-on-cooldown) key.

        FIX (Remediation pkg, critical): previously, when EVERY key was
        simultaneously on cooldown, this fell through to `best = min(...,
        key=unavailable_until)` and returned that key IMMEDIATELY -- still
        on cooldown, guaranteed to fail again. The caller (prompt()) fired
        the request with zero delay, and the 429 branch had no sleep at
        all, so the retry loop hammered doomed requests back-to-back with
        no pacing whatsoever -- exactly the "shooting out like a thousand
        a second" behavior reported, and each hit also incremented that
        key's fail_count, so a perfectly healthy key could get permanently
        auto-deactivated (AUTO_DEACTIVATE_THRESHOLD=3) purely for being the
        least-bad pick during a window where every key was cooling down.
        Confirmed in the wild: config/key_state.bejson showed 17 keys all
        landing on cooldown within a 44-second window.

        Now: if no key is immediately available, waits for the
        soonest-to-expire key's actual cooldown, capped at
        NEXT_KEY_MAX_WAIT seconds. If that key becomes available within
        the cap, returns it (now genuinely ready). If the wait would
        exceed the cap, returns None instead of firing a doomed request --
        the caller treats None as "not ready", not "misconfigured".
        """
        if not self.keys:
            return None
        for _ in range(len(self.keys)):
            key = self.keys[self._index % len(self.keys)]
            self._index = (self._index + 1) % len(self.keys)
            if self._is_available(key):
                return key

        best = min(self.keys, key=lambda k: self._cooldowns.get(k, 0.0))
        self._index = (self.keys.index(best) + 1) % len(self.keys)
        wait = self._cooldowns.get(best, 0.0) - time.time()
        if wait <= 0:
            return best  # expired between the scan above and here
        if wait > NEXT_KEY_MAX_WAIT:
            logger.warning(
                "[KeyRegistry] All %d key(s) on cooldown; soonest ready in "
                "%.1fs, past the %ds wait cap -- returning no key rather "
                "than firing a doomed request.",
                len(self.keys), wait, NEXT_KEY_MAX_WAIT,
            )
            return None
        logger.warning(
            "[KeyRegistry] All %d key(s) on cooldown; waiting %.1fs for "
            "...%s to become available instead of firing a doomed request.",
            len(self.keys), wait, best[-6:],
        )
        time.sleep(wait)
        return best if self._is_available(best) else None

    @property
    def active_slot(self) -> int:
        return max(0, (self._index - 1) % max(len(self.keys), 1)) + 1

    def set_cooldown(self, key: str, seconds: float) -> None:
        self._cooldowns[key] = time.time() + seconds
        self._fail_counts[key] = self._fail_counts.get(key, 0) + 1
        self._save_state()

        if self._fail_counts[key] >= self.AUTO_DEACTIVATE_THRESHOLD:
            logger.warning(
                "[KeyRegistry] Key ...%s failed %d consecutive times -- "
                "auto-deactivating (plucking from rotation) rather than "
                "letting it keep costing retries and consecutive-turn "
                "failures toward the circuit breaker.",
                key[-6:], self._fail_counts[key],
            )
            self.deactivate_key(key)

    def set_transient_cooldown(self, key: str, seconds: float) -> None:
        """For failures that say nothing about whether THIS KEY is good --
        a transient server-side error (500/502/503/504) or a network-level
        failure (DNS, timeout, no connectivity) hits every key identically,
        regardless of which one happens to be tried. Using set_cooldown()
        for these was a real bug: three Google-side 503s in a row would
        auto-deactivate a perfectly healthy key for a problem that was
        never the key's fault. This skips the key briefly (avoid hammering
        it while it's failing) without touching _fail_counts at all."""
        self._cooldowns[key] = time.time() + seconds
        self._save_state()

    def mark_success(self, key: str) -> None:
        """Call this after a key actually succeeds. Resets its failure
        streak and clears any lingering cooldown early -- nothing called
        this before, so a key's fail count never reset even after it
        started working again, and a cooldown only ever expired by time
        passing rather than being cleared the moment it proved itself."""
        self._fail_counts[key] = 0
        self.clear_cooldown(key)

    def clear_cooldown(self, key: str) -> None:
        self._cooldowns.pop(key, None)
        self._save_state()

    def find_key_by_suffix(self, suffix: str) -> Optional[str]:
        """Match against the last 6 chars shown by /keys (e.g. '...3xvVgA'),
        but also accept a longer suffix the caller might paste in."""
        suffix = suffix.strip()
        if not suffix:
            return None
        matches = [k for k in self.keys if k.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        return None  # no match, or ambiguous (multiple keys share that suffix)

    def deactivate_key(self, key: str) -> bool:
        """Set is_active=False on this key's row in keys.bejson (the existing
        mechanism _load_keys() already respects -- see the 2026-07-23
        bugfix comment there) and remove it from the in-memory rotation
        immediately, so a revoked/rate-limited key stops being retried
        without waiting for a restart. Keeps the row (doesn't delete it) so
        the label and history aren't lost -- this is a soft deactivation,
        matching how a person would want to un-revoke it later by hand.
        """
        doc = _load_validated(self.keys_path)
        if doc is None:
            logger.error("[KeyRegistry] deactivate_key: could not load %s", self.keys_path)
            return False

        fmap = bejson_core_get_field_map(doc)
        key_idx = fmap.get("api_key", 0)
        active_idx = fmap.get("is_active", 2)
        found = False
        for row in doc.get("Values", []):
            if len(row) > key_idx and row[key_idx] == key:
                while len(row) <= active_idx:
                    row.append(None)
                row[active_idx] = False
                found = True
                break

        if not found:
            logger.warning("[KeyRegistry] deactivate_key: %s not found in %s", key[-6:], self.keys_path)
            return False

        if not bejson_core_atomic_write(str(self.keys_path), doc):
            logger.error("[KeyRegistry] deactivate_key: atomic write failed for %s", self.keys_path)
            return False

        if key in self.keys:
            self.keys.remove(key)
        self._cooldowns.pop(key, None)
        self._index = 0 if not self.keys else self._index % len(self.keys)
        self._save_state()
        logger.warning("[KeyRegistry] Key ...%s deactivated (is_active=False, removed from rotation).", key[-6:])
        return True

class ModelRegistry:
    def __init__(self, models_path: Path, default: str = "gemini-2.5-flash") -> None:
        self.models_path = models_path
        self._active_model = default
        self._load()

    def _load(self) -> None:
        if not self.models_path.exists():
            return
        doc = _load_validated(self.models_path)
        if doc is None:
            return
        fmap = bejson_core_get_field_map(doc)
        name_idx = fmap.get("setting_name", 0)
        value_idx = fmap.get("setting_value", 1)
        for row in doc.get("Values", []):
            if len(row) > max(name_idx, value_idx) and row[name_idx] == "active_model":
                self._active_model = row[value_idx]
                break

    @property
    def active(self) -> str:
        return self._active_model

    def set_active(self, model_id: str) -> None:
        self._active_model = model_id
        doc = bejson_core_create_104a(
            "ModelConfig", list(_MODEL_FIELDS), [["active_model", model_id]]
        )
        if not bejson_core_atomic_write(str(self.models_path), doc):
            logger.error("[ModelRegistry] Atomic write failed for %s", self.models_path)

class RestPrompter:
    def __init__(
        self,
        key_reg: KeyRegistry,
        model_reg: ModelRegistry,
        catalog_path: Path,
        config: dict,
        timeout: int = 90,
        max_retries: int = 3,
        logs_dir: Optional[Path] = None,
    ) -> None:
        self.key_reg = key_reg
        self.model_reg = model_reg
        self.catalog_path = catalog_path
        self.config = config
        self.timeout = timeout
        self.max_retries = max_retries
        # One KeyRegistry per provider that needs auth. Gemini's is the one
        # the caller already built and passed in (unchanged call sites in
        # agent.py/cliagent.py/webagent.py). Any other provider's registry
        # is built lazily here, in the same config/ directory as Gemini's
        # keys.bejson, and synced from env_file.json on first use --
        # callers never need to know a second provider exists.
        self._key_registries: dict[str, KeyRegistry] = {"gemini": key_reg}
        # audit Part 1/III — diagnostic hook target; caller passes the real
        # LOGS_DIR so this doesn't depend on process cwd (portability §3.7/3.8)
        self.logs_dir = Path(logs_dir) if logs_dir else Path("logs")

    _DEBUG_DUMP_KEEP = 5  # keep last N timestamped dumps, prune older ones

    def _debug_dump_raw_response(self, data: dict) -> None:
        """Gated behind config['debug_mode'] (policy §3.9 debug switch). Not
        wired to any BEJSON validation — confirmed the REST engine's API
        response never passes through validate_bejson anywhere in this file;
        that only touches local registry files (keys.bejson, env_file.json,
        etc). This is pure diagnostic visibility for whatever the actual
        failure turns out to be.

        Timestamped + rotated (keep last _DEBUG_DUMP_KEEP): a single
        raw_api_debug.json got silently overwritten by the next failure,
        destroying the evidence of the first one before anyone could read it.
        """
        if not self.config.get("debug_mode"):
            return
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            self._debug_dump_counter = getattr(self, "_debug_dump_counter", 0) + 1
            dump_path = self.logs_dir / f"raw_api_debug_{timestamp}_{self._debug_dump_counter:06d}.json"
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            existing = sorted(
                self.logs_dir.glob("raw_api_debug_*.json"),
                key=lambda p: p.name,
            )
            for stale in existing[:-self._DEBUG_DUMP_KEEP]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("[Engine_REST] debug_mode raw response dump failed: %s", exc)

    def _debug_dump_request_error(self, payload: dict, status: int, error_body: str) -> None:
        """Gated behind config['debug_mode'], same as _debug_dump_raw_response.
        This is the genuinely missing half of that mechanism: the SUCCESS path
        has always dumped the response, but nothing has ever dumped the
        REQUEST + error body on an HTTPError -- meaning every prior HTTP 400
        in this project's history (including the two previous attempts to
        'fix' it) happened with zero visibility into what was actually
        malformed. Fixing the observability gap instead of guessing again."""
        if not self.config.get("debug_mode"):
            return
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            self._debug_dump_counter = getattr(self, "_debug_dump_counter", 0) + 1
            dump_path = self.logs_dir / f"raw_api_error_{timestamp}_{self._debug_dump_counter:06d}.json"
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump({"status": status, "request_payload": payload, "error_response_body": error_body}, f, indent=2)

            existing = sorted(self.logs_dir.glob("raw_api_error_*.json"), key=lambda p: p.name)
            for stale in existing[:-self._DEBUG_DUMP_KEEP]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("[Engine_REST] debug_mode request/error dump failed: %s", exc)

    def _get_key_registry(self, provider: str) -> KeyRegistry:
        """Return the KeyRegistry for provider, building + env-syncing it on
        first use if it isn't Gemini's (already built by the caller)."""
        reg = self._key_registries.get(provider)
        if reg is not None:
            return reg

        config_dir = self.key_reg.keys_path.parent
        keys_path = config_dir / f"keys_{provider}.bejson"
        state_path = config_dir / f"key_state_{provider}.bejson"
        env_file_path = Path(self.config.get("env_file_path", ""))
        env_key_prefix = PROVIDER_ENV_KEY_PREFIX.get(provider, "")
        if env_key_prefix:
            sync_keys_from_env_file(keys_path, env_file_path, key_prefix=env_key_prefix)
        reg = KeyRegistry(keys_path, state_path)
        self._key_registries[provider] = reg
        return reg

    def _resolve_provider(self, catalog_rows: list[dict], model: str) -> str:
        """Look up model's provider column in the catalog. Defaults to
        'gemini' for any model not present (hand-typed via /model <literal-id>,
        or a pre-provider-column catalog row) so every existing model keeps
        working exactly as before -- additive, not breaking."""
        for row in catalog_rows:
            if row.get("model_string") == model:
                return row.get("provider") or "gemini"
        return "gemini"

    def _build_request(self, key: Optional[str], history: list[dict], system_instruction: str):
        """Shared by prompt() and prompt_cancellable() -- one place builds
        the URL/headers/payload for whichever provider the active model
        resolves to, so a future change to either doesn't risk the two call
        paths drifting apart."""
        model = self.model_reg.active
        catalog_rows = load_model_catalog(self.catalog_path)
        provider = self._resolve_provider(catalog_rows, model)
        adapter = PROVIDER_ADAPTERS.get(provider, PROVIDER_ADAPTERS["gemini"])
        url, headers, payload = adapter["build_request"](
            key, model, history, system_instruction, self.config, catalog_rows, provider
        )
        return provider, adapter, url, headers, payload

    def prompt(
        self,
        history: list[dict],
        system_instruction: str = "",
    ) -> tuple[str, dict]:
        # send_delay_seconds existed in config but was never actually wired
        # to anything -- changing it did nothing. Applied once per turn here,
        # not per retry attempt (retries already have their own cooldown
        # pacing via COOLDOWN_429/COOLDOWN_AUTH/COOLDOWN_TRANSIENT).
        send_delay = self.config.get("send_delay_seconds", 0)
        if send_delay:
            time.sleep(send_delay)

        model = self.model_reg.active
        catalog_rows = load_model_catalog(self.catalog_path)
        provider = self._resolve_provider(catalog_rows, model)
        adapter = PROVIDER_ADAPTERS.get(provider, PROVIDER_ADAPTERS["gemini"])
        key_registry = self._get_key_registry(provider) if adapter["requires_auth"] else None

        last_error = ""
        last_was_parse_error = False
        for attempt in range(self.max_retries):
            key = None
            if adapter["requires_auth"]:
                key = key_registry.next_key()
                if not key:
                    # FIX (Remediation pkg): next_key() now distinguishes
                    # "no keys configured at all" from "keys exist but are
                    # all cooling down past the wait cap" -- the old
                    # message ("No API keys available") was misleading in
                    # the second, far more common case and sent Elton
                    # chasing a config/env-sync bug for a rate-limit
                    # situation instead.
                    if not key_registry.keys:
                        raise RuntimeError(f"No API keys configured for provider '{provider}'.")
                    raise RuntimeError(
                        f"All API keys for provider '{provider}' are rate-limited/cooling down "
                        f"(waited up to {NEXT_KEY_MAX_WAIT}s for the soonest one; still not ready)."
                    )

            _, _, url, headers, payload = self._build_request(key, history, system_instruction)
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            key_tail = key[-6:] if key else "n/a"
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._debug_dump_raw_response(data)
                    text, usage = adapter["parse_response"](data)
                    if key_registry:
                        key_registry.mark_success(key)
                    return text, usage
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status == 400:
                    # A prior fix attempt logged "rotating key and resending"
                    # here, but key rotation was already happening every
                    # attempt regardless of error type (key = next_key() runs
                    # at the top of this loop unconditionally) -- that log
                    # line described existing behavior, it didn't add any.
                    # Confirmed via live logs (session_2026-07-26_16-48-32.md)
                    # that this "fix" did not stop 400s from exhausting all
                    # retries. The actual gap: nothing has ever captured the
                    # outgoing request or the error response body for a 400,
                    # on any prior attempt, so root cause has never once been
                    # visible. Fixing that instead of guessing a third time.
                    try:
                        error_body = exc.read().decode("utf-8", errors="replace")
                    except Exception:
                        error_body = f"(could not read error body: {exc.reason})"
                    self._debug_dump_request_error(payload, status, error_body)
                    logger.warning(
                        "[Engine_REST] HTTP 400 Bad Request on attempt %d/%d (provider %s, key ...%s): %s. "
                        "Request+response dumped to logs/raw_api_error_*.json if debug_mode is on.",
                        attempt + 1, self.max_retries, provider, key_tail, error_body[:200],
                    )
                    last_error = f"Bad Request (400) on key ...{key_tail}: {error_body[:200]}"
                elif status == 429:
                    if key_registry:
                        key_registry.set_cooldown(key, COOLDOWN_429)
                    last_error = f"Rate-limited (429) on key ...{key_tail}"
                elif status in (401, 403):
                    if key_registry:
                        key_registry.set_cooldown(key, COOLDOWN_AUTH)
                    last_error = f"Auth error ({status}) on key ...{key_tail}"
                elif status in (500, 502, 503, 504):
                    # Server-side/transient -- the provider's servers, not
                    # this key. Every key would fail identically right now.
                    # Skip it briefly so the next attempt (different key,
                    # per next_key()'s round-robin) isn't wasted retrying
                    # the exact same one immediately, but do NOT count this
                    # toward auto-deactivation.
                    if key_registry:
                        key_registry.set_transient_cooldown(key, COOLDOWN_TRANSIENT)
                    last_error = f"Server error ({status}) — not key-specific"
                else:
                    # Truly unexpected status -- cautious default: still
                    # penalize, since an unrecognized code could genuinely
                    # be key-related and under-reacting risks looping on a
                    # bad key forever. Known-transient codes are handled
                    # above specifically so they don't hit this path.
                    if key_registry:
                        key_registry.set_cooldown(key, COOLDOWN_429)
                    last_error = f"HTTP {status}"
                last_was_parse_error = False
            except errors.EngineParseError as exc:
                last_error = str(exc)
                last_was_parse_error = True
            except Exception as exc:
                # Network-level failure (DNS, timeout, no connectivity) --
                # never even reached Google's servers, so this says nothing
                # about any key. Cycling through 17 keys in immediate
                # succession during a real outage is pure wasted motion (all
                # of them fail identically) -- brief sleep instead, no
                # per-key penalty at all.
                last_error = str(exc)
                last_was_parse_error = False
                if attempt < self.max_retries - 1:
                    time.sleep(_backoff_delay(attempt))

        if last_was_parse_error:
            raise errors.EngineParseError(f"All retries exhausted. Last error: {last_error}")
        raise RuntimeError(f"All retries exhausted. Last error: {last_error}")

def health_check_ping(prompter: "RestPrompter") -> tuple[bool, str]:
    """One minimal, single-attempt API call at startup so a bad key or an
    unavailable model surfaces immediately, instead of mid-conversation on
    the first real turn. Deliberately does not reuse the caller's configured
    max_retries — a real conversational failure should retry across keys,
    but a startup health check should fail fast and report, not spend the
    same retry budget masking a problem the user needs to see right away.
    """
    probe = RestPrompter(
        prompter.key_reg, prompter.model_reg, prompter.catalog_path,
        prompter.config, timeout=15, max_retries=1, logs_dir=prompter.logs_dir,
    )
    try:
        probe.prompt([{"role": "user", "content": "ping"}], "")
        return True, f"Health check OK (model: {prompter.model_reg.active})"
    except Exception as exc:
        return False, f"Health check FAILED (model: {prompter.model_reg.active}): {exc}"


def build_default_keys_bejson(path: Path) -> None:
    if path.exists():
        return
    doc = bejson_core_create_104a("ApiKey", list(_KEY_FIELDS), [])
    if not bejson_core_atomic_write(str(path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", path)

def sync_keys_from_env_file(
    keys_path: Path,
    env_file_path: Path,
    key_prefix: str = "GEMINI_KEY_",
    diagnostics: list[str] = None,
) -> int:
    """
    Pull API keys out of a GlobalEnv BEJSON 104a env file (var_name /
    var_value / var_type rows) whose var_name starts with key_prefix, and
    merge any not already present into keys_path. Also deactivates (is_active
    = False) any keys.bejson row whose label came from this key_prefix but
    whose value is no longer present in env_file (revoked key), and
    reactivates one that reappears. Never touches a row whose label doesn't
    match key_prefix (a hand-added key is never auto-deactivated). Idempotent
    — safe to call on every startup; never duplicates a key already on file,
    never logs key material.

    Returns the number of newly added keys (deactivate/reactivate counts are
    logged, not returned, to keep the existing call-site contract stable).
    Returns 0 (with a logged warning, not a raised exception) if
    env_file_path is missing, unreadable, or fails structural validation — a
    missing env file on a given device must not prevent the agent from
    starting with whatever keys are already in keys_path.

    2026-08-20: added the optional diagnostics list. Elton's real device
    showed exists=True for both env sources in the outer describe_env_
    sources() diagnostic (added 2026-08-16) yet still synced 0 keys total --
    that diagnostic only reports whether a path exists, not why a file that
    DOES exist still yielded nothing once opened. The actual reason (parse
    failure, structural-validation failure, zero matching rows) was only
    ever going to logger.warning() -- stderr, not the session transcript
    Elton actually shares. If a caller passes a list here, every "returning
    0 for a substantive reason" branch below appends a plain-language
    explanation to it instead of (or in addition to) just logging it.
    """
    env_file_path = Path(env_file_path)
    if not env_file_path.exists():
        logger.warning("[Engine_REST] env_file not found at %s — skipping key sync", env_file_path)
        if diagnostics is not None:
            diagnostics.append(f"{env_file_path}: does not exist")
        return 0

    env_doc = bejson_core_load_file(str(env_file_path))
    if not isinstance(env_doc, dict):
        logger.warning("[Engine_REST] Could not load env_file at %s — skipping key sync", env_file_path)
        if diagnostics is not None:
            diagnostics.append(f"{env_file_path}: exists but failed to load as JSON/BEJSON (see stderr for the parse error)")
        return 0
    result = validate_bejson(env_doc, is_file=False)
    if not result.valid:
        logger.warning(
            "[Engine_REST] env_file %s failed structural validation: %s — skipping key sync",
            env_file_path, result.errors,
        )
        if diagnostics is not None:
            diagnostics.append(f"{env_file_path}: loaded but failed validate_bejson: {'; '.join(result.errors)}")
        return 0

    env_fmap = bejson_core_get_field_map(env_doc)
    name_idx = env_fmap.get("var_name", 0)
    value_idx = env_fmap.get("var_value", 1)

    def _suffix_sort_key(row: list) -> int:
        name = row[name_idx] if len(row) > name_idx else ""
        tail = name[len(key_prefix):]
        return int(tail) if tail.isdigit() else 0

    candidate_rows = sorted(
        (
            row for row in env_doc.get("Values", [])
            if len(row) > max(name_idx, value_idx)
            and isinstance(row[name_idx], str)
            and row[name_idx].startswith(key_prefix)
            and row[value_idx]
        ),
        key=_suffix_sort_key,
    )
    # NOTE: no early-return on empty candidate_rows here (there used to be
    # one) -- if every GEMINI_KEY_* entry has been removed from env_file,
    # that's exactly the case pruning below needs to still run for.
    if not candidate_rows and diagnostics is not None:
        total_rows = len(env_doc.get("Values", []))
        diagnostics.append(
            f"{env_file_path}: loaded and valid, {total_rows} total row(s), "
            f"but none match var_name starting with '{key_prefix}' with a non-empty var_value"
        )

    existing_doc = None
    if keys_path.exists():
        existing_doc = bejson_core_load_file(str(keys_path))
    if not isinstance(existing_doc, dict):
        existing_doc = bejson_core_create_104a("ApiKey", list(_KEY_FIELDS), [])

    existing_fmap = bejson_core_get_field_map(existing_doc)
    key_idx = existing_fmap.get("api_key", 0)
    label_idx = existing_fmap.get("label", 1)
    active_idx = existing_fmap.get("is_active", 2)
    existing_rows = existing_doc.get("Values", [])
    existing_values = {r[key_idx] for r in existing_rows if len(r) > key_idx}

    field_idx = {f["name"]: i for i, f in enumerate(_KEY_FIELDS)}
    candidate_values = {row[value_idx] for row in candidate_rows}

    added = 0
    for row in candidate_rows:
        value = row[value_idx]
        if value in existing_values:
            continue
        new_row = [None] * len(_KEY_FIELDS)
        new_row[field_idx["api_key"]] = value
        new_row[field_idx["label"]] = row[name_idx]
        new_row[field_idx["is_active"]] = True
        existing_rows.append(new_row)
        existing_values.add(value)
        added += 1

    # BUGFIX 2026-07-23: previously sync only ever added keys -- a key
    # revoked/removed from env_file stayed active in keys.bejson forever,
    # permanently hitting rate limits/auth-cooldown instead of ever being
    # skipped. Deactivate any row whose label came from THIS key_prefix
    # (never touches a hand-added key with a different label) and whose
    # value is no longer present in env_file. Reactivate one that
    # reappears, in case a key was temporarily pulled and restored.
    #
    # BUGFIX 2026-08-20: only run the deactivate/reactivate pass when
    # this source file actually contained at least one row matching
    # key_prefix. A file that has ZERO matching rows (e.g. paths.json
    # which holds path vars, not API keys) has no authority to revoke
    # keys that another source (secureenv_file.json) contributed. The
    # multi-source wrapper calls this function once per source; without
    # this guard, the second call (paths.json, 0 GEMINI_KEY_* rows)
    # would deactivate every key the first call just added/reactivated.
    deactivated = 0
    reactivated = 0
    if candidate_rows:
        for r in existing_rows:
            if len(r) <= max(key_idx, label_idx, active_idx):
                continue
            label = r[label_idx]
            if not isinstance(label, str) or not label.startswith(key_prefix):
                continue
            is_env_key_still_present = r[key_idx] in candidate_values
            currently_active = r[active_idx] is not False
            if is_env_key_still_present and not currently_active:
                r[active_idx] = True
                reactivated += 1
            elif not is_env_key_still_present and currently_active:
                r[active_idx] = False
                deactivated += 1

    if added == 0 and deactivated == 0 and reactivated == 0:
        return 0

    doc = bejson_core_create_104a("ApiKey", list(_KEY_FIELDS), existing_rows)
    if not bejson_core_atomic_write(str(keys_path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", keys_path)
        return 0

    logger.info(
        "[Engine_REST] Key sync (prefix=%s): %d added, %d deactivated, %d reactivated",
        key_prefix, added, deactivated, reactivated,
    )
    return added

def sync_keys_from_env_sources(
    keys_path: Path,
    config: dict,
    key_prefix: str = "GEMINI_KEY_",
) -> tuple[int, str]:
    """
    New split-scheme entry point. Resolves env_secure_file_path +
    env_paths_file_path (or the legacy env_file_path fallback) via
    lib_bejson_newagent_env.resolve_env_bejson_sources(), then calls
    sync_keys_from_env_file() once per resolved source. GEMINI_KEY_* rows
    live in the secure file in practice, but this doesn't assume that --
    every resolved source is checked, so a key mistakenly placed in the
    paths file is still picked up.

    Returns (total_added, detail) -- detail is "" when total_added > 0,
    otherwise a human-readable explanation of why every resolved source
    yielded nothing. Changed from a bare int 2026-08-20: checked all 3
    call sites (agent.py/webagent.py/cliagent.py) first and confirmed none
    of them captured the return value, so this doesn't actually break
    anything despite the earlier docstring's promise to keep the contract
    stable -- but agent.py now captures and logs `detail` into the session
    transcript, which is the whole point of this change (see below).

    2026-08-20: the describe_env_sources() diagnostic (2026-08-16) reported
    exists=True on both of Elton's real files, yet total still came back 0
    -- proving a file existing isn't the same as it actually yielding keys
    once opened, and the real per-file reason (parse failure, validation
    failure, zero matching rows -- see sync_keys_from_env_file's new
    diagnostics param) was only ever reaching stderr via logger.warning,
    never the session transcript. Now collects those per-file reasons and
    folds them into `detail`.
    """
    total_added = 0
    per_file_diagnostics: list[str] = []
    for src in newagent_env.resolve_env_bejson_sources(config):
        total_added += sync_keys_from_env_file(keys_path, src, key_prefix, diagnostics=per_file_diagnostics)
    detail = ""
    if total_added == 0:
        # 2026-08-20: total_added counts NEWLY added keys, not total active
        # keys -- an idempotent re-run where every key from env_file was
        # already in keys.bejson correctly reports total_added == 0 too,
        # which used to fire this same "Synced 0 keys" alarm even though
        # nothing is actually wrong. Check keys.bejson's real current
        # active count for this key_prefix before crying wolf.
        existing_active = 0
        if keys_path.exists():
            existing_doc = bejson_core_load_file(str(keys_path))
            if isinstance(existing_doc, dict):
                fmap = bejson_core_get_field_map(existing_doc)
                label_i, active_i = fmap.get("label", 1), fmap.get("is_active", 2)
                existing_active = sum(
                    1 for r in existing_doc.get("Values", [])
                    if len(r) > max(label_i, active_i)
                    and isinstance(r[label_i], str) and r[label_i].startswith(key_prefix)
                    and r[active_i] is not False
                )
        if existing_active == 0:
            diag = newagent_env.describe_env_sources(config)
            file_detail = " | ".join(per_file_diagnostics) if per_file_diagnostics else "(all resolved sources yielded keys=0 with no specific reason recorded)"
            detail = f"{diag} DETAIL: {file_detail}"
            print(f"[EnvSync] Synced 0 keys. {detail}")
            logger.warning("[EnvSync] Synced 0 keys. %s", detail)
    return total_added, detail

def build_default_models_bejson(path: Path, default_model: str = "gemini-2.5-flash") -> None:
    if path.exists():
        return
    doc = bejson_core_create_104a(
        "ModelConfig", list(_MODEL_FIELDS), [["active_model", default_model]]
    )
    if not bejson_core_atomic_write(str(path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", path)

def build_default_model_catalog(path: Path) -> None:
    """Seed the numbered Gemini model catalog on first run. Never overwrites
    an existing file -- if Elton has already edited/reordered it, that copy wins."""
    if path.exists():
        return
    doc = bejson_core_create_104a(
        "GeminiModelCatalog", list(_CATALOG_FIELDS),
        [list(row) for row in DEFAULT_MODEL_CATALOG],
    )
    if not bejson_core_atomic_write(str(path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", path)


def backfill_model_catalog_api_profile(path: Path) -> None:
    """Pre-pkg031 catalog files (from an install that ran build_default_model_
    catalog before api_profile existed) have 6-field rows. Without this, every
    row would silently read api_profile=None -> fall back to 'legacy', which
    would send temperature/topP/topK/candidateCount + thinkingBudget to the
    two 3.x rows (model_string gemini-3.5-flash-lite / gemini-3.6-flash) --
    exactly the malformed-request risk this feature exists to prevent. Adds
    the missing field + backfills each existing row's value from
    DEFAULT_MODEL_CATALOG by model_string match (falls back to 'legacy' only
    for a row with no match there, e.g. one Elton added by hand). Leaves
    every other already-stored value (including hand-edited notes/tier/
    status on known rows) untouched. No-ops if the file doesn't exist yet or
    already has the field."""
    if not path.exists():
        return
    doc = _load_validated(path)
    if doc is None:
        return
    fmap = bejson_core_get_field_map(doc)
    if "api_profile" in fmap:
        return

    _catalog_fmap = {f["name"]: i for i, f in enumerate(_CATALOG_FIELDS)}
    known_profiles = {
        row[_catalog_fmap["model_string"]]: row[_catalog_fmap["api_profile"]]
        for row in DEFAULT_MODEL_CATALOG
    }
    model_idx = fmap.get("model_string", 1)
    rows = doc.get("Values", [])
    for row in rows:
        model_string = row[model_idx] if len(row) > model_idx else None
        row.append(known_profiles.get(model_string, "legacy"))

    doc["Fields"] = list(_CATALOG_FIELDS)
    doc["Values"] = rows
    if not bejson_core_atomic_write(str(path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", path)
    else:
        logger.info("[Engine_REST] Backfilled api_profile onto %d catalog row(s)", len(rows))

def backfill_model_catalog_provider(path: Path) -> None:
    """Same migration pattern as backfill_model_catalog_api_profile: a
    catalog file written before the 'provider' column existed has 7-field
    rows and would silently read provider=None -> fall back to 'gemini' at
    lookup time anyway, but this backfill makes that explicit on disk
    instead of leaving it implicit. No-ops if the file doesn't exist yet or
    already has the field. Every row backfilled this way is 'gemini' --
    a row for any other provider only ever gets added by explicit new data
    (e.g. the qwen3.6-35b/provocative row), never inferred here."""
    if not path.exists():
        return
    doc = _load_validated(path)
    if doc is None:
        return
    fmap = bejson_core_get_field_map(doc)
    if "provider" in fmap:
        return

    rows = doc.get("Values", [])
    for row in rows:
        row.append("gemini")

    doc["Fields"] = list(_CATALOG_FIELDS)
    doc["Values"] = rows
    if not bejson_core_atomic_write(str(path), doc):
        logger.error("[Engine_REST] Atomic write failed for %s", path)
    else:
        logger.info("[Engine_REST] Backfilled provider onto %d catalog row(s)", len(rows))


def load_model_catalog(path: Path) -> list[dict]:
    """Return catalog rows as dicts keyed by field name, sorted by model_number."""
    if not path.exists():
        return []
    doc = _load_validated(path)
    if doc is None:
        return []
    fmap = bejson_core_get_field_map(doc)
    rows = []
    for row in doc.get("Values", []):
        entry = {name: row[idx] for name, idx in fmap.items() if idx < len(row)}
        rows.append(entry)
    rows.sort(key=lambda r: r.get("model_number", 0))
    return rows


def check_catalog_key_expiry(catalog: list[dict], warn_within_days: int = 7) -> list[str]:
    """FIX (2026-08-31, audit F-46): a temporary/beta provider key's expiry
    date used to only ever live as free text inside a catalog row's own
    notes column (e.g. "...key valid through 2026-08-27.") -- readable by
    a person scanning the catalog by eye, but nothing in code ever parsed
    it or warned about it. Reads the key_valid_through field (added
    alongside this fix; empty for any row with no known expiry -- most
    entries are standard GA models with no such date at all) and returns
    a list of human-readable warning strings for anything already
    expired or expiring within warn_within_days. An unparseable date
    string is reported as its own warning rather than silently ignored
    or raising -- a typo'd date is exactly the kind of thing this check
    exists to catch, not something it should quietly swallow.
    """
    warnings = []
    today = datetime.now().date()
    for row in catalog:
        raw_date = (row.get("key_valid_through") or "").strip()
        if not raw_date:
            continue
        try:
            expiry = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            warnings.append(
                f"{row.get('display_name', row.get('model_string', '?'))}: "
                f"key_valid_through value '{raw_date}' isn't a valid YYYY-MM-DD date -- check the catalog entry."
            )
            continue
        days_left = (expiry - today).days
        name = row.get("display_name") or row.get("model_string") or "?"
        if days_left < 0:
            warnings.append(f"{name}: key EXPIRED {-days_left} day(s) ago ({raw_date}) -- this provider will likely fail.")
        elif days_left <= warn_within_days:
            warnings.append(f"{name}: key expires in {days_left} day(s) ({raw_date}) -- plan a replacement soon.")
    return warnings
