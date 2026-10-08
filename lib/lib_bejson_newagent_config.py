"""
Library:        lib_bejson_newagent_config.py
Family:         NewAgent
Description:    BEJSON 104a configuration initialization, loading, and saving.
                Routes reads/writes through the canonical Core BEJSON library
                (lib_bejson_Core_bejson_core) for atomic writes and structural
                validation instead of hand-rolled json.load/dump.
Version:        1.16.0
Date:           2026-09-18
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  e86387d8-9ec0-4c72-a2e0-de4b516902b3

CHANGELOG:
- 1.16.0 (2026-09-18): Remediation pass, audit finding #1 (HIGH --
  locking reinvented per-file). get_or_create_web_auth_token() was a
  second, independently-reinvented instance of the same weaker
  wall-clock-age stale-lock reclaim scheme the audit flagged in
  subagent_common.py's with_file_lock() -- both built this session,
  neither using the proven PID-liveness-checked ResilientPIDLock already
  correct elsewhere in the codebase. Same real risk: a legitimately slow
  holder had its lock stolen by another still-alive process. Lock
  acquisition now goes through ResilientPIDLock; this function's own
  intentional design -- fall back to whatever token is on disk if the
  lock can't be acquired within lock_timeout, rather than hang or raise
  -- is unchanged and preserved. lock_stale_after kept as a parameter for
  call-site compatibility but is now unused (liveness, not age, decides
  reclaim). Verified: 15 concurrent callers racing
  get_or_create_web_auth_token() on a fresh config -> exactly 1 unique
  token generated and returned to all 15; py_compile clean.
- 1.15.0 (2026-09-12): Added "subagents_enabled" (default False) to
  DEFAULT_CONFIG -- the master on/off gate for the new sub-agent library
  family (lib_bejson_newagent_subagent_*.py). Defaults off since it's a
  brand-new/experimental system; lib_bejson_newagent_subagent_runtime.py
  checks this before doing anything, per-call, rather than once at
  startup, so flipping it in config.json takes effect on the very next
  dispatch/resume without a restart.
- 1.14.0 (2026-09-11): Audit remediation (Part 1 §3, "Token Generation
  Race"). Added get_or_create_web_auth_token() -- a lock-file-protected
  (os.O_CREAT|os.O_EXCL) read-generate-write-reread helper so webagent.py
  and JobMaker.py booting at the same moment on a fresh config.json can
  no longer each generate and save a competing web_auth_token, with the
  loser silently left holding a token that no longer matches what's on
  disk. Both call sites migrated to call this instead of their own
  inline "if not token: generate + save" logic. Also closed two deeper
  races this fix's own concurrency testing (10-thread stress test)
  turned up, both in init_config() itself: (1) its "file doesn't exist"
  creation branch was an unconditional atomic_write() -- a slower
  process's write could land AFTER a faster process had already
  generated+saved a real token, reverting the file to blank; changed to
  an os.O_CREAT|os.O_EXCL exclusive claim so only one process performs
  the actual first-content write. (2) A caller whose exists() check
  landed just after that claim (empty stub present, real content not
  yet written) fell straight into the plain "load existing file" path
  with zero protection, reading a torn/empty file and treating it as
  "corrupt, fall back to defaults" -- the actual root cause of most of
  the observed failures, confirmed via traced repro (raw.Fields=None on
  a 0-byte read). That read now retries briefly (up to ~1s) on an
  unparseable/incomplete result before giving up. Also fixed
  get_or_create_web_auth_token()'s stale-lock reclaim, which compared
  time.monotonic() (arbitrary/boot-relative epoch) against
  st_mtime (wall-clock epoch) -- always a huge negative number, so an
  abandoned lock from a crashed process could never actually be
  reclaimed; now uses time.time() to match st_mtime's clock. Verified
  with a 20-run x 10-thread concurrency stress test (0 duplicate tokens
  across 200 threads, down from a failure roughly half the time before
  these two additional fixes) plus a sequential round-trip check and
  the existing malformed-JSON-doesn't-crash regression test. No schema
  change -- DEFAULT_CONFIG's web_auth_token field and its description
  are unchanged.
- 1.13.0 (2026-08-19): "any" is not a valid BEJSON type -- fixed properly
  per Elton's explicit instruction ("treat it like a string if you're
  going to do that") after lib_bejson_Core_bejson_validator.py 2.1.0
  started correctly rejecting it (it previously passed structural
  validation silently). _CONFIG_FIELDS' setting_value changed from "any"
  to "string". Added _stringify_config_value()/_coerce_config_value() as a
  serialize/deserialize pair: every value gets stringified for the file
  (bool -> "true"/"false", list/dict -> JSON-encoded, everything else via
  str()), and coerced back to its real Python type on load using the
  active schema's declared default as the type oracle -- so every other
  file in the app that does config.get("some_bool_setting") keeps getting
  a real bool/int/float/list exactly as before; nothing else needed to
  change. Handles all 4 non-string default value shapes actually present
  in DEFAULT_CONFIG/CLI_DEFAULT_CONFIG: bool, int, float, and one list
  (exec_denylist). Backward compatible: an old file with real JSON bool/
  int/float/list values (or a "string"-non-matching declared type) is
  detected as stale and gets a ONE-TIME on-disk migration -- Fields and
  every row rewritten in the corrected string-typed form -- not just
  patched in memory, since the earlier draft of this fix (before this
  version) would have silently left a stale on-disk file permanently
  invalid even though it loaded fine. make_bejson_structure() and
  save_config() both stringify on write. Verified extensively: fresh
  create is valid BEJSON with all real types in memory (incl. float/list);
  reload round-trips identically; changing a value via save_config and
  reloading preserves the real type and produces a still-valid file;
  simulated backward-compat load of an old-style file with genuine JSON
  bool/int/float/list values under the old declared type; and the actual
  scenario -- ran this against Elton's own real shipped config/config.json
  (was invalid, "type": "any", real bool/float/list values under it) and
  confirmed it now self-heals to valid=True on disk with descriptions
  preserved, not just in the in-memory dict.
- 1.12.0 (2026-08-19): Audit remediation. model_rest/model_interactions
  defaults corrected from stale gemini-2.5-flash to gemini-3.6-flash after
  verifying (grepped every .py file for both string literals) that neither
  is actually read anywhere at runtime -- the real active model comes
  exclusively from config/models.bejson via ModelRegistry. Fields kept
  (not removed -- that's a bigger schema decision than "fix the value"),
  descriptions updated to say so explicitly, full writeup in
  docs/dead_code.md. Verified against an external audit report's finding
  that these two values were stale/inconsistent with models.bejson -- true
  as stated, but the audit's implied risk ("system may attempt to use the
  older model") doesn't hold since nothing reads these fields at all.
- 1.11.0 (2026-08-16): Added env_secure_file_path and env_paths_file_path
  (appended to end of DEFAULT_CONFIG -- BEJSON positional integrity, no
  reordering). These are now the primary env sources; the pre-existing
  env_file_path field is kept unchanged and its description updated to
  reflect its new role as legacy fallback only, used when neither new file
  exists on disk. See lib_bejson_newagent_env.py for the resolution logic.
  Backfills into existing config.json via init_config's existing backfill
  path, same as every prior config addition.
- 1.10.0 (2026-08-09): Added auto_amnesia_memory_retrieval (default True)
  for the renamed /amnesia + /rebirth commands -- toggles whether
  /amnesia's compressed recap is fed straight back into history
  ("rebirth") or left on disk until /rebirth is run manually. Auto-
  backfills into existing config.json files via init_config's existing
  backfill path; picked up automatically by the webagent Config tab
  (renders as a checkbox since the default value is a bool).
- 1.9.1 (2026-08-07): Added network_error_auto_retry (default True) and
  network_error_retry_backoff_seconds (default 3.0) config defaults for
  agent.py's network-error auto-resend fix.
"""

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any
import json

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_index,
    ResilientPIDLock,
)
from lib_bejson_Core_bejson_validator import validate_bejson

