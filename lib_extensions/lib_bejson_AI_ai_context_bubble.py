"""
Library:        lib_bejson_AI_ai_context_bubble.py
Family:         AI
Description:    Provider-agnostic context bubble assembly pipeline for the
                AI family.  Rebuilds a physical Context_Bubble.md (or any
                named file) from scratch each turn using a percentage-based
                budget across independently-togglable sections:

                  Section 1 — Persistent Policy   (always-on system prompt)
                  Section 2 — Active Tasks        (open checklist items in cwd)
                  Section 3 — CWD Context         (context.bejson in cwd)
                  Section 4 — Env File            (env var drip from BEJSON)
                  Section 5 — Keyword Triggers    (on-demand keyword hits)
                  Section 6 — Knowledge Pool      (interval drip of facts)
                  Section 7 — Custom Sections     (caller-registered extras)

                Any section can be disabled by setting its pct_* slot to 0 in
                ai_constants.bejson.  Custom sections allow callers to inject
                application-specific content blocks without modifying this
                library.

                Observer (Part 4 equivalent):
                  Optional auto-compression of the variable sections (keyword
                  + knowledge + custom).  Requires the caller to supply a
                  prompter callable -- the bubble library itself stays
                  provider-agnostic; it just calls the callable if the
                  observer is enabled and the interval fires.

                The persistent policy block is NEVER passed to the observer
                compressor -- structural guarantee, not just an instruction.

                Modelled after NewAgent's lib_bejson_newagent_context_bubble.py
                but generalised, provider-agnostic, and wired to this family's
                ai_constants / ai_keywords libraries.

Version:        1.0.1
Date:           2026-08-13
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID:  f1a2b3c4-d5e6-4708-9a0b-1c2d3e4f5061
Release_Version: 300

Changelog:
  1.0.0 (2026-08-12) -- Initial creation. Provider-agnostic generalisation
        of NewAgent's context bubble, extended with custom-section registry
        and a pluggable observer compressor interface.
  1.0.1 (2026-08-13) -- Refinement pass (carried forward from the prior
        Package v108 delivery, now merged into this tree so both audit
        passes land together):
        - Fixed ZeroDivisionError risk in ai_bubble_assemble(): a user-edited
          chars_per_token of 0 or negative in ai_constants.bejson previously
          crashed every token-count field in the return dict (policy_tokens,
          active_tasks_tokens, etc. all did `used // cpt`). Now guarded --
          falls back to 4 and logs a warning instead of raising.
        - Deduplicated the knowledge-pool schema: ai_bubble_init() was
          hardcoding its own copy of the KnowledgeEntry field list instead of
          reusing ai_keywords_init_knowledge_pool(). The two schemas could
          have drifted apart on a future edit to either file. Now calls the
          keywords library's initializer when available; the inline fallback
          is kept only for the case where ai_keywords itself is unavailable.
"""

# NOTE: No existing AI family files were modified outside this file.

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

VERSION = "1.0.1"

logger = logging.getLogger(__name__)

# ── Sibling resolution ────────────────────────────────────────────────────────

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_LIB_DIR), "Core")
for _p in (_LIB_DIR, _CORE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_get_field_map,
)

# AI family siblings (imported lazily to keep each import optional)
try:
    from lib_bejson_AI_ai_constants import (
        ai_constants_init,
        ai_constants_load,
        ai_constants_budget_chars,
    )
    _CONSTANTS_AVAILABLE = True
except ImportError:
    _CONSTANTS_AVAILABLE = False
    logger.warning("[AIContextBubble] ai_constants not found; using hardcoded defaults.")

try:
    from lib_bejson_AI_ai_keywords import (
        ai_keywords_init,
        ai_keywords_scan,
        ai_keywords_build_section,
        ai_keywords_init_knowledge_pool,
    )
    _KEYWORDS_AVAILABLE = True
except ImportError:
    _KEYWORDS_AVAILABLE = False
    logger.warning("[AIContextBubble] ai_keywords not found; keyword section disabled.")

# ── Hard-coded fallback defaults (when ai_constants is unavailable) ───────────

