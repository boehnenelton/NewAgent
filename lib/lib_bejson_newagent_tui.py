"""
Library:        lib_bejson_newagent_tui.py
Family:         NewAgent
Description:    TUI rendering, color palette, and session statistics.
Version:        1.3.0
Date:           2026-11-14
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  7be14cf5-d96f-4bf1-966e-57d453c6a6f8
"""

import os
import re
from dataclasses import dataclass

VERSION = "1.3.0"

class C:
    RESET    = "\033[0m"
    BOLD     = "\033[1m"
    DIM      = "\033[2m"
    WHITE    = "\033[97m"
    WHITE_B  = "\033[1;97m"
    WHITE_DIM = "\033[2;97m"
    RED      = "\033[38;2;222;38;38m"
    RED_B    = "\033[1;38;2;222;38;38m"
    RED_BG   = "\033[48;2;222;38;38m"
    YELLOW   = "\033[38;2;240;185;11m"
    YELLOW_BG = "\033[48;2;240;185;11m"

    @staticmethod
    def strip(s: str) -> str:
        return re.sub(r"\033\[[^m]*m", "", s)


@dataclass
class ExecResult:
    action_type: str
    source: str
    output: str
    exit_code: int = 0
    cmd: str = ""


@dataclass
class SessionStats:
    turns: int = 0
    turns_sent: int = 0
    execs: int = 0
    key_slot: int = 0
    key_total: int = 0
    engine: str = "rest"
    input_tokens: int = 0
    output_tokens: int = 0


def get_term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def truncate_string(s: str, max_len: int) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def wrap_and_cap(text: str, width: int, max_lines: int = 8) -> list[str]:
    """
    Word-wrap text to `width` columns, capped at `max_lines` lines total.
    If the text is longer than max_lines allows, the last visible line is
    truncated with a trailing ellipsis rather than silently dropping the
    remainder with no indication more content exists.
    Replaces the old single-line truncate_string() use for full replies,
    which crushed multi-paragraph model responses down to a handful of
    characters on narrow (phone-width) terminals.
    """
    import textwrap
    width = max(width, 10)
    lines: list[str] = []
    for para in text.splitlines() or [""]:
        wrapped = textwrap.wrap(para, width=width) or [""]
        lines.extend(wrapped)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last[:width - 1] + "…") if len(last) >= width else (last + " …")
    return lines


