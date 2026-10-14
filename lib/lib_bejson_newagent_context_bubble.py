"""
Library:        lib_bejson_newagent_context_bubble.py
Family:         NewAgent
Description:    Context Bubble pipeline (pkg015) — replaces the pkg014-removed
                Thought Bubble system with a redesigned, fully-logged version:
                a physical Context_Bubble.md wiped and rebuilt each turn from
                a percentage-budgeted registry (Part 1), keyword-triggered
                injection with cooldowns (Part 2), a persistent knowledge pool
                drip (Part 3), and an optional, toggleable Observer that
                compresses oversized bubbles (Part 4).

                Part 4 deliberately does NOT match the reference plan's
                original design of an AI-suggested "Meta-Patch" that rewrites
                constant_config.bejson autonomously. Per explicit instruction,
                the Observer only compresses bubble content — it never writes
                to its own config, and the persistent policy block is never
                even sent to the compression call, so there's a structural
                guarantee it can't be altered by a summarization mistake, not
                just an instruction asking the model not to touch it.
Version:        1.18.0
Date:           2026-09-18
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  833087a5-4830-4990-b9bf-130f217c4a40

CHANGELOG:
- 1.18.0 (2026-10-13): Audit remediation -- build_env_file_section() masks
  secret values (var_type == 'secret' or KEY/TOKEN/SECRET/PASSWORD names)
  via errors.mask_value so raw API keys no longer enter the context bubble
  or session logs.
- 1.17.0 (2026-09-18): Remediation pass, audit finding #4 ("highest-value
  win" per the audit's own Phase 3 roadmap) -- assemble_bubble() re-read
  and re-parsed every static context file (Context_Bubble policy .md,
  triggers.bejson, constant_config.bejson, knowledge_pool.bejson ~28KB)
  from disk on EVERY turn, even though these change on the order of "the
  user edited one via a slash command", not every turn. Added
  _cached_read(path, loader): an mtime+size-keyed cache -- re-reads only
  when a file's stat() signature actually changes, otherwise returns the
  previously-parsed value with zero disk I/O. Wired into all 5 read
  sites: load_constants(), _read_policy(), scan_triggers(),
  build_knowledge_section(), _lookup_knowledge_entry() (the last two
  share knowledge_path's cache entry, so a kb:// keyword-trigger lookup
  in the same turn as the interval-drip pass gets a free second hit).
  Process-local (module-level dict, not persisted) and thread-safe via a
  lock, appropriate for the single-process-multi-thread pattern the
  sub-agent family already assumes elsewhere in this codebase. Verified:
  standalone test confirms a loader is invoked exactly once across two
  reads of an unchanged file, then again after the file's content (and
  therefore size) actually changes; py_compile clean.
- 1.16.0 (2026-08-20): tools/init/Cli_Init.py renamed to CLI_Init.py (all
  caps CLI, matching the rest of the tools/ naming convention after
  Elton's manual rename pass) -- updated the one reference to it in this
  file's docstring/system-prompt text to match. No functional change.
- 1.15.0 (2026-08-20): Elton fixed constant_config.bejson's "any"-typed
  setting_value the same way as config.json's earlier fix (1.13.0) --
  "any" isn't a valid BEJSON type, and lib_bejson_Core_bejson_validator.py
  2.1.0 now correctly rejects it. _coerce_constant_value() added: parses
  the file's string-typed values back to native int/float/bool for
  load_constants()'s return dict (matching the same serialize-for-file /
  coerce-on-load pattern used in lib_bejson_newagent_config.py), so every
  caller reading a constant (e.g. constants.get("knowledge_drip_interval"))
  keeps getting a real Python type. Verified: load_constants() against
  both a fresh-defaults config dir and the actual shipped
  config/constant_config.bejson both return the correct native type
  (int/float/bool) for all 12 constants; config/constant_config.bejson
  itself confirmed valid BEJSON (setting_value declared "string", matching
  config.json's fix).
- 1.14.0 (2026-08-17): build_cwd_context_section now walks from cwd up to
  the filesystem root collecting every ancestor directory's context.bejson,
  instead of only checking cwd itself -- matches how GEMINI.md/CLAUDE.md/
  AGENTS.md work in Gemini CLI, Antigravity, etc: a file placed at, say,
  /storage/emulated/0/context.bejson now applies in
  /storage/emulated/0/Pictures too, not just the exact directory NewAgent
  is sitting in. Merge order is root-to-leaf; a section name repeated at a
  nearer directory REPLACES the broader one entirely rather than appending
  a duplicate block (nearest-directory-wins, same precedence rule as a
  more specific CSS selector). Writing is unchanged -- CLI_Init.py and the
  context_set action tag still write to exactly one directory's own file;
  only the read side now walks the chain. Verified: a leaf directory two
  levels below a root context.bejson with no file of its own correctly
  inherits both sections; adding a same-named section at the intermediate
  directory correctly overrides just that one section (appears exactly
  once, not twice) while the untouched section still inherits from root;
  budget cap still respected.
- 1.13.0 (2026-08-17): INIT -- Issue 4/5 of Elton's request. Added
  upsert_cwd_context_section(cwd, section, content) -- sets one (section,
  content) row in cwd's context.bejson (creating the file first if needed,
  same schema as init_cwd_context_template), replacing that section's
  content in place if it already exists rather than duplicating a row.
  This is the shared engine behind both tools/NA-Init/CLI_Init.py (a new
  standalone CLI that scaffolds/updates a project's context.bejson from
  outside a running NewAgent session) and the new context_set action tag
  (lib_bejson_newagent_actions.py) the model calls in-session. Same file,
  same schema, both paths converge on one thing -- nothing to reconcile.
  Verified: idempotent re-run updates in place (row count stays constant),
  CLI-written file confirmed to correctly auto-inject via
  build_cwd_context_section, validate_bejson clean.
- 1.12.0 (2026-08-16): Persistent Drip -- Issue 3/5 of Elton's request.
  (1) build_knowledge_section rewritten: it used to replay the exact same
  rows in the exact same order every firing, truncated wherever budget ran
  out, so anything past the cutoff never appeared and everything before it
  was identical forever. Now uses a weight-biased round-robin schedule
  (knowledge_pool.bejson's new "weight" column, 1/2/3, default 2 -- lower
  fires more often) with the fire position derived from turn // interval,
  so no separate persisted rotation-cursor state is needed. A row never
  repeats within one firing even if its weight put multiple copies in the
  schedule. Verified 45:30:15 (~3:2:1, matching the 3/2/1 rep counts for
  weight 1/2/3) firing-frequency ratio under a budget that only fits one
  row per firing, and confirmed three consecutive firings under a tight
  budget are not identical (actual rotation, not just weighting).
  (2) build_keyword_section now dedupes by resolved content -- needed
  because bejson_core_* facts are now reachable via multiple keywords
  ("bejson" fires the whole ordered set; "104"/"104a"/"104db"/"mfdb" also
  each fire their own specific entry standalone), and a message mentioning
  both would otherwise inject the same fact twice.
  (3) config/knowledge_pool.bejson: added the "weight" field (appended,
  BEJSON positional integrity); moved all 8 bejson_core_* rows from the
  always-on "bejson_format" category to "keyword_only" -- Elton's
  complaint was that BEJSON info was "spamming...too often" regardless of
  relevance, and the blanket interval drip had no way to NOT show
  something once it existed. Now it only surfaces when actually asked
  about (currently leaves the blanket pool with 0 eligible rows -- the
  rotation/weight mechanism above is tested and ready for whenever new
  blanket-category content gets added). Enriched bejson_core_1 with a
  minimal example schema for each of 104/104a/104db (Elton's request);
  enriched bejson_core_2 (104) with an explicit spreadsheet analogy
  (Fields = fixed header row, each Values row = one spreadsheet row,
  same column position every row).
  (4) config/triggers.bejson: added "bejson" (fires bejson_core_1..8 in
  priority order: general overview+examples first, then 104, then
  104a/104db, then MFDB's own general-then-detail set, then the tool-tag
  reference last) plus standalone "104"/"104a"/"104db"/"mfdb" keywords for
  asking about one format without saying "bejson" itself. Verified against
  Elton's own worked example ("I say BEJSON 104") end-to-end: matched 9
  trigger rows, general fact (bejson_core_1) confirmed to land before the
  104-specific fact (bejson_core_2) in the assembled text, and
  bejson_core_2 (matched twice -- once via "bejson", once via standalone
  "104") confirmed to appear exactly once in the output (dedup working).
- 1.11.0 (2026-08-16): build_env_file_section now takes env_file_paths
  (list[Path]) instead of a single env_file_path, merging var_name=var_value
  rows from every resolved source (new split env_secure_file_path +
  env_paths_file_path, or the single legacy file as fallback) into one
  budget-capped drip, same cadence/skip/truncation rules as before. Reads
  every source fresh from disk on every firing turn -- same rationale as
  the original single-file design: a stale copy of a rotated key baked into
  the pool would drip a revoked/wrong key back into context indefinitely.
  assemble_bubble()'s env_file_path param renamed to env_file_paths
  (list[str]) to match; both call sites (webagent.py, agent.py) updated to
  pass lib_bejson_newagent_env.resolve_env_bejson_sources(config) instead
  of a single config.get("env_file_path").
- 1.10.0 (2026-08-09): Renamed the manual-flush concept to Amnesia/Rebirth
  per Elton. Added save_amnesia_recap/load_amnesia_recap (persist the
  compressed recap to Context/amnesia_recap.txt so it survives past the
  current process) and seed_history_with_recap (the shared "rebirth" step
  -- wipe history, reseed with just the recap). run_full_session_compression
  itself is unchanged; these are the pieces built on top of it so /amnesia
  and /rebirth can be separate, config-gated steps instead of one
  all-in-one action.
- 1.9.0 (2026-08-09): Added run_full_session_compression() for the new
  manual /compress command (agent.py) and webagent Compress button --
  distinct from run_observer_compression's automatic bubble-only
  compression. This one compresses the whole conversation transcript on
  direct request so the caller can wipe history down to a single dense
  recap turn. Fails open (returns None, does not touch history) on any
  API error or empty result -- the caller is responsible for never
  clearing history unless a real recap string comes back.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson
import lib_bejson_newagent_errors as errors

VERSION = "1.18.0"

# ── mtime-based read cache (Remediation pkg, audit finding #4) ─────────────
_FILE_CACHE_LOCK = threading.Lock()
_FILE_CACHE: dict[str, tuple[float, int, Any]] = {}  # path -> (mtime, size, value)


def _cached_read(path: Path, loader):
    """Returns loader(path), skipping the actual read/parse if `path`'s
    mtime+size are unchanged since the last call for this exact path.

    assemble_bubble() used to re-read and re-parse every static context
    file -- Context_Bubble policy .md, triggers.bejson, constant_config.
    bejson, and knowledge_pool.bejson (~28KB per the audit) -- on EVERY
    turn, paying full disk I/O + BEJSON parse + validation cost even
    though these files change on the order of "the user edited one via a
    slash command", not every turn. mtime+size together (not mtime
    alone) as the staleness key: a filesystem with coarse mtime
    resolution (1s on some Android filesystems) could otherwise miss a
    second write landing in the same tick; both come from one stat()
    call so checking both costs nothing extra.
    """
    key = str(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        with _FILE_CACHE_LOCK:
            _FILE_CACHE.pop(key, None)
        return loader(path)
    sig = (st.st_mtime, st.st_size)
    with _FILE_CACHE_LOCK:
        cached = _FILE_CACHE.get(key)
        if cached is not None and (cached[0], cached[1]) == sig:
            return cached[2]
    value = loader(path)
    with _FILE_CACHE_LOCK:
        _FILE_CACHE[key] = (sig[0], sig[1], value)
    return value

BUBBLE_FILENAME = "Context_Bubble.md"
POLICY_FILENAME = "Persistent_Policy.md"

logger = logging.getLogger(__name__)

_DEFAULT_POLICY_TEXT = (
    "You are NewAgent, a terminal agent for Elton Boehnen. Prefer surgical, "
    "minimal changes. Always test edits before declaring them done. Credit "
    "Elton Boehnen in files you create or modify."
)

_CONSTANT_FIELDS = [
    {"name": "constant_name", "type": "string"},
    {"name": "defined_value", "type": "string"},
    {"name": "default_value", "type": "string"},
    {"name": "description", "type": "string"},
]

_DEFAULT_CONSTANTS: list[tuple[str, str, str]] = [
    ("max_context_tokens", "8000", "Total token budget for the assembled bubble"),
    ("pct_persistent_policy", "0.20", "Share of budget for core directives"),
    ("pct_active_tasks", "0.20", "Share of budget for active-task context, sourced from checklist_*.bejson files in the current directory (checklist_create/check/add/view tools)"),
    ("pct_env_file", "0.05", "Share of budget for the live env_file.json drip (see build_env_file_section)"),
    ("pct_keyword_triggers", "0.30", "Share of budget for keyword-triggered files"),
    ("pct_knowledge_pool", "0.15", "Share of budget for knowledge-pool drips"),
    ("pct_cwd_context", "0.10", "Share of budget for cwd/context.bejson — auto-injected, no opt-in"),
    ("chars_per_token", "4", "Chars-per-token estimate used for all budget math (no real tokenizer call)"),
    ("global_default_cooldown", "300", "Default seconds between keyword trips"),
    ("knowledge_drip_interval", "5", "Turns between knowledge-pool injections"),
    ("observer_refinement_interval", "7", "Turns between Observer compression checks"),
    ("observer_enabled", "false", "Part 4 switch — Observer compression on/off"),
]


def _coerce_constant_value(raw: Any) -> Any:
    """Parse a string-typed BEJSON constant back to its native Python type.

    Handles: integer, float, boolean, null/None.  Unrecognised strings
    pass through unchanged.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw  # already native (legacy data)
    lower = raw.strip().lower()
    if lower in ("true", "false"):
        return lower == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw

