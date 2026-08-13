"""
Library:        lib_bejson_newagent_tui.py
Family:         NewAgent
Description:    TUI rendering, color palette, and session statistics.
Version:        1.2.1
Date:           2026-07-23
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  7be14cf5-d96f-4bf1-966e-57d453c6a6f8
"""

import os
import re
from dataclasses import dataclass

VERSION = "1.2.1"

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


def clean_display_tags(text: str) -> str:
    """
    Extract human-readable content from model output for the compact history
    view: keep <speak>...</speak> narration (the model's only user-facing
    channel), strip other action tags (<exec>, <edit_file>, etc.) along with
    their payloads since those are internal instructions, not conversation.

    Previously this stripped <tag>...</tag> as one unit for every tag,
    which deleted the *enclosed text too* -- including <speak> content. Since
    REST-mode responses are typically entirely composed of action tags, that
    meant the history panel showed a role badge with the model's entire
    response silently deleted: no error, just an empty line where the
    reply should be.
    """
    speak_blocks = re.findall(r"<speak>(.*?)</speak>", text, flags=re.DOTALL)
    if speak_blocks:
        return "\n".join(s.strip() for s in speak_blocks if s.strip())

    stripped = re.sub(r"<[^>]+>.*?</[^>]+>|<[^>]+/?>", "", text, flags=re.DOTALL).strip()
    if not stripped and text.strip():
        # The whole response was action tags with no <speak> narration at
        # all -- real, silent tool-only turn. Say so rather than showing an
        # unexplained blank line that looks identical to a bug.
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

    if not pairs:
        print(f"{C.WHITE_DIM}  (no history){C.RESET}")
    else:
        content_width = max(width - 2, 20)
        for u, m in pairs[-history_rows:]:
            ts       = u.get("_ts", "")
            u_text   = clean_display_tags(u.get("content", ""))
            m_text   = clean_display_tags(m.get("content", ""))
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