_FALLBACK_CONSTANTS: dict[str, Any] = {
    "max_context_tokens":           8000,
    "chars_per_token":              4,
    "pct_persistent_policy":        0.20,
    "pct_active_tasks":             0.20,
    "pct_keyword_triggers":         0.30,
    "pct_knowledge_pool":           0.15,
    "pct_cwd_context":              0.10,
    "pct_env_file":                 0.05,
    "knowledge_drip_interval":      5,
    "env_drip_interval":            5,
    "global_default_cooldown":      300,
    "observer_enabled":             False,
    "observer_refinement_interval": 7,
}

# ── Schema constants ──────────────────────────────────────────────────────────

_CWD_CONTEXT_FILENAME    = "context.bejson"
_BUBBLE_FILENAME         = "Context_Bubble.md"
_POLICY_FILENAME         = "Persistent_Policy.md"
_KNOWLEDGE_FILENAME      = "ai_knowledge_pool.bejson"

_TERMINAL_STATUSES = {"done", "complete", "completed", "closed", "cancelled"}

_COMPRESSION_INSTRUCTION = (
    "Compress the following context notes to roughly half their length. "
    "Preserve every distinct fact, path, and instruction -- remove only "
    "redundant phrasing and filler. Do not summarize away specifics. "
    "Return only the compressed text, no commentary."
)

_FULL_COMPRESSION_INSTRUCTION = (
    "The following is a full conversation transcript. Produce a dense recap "
    "that preserves every distinct fact, decision, file path, command, and "
    "open thread the agent would need to continue working with zero prior "
    "memory. Remove only redundant back-and-forth and filler. Return only "
    "the recap text, no commentary, no preamble."
)

_AMNESIA_FILENAME = "amnesia_recap.txt"


# ── Custom section registry ───────────────────────────────────────────────────
# Callers can register extra section builders without touching this file.
# A custom section builder is:
#   fn(constants: dict, cwd: str, config_dir: Path, context_dir: Path) -> tuple[str, int]
# Return ("", 0) to skip the section for this turn.

_custom_sections: list[dict] = []  # [{label, pct_key, builder_fn}, ...]


def ai_bubble_register_section(
    label: str,
    pct_key: str,
    builder_fn: Callable,
) -> None:
    """
    Registers a custom section.  label is the markdown heading text.
    pct_key must exist in ai_constants.bejson (or the fallback dict) to
    receive a budget; if the key is absent the section gets 0 chars.
    builder_fn signature: (constants, cwd, config_dir, context_dir) -> (str, int)
    """
    _custom_sections.append({"label": label, "pct_key": pct_key, "fn": builder_fn})


def ai_bubble_clear_custom_sections() -> None:
    """Removes all registered custom sections (useful for testing)."""
    _custom_sections.clear()


# ── Init ──────────────────────────────────────────────────────────────────────

def ai_bubble_init(
    context_dir: Path,
    config_dir:  Path,
    policy_text: Optional[str] = None,
) -> dict:
    """
    Bootstraps everything the pipeline needs:
      - config_dir / ai_constants.bejson  (via ai_constants_init if available)
      - config_dir / ai_knowledge_pool.bejson  (empty if absent)
      - context_dir / Persistent_Policy.md  (written only if absent)
      - context_dir / Situational_Awareness/  (directory)

    Returns a paths dict identical to what _bubble_paths() returns so the
    caller can inspect or override individual paths.

    policy_text: if supplied, written as the default Persistent_Policy.md
    content when the file doesn't exist.
    """
    context_dir = Path(context_dir)
    config_dir  = Path(config_dir)
    context_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "Situational_Awareness").mkdir(parents=True, exist_ok=True)

    if _CONSTANTS_AVAILABLE:
        ai_constants_init(config_dir)

    if _KEYWORDS_AVAILABLE:
        ai_keywords_init(config_dir)

    knowledge_path = config_dir / _KNOWLEDGE_FILENAME
    if not knowledge_path.exists():
        if _KEYWORDS_AVAILABLE:
            # Single source of truth for the knowledge-pool schema lives in
            # ai_keywords.py -- reuse it instead of duplicating the field list.
            ai_keywords_init_knowledge_pool(config_dir)
        else:
            from lib_bejson_Core_bejson_core import bejson_core_create_104a, bejson_core_atomic_write
            doc = bejson_core_create_104a("KnowledgeEntry", [
                {"name": "info_id",   "type": "string"},
                {"name": "content",   "type": "string"},
                {"name": "category",  "type": "string"},
                {"name": "is_active", "type": "boolean"},
            ], [])
            bejson_core_atomic_write(str(knowledge_path), doc)

    policy_path = context_dir / _POLICY_FILENAME
    if not policy_path.exists() and policy_text:
        policy_path.write_text(policy_text, encoding="utf-8")

    return _bubble_paths(context_dir, config_dir)


