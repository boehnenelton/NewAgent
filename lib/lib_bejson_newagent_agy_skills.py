"""
Library:        lib_bejson_newagent_agy_skills.py
Family:         NewAgent
Description:    Config-gated Antigravity (agy) Skills Compatibility Layer for
                NewAgent. Provides discovery, keyword matching, Context Bubble
                injection, slash-command inspection (/skills), and <agy_skill>
                action execution across installed SKILL.md bundles as an
                alternative/complement to the built-in tool system.
                Strictly gated by config["agy_skills_enabled"] (default False):
                when False, all public entry points return immediately with zero
                filesystem I/O or prompt context overhead.
Version:        1.0.0
Date:           2026-10-24
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  9e624831-3b7c-491a-8d2e-5f1a9c4b7e02
"""

import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

VERSION = "1.0.0"
RELATIONAL_ID = "9e624831-3b7c-491a-8d2e-5f1a9c4b7e02"

module_agy_skills_logger = logging.getLogger(__name__)

DEFAULT_AGY_SKILLS_DIRECTORIES: list[str] = [
    str(Path(__file__).resolve().parent.parent / "skills"),
    "/data/data/com.termux/files/home/.gemini/config/skills",
    "/data/data/com.termux/files/home/.gemini/antigravity-cli/builtin/skills",
]

# In-memory cache keyed by tuple of directory paths -> (composite_mtime_signature, catalog_dict)
_cache_skill_catalog_store: dict[tuple[str, ...], tuple[float, dict[str, dict[str, Any]]]] = {}

_STOPWORD_TOKEN_SET: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "use", "when", "not",
    "into", "your", "are", "can", "will", "all", "any", "how", "what", "make",
    "please", "need", "want", "file", "files", "code", "tool", "tools", "run",
})


def is_agy_skills_enabled(agent_config_dict: Optional[dict[str, Any]]) -> bool:
    """Return True only when agy_skills_enabled is explicitly enabled in config."""
    if not isinstance(agent_config_dict, dict):
        return False
    raw_enabled_flag = agent_config_dict.get("agy_skills_enabled", False)
    if isinstance(raw_enabled_flag, bool):
        return raw_enabled_flag
    return str(raw_enabled_flag).strip().lower() == "true"


def get_configured_skill_directories(agent_config_dict: Optional[dict[str, Any]]) -> list[Path]:
    """Return resolved Path objects for configured agy_skills_directories."""
    if not isinstance(agent_config_dict, dict):
        raw_directory_list: Any = DEFAULT_AGY_SKILLS_DIRECTORIES
    else:
        raw_directory_list = agent_config_dict.get(
            "agy_skills_directories", DEFAULT_AGY_SKILLS_DIRECTORIES
        )
    if isinstance(raw_directory_list, str):
        stripped_text = raw_directory_list.strip()
        if stripped_text.startswith("["):
            import json
            try:
                raw_directory_list = json.loads(stripped_text)
            except Exception:
                raw_directory_list = [stripped_text]
        else:
            raw_directory_list = [
                segment.strip() for segment in stripped_text.split(",") if segment.strip()
            ]
    if not isinstance(raw_directory_list, list):
        raw_directory_list = list(DEFAULT_AGY_SKILLS_DIRECTORIES)

    resolved_directory_paths: list[Path] = []
    for directory_entry in raw_directory_list:
        if directory_entry:
            expanded_path = Path(os.path.expandvars(os.path.expanduser(str(directory_entry))))
            resolved_directory_paths.append(expanded_path)
    return resolved_directory_paths