VERSION = "1.16.0"
logger = logging.getLogger(__name__)

DEFAULT_CONFIG: list[tuple[str, Any, str]] = [
    ("engine_mode", "rest", "Active engine: 'rest' or 'interactions'"),
    ("model_rest", "gemini-3.6-flash", "NOT currently read anywhere at runtime -- see docs/dead_code.md. Kept for reference/future use; the real active model is config/models.bejson via ModelRegistry."),
    ("model_interactions", "gemini-3.6-flash", "NOT currently read anywhere at runtime -- see docs/dead_code.md. Kept for reference/future use; the real active model is config/models.bejson via ModelRegistry."),
    ("key_registry_path", "config/keys.bejson", "API key registry path"),
    ("model_registry_path", "config/models.bejson", "Model registry path"),
    ("key_state_path", "config/key_state.bejson", "Key cooldown state path"),
    ("env_file_path", "/storage/emulated/0/env_file.json", "LEGACY fallback GlobalEnv BEJSON file -- only used when neither env_secure_file_path nor env_paths_file_path exists on disk"),
    ("log_level", "INFO", "Python logging level"),
    ("send_delay_seconds", 2.0, "Delay before each API request (seconds)"),
    ("max_history_turns", 20, "Max conversation turns kept in memory"),
    ("history_panel_rows", 6, "Rows shown in TUI history panel"),
    ("max_actions_per_turn", 10, "Max action tags executed per model response"),
    ("auto_continue_enabled", True, "Auto-feed action results back to model"),
    ("max_autonomy_turns", 20, "Max consecutive autonomous turns (0=unlimited)"),
    ("exec_timeout_seconds", 60, "Max seconds per shell command"),
    ("exec_denylist", ["rm -rf /", "dd if=", "mkfs", ":(){:|:&};:"], "Commands blocked if any of these strings appears anywhere in them (2026-08-25: was 'prefixes blocked before execution' when the check was startswith-only -- audit F-03 found that trivially bypassed by e.g. 'echo hi && rm -rf /'; the check itself lives in lib_bejson_newagent_actions.is_command_denylisted() and is substring-anywhere now, this description is just kept accurate to match)"),
    ("web_auth_token", "", "Shared-secret token webagent.py requires on every request (X-Auth-Token header or ?token= query param). Auto-generated and saved here on first run if empty -- see webagent.py's WebAgentTerminal.__init__ (audit F-02)."),
    ("dryrun_mode", False, "When true: actions shown but not executed"),
    ("confirmation_gate", False, "Pause for Y/n before exec/delete actions"),
    ("input_mode", 0, "0=typed 1=STT 2=dialog+snippets"),
    ("multi_line_mode", False, "Triple-Enter for multi-line typed input"),
    ("live_feed_output", False, "Stream exec stdout/stderr live"),
    ("speak_output_enabled", True, "Print <speak> text to terminal"),
    ("interactions_max_rounds", 10, "Max function-call rounds per Interactions turn"),
    ("native_tools_scope", "all", "Interactions tool scope: 'all' or 'shell_only'"),
    ("resume_mode", "full_history", "Resume strategy: 'full_history' or 'fresh_replay'"),
    ("gen_temperature", 0.7, "Baseline generationConfig.temperature (legacy-profile models only)"),
    ("gen_top_p", 0.95, "Baseline generationConfig.topP (legacy-profile models only)"),
    ("gen_top_k", 40, "Baseline generationConfig.topK (legacy-profile models only)"),
    ("gen_candidate_count", 1, "Baseline generationConfig.candidateCount (legacy-profile models only)"),
    ("gen_thinking_budget", -1, "Baseline thinkingConfig.thinkingBudget (legacy-profile models; -1 = dynamic)"),
    ("gen_thinking_level", "high", "Baseline thinkingConfig.thinkingLevel (v3-profile models: 'low'/'high')"),
    ("debug_mode", True, "When true: write raw REST API request/response pairs to logs/raw_api_debug_*.json and logs/raw_api_error_*.json (rotated, last 5 kept). Defaults True: this being off is why the HTTP 400 issue went undiagnosed through two prior fix attempts."),
    ("health_check_on_startup", True, "When true: fire one minimal REST API call at startup so a bad key/model surfaces immediately instead of mid-conversation"),
    ("network_error_auto_retry", True, "When true: a NETWORK ERROR (dropped connection, no route) auto-resends the same turn instead of waiting for the user to manually retype it"),
    ("network_error_retry_backoff_seconds", 3.0, "Delay before an auto-resend triggered by network_error_auto_retry"),
    ("auto_amnesia_memory_retrieval", True, "When true, /amnesia (agent.py) or the webagent Amnesia button immediately re-feeds the compressed recap back into history ('rebirth') as soon as it wipes memory. When false, /amnesia wipes to a true blank slate and the recap waits on disk until /rebirth is run manually."),
    ("subagents_enabled", False, "Master switch for the sub-agent system (lib_bejson_newagent_subagent_*.py). When false (the default -- new/experimental feature), dispatch_subagent()/run_subagent_turn()/resume_subagent() all refuse immediately with status='disabled' and create/mutate nothing on disk; existing subagent session/signal/profile files are left untouched either way. Flip to true to allow the main agent (or any tool built on top of it) to actually dispatch sub-agent sessions."),
    ("env_secure_file_path", "/storage/emulated/0/.env/secure/secureenv_file.json", "PRIMARY env source (1 of 2): secure/credential vars (API keys etc). See env_templates/ for the blank schema."),
    ("env_paths_file_path", "/storage/emulated/0/.env/user/paths.json", "PRIMARY env source (2 of 2): non-sensitive vars (paths, IDs, model names). See env_templates/ for the blank schema."),
]

