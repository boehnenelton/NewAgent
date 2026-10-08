# Idea: Platform Detection Utility for Core Libraries
**Status:** HYPOTHETICAL — idea only, not planned, not implemented.
**Date:** 2026-08-05
**Related:** docs/IDEAS_2026-08-05_gui_settings_launcher.md (the browser-open
step there is the clearest immediate consumer of this)

## The idea, as described

A detection function living in the Core library family that identifies
which environment the script is actually running under (Termux, Pydroid,
Windows, etc.) so code can branch to the correct platform-specific method
instead of assuming Termux everywhere, the way it does today.

## Viability: yes -- detection itself is cheap, confidence varies by platform

A single function, something like `lib_bejson_Core_bejson_platform.py ::
detect_platform() -> str`, returning one of `"termux" | "pydroid" |
"windows" | "linux" | "macos" | "unknown"`. Rough signal strength per
platform:

- **Termux -- high confidence.** `Path.home() / ".termux"` existing is a
  good signal (as Elton described), and it stacks with a second
  independent check: `PREFIX` env var containing `com.termux`, or
  `/data/data/com.termux` existing. Two independent signals agreeing is
  worth trusting; already-established precedent for "detect Termux, then
  gracefully degrade if the matching tool isn't there" exists in
  `lib_bejson_newagent_actions.py`'s TTS path today.
- **Windows -- high confidence, this one's free.** `os.name == "nt"` (or
  `platform.system() == "Windows"`) is a standard-library one-liner, not a
  heuristic at all.
- **Pydroid -- lower confidence, needs real-device verification.**
  Pydroid 3 on Android runs the interpreter from inside its own app
  sandbox (something under `/data/data/ru.iiec.pydroid3/...` historically),
  so `sys.executable`'s path or `sys.prefix` is the likely signal -- but
  unlike Termux's `~/.termux` marker, this hasn't been confirmed against
  an actual Pydroid install in this codebase. Flagging honestly rather
  than shipping a guessed path check with false confidence: this one
  needs a real "print(sys.executable) on my Pydroid install" before the
  detection logic is trustworthy.
- **Linux/macOS -- fallback via `platform.system()`.** Whatever's left
  after the above, standard library, no heuristics needed.

## Where this would plug in, if built

- **The GUI-launcher idea's browser-open step** -- branch `termux-open-url`
  (Termux) vs `os.startfile`/`webbrowser.open` (Windows) vs `xdg-open`
  (Linux) vs "not supported, tell the user" (Pydroid, if it turns out
  Pydroid has no reliable browser-launch path of its own).
- **TTS** (`lib_bejson_newagent_actions.py`) -- already Termux-only via
  `termux-tts-speak`; this would let it fail with "TTS isn't available on
  {platform}" instead of a generic "not found" regardless of why.
- **`/about` and `/help`** -- surfacing the detected platform in
  `build_about_text()` costs one line and turns "what platform is this
  running on" from a support question into something visible up front.
- **Session logs** -- tagging each `logs/session_*.md` header with the
  detected platform would make cross-device bug reports self-documenting,
  relevant since this whole ecosystem already runs across multiple
  devices per Elton's own device roster (`INTERNAL_STORAGE`, `SD_CARD`,
  Termux `PROJECT_ROOT`, etc. already distinguish devices/paths).

## What this would touch, if built

- New: `lib_bejson_Core_bejson_platform.py` (Core family, so anything
  downstream -- NewAgent, the BEJSON/MFDB ecosystem generally -- can use
  it, not just this one project).
- Callers that currently hardcode a Termux assumption would branch on its
  result instead of assuming; nothing existing breaks if the detected
  platform is unhandled, since every consumer above already has (or would
  get) a "not supported here" fallback message rather than a hard crash.

No code written. Logged per Elton's instruction so this and the GUI
launcher idea can be integrated together later rather than built as two
disconnected things.