def _parse_skill_frontmatter(skill_markdown_text: str, fallback_skill_name: str) -> tuple[str, str, str]:
    """Extract (skill_name, skill_description, markdown_body) from SKILL.md YAML frontmatter."""
    parsed_skill_name = fallback_skill_name
    parsed_skill_description = ""
    markdown_body_text = skill_markdown_text

    if skill_markdown_text.startswith("---"):
        frontmatter_End_index = skill_markdown_text.find("\n---", 3)
        if frontmatter_End_index != -1:
            frontmatter_block = skill_markdown_text[3:frontmatter_End_index].strip()
            markdown_body_text = skill_markdown_text[frontmatter_End_index + 4:].lstrip("\r\n")

            current_multiline_key: Optional[str] = None
            multiline_buffer_lines: list[str] = []

            for raw_line in frontmatter_block.splitlines():
                stripped_line = raw_line.strip()
                if not stripped_line or stripped_line.startswith("#"):
                    continue
                if not raw_line.startswith((" ", "\t")) and ":" in raw_line:
                    if current_multiline_key == "description" and multiline_buffer_lines:
                        parsed_skill_description = " ".join(multiline_buffer_lines).strip()
                    multiline_buffer_lines = []
                    current_multiline_key = None

                    field_key, field_raw_value = raw_line.split(":", 1)
                    normalized_key = field_key.strip().lower()
                    cleaned_value = field_raw_value.strip().strip("'\"")
                    if normalized_key == "name" and cleaned_value:
                        parsed_skill_name = cleaned_value
                    elif normalized_key == "description":
                        if cleaned_value in ("|", ">", "|+", ">+", "|-", ">-"):
                            current_multiline_key = "description"
                        elif cleaned_value:
                            parsed_skill_description = cleaned_value
                            current_multiline_key = "description"
                            multiline_buffer_lines = [cleaned_value]
                        else:
                            current_multiline_key = "description"
                elif current_multiline_key == "description":
                    multiline_buffer_lines.append(stripped_line)

            if current_multiline_key == "description" and multiline_buffer_lines:
                parsed_skill_description = " ".join(multiline_buffer_lines).strip()

    if not parsed_skill_description:
        for body_line in markdown_body_text.splitlines():
            clean_body_line = body_line.strip()
            if clean_body_line and not clean_body_line.startswith("#"):
                parsed_skill_description = clean_body_line[:280]
                break

    return parsed_skill_name, parsed_skill_description, markdown_body_text


def _list_relative_files_in_subdir(skill_root_dir: Path, subdir_name: str) -> list[str]:
    """List relative file paths inside a skill subdirectory (e.g. scripts/, references/)."""
    target_subdir = skill_root_dir / subdir_name
    if not target_subdir.is_dir():
        return []
    discovered_rel_paths: list[str] = []
    try:
        for child_path in sorted(target_subdir.rglob("*")):
            if child_path.is_file() and "__pycache__" not in child_path.parts:
                discovered_rel_paths.append(str(child_path.relative_to(skill_root_dir)))
    except OSError:
        pass
    return discovered_rel_paths


