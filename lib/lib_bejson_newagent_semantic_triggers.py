"""
Library:        lib_bejson_newagent_semantic_triggers.py
Family:         NewAgent
Description:    Semantic Conditions Trigger Engine — replaces the flat keyword
                substring matching system (scan_triggers + build_keyword_section)
                with a conditional trigger pipeline:

                1. Each trigger row defines pipe-separated semantic_conditions
                   (positive match phrases) and negative_conditions (exclusion
                   phrases) with a triggered_action pointing to an agy skill
                   folder path via the skill:// protocol.

                2. The agent ALWAYS sees the full conditions table in its
                   context window (situational awareness of what triggers
                   exist and their boundaries).

                3. Skill paths and chunked skill folder content are ONLY
                   injected when:
                   (a) At least one semantic_condition phrase matches the
                       user message (case-insensitive substring).
                   (b) NO negative_condition phrase matches the user message.
                   (c) The trigger's cooldown period has expired.

                4. When triggered, the skill's SKILL.md is chunked and injected
                   into the context window, providing the agent with detailed
                   instructions for the relevant tools/workflows.

                Backward-compatible: the existing triggers.bejson keyword
                system continues to operate independently. This module runs
                alongside it as a parallel, higher-fidelity trigger layer.

Version:        1.0.0
Date:           2026-11-11
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  a4d27f83-9c1e-4b8a-bf62-71e3a5d09c14
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_get_field_map,
)

VERSION = "1.0.0"
RELATIONAL_ID = "a4d27f83-9c1e-4b8a-bf62-71e3a5d09c14"

semantic_trigger_module_logger = logging.getLogger(__name__)

# ── mtime-based read cache (mirrors context_bubble's _cached_read) ─────────
_SEMANTIC_CACHE_LOCK = threading.Lock()
_SEMANTIC_CACHE: dict[str, tuple[float, int, Any]] = {}


def _cached_read_semantic(file_path: Path, loader_function):
    """mtime+size-keyed cache — re-reads only when the file changes."""
    cache_key = str(file_path)
    try:
        stat_result = file_path.stat()
    except FileNotFoundError:
        with _SEMANTIC_CACHE_LOCK:
            _SEMANTIC_CACHE.pop(cache_key, None)
        return loader_function(file_path)
    stat_signature = (stat_result.st_mtime, stat_result.st_size)
    with _SEMANTIC_CACHE_LOCK:
        cached_entry = _SEMANTIC_CACHE.get(cache_key)
        if cached_entry is not None and (cached_entry[0], cached_entry[1]) == stat_signature:
            return cached_entry[2]
    loaded_value = loader_function(file_path)
    with _SEMANTIC_CACHE_LOCK:
        _SEMANTIC_CACHE[cache_key] = (stat_signature[0], stat_signature[1], loaded_value)
    return loaded_value


# ── Condition evaluation ───────────────────────────────────────────────────

def _parse_pipe_separated_conditions(raw_conditions_text: str) -> list[str]:
    """Split a pipe-separated string into cleaned, lowercase condition phrases.
    Example: 'validate|104 schema|verify bejson' → ['validate', '104 schema', 'verify bejson']
    """
    if not raw_conditions_text:
        return []
    return [
        phrase.strip().lower()
        for phrase in raw_conditions_text.split("|")
        if phrase.strip()
    ]


def evaluate_semantic_conditions(
    user_message_text: str,
    semantic_conditions_raw: str,
    negative_conditions_raw: str,
) -> dict[str, Any]:
    """Evaluate whether a trigger's conditions are met against a user message.

    Returns a dict with:
      - 'triggered': bool — True if conditions are satisfied
      - 'matched_positive': list[str] — which positive phrases matched
      - 'matched_negative': list[str] — which negative phrases matched (blocks trigger)
      - 'positive_phrases': list[str] — all positive condition phrases
      - 'negative_phrases': list[str] — all negative condition phrases
    """
    user_message_lower = user_message_text.lower()

    positive_phrase_list = _parse_pipe_separated_conditions(semantic_conditions_raw)
    negative_phrase_list = _parse_pipe_separated_conditions(negative_conditions_raw)

    matched_positive_phrases = [
        phrase for phrase in positive_phrase_list
        if phrase in user_message_lower
    ]
    matched_negative_phrases = [
        phrase for phrase in negative_phrase_list
        if phrase in user_message_lower
    ]

    is_triggered = bool(matched_positive_phrases) and not bool(matched_negative_phrases)

    return {
        "triggered": is_triggered,
        "matched_positive": matched_positive_phrases,
        "matched_negative": matched_negative_phrases,
        "positive_phrases": positive_phrase_list,
        "negative_phrases": negative_phrase_list,
    }


# ── Skill folder chunking ─────────────────────────────────────────────────

def chunk_skill_folder(
    skill_folder_path: Path,
    budget_chars: int = 4000,
) -> Optional[str]:
    """Read and chunk a skill folder's SKILL.md + metadata for context injection.

    Reads SKILL.md as the primary content source. If the skill folder contains
    scripts/, references/, or resources/ subdirectories, appends a summary
    listing of their contents.

    Returns None if the skill folder or SKILL.md doesn't exist.
    Truncates output to budget_chars.
    """
    if not skill_folder_path.is_dir():
        semantic_trigger_module_logger.warning(
            "[SemanticTriggers] Skill folder not found: %s", skill_folder_path
        )
        return None

    skill_md_path = skill_folder_path / "SKILL.md"
    if not skill_md_path.is_file():
        semantic_trigger_module_logger.warning(
            "[SemanticTriggers] SKILL.md not found in: %s", skill_folder_path
        )
        return None

    try:
        skill_content_text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as read_error:
        semantic_trigger_module_logger.error(
            "[SemanticTriggers] Failed to read %s: %s", skill_md_path, read_error
        )
        return None

    # Build metadata footer
    metadata_footer_lines = [
        "",
        "---",
        f"Skill Directory: {skill_folder_path}",
        f"SKILL.md Path:   {skill_md_path}",
    ]

    for subdirectory_name in ("scripts", "references", "resources"):
        subdirectory_path = skill_folder_path / subdirectory_name
        if subdirectory_path.is_dir():
            try:
                relative_file_paths = sorted(
                    str(child_path.relative_to(skill_folder_path))
                    for child_path in subdirectory_path.rglob("*")
                    if child_path.is_file() and "__pycache__" not in child_path.parts
                )
                if relative_file_paths:
                    metadata_footer_lines.append(
                        f"{subdirectory_name.title()}: {', '.join(relative_file_paths)}"
                    )
            except OSError:
                pass

    metadata_footer = "\n".join(metadata_footer_lines)
    footer_len = len(metadata_footer) + 1 if metadata_footer else 0

    if len(skill_content_text) + footer_len > budget_chars:
        trunc_marker = "\n... [truncated]\n"
        allowed_body = budget_chars - footer_len - len(trunc_marker)
        if allowed_body > 0:
            skill_content_text = skill_content_text[:allowed_body] + trunc_marker
        else:
            combined = skill_content_text + (f"\n{metadata_footer}" if metadata_footer else "")
            if budget_chars > len(trunc_marker):
                return combined[:budget_chars - len(trunc_marker)] + "\n... [truncated]"
            return combined[:budget_chars]

    if metadata_footer:
        return f"{skill_content_text}\n{metadata_footer}"
    return skill_content_text


# ── Resolve skill:// protocol path ────────────────────────────────────────

def resolve_triggered_action_path(
    triggered_action_value: str,
    project_root_path: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a triggered_action value to a filesystem Path.

    Supports:
      - skill:///absolute/path/to/skill-folder → Path(/absolute/path/to/skill-folder)
      - skill://skills/<folder> → Path(project_root / skills / <folder>)
      - agy://<skill-name> → search project skills/, config/skills/, builtin/skills/
      - /absolute/path/to/skill-folder → Path(/absolute/path/to/skill-folder)

    Returns None if the value is empty or unrecognized.
    """
    if not triggered_action_value:
        return None

    action_text_stripped = triggered_action_value.strip()
    root_dir = project_root_path or Path(__file__).resolve().parent.parent

    if action_text_stripped.startswith(("agy://", "skill://")):
        prefix = "agy://" if action_text_stripped.startswith("agy://") else "skill://"
        target_path_str = action_text_stripped[len(prefix):].strip()
        candidate_path = Path(target_path_str)
        if candidate_path.is_absolute() and candidate_path.is_dir():
            return candidate_path
        if (root_dir / candidate_path).is_dir():
            return (root_dir / candidate_path).resolve()

        skill_name = target_path_str.strip("/")
        candidate_directories = [
            root_dir / "skills" / skill_name,
            Path("/data/data/com.termux/files/home/.gemini/config/skills") / skill_name,
            Path("/data/data/com.termux/files/home/.gemini/antigravity-cli/builtin/skills") / skill_name,
        ]
        for candidate in candidate_directories:
            if candidate.is_dir():
                return candidate.resolve()
        return (root_dir / candidate_path).resolve()

    elif action_text_stripped.startswith("/"):
        return Path(action_text_stripped)
    else:
        candidate_path = (root_dir / action_text_stripped).resolve()
        if candidate_path.is_dir():
            return candidate_path
        # Also check in skills/
        if (root_dir / "skills" / action_text_stripped).is_dir():
            return (root_dir / "skills" / action_text_stripped).resolve()
        semantic_trigger_module_logger.warning(
            "[SemanticTriggers] Unrecognized triggered_action format: %s",
            action_text_stripped,
        )
        return None