# Percentage-category constants a budget view/editor should walk in order.
_PCT_KEYS = [
    "pct_persistent_policy", "pct_active_tasks", "pct_env_file", "pct_keyword_triggers",
    "pct_knowledge_pool", "pct_cwd_context",
]

CWD_CONTEXT_FILENAME = "context.bejson"

_CWD_CONTEXT_FIELDS = [
    {"name": "section", "type": "string"},
    {"name": "content", "type": "string"},
]

_TRIGGER_FIELDS = [
    {"name": "keyword", "type": "string"},
    {"name": "context_path", "type": "string"},
    {"name": "cooldown_seconds", "type": "integer"},
]

_KNOWLEDGE_FIELDS = [
    {"name": "info_id", "type": "string"},
    {"name": "content", "type": "string"},
    {"name": "category", "type": "string"},
    {"name": "is_active", "type": "boolean"},
]


# ── Paths ────────────────────────────────────────────────────────────────────

def _paths(context_dir: Path, config_dir: Path, logs_dir: Path) -> dict:
    return {
        "bubble": context_dir / BUBBLE_FILENAME,
        "policy": context_dir / POLICY_FILENAME,
        "situational": context_dir / "Situational_Awareness",
        "constants": config_dir / "constant_config.bejson",
        "triggers": config_dir / "triggers.bejson",
        "knowledge": config_dir / "knowledge_pool.bejson",
        "logs": logs_dir / "context_logs.bejson",
    }