def discover_installed_agy_skills(
    agent_config_dict: Optional[dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Discover installed Antigravity (agy) SKILL.md bundles when agy_skills_enabled is True.
    Returns an empty dict immediately when agy_skills_enabled is False.
    """
    if not is_agy_skills_enabled(agent_config_dict):
        return {}

    configured_dirs = get_configured_skill_directories(agent_config_dict)
    cache_key_tuple = tuple(str(dir_path) for dir_path in configured_dirs)

    composite_mtime_sum = 0.0
    for skill_root_parent in configured_dirs:
        if skill_root_parent.is_dir():
            try:
                composite_mtime_sum += skill_root_parent.stat().st_mtime
            except OSError:
                pass

    if not force_refresh and cache_key_tuple in _cache_skill_catalog_store:
        cached_mtime, cached_catalog = _cache_skill_catalog_store[cache_key_tuple]
        if cached_mtime == composite_mtime_sum:
            return cached_catalog

    discovered_catalog: dict[str, dict[str, Any]] = {}
    for skill_root_parent in configured_dirs:
        if not skill_root_parent.is_dir():
            continue
        try:
            child_entries = sorted(skill_root_parent.iterdir(), key=lambda entry: entry.name)
        except OSError:
            continue

        for skill_folder_path in child_entries:
            if not skill_folder_path.is_dir():
                continue
            skill_md_path = skill_folder_path / "SKILL.md"
            if not skill_md_path.is_file():
                continue
            try:
                raw_markdown_content = skill_md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            fallback_folder_name = skill_folder_path.name.replace("_", "-")
            skill_name, skill_description, _ = _parse_skill_frontmatter(
                raw_markdown_content, fallback_folder_name
            )
            normalized_skill_key = skill_name.strip()
            if normalized_skill_key in discovered_catalog:
                continue

            discovered_catalog[normalized_skill_key] = {
                "skill_name": normalized_skill_key,
                "folder_name": skill_folder_path.name,
                "skill_description": skill_description,
                "skill_md_path": str(skill_md_path.resolve()),
                "skill_dir_path": str(skill_folder_path.resolve()),
                "scripts": _list_relative_files_in_subdir(skill_folder_path, "scripts"),
                "references": _list_relative_files_in_subdir(skill_folder_path, "references"),
                "resources": _list_relative_files_in_subdir(skill_folder_path, "resources"),
            }

    _cache_skill_catalog_store[cache_key_tuple] = (composite_mtime_sum, discovered_catalog)
    return discovered_catalog


def match_agy_skills_for_prompt(
    user_prompt_text: str,
    agent_config_dict: Optional[dict[str, Any]],
    max_matched_skills: int = 5,
) -> list[dict[str, Any]]:
    """
    Match user_prompt_text against discovered agy skills by name and description keywords.
    Returns [] immediately if agy_skills_enabled is False.
    """
    if not is_agy_skills_enabled(agent_config_dict) or not user_prompt_text:
        return []

    skill_catalog = discover_installed_agy_skills(agent_config_dict)
    if not skill_catalog:
        return []

    prompt_lower_text = user_prompt_text.lower()
    prompt_word_tokens = {
        word_token
        for word_token in re.findall(r"[a-z0-9]{3,}", prompt_lower_text)
        if word_token not in _STOPWORD_TOKEN_SET
    }
    if not prompt_word_tokens:
        return []

    scored_skill_records: list[tuple[int, str, dict[str, Any]]] = []
    for skill_key, skill_record in skill_catalog.items():
        relevance_score = 0
        skill_name_lower = skill_key.lower()
        folder_name_lower = skill_record.get("folder_name", "").lower()

        if skill_name_lower in prompt_lower_text or folder_name_lower in prompt_lower_text:
            relevance_score += 20

        name_part_tokens = {
            part_token
            for part_token in re.findall(r"[a-z0-9]{3,}", skill_name_lower)
            if part_token not in _STOPWORD_TOKEN_SET
        }
        matched_name_parts = prompt_word_tokens & name_part_tokens
        relevance_score += len(matched_name_parts) * 5

        description_lower = skill_record.get("skill_description", "").lower()
        # Score positive part of description (before "Do NOT use")
        positive_description_segment = description_lower.split("do not use")[0]
        description_tokens = {
            desc_token
            for desc_token in re.findall(r"[a-z0-9]{3,}", positive_description_segment)
            if desc_token not in _STOPWORD_TOKEN_SET
        }
        matched_desc_tokens = prompt_word_tokens & description_tokens
        relevance_score += len(matched_desc_tokens) * 2

        if relevance_score >= 4:
            scored_skill_records.append((relevance_score, skill_key, skill_record))

    scored_skill_records.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in scored_skill_records[:max_matched_skills]]


def build_agy_skills_context_section(
    user_prompt_text: str,
    agent_config_dict: Optional[dict[str, Any]],
    budget_chars: int = 1600,
) -> tuple[str, int]:
    """
    Build the Context Bubble section for Antigravity (agy) skills when enabled.
    Returns ("", 0) immediately when agy_skills_enabled is False.
    """
    if not is_agy_skills_enabled(agent_config_dict):
        return "", 0

    skill_catalog = discover_installed_agy_skills(agent_config_dict)
    if not skill_catalog:
        return "", 0

    matched_skills = match_agy_skills_for_prompt(
        user_prompt_text, agent_config_dict, max_matched_skills=5
    )

    section_lines: list[str] = [
        "## Antigravity (agy) Skills Compatibility Layer (ENABLED)",
        f"- **{len(skill_catalog)} installed `agy` skills** available as an alternative/complement to built-in tools.",
        "- Action tags:",
        '  - `<agy_skill action="list"/>` — list all installed skills (optional `filter="keyword"`).',
        '  - `<agy_skill name="<skill-name>" action="read"/>` — load full `SKILL.md` instructions and bundled script paths.',
        '  - `<agy_skill name="<skill-name>" action="exec" script="scripts/<file>.py">args</agy_skill>` — run a skill helper script.',
    ]

    if matched_skills:
        section_lines.append("- **Relevant skills matched for current prompt**:")
        for matched_entry in matched_skills:
            short_desc = matched_entry.get("skill_description", "")
            if len(short_desc) > 160:
                short_desc = short_desc[:157] + "..."
            scripts_list = matched_entry.get("scripts", [])
            scripts_note = f" (scripts: {len(scripts_list)})" if scripts_list else ""
            section_lines.append(
                f"  - `{matched_entry['skill_name']}`{scripts_note}: {short_desc}"
            )

    assembled_text = "\n".join(section_lines)
    if len(assembled_text) > budget_chars:
        assembled_text = assembled_text[: max(0, budget_chars - 18)] + "\n...[truncated]"
    return assembled_text, len(matched_skills)


def execute_agy_skill_action(
    skill_action_attrs: dict[str, str],
    skill_action_content: str,
    current_working_dir: str,
    agent_config_dict: Optional[dict[str, Any]],
) -> tuple[int, str]:
    """
    Execute an <agy_skill ...> action tag.
    Strictly checks is_agy_skills_enabled(agent_config_dict) first.
    """
    if not is_agy_skills_enabled(agent_config_dict):
        return (
            1,
            "[DISABLED] Antigravity (agy) skills compatibility layer is disabled "
            "(agy_skills_enabled=false in config/config.json). Enable via '/skills on' "
            "or set agy_skills_enabled to 'true' in config/config.json.",
        )

    skill_catalog = discover_installed_agy_skills(agent_config_dict)
    requested_action_mode = (
        skill_action_attrs.get("action")
        or skill_action_attrs.get("mode")
        or ("exec" if skill_action_attrs.get("script") else "")
        or ("read" if skill_action_attrs.get("name") or skill_action_content.strip() else "list")
    ).strip().lower()

    target_skill_name = (
        skill_action_attrs.get("name")
        or skill_action_attrs.get("skill")
        or (skill_action_content.strip() if requested_action_mode == "read" else "")
    ).strip()

    if requested_action_mode == "list":
        filter_keyword = (
            skill_action_attrs.get("filter") or skill_action_content.strip()
        ).lower()
        matching_lines: list[str] = []
        for skill_key in sorted(skill_catalog.keys()):
            skill_meta = skill_catalog[skill_key]
            skill_desc = skill_meta.get("skill_description", "")
            if filter_keyword and (
                filter_keyword not in skill_key.lower()
                and filter_keyword not in skill_desc.lower()
            ):
                continue
            short_desc = skill_desc[:140] + ("..." if len(skill_desc) > 140 else "")
            matching_lines.append(f"- {skill_key}: {short_desc}")
        header_line = (
            f"[AGY SKILLS] {len(matching_lines)}/{len(skill_catalog)} skill(s)"
            + (f" matching '{filter_keyword}':" if filter_keyword else ":")
        )
        return 0, header_line + ("\n" + "\n".join(matching_lines) if matching_lines else " (none)")

    # Resolve target skill by exact name or folder name
    resolved_skill_meta = skill_catalog.get(target_skill_name)
    if not resolved_skill_meta and target_skill_name:
        normalized_lookup = target_skill_name.lower().replace("_", "-")
        for candidate_key, candidate_meta in skill_catalog.items():
            if (
                candidate_key.lower() == normalized_lookup
                or candidate_meta.get("folder_name", "").lower().replace("_", "-") == normalized_lookup
            ):
                resolved_skill_meta = candidate_meta
                break

    if not resolved_skill_meta:
        return (
            1,
            f"[AGY SKILL NOT FOUND] '{target_skill_name}'. Use <agy_skill action=\"list\"/> "
            f"to view the {len(skill_catalog)} available skills.",
        )

    if requested_action_mode == "read":
        skill_md_file = Path(resolved_skill_meta["skill_md_path"])
        try:
            full_skill_text = skill_md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as read_err:
            return 1, f"[ERROR] Could not read {skill_md_file}: {read_err}"

        summary_footer_lines = [
            "",
            "---",
            f"Skill Directory: {resolved_skill_meta['skill_dir_path']}",
            f"SKILL.md Path:   {resolved_skill_meta['skill_md_path']}",
        ]
        if resolved_skill_meta.get("scripts"):
            summary_footer_lines.append(
                "Bundled Scripts: " + ", ".join(resolved_skill_meta["scripts"])
            )
        if resolved_skill_meta.get("references"):
            summary_footer_lines.append(
                "References:      " + ", ".join(resolved_skill_meta["references"])
            )
        if resolved_skill_meta.get("resources"):
            summary_footer_lines.append(
                "Resources:       " + ", ".join(resolved_skill_meta["resources"])
            )
        return 0, full_skill_text + "\n".join(summary_footer_lines)

    if requested_action_mode == "exec":
        script_rel_arg = (skill_action_attrs.get("script") or "").strip()
        if not script_rel_arg:
            available_scripts = resolved_skill_meta.get("scripts", [])
            if len(available_scripts) == 1:
                script_rel_arg = available_scripts[0]
            else:
                return (
                    1,
                    f"[ERROR] Missing script attribute for <agy_skill action=\"exec\" name=\"{resolved_skill_meta['skill_name']}\"/>. "
                    f"Available scripts: {available_scripts}",
                )

        skill_root_dir = Path(resolved_skill_meta["skill_dir_path"]).resolve()
        candidate_script_path = (skill_root_dir / script_rel_arg).resolve()
        if not candidate_script_path.is_file() and not script_rel_arg.startswith("scripts/"):
            alt_script_path = (skill_root_dir / "scripts" / script_rel_arg).resolve()
            if alt_script_path.is_file():
                candidate_script_path = alt_script_path

        # Path traversal guard: script must reside inside skill_root_dir
        try:
            candidate_script_path.relative_to(skill_root_dir)
        except ValueError:
            return 1, f"[BLOCKED] Script path '{script_rel_arg}' escapes skill root directory."

        if not candidate_script_path.is_file():
            return (
                1,
                f"[ERROR] Script '{script_rel_arg}' not found in {skill_root_dir}. "
                f"Available scripts: {resolved_skill_meta.get('scripts', [])}",
            )

        extra_cli_args: list[str] = []
        if skill_action_content and skill_action_content.strip():
            try:
                extra_cli_args = shlex.split(skill_action_content.strip())
            except ValueError:
                extra_cli_args = skill_action_content.strip().split()

        if candidate_script_path.suffix == ".py":
            exec_argv = ["python3", str(candidate_script_path)] + extra_cli_args
        elif candidate_script_path.suffix == ".sh":
            exec_argv = ["bash", str(candidate_script_path)] + extra_cli_args
        else:
            exec_argv = [str(candidate_script_path)] + extra_cli_args

        timeout_secs = int((agent_config_dict or {}).get("exec_timeout_seconds", 60))
        try:
            completed_proc = subprocess.run(
                exec_argv,
                cwd=current_working_dir or str(skill_root_dir),
                capture_output=True,
                text=True,
                timeout=timeout_secs,
            )
            combined_output = (
                (completed_proc.stdout or "") + (completed_proc.stderr or "")
            ).strip()
            return completed_proc.returncode, combined_output or "(no output)"
        except subprocess.TimeoutExpired:
            return 124, f"[TIMEOUT] Skill script exceeded {timeout_secs}s limit"
        except Exception as exec_exc:
            return 1, f"[EXEC ERROR] {exec_exc}"

    return 1, f"[ERROR] Unknown agy_skill action '{requested_action_mode}'. Use 'list', 'read', or 'exec'."


def format_agy_skills_status_report(
    agent_config_dict: Optional[dict[str, Any]],
    filter_query: str = "",
) -> str:
    """Format a status and catalog summary for the /skills slash command."""
    enabled_flag = is_agy_skills_enabled(agent_config_dict)
    configured_dirs = [str(p) for p in get_configured_skill_directories(agent_config_dict)]
    status_label = "ENABLED (true)" if enabled_flag else "DISABLED (false)"

    report_lines = [
        f"Antigravity (agy) Skills Compatibility Layer: {status_label}",
        f"Config key: agy_skills_enabled = {str(enabled_flag).lower()}",
        f"Directories: {', '.join(configured_dirs)}",
    ]
    if not enabled_flag:
        report_lines.append(
            "Use '/skills on' to enable (persists to config/config.json) or '/skills off' to disable."
        )
        return "\n".join(report_lines)

    skill_catalog = discover_installed_agy_skills(agent_config_dict)
    report_lines.append(f"Discovered skills: {len(skill_catalog)}")
    normalized_filter = filter_query.strip().lower()
    displayed_count = 0
    for skill_key in sorted(skill_catalog.keys()):
        skill_meta = skill_catalog[skill_key]
        skill_desc = skill_meta.get("skill_description", "")
        if normalized_filter and (
            normalized_filter not in skill_key.lower()
            and normalized_filter not in skill_desc.lower()
        ):
            continue
        short_desc = skill_desc[:100] + ("..." if len(skill_desc) > 100 else "")
        report_lines.append(f"  - {skill_key}: {short_desc}")
        displayed_count += 1
        if not normalized_filter and displayed_count >= 25:
            remaining_count = len(skill_catalog) - displayed_count
            if remaining_count > 0:
                report_lines.append(
                    f"  ... and {remaining_count} more (use '/skills list <keyword>' or '/skills info <name>')."
                )
            break
    return "\n".join(report_lines)