# ── Paths ─────────────────────────────────────────────────────────────────────

def _bubble_paths(context_dir: Path, config_dir: Path) -> dict:
    return {
        "bubble":       context_dir / _BUBBLE_FILENAME,
        "policy":       context_dir / _POLICY_FILENAME,
        "situational":  context_dir / "Situational_Awareness",
        "knowledge":    config_dir  / _KNOWLEDGE_FILENAME,
        "amnesia":      context_dir / _AMNESIA_FILENAME,
    }


# ── Budget helper ─────────────────────────────────────────────────────────────

def _budget(constants: dict, pct_key: str) -> int:
    if _CONSTANTS_AVAILABLE:
        return ai_constants_budget_chars(constants, pct_key)
    return int(
        constants.get("max_context_tokens", 8000)
        * constants.get(pct_key, 0.0)
        * constants.get("chars_per_token", 4)
    )


# ── Section builders ──────────────────────────────────────────────────────────

def _build_policy_section(policy_path: Path, budget_chars: int) -> tuple[str, int]:
    if budget_chars <= 0 or not policy_path.exists():
        return "", 0
    text = policy_path.read_text("utf-8", errors="replace")[:budget_chars]
    return text, len(text)


def _build_cwd_context_section(cwd: str, budget_chars: int) -> tuple[str, int]:
    if budget_chars <= 0:
        return "", 0
    fpath = Path(cwd) / _CWD_CONTEXT_FILENAME
    if not fpath.exists():
        return "", 0
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return "", 0
    fmap        = bejson_core_get_field_map(doc)
    section_idx = fmap.get("section", 0)
    content_idx = fmap.get("content", 1)
    parts, used = [], 0
    for row in doc.get("Values", []):
        if len(row) <= max(section_idx, content_idx):
            continue
        block = f"[{row[section_idx]}]\n{row[content_idx]}"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts), used


def _build_active_tasks_section(cwd: str, budget_chars: int) -> tuple[str, int]:
    if budget_chars <= 0:
        return "", 0
    cwd_path = Path(cwd)
    if not cwd_path.is_dir():
        return "", 0
    parts, used = [], 0
    for fpath in sorted(cwd_path.glob("checklist_*.bejson")):
        doc = bejson_core_load_file(str(fpath))
        if not isinstance(doc, dict):
            continue
        fmap       = bejson_core_get_field_map(doc)
        id_idx     = fmap.get("task_id",     0)
        desc_idx   = fmap.get("description", 1)
        status_idx = fmap.get("status",      2)
        title = doc.get("Job_Title", fpath.name)
        pending = []
        for row in doc.get("Values", []):
            if len(row) <= max(id_idx, desc_idx, status_idx):
                continue
            if str(row[status_idx] or "").strip().lower() in _TERMINAL_STATUSES:
                continue
            pending.append(f"  - [{row[id_idx]}] {row[desc_idx]}")
        if not pending:
            continue
        block = f"{fpath.name} -- '{title}':\n" + "\n".join(pending)
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block) + 1
    return "\n".join(parts), used


