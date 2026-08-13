"""
Library:        lib_bejson_newagent_startup.py
Family:         NewAgent
Description:    POWERED BY BEJSON intro splash screen with animated reveal.
Version:        2.0.0
Date:           2026-08-09
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  bd7b110e-1a17-4ebd-81ce-f14fe85fde92

CHANGELOG:
- 2.0.0 (2026-08-09): Replaced the fixed-width ASCII block-letter art
  entirely -- per Elton, it has never fit a mobile screen (BEJSON art was
  54 chars wide, NEWAGENT art was 75, both hardcoded regardless of actual
  terminal size, guaranteed to wrap/break on any phone-width terminal).
  New _drop_reveal_word() renders each word as plain, width-relative
  centered text -- "B E J S O N" then "NEW A G E N T" -- comfortably under
  20 chars even fully spaced, safe on any realistic terminal width. Each
  letter animates in independently: it falls down its own column as a
  random JSON-syntax glyph ({ } [ ] : , " 0 1 -- a direct nod to BEJSON
  itself) from a randomized height, then locks into the real letter the
  moment it lands. Different letters land at different times, so the word
  assembles progressively, "one letter at a time," rather than snapping
  in all at once, with each letter finding its own correct column
  independent of its neighbors ("vacuumed into the right column").
  Implemented with ANSI save/restore-cursor (\033[s / \033[u) plus
  purely relative movement from that anchor for every frame -- deliberately
  avoids absolute row addressing, which would require knowing the
  terminal's current absolute cursor row (not reliably queryable in a
  simple portable way). This carries the same class of cross-terminal
  ANSI-support risk the existing _loading_bar's \r-redraw already
  accepts (see its own docstring) -- worst case on an unsupportive
  terminal is a garbled-looking reveal, not a crash, consistent with that
  established precedent.
"""

import os
import random
import sys
import time
from datetime import datetime

VERSION = "2.0.0"

# -- Color constants ---------------------------------------------------------
_RESET     = "\033[0m"
_BOLD      = "\033[1m"
_DIM       = "\033[2m"
_RED       = "\033[38;2;222;38;38m"
_RED_B     = "\033[1;38;2;222;38;38m"
_RED_BG    = "\033[48;2;222;38;38m"
_WHITE     = "\033[97m"
_WHITE_B   = "\033[1;97m"
_WHITE_DIM = "\033[2;97m"
_DARK      = "\033[38;2;80;10;10m"