_CONFIG_FIELDS = [
    {"name": "setting_name", "type": "string"},
    {"name": "setting_value", "type": "string"},
    {"name": "description", "type": "string"},
]


def _stringify_config_value(val: Any) -> str:
    """
    BEJSON has no valid "any" type (fixed 2026-08-19 -- see
    lib_bejson_Core_bejson_validator.py 2.1.0's new VALID_FIELD_TYPES
    check, which now correctly rejects it). setting_value is declared
    "string", so every value gets stringified for the file -- including
    exec_denylist, the one list-valued default, via JSON encoding. The
    in-memory config dict init_config() returns still carries the
    correctly-typed Python value (bool/int/float/list/str) -- see
    _coerce_config_value below, which reverses this on load using the
    active schema's declared default as the type oracle, so no other code
    in the app needed to change.
    """
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return str(val)


def _coerce_config_value(raw: Any, default_val: Any) -> Any:
    """
    Reverses _stringify_config_value using default_val's type (from the
    active schema) as the oracle. Backward-compatible with a config.json
    written before this fix, where a row might still hold a real JSON
    bool/int/float/list instead of a string -- in that case raw is already
    the right type and passes through unchanged, so old files self-heal on
    next load rather than needing a migration step. Checked in this order
    deliberately: bool before int, since bool is an int subclass in Python.
    """
    if isinstance(default_val, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() == "true"
    if isinstance(default_val, (list, dict)):
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default_val
    if isinstance(default_val, float):
        if isinstance(raw, float):
            return raw
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default_val
    if isinstance(default_val, int) and not isinstance(default_val, bool):
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default_val
    return raw


def make_bejson_structure(values: list[tuple]) -> dict:
    return bejson_core_create_104a(
        "ScriptConfig",
        list(_CONFIG_FIELDS),
        [[name, _stringify_config_value(val), desc] for name, val, desc in values],
    )


def _validate_or_warn(path: Path, doc: dict) -> None:
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        logger.warning("[Config] %s failed structural validation: %s", path, result.errors)


def init_config(config_path: Path, schema: list[tuple] = None) -> dict:
    """Load (or create) a BEJSON 104a ScriptConfig file at config_path.

    schema defaults to DEFAULT_CONFIG (agent.py/webagent.py's shared
    config.json, unchanged behavior) but any caller can pass its own
    (name, default_value, description) triples to get an independently
    persisted config file with its own defaults/backfill -- e.g. cliagent.py
    passing CLI_DEFAULT_CONFIG to get config/cliagent_config.json instead of
    sharing the TUI's config.json.
    """
    active_schema = schema if schema is not None else DEFAULT_CONFIG
    defaults = {name: val for name, val, _ in active_schema}

    if not config_path.exists():
        # FIX (2026-09-11, audit remediation Part 1 §3 "Token Generation
        # Race", extended): this used to be an unconditional
        # bejson_core_atomic_write() -- fine for a single process, but
        # the audit's actual scenario is TWO processes booting against a
        # SAME, genuinely-not-yet-existing config_path (webagent.py and
        # JobMaker.py on a fresh install). Both would reach this branch,
        # both compute get_or_create_web_auth_token() afterward, and a
        # slower process's unconditional atomic_write() here could land
        # AFTER a faster process had already generated and saved a real
        # token via that lock -- silently reverting the file back to
        # blank defaults and reproducing the exact original bug one
        # layer up.
        #
        # os.O_CREAT|os.O_EXCL makes CLAIMING the path itself exclusive
        # -- only one caller can win -- but note this only closes the
        # race for callers who observe exists()==False in the first
        # place. A caller whose exists() check lands a moment later (as
        # soon as the winner's claim-empty-file appears, before the
        # winner has actually written real content into it) sees
        # exists()==True and falls straight through to the "load
        # existing file" read below -- which is why that read (not just
        # this branch) is the one that needed to become torn-read-
        # tolerant; see the retry loop below. This block only needs to
        # guarantee ONE writer performs the actual first-content write,
        # not that every reader takes this branch.
        try:
            claim_fd = os.open(str(config_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(claim_fd)
        except FileExistsError:
            pass  # someone else is creating it -- fall through to the tolerant read below
        else:
            doc = make_bejson_structure(active_schema)
            if not bejson_core_atomic_write(str(config_path), doc):
                logger.error("[Config] Atomic write failed for %s", config_path)
            return dict(defaults)

    # FIX (2026-09-11, audit remediation Part 1 §3, extended): a plain
    # single bejson_core_load_file() here used to be enough when this was
    # the only reader of a file nothing else could be mid-write on. Once
    # two processes can legitimately be racing to populate the SAME
    # config_path (see above), this is the one read every caller
    # converges on regardless of which branch above they took -- so it's
    # also the one place a caller can land moments after another
    # process's os.O_CREAT|os.O_EXCL claim created an empty stub file but
    # before that process's own bejson_core_atomic_write() has replaced
    # it with real content (an empty/unparseable file, not a missing
    # one -- config_path.exists() is already True by then, so the branch
    # above is skipped entirely and offers no protection here). Retrying
    # briefly on a parse failure -- rather than immediately treating it
    # as "file is corrupt, fall back to defaults" -- is what actually
    # closes the race for every caller, not just the ones who happened
    # to see exists()==False.
    raw = None
    for attempt in range(20):  # ~1s worst case -- atomic_write of a small config is near-instant
        raw = bejson_core_load_file(str(config_path))
        if isinstance(raw, dict) and raw.get("Values") is not None:
            break
        time.sleep(0.05)
    if not isinstance(raw, dict):
        logger.warning("[Config] Could not load %s, falling back to defaults", config_path)
        raw = {}
    else:
        _validate_or_warn(config_path, raw)

    name_idx = bejson_core_get_field_index(raw, "setting_name") if raw.get("Fields") else 0
    value_idx = bejson_core_get_field_index(raw, "setting_value") if raw.get("Fields") else 1
    if name_idx == -1:
        name_idx = 0
    if value_idx == -1:
        value_idx = 1

    rows = raw.get("Values", [])
    cfg = {}
    for row in rows:
        if len(row) > max(name_idx, value_idx):
            name = row[name_idx]
            cfg[name] = _coerce_config_value(row[value_idx], defaults.get(name))

    # One-time migration: an existing file still declaring setting_value as
    # "any" (or any type other than "string") gets its Fields AND every row
    # rewritten in the string-typed form -- otherwise the load-time
    # coercion above only fixes the value in memory, and the invalid type
    # declaration (plus raw bool/int/float/list values under a "string"
    # field) would sit on disk forever, un-migrated, the next validate_bejson
    # call still reporting it invalid. 2026-08-19: "any" isn't a valid
    # BEJSON type (lib_bejson_Core_bejson_validator.py 2.1.0 now correctly
    # rejects it); this closes the gap for every config.json/cliagent_
    # config.json that predates that fix.
    schema_stale = raw.get("Fields") != _CONFIG_FIELDS
    if schema_stale:
        desc_map = {name: desc for name, _, desc in active_schema}
        rows = [[row[name_idx], _stringify_config_value(cfg.get(row[name_idx])), desc_map.get(row[name_idx], "")]
                for row in rows if len(row) > max(name_idx, value_idx)]

    # Backfill newly added keys
    changed = schema_stale
    for name, val, desc in active_schema:
        if name not in cfg:
            cfg[name] = val
            rows.append([name, _stringify_config_value(val), desc])
            changed = True

    if changed:
        raw["Fields"] = list(_CONFIG_FIELDS)
        raw["Values"] = rows
        raw.setdefault("Format", "BEJSON")
        raw.setdefault("Format_Version", "104a")
        raw.setdefault("Format_Creator", "Elton Boehnen")
        raw.setdefault("Records_Type", ["ScriptConfig"])
        raw.setdefault("Fields", list(_CONFIG_FIELDS))
        if not bejson_core_atomic_write(str(config_path), raw):
            logger.error("[Config] Atomic write failed for %s", config_path)

    return {**defaults, **cfg}


def get_or_create_web_auth_token(
    config_path: Path,
    config: dict,
    schema: list[tuple] = None,
    *,
    lock_timeout: float = 10.0,
    lock_stale_after: float = 30.0,
) -> str:
    """Atomically ensure config["web_auth_token"] is set and persisted to
    config_path, resolving the boot-time race (audit remediation Part 1
    §3, "Token Generation Race"): webagent.py and JobMaker.py both read
    the same shared config.json and, on a fresh install, would each
    independently generate their own secrets.token_urlsafe(24) and save
    it if launched at (or near) the same moment. Whichever process's
    bejson_core_atomic_write() landed last used to silently win on disk;
    the other process kept running in memory with the token it generated
    itself, which no longer matched the file, and rejected every request
    with that token forever until restarted.

    Fix: a plain lock FILE created with os.O_CREAT|os.O_EXCL, which the
    OS guarantees only one process can succeed at creating. The loser
    polls until the winner deletes it, then re-reads config.json from
    disk rather than trusting its own in-memory copy -- the winner's
    write is the one that's actually real. A process that still can't
    acquire the lock within lock_timeout falls back to whatever token is
    on disk (generating one itself unlocked only as an absolute last
    resort, rather than hanging indefinitely).

    Lock acquisition itself (Remediation pkg, audit finding #1) is
    ResilientPIDLock -- this file's own reclaim logic was a second,
    independently-reinvented instance of the same weaker wall-clock-age
    stale-lock scheme the audit flagged in subagent_common.py's
    with_file_lock(). Same real risk either place: a legitimately slow
    holder (a large write on a loaded phone) taking longer than
    lock_stale_after had its lock stolen by another process that was
    still alive and running -- a genuine concurrent-write race.
    ResilientPIDLock checks os.kill(pid, 0) before reclaiming, so a lock
    is only ever taken from a holder that's actually dead. lock_stale_after
    is no longer used (kept as a parameter for call-site compatibility)
    now that liveness, not age, decides reclaim.
    """
    existing = (config or {}).get("web_auth_token") or ""
    if existing:
        return existing

    lock_path = config_path.with_name(config_path.name + ".weblock")
    lock = ResilientPIDLock(str(lock_path), timeout_seconds=int(lock_timeout))
    lock_acquired = lock.acquire()  # if this times out, fall through to the disk-fallback path below (see docstring)

    try:
        # Double-checked against disk: another process may have written
        # the real token while we were waiting on the lock (or we never
        # got the lock at all -- see the deadline fallback below).
        fresh = init_config(config_path, schema=schema)
        token = fresh.get("web_auth_token") or ""
        if token:
            config["web_auth_token"] = token
            return token

        token = secrets.token_urlsafe(24)
        config["web_auth_token"] = token
        save_config(config_path, config, schema=schema)
        return token
    finally:
        if lock_acquired:
            lock.release()


def save_config(config_path: Path, cfg: dict, schema: list[tuple] = None) -> None:
    active_schema = schema if schema is not None else DEFAULT_CONFIG
    desc_map = {name: desc for name, _, desc in active_schema}
    values = [[k, _stringify_config_value(v), desc_map.get(k, "")] for k, v in cfg.items()]
    doc = bejson_core_create_104a("ScriptConfig", list(_CONFIG_FIELDS), values)
    if not bejson_core_atomic_write(str(config_path), doc):
        logger.error("[Config] Atomic write failed for %s", config_path)