def _build_env_section(
    env_path: Optional[Path],
    turn: int,
    interval: int,
    budget_chars: int,
) -> tuple[str, int]:
    if budget_chars <= 0 or interval <= 0 or turn % interval != 0:
        return "", 0
    if not env_path or not Path(env_path).exists():
        return "", 0
    doc = bejson_core_load_file(str(env_path))
    if not isinstance(doc, dict):
        return "", 0
    fmap      = bejson_core_get_field_map(doc)
    name_idx  = fmap.get("var_name",  0)
    value_idx = fmap.get("var_value", 1)
    parts, used = [], 0
    for row in doc.get("Values", []):
        if len(row) <= max(name_idx, value_idx):
            continue
        name = row[name_idx]
        if not name:
            continue
        block = f"{name}={row[value_idx]}"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block) + 1
    return "\n".join(parts), used


def _build_knowledge_section(
    knowledge_path: Path,
    turn: int,
    interval: int,
    budget_chars: int,
    keyword_only_category: str = "keyword_only",
) -> tuple[str, int]:
    if budget_chars <= 0 or interval <= 0 or turn % interval != 0:
        return "", 0
    if not knowledge_path.exists():
        return "", 0
    doc = bejson_core_load_file(str(knowledge_path))
    if not isinstance(doc, dict):
        return "", 0
    fmap        = bejson_core_get_field_map(doc)
    content_idx  = fmap.get("content",   1)
    category_idx = fmap.get("category",  2)
    active_idx   = fmap.get("is_active", 3)
    parts, used = [], 0
    for row in doc.get("Values", []):
        if len(row) <= max(content_idx, category_idx, active_idx):
            continue
        if not row[active_idx]:
            continue
        if row[category_idx] == keyword_only_category:
            continue
        block = f"[{row[category_idx]}]\n{row[content_idx]}"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used
            if remaining > 0:
                parts.append(block[:remaining])
                used = budget_chars
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts), used


# ── Main assembly ─────────────────────────────────────────────────────────────