# Falling "rain" glyphs -- JSON syntax characters, since BEJSON is the
# product being spelled out. The symbolism: raw JSON-shaped noise falling
# and resolving into structured, named letters, mirrors what BEJSON (the
# format) actually does to a document.
_RAIN_CHARS = '{}[]:,"01'


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _center(text: str, width: int) -> str:
    """Center a string accounting for ANSI escape sequences."""
    import re
    visible_len = len(re.sub(r"\033\[[^m]*m", "", text))
    pad = max(0, (width - visible_len) // 2)
    return " " * pad + text


def _bar(width: int, char: str = "═") -> str:
    return f"{_RED_B}{char * width}{_RESET}"


def _print_centered(text: str, width: int, color: str = "") -> None:
    print(_center(f"{color}{text}{_RESET if color else ''}", width))


def _fit_segments(segments: list, width: int, prefix: str = "  ", sep: str = "  ·  ") -> str:
    """
    Joins `segments` (most-important-first) with `sep`, dropping from the
    END (least important) until the result fits `width`. Falls back to a
    hard-truncated first segment if even that alone can't fit -- guarantees
    the returned string is never wider than `width`, unlike a single fixed
    f-string that just wraps unpredictably on narrow terminals.
    """
    for n in range(len(segments), 0, -1):
        text = prefix + sep.join(segments[:n])
        if len(text) <= width:
            return text
    return (prefix + segments[0])[:max(0, width)]


def _loading_bar(label: str, width: int, steps: int = 10, delay: float = 0.06) -> None:
    """
    Animated loading bar that fills left-to-right.

    steps is kept low deliberately: on terminals that don't honor a bare \r
    as a same-line overwrite (observed on at least one Android terminal app),
    every frame prints as its own line instead of redrawing in place. Fewer
    frames means that failure mode floods far less of the screen. \x1b[K
    (erase-to-end-of-line) is appended after \r for terminals that do
    support it, so a shrinking bar never leaves stale characters behind.

    label shortens to "Init" on narrow terminals, and bar_width is derived
    from the actual fixed-text width rather than a flat guess, so the whole
    line -- not just the bar itself -- never exceeds `width` even on a
    small phone screen.
    """
    short_label = label if width >= 34 else ("Init" if len(label) > 4 else label)
    fixed_width = len(f"  {short_label}  []  100%  ")
    bar_width = max(4, min(40, width - fixed_width))
    print()
    for i in range(steps + 1):
        filled   = int(bar_width * i / steps)
        empty    = bar_width - filled
        pct      = int(100 * i / steps)
        bar      = f"{_RED_B}{'█' * filled}{_RESET}{_DIM}{'░' * empty}{_RESET}"
        line     = f"\r\x1b[K  {_WHITE_DIM}{short_label}{_RESET}  [{bar}]  {_RED_B}{pct:3d}%{_RESET}  "
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def _drop_reveal_word(
    text: str,
    color: str,
    width: int,
    max_drop: int = 5,
    frame_delay: float = 0.045,
) -> None:
    """
    Reveals `text` letter-by-letter via a falling-rain effect, centered on
    `width`. Each non-space character starts as a random JSON-syntax glyph
    falling down its own column from a randomized height (2..max_drop rows
    above where it lands), then locks into the real letter the instant it
    lands. Randomized per-letter drop heights mean different letters land
    at different times -- the word assembles progressively rather than all
    at once, and every letter's landing column is fixed from the start, so
    it always resolves into the correct spelling regardless of fall order.

    Reserves max_drop blank rows above the landing row (so the tallest
    possible fall never draws above already-printed content), anchors
    there with \033[s, then for every frame re-homes via \033[u before
    each relative move -- this avoids ever needing to know the terminal's
    absolute cursor row, only relative offsets from a single saved point.
    """
    col_start = max(1, (width - len(text)) // 2 + 1)
    letter_cols = [(j, ch) for j, ch in enumerate(text) if ch != " "]
    if not letter_cols:
        print(text)
        return

    for _ in range(max_drop):
        print()
    sys.stdout.write("\033[s")  # anchor = the landing row

    targets = [
        {
            "col": col_start + j,
            "char": ch,
            "remaining": random.randint(2, max_drop),
            "last_offset": None,
        }
        for j, ch in letter_cols
    ]
    total_frames = max((t["remaining"] for t in targets), default=0) + 1

    for _ in range(total_frames):
        for t in targets:
            # Erase whatever this column drew last frame (a mid-fall rain
            # glyph) before drawing this frame's position -- keeps each
            # letter a single clean falling character, not a smeared trail.
            if t["last_offset"] is not None:
                sys.stdout.write(f"\033[u\033[{t['last_offset']}A\033[{t['col']}G \033[0m")
                t["last_offset"] = None

            if t["remaining"] > 0:
                offset = t["remaining"]
                t["remaining"] -= 1
                glyph = random.choice(_RAIN_CHARS)
                sys.stdout.write(f"\033[u\033[{offset}A\033[{t['col']}G{_DIM}{_RED}{glyph}{_RESET}")
                t["last_offset"] = offset
            else:
                # Landed -- lock in the real letter. Redrawn every
                # subsequent frame too (harmless no-op) so it stays put
                # while neighboring letters are still falling.
                sys.stdout.write(f"\033[u\033[{t['col']}G{color}{t['char']}{_RESET}")

        sys.stdout.flush()
        time.sleep(frame_delay)

    # Move the cursor down past the landing row so normal print() calls
    # continue naturally below the reveal.
    sys.stdout.write("\033[u\033[1B\r")
    print()


def show_startup(agent_version: str = "", key_count: int = 0, model: str = "") -> None:
    """
    Display the full intro splash: loading bar first, then the
    POWERED BY BEJSON letter-drop reveal.

    Args:
        agent_version: Version string shown under NEWAGENT title.
        key_count:     Number of API keys loaded (shown in status line).
        model:         Active model name shown in status line.
    """
    width = _term_width()

    # -- Clear --------------------------------------------------------------
    print("\033[2J\033[H", end="")
    time.sleep(0.05)

    # -- Top rule -------------------------------------------------------------
    print(_bar(width))

    # -- Loading bar (plays first) --------------------------------------------
    _loading_bar("Initializing", width, steps=10, delay=0.06)
    print()

    # -- "POWERED BY" label -----------------------------------------------------
    time.sleep(0.08)
    _print_centered("P O W E R E D   B Y", width, f"{_WHITE_DIM}")
    print()

    # -- Letter-drop reveal: BEJSON, then NEW AGENT ----------------------------
    _drop_reveal_word("B E J S O N", _RED_B, width, max_drop=5, frame_delay=0.045)
    time.sleep(0.15)
    _drop_reveal_word("NEW A G E N T", _RED, width, max_drop=5, frame_delay=0.045)
    time.sleep(0.1)

    # -- Separator --------------------------------------------------------------
    print()
    print(_bar(width, "─"))
    print()

    # -- Version & meta -----------------------------------------------------------
    ver_str   = f"v{agent_version}" if agent_version else ""
    key_str   = f"{key_count} key{'s' if key_count != 1 else ''} loaded" if key_count else "no keys"
    model_str = model or "-"
    date_str  = datetime.now().strftime("%Y-%m-%d")
    meta_segments = [s for s in (ver_str, key_str, f"model: {model_str}", date_str) if s]
    print(f"{_DIM}{_fit_segments(meta_segments, width)}{_RESET}")

    # -- Author credit --------------------------------------------------------------
    credit_segments = ["Elton Boehnen", "boehnenelton2024@gmail.com", "github.com/boehnenelton"]
    print(f"{_WHITE_DIM}{_fit_segments(credit_segments, width)}{_RESET}")
    print()

    # -- Bottom rule ------------------------------------------------------------
    print(_bar(width))
    time.sleep(3.0)