def clean_display_tags(text: str, show_commands: bool = True) -> str:
    """
    Extract human-readable content from turn messages for the history view.
    When show_commands is False:
      Extract <speak>...</speak> narration and strip other action tags (<exec>, <edit_file>, etc.)
      along with their payloads.
    When show_commands is True (default):
      Preserve action tags (<exec>cmd</exec>, etc.) and format outgoing action results
      so that model response commands and outgoing results remain visible to the user.
    """
    if not show_commands:
        speak_blocks = re.findall(r"<speak>(.*?)</speak>", text, flags=re.DOTALL)
        if speak_blocks:
            return "\n".join(s.strip() for s in speak_blocks if s.strip())

        stripped = re.sub(r"<[^>]+>.*?</[^>]+>|<[^>]+/?>", "", text, flags=re.DOTALL).strip()
        if not stripped and text.strip():
            return "[actions executed, no narration]"
        return stripped

    # 1. Action results payload (outgoing user-system action results)
    result_blocks = re.findall(r"<(\w+)_result(?:\s+[^>]*?)?>(.*?)</\1_result>", text, flags=re.DOTALL)
    if result_blocks:
        formatted_res = []
        for tag, content in result_blocks:
            content_clean = content.strip()
            first_line = content_clean.splitlines()[0] if content_clean else "(empty)"
            formatted_res.append(f"[{tag}_result] {first_line}")
        return "\n".join(formatted_res)

    # 2. Extract speak narration blocks
    speak_blocks = [s.strip() for s in re.findall(r"<speak>(.*?)</speak>", text, flags=re.DOTALL) if s.strip()]

    # 3. Extract action tags
    action_matches = re.findall(
        r"<(exec|read_file|write_file|edit_file|list_dir|tree_view|make_dir|delete_file|"
        r"copy_file|diff_file|restore_file|http_get|find_files|search_text|fuzzy_find|env_get|"
        r"checkpoint|checklist_create|checklist_check|checklist_add|checklist_view|"
        r"html_report|html_report_append|project_log|request_continue|"
        r"bejson_fields|bejson_add_field|bejson_delete_field|bejson_create_record|"
        r"bejson_delete_record|bejson_set_value|bejson_columns|bejson_create|context_set|"
        r"exec_bg|task_status|task_kill|task_list|job_task_done|agy_skill)(?:\s+([^>]*?))?(?<!/)>(.*?)</\1>|"
        r"<(copy_file|task_list|job_task_done|agy_skill)(?:\s+([^>]*?))?\s*/>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    formatted_actions = []
    for m in action_matches:
        tag = m[0] or m[3]
        attrs = (m[1] or m[4] or "").strip()
        body = (m[2] or "").strip()
        if tag.lower() == "exec":
            formatted_actions.append(f"<exec>{body}</exec>")
        elif body:
            attr_str = f" {attrs}" if attrs else ""
            body_snippet = body.splitlines()[0][:60] if body else ""
            formatted_actions.append(f"<{tag}{attr_str}>{body_snippet}</{tag}>")
        else:
            attr_str = f" {attrs}" if attrs else ""
            formatted_actions.append(f"<{tag}{attr_str}/>")

    items = []
    if speak_blocks:
        items.extend(speak_blocks)
    if formatted_actions:
        items.extend(formatted_actions)
    if items:
        return "\n".join(items)

    stripped = re.sub(r"<[^>]+>.*?</[^>]+>|<[^>]+/?>", "", text, flags=re.DOTALL).strip()
    if not stripped and text.strip():
        return "[actions executed, no narration]"
    return stripped


def _fmt_tokens(input_tok: int, output_tok: int) -> str:
    """Format token usage for the header bar. Returns empty string if both are zero."""
    if not input_tok and not output_tok:
        return ""
    def _abbr(n: int) -> str:
        return f"{n/1000:.1f}k" if n >= 1000 else str(n)
    return f" ↑{_abbr(input_tok)} ↓{_abbr(output_tok)}"


def refresh_ui(
    *,
    history: list[dict],
    exec_results: list[ExecResult],
    stats: SessionStats,
    cwd: str,
    status: str = "",
    history_rows: int = 6,
    dryrun: bool = False,
    input_mode: int = 0,
    agent_version: str = "",
    context_bloat: bool = False,
    show_outgoing_prompts: bool = True,
    show_response_commands: bool = True,
) -> None:
    width = get_term_width()
    bar = "═" * width

    # ── Clear terminal ──────────────────────────────────────────────────────────
    print("\033[2J\033[H", end="")

    # ── Header bar ─────────────────────────────────────────────────────────────
    ver = agent_version or VERSION
    engine_badge = f"[{stats.engine.upper()}]"
    badges = ""
    if dryrun:
        badges += f" {C.YELLOW_BG}\033[30m[DRYRUN]{C.RESET}{C.WHITE_B}"
    if context_bloat:
        badges += f" {C.YELLOW_BG}\033[30m[CTX BLOAT]{C.RESET}{C.WHITE_B}"
    if input_mode == 1:
        badges += " [STT]"
    elif input_mode == 2:
        badges += " [DLG]"

    token_info = _fmt_tokens(stats.input_tokens, stats.output_tokens)

    left  = f" NewAgent v{ver} {engine_badge}{badges}"
    right = f"T:{stats.turns} E:{stats.execs} K:{stats.key_slot}/{stats.key_total}{token_info} "

    # Calculate padding accounting for ANSI escape codes
    left_visible  = f" NewAgent v{ver} {C.strip(engine_badge)}{C.strip(badges)}"
    right_visible = C.strip(right)
    pad = max(0, width - len(left_visible) - len(right_visible))

    print(f"{C.RED_BG}{C.WHITE_B}{left}{' ' * pad}{right}{C.RESET}")
    print(f"{C.WHITE_DIM}{bar}{C.RESET}")

    # ── History panel ──────────────────────────────────────────────────────────
    # Show last N user/model pairs
    visible = history[-(history_rows * 2):]
    pairs: list[tuple[dict, dict]] = []
    i = 0
    while i < len(visible) - 1:
        if visible[i]["role"] == "user" and visible[i + 1]["role"] == "model":
            pairs.append((visible[i], visible[i + 1]))
            i += 2
        else:
            i += 1

    trailing_user = None
    if show_outgoing_prompts and visible and visible[-1]["role"] == "user":
        if not pairs or pairs[-1][0] is not visible[-1]:
            trailing_user = visible[-1]

    if not pairs and not trailing_user:
        print(f"{C.WHITE_DIM}  (no history){C.RESET}")
    else:
        content_width = max(width - 2, 20)
        for u, m in pairs[-history_rows:]:
            ts       = u.get("_ts", "")
            u_text   = clean_display_tags(u.get("content", ""), show_commands=show_response_commands)
            m_text   = clean_display_tags(m.get("content", ""), show_commands=show_response_commands)
            m_ts     = m.get("_ts", "")

            u_lines = wrap_and_cap(u_text, content_width, max_lines=8)
            m_lines = wrap_and_cap(m_text, content_width, max_lines=8)

            print(f"{C.WHITE_DIM}{ts} {C.RESET}{C.WHITE_B}[YOU]{C.RESET}")
            for line in u_lines:
                print(f"  {C.WHITE}{line}{C.RESET}")
            print()

            print(f"{C.WHITE_DIM}{m_ts} {C.RESET}{C.RED_B}[GEMINI]{C.RESET}")
            for line in m_lines:
                print(f"  {C.WHITE}{line}{C.RESET}")
            print()

        if trailing_user:
            ts = trailing_user.get("_ts", "")
            u_text = clean_display_tags(trailing_user.get("content", ""), show_commands=show_response_commands)
            u_lines = wrap_and_cap(u_text, content_width, max_lines=8)
            print(f"{C.WHITE_DIM}{ts} {C.RESET}{C.WHITE_B}[YOU]{C.RESET} {C.YELLOW}[OUTGOING]{C.RESET}")
            for line in u_lines:
                print(f"  {C.WHITE}{line}{C.RESET}")
            print()

    # ── Exec output panel ──────────────────────────────────────────────────────
    if exec_results:
        print(f"{C.WHITE_DIM}{bar}{C.RESET}")
        for r in exec_results[-10:]:
            icon = f"{C.WHITE_B}✓{C.RESET}" if r.exit_code == 0 else f"{C.RED_B}✗{C.RESET}"
            src  = truncate_string(r.source, 40)
            print(f"  {icon} {C.RED}{r.action_type}{C.RESET}  {C.WHITE_DIM}{src}{C.RESET}")
            for line in wrap_and_cap(r.output, width - 10, max_lines=8):
                print(f"       {C.WHITE_DIM}{line}{C.RESET}")

    # ── CWD & status bar ───────────────────────────────────────────────────────
    print(f"{C.WHITE_DIM}{bar}{C.RESET}")
    if status:
        # "Error" and "API Error" in red, status messages in dim white
        if status.lower().startswith(("api error", "error")):
            print(f"  {C.RED_B}{status}{C.RESET}")
        else:
            print(f"  {C.WHITE_DIM}{status}{C.RESET}")
    print(f"  {C.WHITE_B}{cwd}{C.RESET}")
    print(f"{C.WHITE_DIM}{bar}{C.RESET}")