def ai_bubble_assemble(
    context_dir:    Path,
    config_dir:     Path,
    user_msg:       str,
    turn:           int,
    cooldown_state: dict[str, float],
    cwd:            str = ".",
    env_path:       Optional[Path] = None,
    bubble_filename: str = _BUBBLE_FILENAME,
) -> dict:
    """
    Builds the complete context bubble and writes it to
    context_dir/<bubble_filename>.  All sections are assembled in memory
    first; the file is written once (atomic) at the end.

    Returns a breakdown dict with per-section token estimates plus the
    assembled text (key "text").

    cooldown_state is mutated in-place for keyword trigger cooldowns.
    Pass the same dict across turns to maintain cooldown persistence.

    env_path: optional path to a BEJSON GlobalEnv file (secureenv_file.json
              or paths.json) for the env-drip section.
    """
    context_dir = Path(context_dir)
    config_dir  = Path(config_dir)
    p = _bubble_paths(context_dir, config_dir)

    # Load constants
    if _CONSTANTS_AVAILABLE:
        constants = ai_constants_load(config_dir)
    else:
        constants = dict(_FALLBACK_CONSTANTS)

    # Guard against a user-edited chars_per_token of 0/negative in
    # ai_constants.bejson -- every token estimate below divides by cpt.
    cpt = constants.get("chars_per_token", 4)
    if not cpt or cpt <= 0:
        logger.warning("[AIContextBubble] chars_per_token <= 0 (%r); using 4 for token math.", cpt)
        cpt = 4

    # ── Section 1: Persistent Policy ─────────────────────────────────────────
    policy_text, policy_used = _build_policy_section(
        p["policy"], _budget(constants, "pct_persistent_policy")
    )

    # ── Section 2: Active Tasks ───────────────────────────────────────────────
    active_text, active_used = _build_active_tasks_section(
        cwd, _budget(constants, "pct_active_tasks")
    )

    # ── Section 3: CWD Context ────────────────────────────────────────────────
    cwd_text, cwd_used = _build_cwd_context_section(
        cwd, _budget(constants, "pct_cwd_context")
    )

    # ── Section 4: Env File ───────────────────────────────────────────────────
    env_text, env_used = _build_env_section(
        env_path, turn,
        constants.get("env_drip_interval", 5),
        _budget(constants, "pct_env_file"),
    )

    # ── Section 5: Keyword Triggers ───────────────────────────────────────────
    keyword_text, keyword_used = "", 0
    if _KEYWORDS_AVAILABLE and _budget(constants, "pct_keyword_triggers") > 0:
        matches = ai_keywords_scan(
            user_msg, config_dir, cooldown_state,
            global_default_cooldown=constants.get("global_default_cooldown", 300),
        )
        keyword_text, keyword_used = ai_keywords_build_section(
            matches,
            p["situational"],
            _budget(constants, "pct_keyword_triggers"),
            knowledge_pool_path=p["knowledge"],
        )

    # ── Section 6: Knowledge Pool ─────────────────────────────────────────────
    knowledge_text, knowledge_used = _build_knowledge_section(
        p["knowledge"], turn,
        constants.get("knowledge_drip_interval", 5),
        _budget(constants, "pct_knowledge_pool"),
    )

    # ── Section 7: Custom Sections ────────────────────────────────────────────
    custom_blocks: list[tuple[str, str, int]] = []  # (label, text, used)
    for cs in _custom_sections:
        try:
            cs_budget = _budget(constants, cs["pct_key"])
            if cs_budget <= 0:
                continue
            cs_text, cs_used = cs["fn"](constants, cwd, config_dir, context_dir)
            if cs_text:
                custom_blocks.append((cs["label"], cs_text, cs_used))
        except Exception as exc:
            logger.warning("[AIContextBubble] Custom section '%s' failed: %s", cs["label"], exc)

    # ── Observer compression (variable sections only) ─────────────────────────
    # Policy block is structurally excluded — never passed to the compressor.
    observer_on = bool(constants.get("observer_enabled", False))
    obs_interval = int(constants.get("observer_refinement_interval", 7))
    if observer_on and obs_interval > 0 and turn % obs_interval == 0:
        keyword_text, knowledge_text = _maybe_compress(
            keyword_text, knowledge_text, constants
        )

    # ── Assemble ──────────────────────────────────────────────────────────────
    sections: list[str] = []
    if policy_text:
        sections.append(f"## Persistent Policy\n{policy_text}")
    if active_text:
        sections.append(f"## Active Tasks\n{active_text}")
    if cwd_text:
        sections.append(f"## Project Context ({cwd})\n{cwd_text}")
    if env_text:
        sections.append(f"## Environment\n{env_text}")
    if keyword_text:
        sections.append(f"## Keyword Triggers\n{keyword_text}")
    if knowledge_text:
        sections.append(f"## Knowledge Pool\n{knowledge_text}")
    for label, cs_text, _ in custom_blocks:
        sections.append(f"## {label}\n{cs_text}")

    full_text = "\n\n".join(sections)

    # Write bubble file
    bubble_path = context_dir / bubble_filename
    try:
        bubble_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = bubble_path.with_suffix(".tmp")
        tmp.write_text(full_text, encoding="utf-8")
        tmp.replace(bubble_path)
    except Exception as exc:
        logger.error("[AIContextBubble] Failed to write bubble: %s", exc)

    custom_used_total = sum(u for _, _, u in custom_blocks)

    return {
        "text":                full_text,
        "policy_tokens":       policy_used   // cpt,
        "active_tasks_tokens": active_used   // cpt,
        "cwd_tokens":          cwd_used      // cpt,
        "env_tokens":          env_used      // cpt,
        "keyword_tokens":      keyword_used  // cpt,
        "knowledge_tokens":    knowledge_used // cpt,
        "custom_tokens":       custom_used_total // cpt,
        "max_context_tokens":  constants.get("max_context_tokens", 8000),
        "chars_per_token":     cpt,
        "observer_enabled":    observer_on,
        "observer_interval":   obs_interval,
        "bubble_path":         str(bubble_path),
    }