# ── Init (Part 1) ────────────────────────────────────────────────────────────

def init_context_bubble(context_dir: Path, config_dir: Path, logs_dir: Path) -> dict:
    """Create every registry this pipeline needs if it doesn't exist yet. Never
    overwrites an existing file — safe to call on every startup."""
    p = _paths(context_dir, config_dir, logs_dir)
    context_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    p["situational"].mkdir(parents=True, exist_ok=True)

    if not p["constants"].exists():
        doc = bejson_core_create_104a(
            "Constant", list(_CONSTANT_FIELDS),
            [[name, None, default, desc] for name, default, desc in _DEFAULT_CONSTANTS],
        )
        if not bejson_core_atomic_write(str(p["constants"]), doc):
            logger.error("[ContextBubble] Atomic write failed for %s", p["constants"])
    else:
        _backfill_constants(p["constants"])

    if not p["triggers"].exists():
        doc = bejson_core_create_104a("Trigger", list(_TRIGGER_FIELDS), [])
        bejson_core_atomic_write(str(p["triggers"]), doc)

    if not p["knowledge"].exists():
        doc = bejson_core_create_104a("KnowledgeEntry", list(_KNOWLEDGE_FIELDS), [])
        bejson_core_atomic_write(str(p["knowledge"]), doc)

    if not p["policy"].exists():
        p["policy"].write_text(_DEFAULT_POLICY_TEXT, encoding="utf-8")

    return p


# ── Constants (Part 1) ───────────────────────────────────────────────────────

def _backfill_constants(constants_path: Path) -> None:
    """
    Adds any constant defined in _DEFAULT_CONSTANTS that's missing from an
    already-initialized registry (e.g. pct_cwd_context on an install that
    ran init before it existed). Never touches an existing row — if a
    project's percentages don't sum to 1.0 after a backfill because an old
    default (like pct_active_tasks) wasn't shrunk to make room for the new
    one, that's surfaced by /budget's sum warning, not silently rewritten
    out from under whatever the person already had configured.
    """
    doc = bejson_core_load_file(str(constants_path))
    if not isinstance(doc, dict):
        return
    fmap = bejson_core_get_field_map(doc)
    name_idx = fmap["constant_name"]
    rows = doc.get("Values", [])
    existing = {row[name_idx] for row in rows if len(row) > name_idx}

    missing = [(n, d, desc) for n, d, desc in _DEFAULT_CONSTANTS if n not in existing]
    if not missing:
        return
    for name, default, desc in missing:
        rows.append([name, None, str(default), desc])
    new_doc = bejson_core_create_104a("Constant", list(_CONSTANT_FIELDS), rows)
    if not bejson_core_atomic_write(str(constants_path), new_doc):
        logger.error("[ContextBubble] Atomic write failed backfilling %s", constants_path)