# ── Main scanning pipeline ────────────────────────────────────────────────

def scan_semantic_triggers(
    user_message_text: str,
    semantic_triggers_path: Path,
    cooldown_state: dict[str, float],
    now_timestamp: float,
    global_default_cooldown_seconds: int,
) -> list[dict[str, Any]]:
    """Scan semantic_triggers.bejson and evaluate conditions against user message.

    Returns a list of trigger result dicts, one per row, each containing:
      - 'trigger_name': str
      - 'semantic_conditions': str (raw pipe-separated)
      - 'negative_conditions': str (raw pipe-separated)
      - 'triggered_action': str (skill:// path)
      - 'priority': int
      - 'evaluation': dict from evaluate_semantic_conditions()
      - 'fired': bool — True if conditions met AND cooldown expired

    ALL triggers are returned (for conditions awareness display), with
    'fired' indicating which ones actually activated.
    """
    if not semantic_triggers_path.exists():
        return []

    trigger_document = _cached_read_semantic(
        semantic_triggers_path,
        lambda path_arg: bejson_core_load_file(str(path_arg)),
    )
    if not isinstance(trigger_document, dict):
        return []

    field_map = bejson_core_get_field_map(trigger_document)
    trigger_name_field_index = field_map["trigger_name"]
    semantic_conditions_field_index = field_map["semantic_conditions"]
    negative_conditions_field_index = field_map["negative_conditions"]
    triggered_action_field_index = field_map["triggered_action"]
    cooldown_seconds_field_index = field_map["cooldown_seconds"]
    priority_field_index = field_map["priority"]

    max_required_field_index = max(
        trigger_name_field_index, semantic_conditions_field_index,
        negative_conditions_field_index, triggered_action_field_index,
        cooldown_seconds_field_index, priority_field_index,
    )

    all_trigger_results: list[dict[str, Any]] = []

    for trigger_row in trigger_document.get("Values", []):
        if len(trigger_row) <= max_required_field_index:
            continue

        trigger_name_value = trigger_row[trigger_name_field_index] or ""
        semantic_conditions_value = trigger_row[semantic_conditions_field_index] or ""
        negative_conditions_value = trigger_row[negative_conditions_field_index] or ""
        triggered_action_value = trigger_row[triggered_action_field_index] or ""
        cooldown_seconds_value = trigger_row[cooldown_seconds_field_index]
        priority_value = trigger_row[priority_field_index] or 2

        if cooldown_seconds_value is None:
            cooldown_seconds_value = global_default_cooldown_seconds

        # Evaluate conditions
        evaluation_result = evaluate_semantic_conditions(
            user_message_text,
            semantic_conditions_value,
            negative_conditions_value,
        )

        # Check cooldown only if conditions are met
        trigger_fired = False
        if evaluation_result["triggered"]:
            cooldown_cache_key = f"semantic::{trigger_name_value}::{triggered_action_value}"
            last_fired_timestamp = cooldown_state.get(cooldown_cache_key, 0.0)
            if now_timestamp - last_fired_timestamp >= cooldown_seconds_value:
                cooldown_state[cooldown_cache_key] = now_timestamp
                trigger_fired = True

        all_trigger_results.append({
            "trigger_name": trigger_name_value,
            "semantic_conditions": semantic_conditions_value,
            "negative_conditions": negative_conditions_value,
            "triggered_action": triggered_action_value,
            "priority": priority_value,
            "evaluation": evaluation_result,
            "fired": trigger_fired,
        })

    # Sort by priority (1=highest), then by name
    all_trigger_results.sort(key=lambda trigger_entry: (trigger_entry["priority"], trigger_entry["trigger_name"]))

    return all_trigger_results


