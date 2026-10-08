# Idea: On-Demand GUI Settings Launcher
**Status:** HYPOTHETICAL — idea only, not planned, not implemented.
**Date:** 2026-08-05

## The idea, as described

From the standard TUI agent (`agent.py`), a command spins up `webagent.py`'s
Flask server in a background subprocess, opens the phone's browser to it
via Termux, and auto-kills the subprocess + server if 5 minutes pass with
no config change made in the page.

## Viability: yes, and cheaper than it sounds

Most of this already exists:

- `webagent.py` already IS a graphical settings/config surface --
  `/api/config` (GET+POST) and `/api/models` (GET+POST) routes are already
  built and tested (per the v3.1.0 pkg051 entry in
  docs/HISTORY_2026-08-05.md). This idea doesn't need a new settings UI,
  just a launcher + lifecycle wrapper around what's already there.
- Subprocess spawn is a one-liner (`subprocess.Popen([sys.executable,
  "webagent.py", ...])`), and NewAgent already has the pattern of shelling
  out to external tools elsewhere in the codebase.
- Opening the browser from Termux has a direct precedent already in the
  code: `lib_bejson_newagent_actions.py`'s TTS path already checks for a
  Termux:API binary (`termux-tts-speak`) and gives an instructive error if
  it's missing. The browser-open equivalent is `termux-open-url <url>`,
  same dependency (`pkg install termux-api` + the Termux:API app), same
  graceful-failure pattern would apply.

## Real design questions this idea raises (not blockers, just decisions)

1. **Bind to loopback only.** The settings page can read/edit config
   that touches API keys. `host="127.0.0.1"`, never `0.0.0.0` -- otherwise
   it's briefly reachable by anything else on the same network while open.
2. **Ephemeral port.** Bind with port `0` and read back the OS-assigned
   port before building the URL, so this never collides with a
   `webagent.py` someone already has running manually.
3. **Idle-shutdown belongs inside the child, not the parent.** Simplest
   and most robust: the spawned process runs its own watchdog thread that
   tracks a `last_config_write` timestamp (bumped only by `/api/config`
   POST and `/api/models` POST, matching "no cfg changes" as literally
   asked) and self-terminates after 5 minutes idle. The parent TUI just
   spawns it and moves on -- no need to poll a child process from
   `agent.py` at all.
4. **Flask's `app.run()` has no clean `.shutdown()` from another thread.**
   Since this would be a disposable, single-purpose process (not the
   long-running interactive agent), the honest, low-risk option is the
   watchdog thread calling `os._exit(0)` directly rather than trying to
   wire up `werkzeug.serving.make_server()` for a graceful stop -- more
   moving parts for a case where "the whole process was going to die
   anyway" already gets the job done.
5. **"No cfg changes" vs. "page just sitting open."** As literally
   specified, the 5-minute timer only resets on an actual save, not on
   merely having the page open -- meaning it's possible to be mid-edit,
   not yet saved, and have it close under you. Worth deciding on purpose
   rather than by accident: either keep it exactly as specified, or reset
   the timer on any request to the page (not just saves) so it only closes
   when truly abandoned.

## What this would touch, if built

- New: a small launcher (a `/gui` slash command in
  `lib_bejson_newagent_commands.py`, or a standalone script) that picks a
  port, spawns `webagent.py`, and calls `termux-open-url`.
- `webagent.py`: an idle-watchdog thread, gated so it only runs when
  launched in this "disposable settings session" mode -- a normal
  intentional `webagent.py` run (someone starting the full web client on
  purpose) should not self-destruct after 5 idle minutes.

No code written. Flagging here per Elton's instruction so this doesn't get
lost, and so a future "let's build the multi-provider engine" style
green-light can reference it directly.