def load_constants(config_dir: Path) -> dict[str, Any]:
    """Effective value = defined_value if set, else default_value.

    Values are stored as strings in the BEJSON file and coerced back
    to native Python types (int / float / bool) via _coerce_constant_value.
    """
    path = config_dir / "constant_config.bejson"
    result = {name: _coerce_constant_value(default) for name, default, _ in _DEFAULT_CONSTANTS}
    if not path.exists():
        return result

    doc = _cached_read(path, lambda p: bejson_core_load_file(str(p)))
    if not isinstance(doc, dict):
        return result
    validation = validate_bejson(doc, is_file=False)
    if not validation.valid:
        logger.warning("[ContextBubble] %s failed validation: %s", path, validation.errors)

    fmap = bejson_core_get_field_map(doc)
    name_idx = fmap["constant_name"]
    defined_idx = fmap["defined_value"]
    default_idx = fmap["default_value"]
    for row in doc.get("Values", []):
        if len(row) <= max(name_idx, defined_idx, default_idx):
            continue
        name = row[name_idx]
        raw = row[defined_idx] if row[defined_idx] is not None else row[default_idx]
        result[name] = _coerce_constant_value(raw)
    return result


def set_constant(config_dir: Path, name: str, value: Any) -> bool:
    """Write a constant's defined_value (used by /observer toggle etc).

    Converts the native value to a string for BEJSON storage.  Pass None
    to clear the override and fall back to the default.
    """
    path = config_dir / "constant_config.bejson"
    doc = bejson_core_load_file(str(path)) if path.exists() else None
    if not isinstance(doc, dict):
        return False
    fmap = bejson_core_get_field_map(doc)
    name_idx = fmap["constant_name"]
    defined_idx = fmap["defined_value"]
    rows = doc.get("Values", [])
    stored = str(value).lower() if isinstance(value, bool) else (str(value) if value is not None else None)
    for row in rows:
        if len(row) > name_idx and row[name_idx] == name:
            row[defined_idx] = stored
            return bejson_core_atomic_write(str(path), doc)
    return False


def _budget_chars(constants: dict, pct_key: str) -> int:
    return int(
        constants.get("max_context_tokens", 8000)
        * constants.get(pct_key, 0)
        * constants.get("chars_per_token", 4)
    )


# ── Bubble assembly ──────────────────────────────────────────────────────────

def _read_policy(policy_path: Path, budget_chars: int) -> str:
    if not policy_path.exists():
        return ""
    text = _cached_read(policy_path, lambda p: p.read_text("utf-8", errors="replace"))
    return text[:budget_chars]


def trim_history(history: list, max_turns: int) -> None:
    """FIX (2026-08-27, audit F-11): max_history_turns has had a config
    entry (with a default and a description) since it was first added,
    but nothing ever actually read it -- history grew unbounded for the
    life of every session, in both agent.py and webagent.py.

    Mutates `history` in place (keeps the object identity both callers
    already hold references to, rather than requiring every append site
    to also reassign `history = trim_history(...)`), trimming from the
    front (oldest first) down to the most recent max_turns*2 entries -- a
    "turn" here means one user message plus its one model response, so
    the multiplier keeps whole turns together rather than risking a cut
    that leaves a dangling response with no matching user message (or
    vice versa) at the boundary. max_turns <= 0 means unlimited (no
    trim), matching how a 0/negative budget is treated elsewhere in this
    codebase's config handling.
    """
    if max_turns is None or max_turns <= 0:
        return
    max_entries = max_turns * 2
    if len(history) > max_entries:
        del history[: len(history) - max_entries]


# ── Keyword triggers (Part 2) ────────────────────────────────────────────────

def scan_triggers(
    user_msg: str,
    triggers_path: Path,
    cooldown_state: dict[str, float],
    now_ts: float,
    global_default_cooldown: int,
) -> list[dict]:
    """Returns matched trigger rows whose cooldown has expired, and updates
    cooldown_state in place for every match (cooldown resets on trip, whether
    or not it ends up fitting the token budget later — a match that's about
    to inject shouldn't immediately re-trigger next turn just because budget
    trimmed it)."""
    if not triggers_path.exists():
        return []
    doc = _cached_read(triggers_path, lambda p: bejson_core_load_file(str(p)))
    if not isinstance(doc, dict):
        return []
    fmap = bejson_core_get_field_map(doc)
    kw_idx = fmap["keyword"]
    path_idx = fmap["context_path"]
    cd_idx = fmap["cooldown_seconds"]

    user_lower = user_msg.lower()
    matches = []
    for row in doc.get("Values", []):
        if len(row) <= max(kw_idx, path_idx, cd_idx):
            continue
        keyword = row[kw_idx] or ""
        if not keyword or keyword.lower() not in user_lower:
            continue
        cooldown = row[cd_idx] if row[cd_idx] is not None else global_default_cooldown
        # Keyed on (keyword, context_path), not keyword alone — multiple rows
        # sharing a keyword (e.g. one "becss" row per distinct fact) need
        # independent cooldowns. Keying on keyword alone meant the first
        # matching row's trip would falsely put every other row with the
        # same keyword on cooldown too, in the very same scan.
        cd_key = f"{keyword}::{row[path_idx]}"
        last = cooldown_state.get(cd_key, 0.0)
        if now_ts - last < cooldown:
            continue
        cooldown_state[cd_key] = now_ts
        matches.append({"keyword": keyword, "context_path": row[path_idx]})
    return matches


def build_keyword_section(
    matches: list[dict], situational_dir: Path, budget_chars: int,
    knowledge_path: Optional[Path] = None,
) -> tuple[str, int]:
    if not matches or budget_chars <= 0:
        return "", 0
    parts = []
    used = 0
    seen_content = set()  # dedup: e.g. "bejson" and "104a" both said in one
                           # message both resolve kb://bejson_core_3 -- only
                           # inject it once, under whichever keyword matched
                           # first (trigger row order in triggers.bejson).
    for m in matches:
        context_path = m["context_path"] or ""
        if context_path.startswith("kb://"):
            # Points at one specific knowledge_pool.bejson entry by info_id
            # instead of a whole file — a keyword can surface a single
            # focused fact rather than dragging in an entire document.
            content = _lookup_knowledge_entry(knowledge_path, context_path[5:]) if knowledge_path else None
            if content is None:
                continue
        else:
            fpath = situational_dir / context_path
            if not fpath.exists():
                continue
            try:
                content = fpath.read_text("utf-8", errors="replace")
            except Exception:
                continue
        if content in seen_content:
            continue
        seen_content.add(content)
        block = f"[{m['keyword']}]\n{content}"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts), used