# ── Context Bubble section builders ───────────────────────────────────────

def build_conditions_awareness_section(
    all_trigger_results: list[dict[str, Any]],
    budget_chars: int = 2000,
) -> tuple[str, int]:
    """Build the always-visible conditions awareness table.

    This section is ALWAYS injected into the context window so the agent
    knows what semantic triggers exist and their boundaries — regardless
    of whether any triggered.

    Returns (section_text, chars_used).
    """
    if not all_trigger_results:
        return "", 0

    awareness_section_lines = [
        "Available semantic triggers (conditions → skill injection when met):",
    ]

    for trigger_result in all_trigger_results:
        trigger_name_display = trigger_result["trigger_name"]
        positive_conditions_display = trigger_result["semantic_conditions"].replace("|", ", ")
        negative_conditions_display = trigger_result["negative_conditions"].replace("|", ", ")
        evaluation_data = trigger_result["evaluation"]
        was_fired = trigger_result["fired"]

        # Status indicator
        if was_fired:
            status_indicator = "✓ ACTIVE"
        elif evaluation_data["matched_negative"]:
            status_indicator = "✗ BLOCKED"
        elif evaluation_data["matched_positive"]:
            status_indicator = "⏳ COOLDOWN"
        else:
            status_indicator = "○ IDLE"

        trigger_line = (
            f"- [{status_indicator}] **{trigger_name_display}** "
            f"(P{trigger_result['priority']})\n"
            f"  Conditions: {positive_conditions_display}\n"
            f"  Exclusions: {negative_conditions_display}"
        )
        awareness_section_lines.append(trigger_line)

    awareness_text = "\n".join(awareness_section_lines)

    if len(awareness_text) > budget_chars:
        awareness_text = awareness_text[:budget_chars - 20] + "\n... [truncated]"

    return awareness_text, len(awareness_text)