def ai_bubble_minimal(context_dir: Path) -> dict:
    """
    Degraded-mode fallback.  Returns only the Persistent Policy if the full
    assembly fails, so the caller always has something to send to the model.
    """
    context_dir = Path(context_dir)
    policy_path = context_dir / _POLICY_FILENAME
    try:
        policy_text = policy_path.read_text("utf-8", errors="replace")[:4000]
    except Exception:
        policy_text = ""
    full_text = f"## Persistent Policy\n{policy_text}\n\n(Degraded context -- bubble assembly failed this turn.)"
    return {
        "text": full_text,
        "policy_tokens": len(policy_text) // 4,
        "max_context_tokens": 8000,
        "observer_enabled": False,
        "bubble_path": str(context_dir / _BUBBLE_FILENAME),
    }


# ── Observer ──────────────────────────────────────────────────────────────────

# Caller registers a compressor here before using the observer.
# Signature: (combined_text: str) -> Optional[str]
# Returns compressed text or None on failure.
_observer_compressor: Optional[Callable[[str], Optional[str]]] = None


def ai_bubble_set_compressor(fn: Callable[[str], Optional[str]]) -> None:
    """
    Registers the observer compressor callable.  The function receives the
    combined variable sections text and must return compressed text or None.
    Example wiring with Gemini:

        def my_compressor(text: str) -> Optional[str]:
            return gemini_api.generate(text, system_instruction=_COMPRESSION_INSTRUCTION)

        ai_bubble_set_compressor(my_compressor)
    """
    global _observer_compressor
    _observer_compressor = fn


def _maybe_compress(
    keyword_text: str,
    knowledge_text: str,
    constants: dict,
) -> tuple[str, str]:
    """
    Attempts observer compression of variable sections.  Fails open --
    returns the original texts unchanged if the compressor is unavailable
    or raises.
    """
    if _observer_compressor is None:
        return keyword_text, knowledge_text
    combined = "\n\n".join(t for t in (keyword_text, knowledge_text) if t)
    if not combined:
        return keyword_text, knowledge_text
    try:
        result = _observer_compressor(combined)
        if result and result.strip():
            return result.strip(), ""
    except Exception as exc:
        logger.warning("[AIContextBubble] Observer compression failed, using original: %s", exc)
    return keyword_text, knowledge_text


# ── Full-session compression (manual flush) ───────────────────────────────────

def ai_bubble_compress_history(
    history: list[dict],
    compressor_fn: Callable[[str], Optional[str]],
) -> Optional[str]:
    """
    Compresses a full conversation history to a dense recap string.
    compressor_fn receives the concatenated transcript and must return the
    compressed string or None on failure.  Fails open -- returns None without
    touching history if compression produces nothing.

    Intended for a /compress or /amnesia command; the caller decides whether
    to wipe and reseed history.
    """
    if not history:
        return None
    transcript = "\n\n".join(
        f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in history
    )
    if not transcript.strip():
        return None
    try:
        result = compressor_fn(transcript)
        if result and result.strip():
            return result.strip()
    except Exception as exc:
        logger.warning("[AIContextBubble] History compression failed: %s", exc)
    return None


# ── Amnesia / Rebirth ─────────────────────────────────────────────────────────

def ai_bubble_save_amnesia_recap(context_dir: Path, recap: str) -> None:
    """Persists the latest compression recap to disk for deferred rebirth."""
    context_dir = Path(context_dir)
    context_dir.mkdir(parents=True, exist_ok=True)
    target = context_dir / _AMNESIA_FILENAME
    tmp = target.with_suffix(".tmp")
    tmp.write_text(recap, encoding="utf-8")
    tmp.replace(target)


def ai_bubble_load_amnesia_recap(context_dir: Path) -> Optional[str]:
    """Returns the most recently saved amnesia recap, or None if absent."""
    target = Path(context_dir) / _AMNESIA_FILENAME
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8").strip()
    return text or None


def ai_bubble_rebirth(history: list[dict], recap: str) -> None:
    """
    Wipes history and reseeds it with the recap as the sole turn.
    Mutates history in place.  Call ai_bubble_load_amnesia_recap() first
    to retrieve the recap.
    """
    history.clear()
    history.append({
        "role":    "user",
        "content": f"[Rebirth -- compressed session recap]\n{recap}",
    })