def _lookup_knowledge_entry(knowledge_path: Path, info_id: str) -> Optional[str]:
    """Fetches one row's content from knowledge_pool.bejson by info_id, for
    kb:// keyword-trigger targets. Returns None if the pool doesn't exist,
    the id isn't found, or the entry is inactive — inactive entries are
    excluded here the same way they're excluded from the interval drip."""
    if not knowledge_path.exists():
        return None
    doc = _cached_read(knowledge_path, lambda p: bejson_core_load_file(str(p)))
    if not isinstance(doc, dict):
        return None
    fmap = bejson_core_get_field_map(doc)
    id_idx = fmap["info_id"]
    content_idx = fmap["content"]
    active_idx = fmap["is_active"]
    for row in doc.get("Values", []):
        if len(row) <= max(id_idx, content_idx, active_idx):
            continue
        if row[id_idx] == info_id:
            return row[content_idx] if row[active_idx] else None
    return None


# ── Knowledge pool (Part 3) ──────────────────────────────────────────────────

KEYWORD_ONLY_CATEGORY = "keyword_only"

def build_knowledge_section(
    knowledge_path: Path, turn: int, interval: int, budget_chars: int
) -> tuple[str, int]:
    """
    The blanket interval drip. Rows tagged category == KEYWORD_ONLY_CATEGORY
    are deliberately excluded here — they're meant to be reached only via a
    kb:// keyword trigger targeting their specific info_id (see
    build_keyword_section), not folded into the general drip. Without this,
    a growing set of topic-specific facts (e.g. one design system's worth of
    detail) would compete with foundational always-relevant facts for the
    same fixed budget and could silently crowd them out as more get added.

    2026-08-16 (Elton's Persistent Drip request): this used to always show
    the exact same rows in the exact same order every time it fired,
    front-to-back, truncated wherever the budget ran out -- so anything
    past the truncation point never appeared, and everything before it
    appeared identically on every single firing forever. Now it rotates: a
    `weight` column (1/2/3, default 2 -- lower fires more often) controls
    how many times each row enters a repeating fire schedule, and the
    schedule's start point advances by one position every time this
    function actually fires (derived from turn // interval, so no separate
    persisted rotation-cursor state is needed -- the caller's own turn
    counter already provides it). Within one firing, a row is never shown
    twice even if its weight put multiple copies in the schedule.
    """
    if interval <= 0 or turn % interval != 0 or budget_chars <= 0:
        return "", 0
    if not knowledge_path.exists():
        return "", 0
    doc = _cached_read(knowledge_path, lambda p: bejson_core_load_file(str(p)))
    if not isinstance(doc, dict):
        return "", 0
    fmap = bejson_core_get_field_map(doc)
    content_idx = fmap["content"]
    category_idx = fmap["category"]
    active_idx = fmap["is_active"]
    weight_idx = fmap["weight"]

    eligible = []  # (block_text,) per active, non-keyword_only row, in file order
    for row in doc.get("Values", []):
        if len(row) <= max(content_idx, category_idx, active_idx):
            continue
        if not row[active_idx]:
            continue
        if row[category_idx] == KEYWORD_ONLY_CATEGORY:
            continue
        weight = row[weight_idx] if len(row) > weight_idx and row[weight_idx] in (1, 2, 3) else 2
        eligible.append((f"[{row[category_idx]}]\n{row[content_idx]}", weight))
    if not eligible:
        return "", 0

    # Round-robin schedule: row order preserved within each pass, but a
    # weight-1 row gets 3 passes, weight-2 gets 2, weight-3 gets 1 -- so
    # frequent rows recur spread out across the cycle instead of clumped
    # at the front, and weight purely controls how OFTEN a row comes up
    # across many firings, not where it sits within one.
    schedule = []
    for pass_num in range(3):
        for idx, (_block, weight) in enumerate(eligible):
            reps = 4 - weight  # weight 1->3, 2->2, 3->1
            if pass_num < reps:
                schedule.append(idx)
    cycle_len = len(schedule)
    cursor = (turn // interval) % cycle_len

    parts = []
    used = 0
    picked = set()
    steps = 0
    while steps < cycle_len and used < budget_chars:
        idx = schedule[(cursor + steps) % cycle_len]
        steps += 1
        if idx in picked:
            continue
        picked.add(idx)
        block = eligible[idx][0]
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts), used


def build_env_file_section(env_file_paths: list[Path], turn: int, interval: int, budget_chars: int) -> tuple[str, int]:
    """
    Elton's request 2026-07-24: the env source(s) (GlobalEnv files
    env_file.py/env_file.sh/~/.bashrc -- now split into a secure file and a
    paths file -- all read from) should be a permanent fact the agent
    regularly re-sees, not something it only catches if it happens to
    read_file it mid-session. Uses the same interval-drip cadence and
    budget-capping pattern as build_knowledge_section, but reads every
    source fresh from disk on every firing turn instead of storing a
    snapshot in knowledge_pool.bejson -- env vars (API keys especially) get
    rotated, and a stale copy baked into the knowledge pool would drip a
    revoked/wrong key back into context indefinitely. Skips rows with no
    var_name (these files have been seen with trailing [null, null, null]
    padding rows in practice).

    2026-08-16: takes a list of sources instead of one (new split env
    scheme -- secure + paths, or the single legacy file as fallback) and
    merges their rows into a single budget-capped drip, source by source in
    the order given.
    """
    if interval <= 0 or turn % interval != 0 or budget_chars <= 0:
        return "", 0
    if not env_file_paths:
        return "", 0

    parts = []
    used = 0
    for env_file_path in env_file_paths:
        fpath = Path(env_file_path)
        if not env_file_path or not fpath.exists():
            continue
        doc = bejson_core_load_file(str(fpath))
        if not isinstance(doc, dict):
            continue
        fmap = bejson_core_get_field_map(doc)
        name_idx = fmap["var_name"]
        value_idx = fmap["var_value"]
        type_idx = fmap.get("var_type")  # optional column

        for row in doc.get("Values", []):
            if len(row) <= max(name_idx, value_idx):
                continue
            name = row[name_idx]
            if not name:
                continue
            raw_value = row[value_idx]
            vtype = row[type_idx] if (type_idx is not None and len(row) > type_idx) else ""
            # 2026-10-13 audit fix: secrets were dripped raw into the system
            # prompt and therefore into logs/session_*. Mask at the source.
            if errors.is_secret_name(name, vtype):
                raw_value = errors.mask_value(raw_value)
            else:
                raw_value = errors.redact_secrets(raw_value)
            block = f"{name}={raw_value}"
            if used + len(block) > budget_chars:
                remaining = budget_chars - used
                if remaining > 0:
                    parts.append(block[:remaining])
                    used = budget_chars
                return "\n".join(parts), used
            parts.append(block)
            used += len(block) + 1  # +1 for the joining newline below
    return "\n".join(parts), used