def build_triggered_actions_section(
    all_trigger_results: list[dict[str, Any]],
    budget_chars: int = 4000,
) -> tuple[str, int]:
    """Build the skill-injection section for fired triggers ONLY.

    This section is ONLY injected when at least one trigger's conditions
    are met. It chunks and injects each fired trigger's skill folder
    content into the context window.

    Returns (section_text, chars_used).
    """
    fired_trigger_results = [
        trigger_result for trigger_result in all_trigger_results
        if trigger_result["fired"]
    ]

    if not fired_trigger_results:
        return "", 0

    injected_skill_content_blocks: list[str] = []
    total_chars_used = 0
    injected_skill_paths_seen: set[str] = set()

    for fired_trigger in fired_trigger_results:
        triggered_action_value = fired_trigger["triggered_action"]

        # Dedup: same skill path triggered by multiple rows → inject once
        if triggered_action_value in injected_skill_paths_seen:
            continue
        injected_skill_paths_seen.add(triggered_action_value)

        resolved_skill_path = resolve_triggered_action_path(triggered_action_value)
        if resolved_skill_path is None:
            continue

        remaining_budget = budget_chars - total_chars_used
        if remaining_budget <= 100:
            break

        skill_chunk_text = chunk_skill_folder(resolved_skill_path, budget_chars=remaining_budget)
        if skill_chunk_text is None:
            continue

        skill_injection_header = (
            f"### Triggered: {fired_trigger['trigger_name']} "
            f"(matched: {', '.join(fired_trigger['evaluation']['matched_positive'])})"
        )
        full_injection_block = f"{skill_injection_header}\n{skill_chunk_text}"

        injected_skill_content_blocks.append(full_injection_block)
        total_chars_used += len(full_injection_block)

    if not injected_skill_content_blocks:
        return "", 0

    combined_injection_text = "\n\n".join(injected_skill_content_blocks)
    return combined_injection_text, len(combined_injection_text)


def build_semantic_triggers_context(
    user_message_text: str,
    semantic_triggers_path: Path,
    cooldown_state: dict[str, float],
    awareness_budget_chars: int = 2000,
    action_budget_chars: int = 4000,
    global_default_cooldown_seconds: int = 300,
) -> tuple[str, int, int]:
    """Top-level entry point: scan triggers, build both sections.

    Returns:
      (full_section_text, awareness_chars_used, action_chars_used)

    The full_section_text contains:
      1. The always-visible conditions awareness table
      2. The fired-only skill injection section (if any triggered)
    """
    now_timestamp = time.time()

    all_trigger_results = scan_semantic_triggers(
        user_message_text,
        semantic_triggers_path,
        cooldown_state,
        now_timestamp,
        global_default_cooldown_seconds,
    )

    if not all_trigger_results:
        return "", 0, 0

    awareness_text, awareness_chars_used = build_conditions_awareness_section(
        all_trigger_results, budget_chars=awareness_budget_chars,
    )

    actions_text, actions_chars_used = build_triggered_actions_section(
        all_trigger_results, budget_chars=action_budget_chars,
    )

    section_parts = []
    if awareness_text:
        section_parts.append(awareness_text)
    if actions_text:
        section_parts.append(actions_text)

    full_section_text = "\n\n".join(section_parts)
    return full_section_text, awareness_chars_used, actions_chars_used
