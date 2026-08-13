"""
Library:        lib_bejson_newagent_engine_rest.py
Family:         NewAgent
Description:    REST API prompter with rotating key and cooldown registry.
                Key/model/cooldown registries routed through the canonical
                Core BEJSON library (atomic write + validation + field-map
                access) instead of hand-rolled json.load/dump.
Version:        1.15.0
Date:           2026-08-05
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  9aac21e8-2785-404b-9ea4-75aa16d3970c
"""

import json
import logging
import time
import subprocess
import urllib.error
import urllib.request
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

VERSION = "1.15.0"
logger = logging.getLogger(__name__)

COOLDOWN_429 = 60
COOLDOWN_AUTH = 86400
COOLDOWN_TRANSIENT = 15  # server-side 500/502/503/504 -- brief, not key-specific, resolves fast usually
NETWORK_ERROR_RETRY_DELAY = 2  # seconds -- brief pause before retrying after a DNS/timeout/connectivity failure

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
        if not self.keys:
            return None
        for _ in range(len(self.keys)):
            key = self.keys[self._index % len(self.keys)]
            self._index = (self._index + 1) % len(self.keys)
            if self._is_available(key):
                return key
        best = min(self.keys, key=lambda k: self._cooldowns.get(k, 0.0))
        self._index = (self.keys.index(best) + 1) % len(self.keys)
        return best

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
                    raise RuntimeError(f"No API keys available for provider '{provider}'.")

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
                    time.sleep(NETWORK_ERROR_RETRY_DELAY)

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
    """
    env_file_path = Path(env_file_path)
    if not env_file_path.exists():
        logger.warning("[Engine_REST] env_file not found at %s — skipping key sync", env_file_path)
        return 0

    env_doc = bejson_core_load_file(str(env_file_path))
    if not isinstance(env_doc, dict):
        logger.warning("[Engine_REST] Could not load env_file at %s — skipping key sync", env_file_path)
        return 0
    result = validate_bejson(env_doc, is_file=False)
    if not result.valid:
        logger.warning(
            "[Engine_REST] env_file %s failed structural validation: %s — skipping key sync",
            env_file_path, result.errors,
        )
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
    deactivated = 0
    reactivated = 0
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

    known_profiles = {row[1]: row[6] for row in DEFAULT_MODEL_CATALOG}
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