def build_cwd_context_section(cwd: Path, budget_chars: int) -> tuple[str, int]:
    """
    Checks the CURRENT working directory (re-evaluated every turn — cwd can
    change mid-session via /cd or a shell `cd`) for context.bejson, AND
    every ancestor directory above it, all the way to the filesystem root.
    If it exists anywhere in that chain, it's always included — no keyword
    trigger, no cooldown, no opt-in. Still capped to its reserved budget
    slice like every other section: "no choice" means the client doesn't
    get to skip it, not that it can blow past its allotment and starve
    everything else.

    2026-08-17 (Elton's request): matches how GEMINI.md/CLAUDE.md/AGENTS.md
    work in Gemini CLI, Antigravity, etc. -- a context file placed at, say,
    /storage/emulated/0/context.bejson applies everywhere underneath it too,
    including /storage/emulated/0/Pictures, not just in the exact directory
    NewAgent happens to be sitting in. Merge order is root-to-leaf (broadest
    first, nearest/most specific last): if the same section name shows up
    at more than one level (e.g. every directory in a repo declaring
    "Rules"), the NEAREST directory's version wins and replaces the
    broader one entirely, the same way a more specific CSS rule overrides
    a general one -- it does not concatenate both. tools/NA-Init/CLI_Init.py
    and the context_set action still write to exactly one directory's own
    context.bejson (that part is unchanged and correct as-is); only the
    READ side now walks the chain.
    """
    if budget_chars <= 0:
        return "", 0
    cwd = Path(cwd).resolve()
    ancestors_root_first = list(reversed(list(cwd.parents))) + [cwd]

    sections: dict[str, str] = {}
    order: list[str] = []  # first-seen position is kept even when overridden
    for d in ancestors_root_first:
        fpath = d / CWD_CONTEXT_FILENAME
        if not fpath.exists():
            continue
        doc = bejson_core_load_file(str(fpath))
        if not isinstance(doc, dict):
            continue
        result = validate_bejson(doc, is_file=False)
        if not result.valid:
            logger.warning("[ContextBubble] %s failed structural validation: %s", fpath, result.errors)
            continue
        fmap = bejson_core_get_field_map(doc)
        section_idx = fmap["section"]
        content_idx = fmap["content"]
        for row in doc.get("Values", []):
            if len(row) <= max(section_idx, content_idx):
                continue
            name = row[section_idx]
            if not name:
                continue
            if name not in sections:
                order.append(name)
            sections[name] = row[content_idx]  # nearer dir overwrites, keeps position

    if not sections:
        return "", 0

    parts = []
    used = 0
    for name in order:
        block = f"[{name}]\n{sections[name]}"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts), used


_TERMINAL_CHECKLIST_STATUSES = {"done", "complete", "completed", "closed", "cancelled"}


def build_active_tasks_section(cwd: str, budget_chars: int) -> tuple[str, int]:
    """
    Wires pct_active_tasks to the persistent per-directory task-checklist
    system (checklist_create/check/add/view tools; files named
    checklist_*.bejson living in cwd, one per job -- not a single global
    checklist.bejson). Scans the CURRENT directory (non-recursive, matching
    the same 'as we navigate' scope the auto-cleanup uses) for every
    checklist file, surfaces incomplete tasks from all of them so the model
    sees what's still open in whatever job(s) live where it's currently
    working. A finished task ages out on its own (status == 'done'), and a
    fully-completed list also disappears here well before the 24h
    auto-cleanup would ever delete the file.
    """
    if budget_chars <= 0:
        return "", 0
    cwd_path = Path(cwd)
    if not cwd_path.is_dir():
        return "", 0

    parts = []
    used = 0
    for fpath in sorted(cwd_path.glob("checklist_*.bejson")):
        doc = bejson_core_load_file(str(fpath))
        if not isinstance(doc, dict):
            continue
        fmap = bejson_core_get_field_map(doc)
        id_idx = fmap["task_id"]
        desc_idx = fmap["description"]
        status_idx = fmap["status"]
        title = doc.get("Job_Title", fpath.name)

        pending_blocks = []
        for row in doc.get("Values", []):
            if len(row) <= max(id_idx, desc_idx, status_idx):
                continue
            status = str(row[status_idx] or "")
            if status.strip().lower() in _TERMINAL_CHECKLIST_STATUSES:
                continue
            pending_blocks.append(f"  - [{row[id_idx]}] {row[desc_idx]}")
        if not pending_blocks:
            continue  # this list is fully done -- don't surface it at all

        block = f"{fpath.name} — '{title}':\n" + "\n".join(pending_blocks)
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block) + 1

    return "\n".join(parts), used


def init_cwd_context_template(cwd: str) -> tuple[bool, str]:
    """Scaffolds an empty context.bejson in cwd with the correct dual-field
    (section, content) schema. Used by /init. Refuses to overwrite an
    existing file rather than silently clobbering it."""
    fpath = Path(cwd) / CWD_CONTEXT_FILENAME
    if fpath.exists():
        return False, f"{fpath} already exists — not overwriting it."
    doc = bejson_core_create_104a("CwdContext", list(_CWD_CONTEXT_FIELDS), [])
    if not bejson_core_atomic_write(str(fpath), doc):
        return False, f"Atomic write failed for {fpath}."
    return True, f"Created {fpath} — add rows with [\"section\", \"content\"] and it'll auto-inject every turn."


def upsert_cwd_context_section(cwd: str, section: str, content: str) -> tuple[bool, str]:
    """
    Sets one (section, content) row in cwd's context.bejson -- creates the
    file first (same schema as init_cwd_context_template) if it doesn't
    exist yet, so this is always safe to call directly without a separate
    /init step first. Upsert semantics: a row whose section already matches
    (case-sensitive) has its content REPLACED, not duplicated -- calling
    this twice with the same section is how you correct/update it, not how
    you accumulate two rows for the same topic.

    2026-08-16 (Elton's INIT request): this is the shared engine behind
    both the standalone tools/NA-Init/CLI_Init.py CLI (for scaffolding a
    project from outside a running NewAgent session) and the instruction in
    Persistent_Policy.md telling the in-session model to call this same
    upsert whenever the user hands it a project's purpose or ground rules,
    so that context survives beyond conversational memory / Amnesia.
    """
    fpath = Path(cwd) / CWD_CONTEXT_FILENAME
    if fpath.exists():
        doc = bejson_core_load_file(str(fpath))
        if not isinstance(doc, dict):
            return False, f"{fpath} exists but isn't readable as BEJSON -- fix or delete it first."
    else:
        doc = bejson_core_create_104a("CwdContext", list(_CWD_CONTEXT_FIELDS), [])

    fmap = bejson_core_get_field_map(doc)
    section_idx = fmap["section"]
    content_idx = fmap["content"]

    for row in doc.get("Values", []):
        if len(row) > section_idx and row[section_idx] == section:
            row[content_idx] = content
            break
    else:
        doc.setdefault("Values", []).append([section, content])

    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        return False, f"Refusing to write -- resulting {fpath} would be invalid: {'; '.join(result.errors)}"

    if not bejson_core_atomic_write(str(fpath), doc):
        return False, f"Atomic write failed for {fpath}."
    return True, f"Set [{section}] in {fpath}."


# ── Assembly entrypoint ──────────────────────────────────────────────────────

def build_minimal_bubble(context_dir: Path, config_dir: Path) -> dict:
    """Degraded-mode fallback for when assemble_bubble() raises
    ContextInjectionError (audit Part 1/I 'ContextInjectionError... allowing
    the agent to retry with a minimal default context'). Only the Persistent
    Policy is included — no knowledge pool, no keyword triggers, no cwd/env
    sections — since those are exactly the parts that can fail on a bad
    BEJSON row or a missing constants file. Uses defensive .get()-style
    defaults throughout rather than re-running load_constants(), since a
    corrupted constants file may be *why* the normal path just failed.
    """
    p = _paths(context_dir, config_dir, context_dir.parent / "logs")
    try:
        policy_text = _read_policy(p["policy"], 4000)
    except Exception:
        policy_text = ""
    full_text = f"## Persistent Policy\n{policy_text}\n\n(Degraded context — Thought Bubble assembly failed this turn.)"
    return {
        "text": full_text,
        "policy_tokens": len(policy_text) // 4,
        "active_tasks_tokens": 0,
        "env_file_tokens": 0,
        "cwd_tokens": 0,
        "keyword_tokens": 0,
        "knowledge_tokens": 0,
        "max_context_tokens": 8000,
        "chars_per_token": 4,
        "observer_enabled": False,
        "observer_refinement_interval": 7,
    }


def assemble_bubble(
    context_dir: Path,
    config_dir: Path,
    user_msg: str,
    turn: int,
    cooldown_state: dict[str, float],
    cwd: str = ".",
    env_file_paths: list[str] = None,
) -> dict:
    """
    Builds the full bubble content in memory (one atomic write at the end,
    not truncate-then-append-piecemeal — a process dying mid-assembly leaves
    the previous turn's bubble on disk intact rather than a half-written
    file) and writes it once to Context_Bubble.md.

    Returns a dict with the assembled text and a token breakdown, which the
    caller logs to context_logs.bejson.
    """
    p = _paths(context_dir, config_dir, context_dir.parent / "logs")

    try:
        constants = load_constants(config_dir)

        policy_budget = _budget_chars(constants, "pct_persistent_policy")
        active_tasks_budget = _budget_chars(constants, "pct_active_tasks")
        env_file_budget = _budget_chars(constants, "pct_env_file")
        keyword_budget = _budget_chars(constants, "pct_keyword_triggers")
        knowledge_budget = _budget_chars(constants, "pct_knowledge_pool")
        cwd_budget = _budget_chars(constants, "pct_cwd_context")

        policy_text = _read_policy(p["policy"], policy_budget)
        active_tasks_text, active_tasks_used = build_active_tasks_section(cwd, active_tasks_budget)
        cwd_text, cwd_used = build_cwd_context_section(Path(cwd), cwd_budget)
        env_file_text, env_file_used = build_env_file_section(
            [Path(p) for p in (env_file_paths or [])],
            turn, constants.get("knowledge_drip_interval", 5), env_file_budget,
        )

        matches = scan_triggers(
            user_msg, p["triggers"], cooldown_state, time.time(),
            constants.get("global_default_cooldown", 300),
        )
        keyword_text, keyword_used = build_keyword_section(
            matches, p["situational"], keyword_budget, knowledge_path=p["knowledge"],
        )

        knowledge_text, knowledge_used = build_knowledge_section(
            p["knowledge"], turn, constants.get("knowledge_drip_interval", 5), knowledge_budget
        )
    except Exception as exc:
        raise errors.ContextInjectionError(
            f"Thought Bubble assembly failed while building sections: {exc}"
        ) from exc

    sections = [f"## Persistent Policy\n{policy_text}"]
    if active_tasks_text:
        sections.append(f"## Active Tasks\n{active_tasks_text}")
    if cwd_text:
        sections.append(f"## Project Context ({cwd})\n{cwd_text}")
    if env_file_text:
        sources_label = ", ".join(str(p) for p in (env_file_paths or []))
        sections.append(f"## Environment ({sources_label})\n{env_file_text}")
    if keyword_text:
        sections.append(f"## Keyword Triggers\n{keyword_text}")
    if knowledge_text:
        sections.append(f"## Knowledge Pool\n{knowledge_text}")
    full_text = "\n\n".join(sections)

    try:
        p["bubble"].parent.mkdir(parents=True, exist_ok=True)
        p["bubble"].write_text(full_text, encoding="utf-8")
    except Exception as exc:
        logger.error("[ContextBubble] Failed to write %s: %s", p["bubble"], exc)

    return {
        "text": full_text,
        "policy_tokens": len(policy_text) // constants.get("chars_per_token", 4),
        "active_tasks_tokens": active_tasks_used // constants.get("chars_per_token", 4),
        "env_file_tokens": env_file_used // constants.get("chars_per_token", 4),
        "cwd_tokens": cwd_used // constants.get("chars_per_token", 4),
        "keyword_tokens": keyword_used // constants.get("chars_per_token", 4),
        "knowledge_tokens": knowledge_used // constants.get("chars_per_token", 4),
        "max_context_tokens": constants.get("max_context_tokens", 8000),
        "chars_per_token": constants.get("chars_per_token", 4),
        "observer_enabled": bool(constants.get("observer_enabled", False)),
        "observer_refinement_interval": constants.get("observer_refinement_interval", 7),
    }


# NOTE: log_context_send()/get_log_entry() (the standalone context_logs.bejson
# this module used to write) were removed here — context data now lives as
# columns on the same row as its prompt in the session transcript
# (lib_bejson_newagent_session.py's SessionLogger.log()/update_last_bubble()/
# get_entry()), not a separate file. See Docs/Changelogs.md.


# ── Observer (Part 4 — compression only, toggleable, no self-patching) ──────

_COMPRESSION_INSTRUCTION = (
    "Compress the following context notes to roughly half their length. "
    "Preserve every distinct fact, path, and instruction — remove only "
    "redundant phrasing and filler. Do not summarize away specifics. "
    "Return only the compressed text, no commentary."
)

_FULL_HISTORY_COMPRESSION_INSTRUCTION = (
    "The following is a full conversation transcript between a user and an "
    "AI terminal agent. Produce a dense recap that preserves every distinct "
    "fact, decision, file path, command, and open thread the agent would "
    "need to keep working competently with zero prior memory — this recap "
    "IS about to become the agent's entire memory of the session, so do not "
    "drop specifics for brevity. Remove only redundant back-and-forth and "
    "filler. Return only the recap text, no commentary, no preamble."
)


def run_full_session_compression(
    history: list[dict],
    rest_prompter,
) -> Optional[str]:
    """
    Force-compression for a manual /compress (or webagent Compress button)
    command — distinct from run_observer_compression below, which only ever
    touches the context bubble's keyword/knowledge sections on an automatic
    schedule. This one compresses the actual conversation transcript itself,
    on direct user request, so it can be used to flush history down to a
    single recap turn.

    Returns the compressed recap text, or None if there was nothing to
    compress or the call failed (fails open — caller must NOT clear history
    unless this returns a real string, or the flush would destroy the
    session's memory with nothing to replace it).
    """
    if not history:
        return None
    transcript = "\n\n".join(
        f"[{turn.get('role', '?')}]: {turn.get('content', '')}" for turn in history
    )
    if not transcript.strip():
        return None
    try:
        compressed, _usage = rest_prompter.prompt(
            history=[{"role": "user", "content": transcript}],
            system_instruction=_FULL_HISTORY_COMPRESSION_INSTRUCTION,
        )
    except Exception as exc:
        logger.warning("[ContextBubble] Full-session compression call failed, session NOT flushed: %s", exc)
        return None
    if not compressed or not compressed.strip():
        return None
    return compressed.strip()


# ── Amnesia / Rebirth persistence (2026-08-09) ──────────────────────────────
# /amnesia compresses+wipes; /rebirth retrieves. Whether rebirth happens
# automatically right after amnesia, or is deferred until run manually, is
# the auto_amnesia_memory_retrieval config toggle -- these two helpers give
# the recap somewhere durable to wait, independent of that choice.

_AMNESIA_RECAP_FILENAME = "amnesia_recap.txt"


def save_amnesia_recap(context_dir: Path, recap: str) -> None:
    """Persist the most recent /amnesia recap to disk so /rebirth can
    retrieve it later, independent of whether it was fed back in
    immediately. Plain text, atomic temp-then-replace write."""
    context_dir.mkdir(parents=True, exist_ok=True)
    target = context_dir / _AMNESIA_RECAP_FILENAME
    tmp = target.with_suffix(".tmp")
    tmp.write_text(recap, encoding="utf-8")
    tmp.replace(target)


def load_amnesia_recap(context_dir: Path) -> Optional[str]:
    """Returns the most recently saved /amnesia recap, or None if there
    isn't one (e.g. /amnesia has never been run, or it produced nothing)."""
    target = context_dir / _AMNESIA_RECAP_FILENAME
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8").strip()
    return text or None


def seed_history_with_recap(history: list[dict], recap: str) -> None:
    """Wipes history and reseeds it with exactly the recap as the sole
    turn -- the shared 'rebirth' step used both by /amnesia (when
    auto_amnesia_memory_retrieval is on) and by /rebirth (manual)."""
    history.clear()
    history.append({
        "role": "user",
        "content": f"[Rebirth -- compressed session recap]\n{recap}",
    })


def run_observer_compression(
    keyword_text: str,
    knowledge_text: str,
    rest_prompter,
) -> Optional[tuple[str, str]]:
    """
    Compresses ONLY the keyword-trigger and knowledge-pool sections — the
    persistent policy text is never passed into this function at all, so
    there's a structural guarantee (not just an instruction the model could
    ignore) that compression can never alter core directives. Returns
    (compressed_keyword_text, compressed_knowledge_text) or None if there
    was nothing to compress or the compression call failed (fails open:
    caller should fall back to the uncompressed text, never block the turn
    on this).
    """
    combined = "\n\n".join(t for t in (keyword_text, knowledge_text) if t)
    if not combined:
        return None
    try:
        compressed, _usage = rest_prompter.prompt(
            history=[{"role": "user", "content": combined}],
            system_instruction=_COMPRESSION_INSTRUCTION,
        )
    except Exception as exc:
        logger.warning("[ContextBubble] Observer compression call failed, using uncompressed bubble: %s", exc)
        return None

    if not compressed or not compressed.strip():
        return None
    # Split back proportionally isn't meaningful post-compression; re-file
    # everything under keyword_text and leave knowledge_text empty rather
    # than guess a split point.
    return compressed.strip(), ""
