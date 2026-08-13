"""
Library:        lib_bejson_newagent_commands.py
Family:         NewAgent
Description:    TUI slash command handler and helper displays.
Version:        1.17.0
Date:           2026-08-09
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  7a9c1e3f-4b6d-4e8f-9a1c-3e5b7d9f1a58

CHANGELOG:
- 1.17.0 (2026-08-09): Renamed /compress to /amnesia and split it per
  Elton's follow-up: compression + wipe is unconditional whenever
  /amnesia runs, but feeding the recap straight back into memory
  ("rebirth") is now gated on the new auto_amnesia_memory_retrieval
  config toggle (default True, preserves the prior all-in-one behavior).
  When off, /amnesia wipes to a true blank slate and persists the recap
  to Context/amnesia_recap.txt (context_bubble.save_amnesia_recap); a
  new /rebirth command retrieves it later and feeds it in on demand
  (context_bubble.load_amnesia_recap + seed_history_with_recap). Same
  fail-closed guarantee as before -- history is only ever touched if a
  real recap came back from the compression call.
- 1.16.0 (2026-08-09): handle_slash_commands is now `async def` (was sync)
  to support the new /compress command, which needs to do a blocking
  compression network call without stalling agent.py's event loop --
  run via asyncio.to_thread. Every other branch is unchanged internally
  and still returns synchronously; only the function signature and its
  one call site (agent.py, now `await`ed) changed. /compress force-runs
  context_bubble.run_full_session_compression() on the live ctx["_history"],
  then wipes and reseeds history with just the recap -- fails closed
  (leaves history untouched) on any compression failure, and never
  touches the on-disk transcript logger.
- 1.15.0 (2026-08-09): Fixed a real CWD drift bug in /cd and /goto: they
  called Path(arg).resolve(), which resolves a relative arg against the
  real OS process directory -- agent.py never os.chdir()s, so that
  directory never moves, while ctx["_cwd"] (the agent's actual tracked
  location) does, via <exec>cd ...</exec>. After any chat-driven cd, a
  relative /cd or /goto would resolve from the wrong anchor and land
  somewhere the user didn't intend. Now resolves (Path(ctx["_cwd"]) /
  arg).resolve() -- correct for both relative and absolute arg, since
  Path.__truediv__ discards the left side when arg is already absolute.
  Verified: relative-path drift case now lands correctly; absolute-path
  input, the /goto alias, and the nonexistent-directory error path all
  unchanged (no regression).
- 1.14.0 (2026-08-08): Added /jobs and /jobstart <name> for the Job Creation
  System (lib_bejson_newagent_jobs) -- lists pending jobs.bejson files and
  lets the user explicitly start one, setting ctx["_active_job_path"]/
  ["_active_job_doc"] so build_system_prompt() injects it.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import lib_bejson_newagent_session as session_lib
from lib_bejson_newagent_tui import C, truncate_string
from lib_bejson_Core_bejson_core import bejson_core_load_file, bejson_core_get_field_map
import lib_bejson_newagent_context_bubble as context_bubble
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_jobs as jobs_lib

VERSION = "1.17.0"

HELP_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show this help reference"),
    ("/exit", "Exit and optionally archive named session"),
    ("/cls", "Clear terminal screen"),
    ("/clear", "Clear conversation history"),
    ("/ml", "Toggle multi-line input mode"),
    ("/feed", "Toggle live subprocess stdout/stderr streaming"),
    ("/speak", "Toggle printing of TTS output"),
    ("/ac", "Toggle auto-continue after action execution"),
    ("/spk", "Cycle input mode: 0 (typed) -> 1 (STT) -> 2 (dialog) -> 0"),
    ("/snip [cmd]", "Snippet manager: list | add <lbl>|<txt> | del <id> | off <id>"),
    ("/dryrun", "Toggle dry-run mode (actions are simulated)"),
    ("/cd <path>", "Change active working directory immediately"),
    ("/goto <path>", "Alias for /cd to change active working directory immediately"),
    ("/history", "Print full scrollable history with role badges"),
    ("/export [path]", "Export full conversation to Markdown file"),
    ("/backups", "List unexpired backups in backup_log.bejson"),
    ("/restore <id>", "Restore a file to its backed-up snapshot"),
    ("/sessions", "List archived sessions"),
    ("/keys", "View Gemini API keys status and call counts"),
    ("/keys deactivate <suffix>", "Permanently deactivate a key (is_active=False) so it stops rotating in"),
    ("/model [num|id]", "Show numbered model catalog / switch by number or literal ID"),
    ("/config", "Display active ScriptConfig parameters"),
    ("/stats", "Display session statistics"),
    ("/status", "Show circuit-breaker state, uptime, active key, current model"),
    ("/engine", "Toggle between REST and Interactions engines"),
    ("/toolscope", "Cycle interactions tool scope (all | shell_only)"),
    ("/resumemode", "Toggle Interactions resume strategy"),
    ("/checkpoints", "List saved named rollback checkpoints"),
    ("/rollback <lbl>", "Rollback all files in checkpoint to prior state"),
    ("/ctxlog [n]", "View the context bubble sent with a past turn (Context Button)"),
    ("/observer", "Toggle Part 4 context compression on/off"),
    ("/init", "Scaffold an empty context.bejson in the current directory"),
    ("/budget [name val]", "View or set context budget (max tokens, category percentages)"),
    ("/gate", "Toggle confirmation gate for risky actions"),
    ("/debug", "Toggle debug_mode: dump raw API request/response pairs on every call and error"),
    ("/jobs", "List pending jobs in jobs/ and show the currently active one"),
    ("/jobstart <name>", "Start a job (injects its goal+tasks into the system prompt)"),
    ("/amnesia", "Force-compress the live session history to a recap, then wipe agent memory (on-disk logs untouched). Auto-feeds the recap back in unless auto_amnesia_memory_retrieval is off."),
    ("/rebirth", "Retrieve the last /amnesia recap and feed it back into memory (manual step when auto_amnesia_memory_retrieval is off)"),
    ("/about", "Display version and author information"),
]

def _build_help_text() -> str:
    # Each command gets its own line; its description follows on the next
    # line as a "- " bullet. No column-padding needed since command and
    # description no longer share a line.
    lines = [f"{C.RED_B}NewAgent Slash Commands:{C.RESET}"]
    for cmd, desc in HELP_COMMANDS:
        lines.append(f"{C.RED_B}{cmd}{C.RESET}")
        lines.append(f"{C.WHITE}- {desc}{C.RESET}")
    return "\n" + "\n".join(lines) + "\n"

HELP_TEXT = _build_help_text()

def build_about_text() -> str:
    return f"""
{C.RED_B}NewAgent Terminal Client{C.RESET}
Version:        {VERSION}
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com
Website:        boehnenelton2024.pages.dev
Format Creator: Elton Boehnen
Format:         BEJSON / MFDB
"""

async def handle_slash_commands(raw: str, ctx: dict) -> tuple[bool, Optional[str]]:
    """
    Dispatcher. Returns (processed, output_message).
    """
    parts = raw.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return True, HELP_TEXT

    elif cmd == "/about":
        return True, build_about_text()

    elif cmd == "/cls":
        print("\033[2J\033[H", end="")
        return True, None

    elif cmd == "/exit":
        ctx["_exit_requested"] = True
        return True, "Exiting..."

    elif cmd == "/clear":
        ctx["history"].clear()
        if "prompter" in ctx and hasattr(ctx["prompter"], "reset_session"):
            ctx["prompter"].reset_session()
        ctx["_clear_resume"]()
        return True, "History cleared."

    elif cmd == "/ml":
        ctx["config"]["multi_line_mode"] = not ctx["config"]["multi_line_mode"]
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["multi_line_mode"] else "OFF"
        return True, f"Multi-line mode {state}"

    elif cmd == "/feed":
        ctx["config"]["live_feed_output"] = not ctx["config"]["live_feed_output"]
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["live_feed_output"] else "OFF"
        return True, f"Live subprocess feed {state}"

    elif cmd == "/speak":
        ctx["config"]["speak_output_enabled"] = not ctx["config"]["speak_output_enabled"]
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["speak_output_enabled"] else "OFF"
        return True, f"Speak output {state}"

    elif cmd == "/ac":
        ctx["config"]["auto_continue_enabled"] = not ctx["config"]["auto_continue_enabled"]
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["auto_continue_enabled"] else "OFF"
        return True, f"Auto-continue {state}"

    elif cmd == "/spk":
        ctx["config"]["input_mode"] = (ctx["config"]["input_mode"] + 1) % 3
        ctx["_save_config"]()
        modes = ["0 (Typed)", "1 (STT)", "2 (Snippet Dialog)"]
        return True, f"Input mode: {modes[ctx['config']['input_mode']]}"

    elif cmd == "/dryrun":
        ctx["config"]["dryrun_mode"] = not ctx["config"]["dryrun_mode"]
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["dryrun_mode"] else "OFF"
        return True, f"Dry-run mode {state}"

    elif cmd in ("/cd", "/goto"):
        if not arg:
            return True, f"Current CWD: {ctx['_cwd']}"
        # BUGFIX (2026-08-09): was Path(arg).resolve(), which resolves a
        # relative arg against the real OS process directory (agent.py
        # never calls os.chdir() -- ctx["_cwd"] is the only thing tracking
        # "where you are"). After any <exec>cd ...</exec>, that OS directory
        # and ctx["_cwd"] diverge, so a relative /cd or /goto would silently
        # resolve from the wrong anchor and drift out of sync. Anchoring on
        # ctx["_cwd"] first fixes it for both relative and absolute arg --
        # Path.__truediv__ discards the left side automatically when arg is
        # already absolute, so this is not conditional on arg's shape.
        target = (Path(ctx["_cwd"]) / arg).resolve()
        if not target.exists():
            return True, f"Directory does not exist: {target}"
        if not target.is_dir():
            return True, f"Not a directory: {target}"
        ctx["_cwd"] = str(target)
        return True, f"Changed directory to: {target}"

    elif cmd == "/engine":
        current = ctx["config"]["engine_mode"]
        new = "interactions" if current == "rest" else "rest"
        ctx["config"]["engine_mode"] = new
        ctx["_save_config"]()
        ctx["_init_engine"]()
        return True, f"Switched engine to: {new.upper()}"

    elif cmd == "/gate":
        ctx["config"]["confirmation_gate"] = not ctx["config"]["confirmation_gate"]
        ctx["_save_config"]()
        state = "ACTIVE" if ctx["config"]["confirmation_gate"] else "DISABLED"
        return True, f"Interactive confirmation gate {state}"

    elif cmd == "/debug":
        ctx["config"]["debug_mode"] = not ctx["config"].get("debug_mode", False)
        ctx["_save_config"]()
        state = "ON" if ctx["config"]["debug_mode"] else "OFF"
        return True, f"debug_mode {state} -- raw API request/response pairs will {'now' if state == 'ON' else 'no longer'} be written to logs/raw_api_debug_*.json and logs/raw_api_error_*.json"

    elif cmd == "/toolscope":
        scope = ctx["config"]["native_tools_scope"]
        new = "shell_only" if scope == "all" else "all"
        ctx["config"]["native_tools_scope"] = new
        ctx["_save_config"]()
        if "prompter" in ctx and hasattr(ctx["prompter"], "tool_scope"):
            ctx["prompter"].tool_scope = new
        return True, f"Interactions tool scope: {new.upper()}"

    elif cmd == "/resumemode":
        mode = ctx["config"]["resume_mode"]
        new = "fresh_replay" if mode == "full_history" else "full_history"
        ctx["config"]["resume_mode"] = new
        ctx["_save_config"]()
        return True, f"Resume Strategy: {new.upper()}"

    elif cmd == "/stats":
        stats = ctx["stats"]
        def _abbr(n: int) -> str:
            return f"{n/1000:.1f}k" if n >= 1000 else str(n)
        return True, f"""
{C.RED_B}Session Statistics:{C.RESET}
  Total turns (sent):    {stats.turns_sent}
  Total turns (model):   {stats.turns}
  Actions executed:      {stats.execs}
  Active key slot:       {stats.key_slot}/{stats.key_total}
  Current Engine:        {stats.engine.upper()}
  Last turn tokens in:   {_abbr(stats.input_tokens)}
  Last turn tokens out:  {_abbr(stats.output_tokens)}
"""

    elif cmd == "/status":
        uptime_s = time.time() - ctx.get("_start_time", time.time())
        hours, rem = divmod(int(uptime_s), 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        failures = ctx.get("_consecutive_turn_failures", 0)
        max_failures = ctx.get("_max_consecutive_turn_failures", 3)
        breaker_state = f"{C.RED_B}WARNING{C.RESET}" if failures > 0 else "OK"

        stats = ctx["stats"]
        model_reg = ctx.get("model_reg")
        active_model = model_reg.active if model_reg else "?"

        return True, f"""
{C.RED_B}Agent Status:{C.RESET}
  Uptime:                {uptime_str}
  Circuit breaker:       {breaker_state}  ({failures}/{max_failures} consecutive failures)
  Active key slot:       {stats.key_slot}/{stats.key_total}
  Current model:         {active_model}
  Current engine:        {stats.engine.upper()}
"""

    elif cmd == "/config":
        lines = [f"{C.RED_B}Active configuration parameters:{C.RESET}"]
        for k, v in ctx["config"].items():
            lines.append(f"  {k:28} = {v}")
        return True, "\n".join(lines)

    elif cmd == "/keys":
        key_reg = ctx["key_reg"]
        sub_parts = arg.strip().split(maxsplit=1) if arg else []

        if sub_parts and sub_parts[0].lower() == "deactivate":
            if len(sub_parts) < 2 or not sub_parts[1].strip():
                return True, f"{C.RED_B}Usage:{C.RESET} /keys deactivate <key-suffix>  (e.g. /keys deactivate 3xvVgA)"
            suffix = sub_parts[1].strip()
            match = key_reg.find_key_by_suffix(suffix)
            if match is None:
                # Distinguish "not found" from "ambiguous" so the person
                # isn't left guessing which case they hit.
                any_hits = [k for k in key_reg.keys if k.endswith(suffix)]
                if len(any_hits) > 1:
                    return True, f"{C.RED_B}Ambiguous:{C.RESET} {len(any_hits)} keys end in '{suffix}' -- use a longer suffix."
                return True, f"{C.RED_B}Not found:{C.RESET} no active key ends in '{suffix}'. Check /keys for the current list."
            ok = key_reg.deactivate_key(match)
            if ok:
                return True, f"{C.RED_B}Deactivated{C.RESET} key ...{match[-6:]} (is_active=False, removed from rotation)."
            return True, f"{C.RED_B}Failed{C.RESET} to deactivate ...{match[-6:]} -- see logs for details."

        lines = [f"{C.RED_B}API Key Registry:{C.RESET}"]
        for i, k in enumerate(key_reg.keys):
            calls = ctx["key_call_counts"].get(k, 0)
            avail = "Available" if key_reg._is_available(k) else "Cooling Down"
            lines.append(f"  [{i+1}] ...{k[-6:]} : {calls} calls ({avail})")
        return True, "\n".join(lines)

    elif cmd == "/model":
        model_reg = ctx["model_reg"]
        catalog_path = ctx["_config_dir"] / "gemini_catalog.bejson"
        catalog = rest.load_model_catalog(catalog_path)

        if not arg:
            lines = [f"{C.RED_B}Gemini Model Catalog:{C.RESET}"]
            for row in catalog:
                marker = " *" if row.get("model_string") == model_reg.active else "  "
                lines.append(
                    f"{marker}[{row.get('model_number')}] {row.get('display_name')} "
                    f"({row.get('model_string')}) -- {row.get('notes', '')}"
                )
            lines.append(f"\nActive model: {model_reg.active}")
            lines.append("Enter a number above to switch, or /model <model-id> for a literal ID not in the catalog.")
            return True, "\n".join(lines)

        if arg.isdigit():
            match = next((row for row in catalog if str(row.get("model_number")) == arg), None)
            if match is None:
                return True, f"No catalog entry for number {arg}. Use /model with no argument to see the list."
            model_reg.set_active(match["model_string"])
            return True, f"Activated model: {match['display_name']} ({match['model_string']})"

        # Non-numeric: treat as a literal model ID, preserving prior behavior
        # for anyone scripting this or using a model not yet in the catalog.
        model_reg.set_active(arg)
        return True, f"Activated model: {arg}"

    elif cmd == "/history":
        lines = [f"{C.RED_B}Conversation History:{C.RESET}"]
        for msg in ctx["history"]:
            role = f"{C.WHITE_B}[YOU]{C.RESET}" if msg["role"] == "user" else f"{C.RED_B}[GEMINI]{C.RESET}"
            lines.append(f"  {msg.get('_ts', '')} {role}\n  {msg['content']}\n")
        return True, "\n".join(lines)

    elif cmd == "/snip":
        sub_parts = arg.split(maxsplit=1)
        sub = sub_parts[0].lower() if sub_parts else "list"
        sub_arg = sub_parts[1] if len(sub_parts) > 1 else ""

        if sub == "list":
            snips = ctx["_list_snippets"]()
            if not snips:
                return True, "No snippets saved."
            lines = [f"{C.RED_B}Saved snippets:{C.RESET}"]
            for s in snips:
                status = "ON" if s["is_active"] else "OFF"
                lines.append(f"  [{s['snippet_id']}] ({status}) {s['label']} -> {s['text'][:60]}...")
            return True, "\n".join(lines)

        elif sub == "add":
            if "|" not in sub_arg:
                return True, "Usage: /snip add Label | Snippet Prompt text"
            lbl, txt = sub_arg.split("|", 1)
            sid = ctx["_add_snippet"](lbl.strip(), txt.strip())
            return True, f"Added snippet [{sid}]: {lbl.strip()}"

        elif sub == "del":
            if ctx["_delete_snippet"](sub_arg.strip()):
                return True, f"Deleted snippet [{sub_arg.strip()}]."
            return True, f"Snippet ID [{sub_arg.strip()}] not found."

        elif sub == "off":
            res = ctx["_toggle_snippet"](sub_arg.strip())
            if res is None:
                return True, f"Snippet ID [{sub_arg.strip()}] not found."
            state = "ON" if res else "OFF"
            return True, f"Snippet [{sub_arg.strip()}] is now {state}"

    elif cmd == "/backups":
        backups = ctx["_list_backups"](arg)
        if not backups:
            return True, "No backups found."
        lines = [f"{C.RED_B}Active File Backups (24h TTL):{C.RESET}"]
        for b in backups:
            lines.append(f"  [{b['backup_id']}] {b['file_path']} ({b['size']} bytes) - Label: {b['label']}")
        return True, "\n".join(lines)

    elif cmd == "/restore":
        if not arg:
            return True, "Usage: /restore <backup_id>"
        ok, msg = ctx["_restore_backup"](arg.strip())
        return True, msg

    elif cmd == "/ctxlog":
        # Context Button: view the bubble that was sent with a past turn,
        # tied directly to that prompt's row in the session transcript.
        n = 1
        if arg.strip().isdigit():
            n = int(arg.strip())
        entry = ctx["_logger"].get_entry(index_from_end=n)
        if not entry:
            return True, f"No transcript entry at position {n}."
        lines = [
            f"{C.RED_B}Context Bubble — turn -{n}{C.RESET}",
            f"{C.WHITE_DIM}Logged: {entry.get('timestamp', '?')} [{entry.get('role', '?')}]{C.RESET}",
            f"{C.WHITE_B}Content:{C.RESET} {truncate_string(entry.get('content', ''), 200)}",
        ]
        if not entry.get("bubble_content"):
            lines.append(f"{C.WHITE_DIM}(no context bubble was sent with this row){C.RESET}")
        else:
            lines.append(
                f"{C.WHITE_DIM}Tokens — policy:{entry.get('policy_tokens', 0)} "
                f"tasks:{entry.get('active_tasks_tokens', 0)} "
                f"env:{entry.get('env_file_tokens', 0)} "
                f"cwd:{entry.get('cwd_tokens', 0)} "
                f"keyword:{entry.get('keyword_tokens', 0)} knowledge:{entry.get('knowledge_tokens', 0)}"
                f"{C.RESET}"
            )
            if entry.get("observer_note"):
                lines.append(f"{C.YELLOW}Observer: {entry['observer_note']}{C.RESET}")
            lines.append(f"{C.WHITE_DIM}--- bubble content ---{C.RESET}")
            lines.append(entry["bubble_content"])
        return True, "\n".join(lines)

    elif cmd == "/observer":
        constants = context_bubble.load_constants(ctx["_config_dir"])
        new_state = not constants.get("observer_enabled", False)
        ok = context_bubble.set_constant(ctx["_config_dir"], "observer_enabled", new_state)
        if not ok:
            return True, "Failed to update observer_enabled in constant_config.bejson."
        return True, f"Observer (Part 4 compression) is now {'ON' if new_state else 'OFF'}."

    elif cmd == "/init":
        ok, msg = context_bubble.init_cwd_context_template(ctx["_cwd"])
        return True, msg

    elif cmd == "/budget":
        parts_b = arg.split()
        constants = context_bubble.load_constants(ctx["_config_dir"])

        if not parts_b:
            # View: total budget, each category's share and computed tokens,
            # a warning if percentages don't sum to 1.0 — surfaced, not hidden.
            total = constants.get("max_context_tokens", 8000)
            cpt = constants.get("chars_per_token", 4)
            lines = [
                f"{C.RED_B}Context Budget{C.RESET}  "
                f"{C.WHITE_DIM}(chars_per_token={cpt}){C.RESET}",
                f"  {C.WHITE_B}max_context_tokens{C.RESET} = {total}",
            ]
            pct_sum = 0.0
            for key in context_bubble._PCT_KEYS:
                pct = constants.get(key, 0.0)
                pct_sum += pct
                tokens = int(total * pct)
                lines.append(f"    {C.WHITE_B}{key}{C.RESET} = {pct:.2f}  ({tokens} tokens)")
            if abs(pct_sum - 1.0) > 0.001:
                lines.append(
                    f"  {C.YELLOW}Warning: percentages sum to {pct_sum:.2f}, not 1.00 "
                    f"— {'over' if pct_sum > 1.0 else 'under'} budget by "
                    f"{abs(pct_sum - 1.0):.2f}{C.RESET}"
                )
            lines.append(f"{C.WHITE_DIM}Set with: /budget <name> <value>{C.RESET}")
            return True, "\n".join(lines)

        if len(parts_b) != 2:
            return True, "Usage: /budget <constant_name> <value>  (no args to view)"

        name, raw_value = parts_b[0], parts_b[1]
        if name not in constants:
            return True, f"Unknown constant '{name}'. Run /budget with no args to see valid names."

        try:
            if name.startswith("pct_"):
                value = float(raw_value)
                if not (0.0 <= value <= 1.0):
                    return True, f"{name} must be between 0.0 and 1.0 (got {value})."
            elif name == "observer_enabled":
                value = raw_value.lower() in ("true", "1", "on", "yes")
            else:
                value = float(raw_value) if "." in raw_value else int(raw_value)
                if value < 0:
                    return True, f"{name} must be non-negative (got {value})."
        except ValueError:
            return True, f"Couldn't parse '{raw_value}' for {name}."

        ok = context_bubble.set_constant(ctx["_config_dir"], name, value)
        if not ok:
            return True, f"Failed to update {name} in constant_config.bejson."

        msg = f"{name} set to {value}."
        if name.startswith("pct_"):
            new_constants = context_bubble.load_constants(ctx["_config_dir"])
            pct_sum = sum(new_constants.get(k, 0.0) for k in context_bubble._PCT_KEYS)
            if abs(pct_sum - 1.0) > 0.001:
                msg += (
                    f" {C.YELLOW}Note: percentages now sum to {pct_sum:.2f}, not 1.00 "
                    f"— run /budget to review.{C.RESET}"
                )
        return True, msg

    elif cmd == "/checkpoints":
        cp_path = ctx["_backups_dir"] / "checkpoints.bejson"
        if not cp_path.exists():
            return True, "No checkpoints saved."
        try:
            doc = bejson_core_load_file(str(cp_path))
            if not isinstance(doc, dict):
                return True, f"Checkpoint file unreadable: {cp_path}"
            fmap = bejson_core_get_field_map(doc)
            label_idx = fmap.get("label", 0)
            bids_idx = fmap.get("backup_ids", 1)
            created_idx = fmap.get("created_at", 2)
            lines = [f"{C.RED_B}Rollback Checkpoints:{C.RESET}"]
            for row in doc.get("Values", []):
                lines.append(
                    f"  - {row[label_idx]} ({len(row[bids_idx])} backups) Created: {row[created_idx]}"
                )
            return True, "\n".join(lines)
        except Exception as e:
            return True, f"Failed to list checkpoints: {e}"

    elif cmd == "/sessions":
        sessions_index = ctx["_config_dir"].parent / "logs" / "sessions" / "session_index.bejson"
        sessions = session_lib.list_named_sessions(sessions_index)
        if not sessions:
            return True, "No named sessions archived yet. Use /exit and enter a label to save one."
        lines = [f"{C.RED_B}Archived Sessions:{C.RESET}"]
        for s in sessions:
            lines.append(f"  [{s['label']}]  saved: {s['saved_at'][:19]}  log: {s['log_path']}")
        return True, "\n".join(lines)

    elif cmd == "/export":
        history = ctx["history"]
        if not history:
            return True, "Nothing to export — history is empty."
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if arg:
            export_path = Path(arg).expanduser().resolve()
        else:
            export_path = Path(ctx["_cwd"]) / f"session_export_{ts}.md"
        lines = [f"# NewAgent Session Export", f"Exported: {datetime.now().isoformat()}", ""]
        for msg in history:
            role  = "**YOU**" if msg["role"] == "user" else "**GEMINI**"
            stamp = msg.get("_ts", "")
            lines.append(f"### {role} {stamp}")
            lines.append(msg["content"])
            lines.append("")
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text("\n".join(lines), encoding="utf-8")
            return True, f"Exported {len(history)} messages → {export_path}"
        except Exception as exc:
            return True, f"Export failed: {exc}"

    elif cmd == "/rollback":
        if not arg:
            return True, "Usage: /rollback <label>"
        ok, msg = ctx["_rollback_checkpoint"](arg.strip())
        return True, msg

    elif cmd == "/jobs":
        job_list = jobs_lib.scan_jobs(ctx["_jobs_dir"])
        if not job_list:
            return True, "No pending jobs in jobs/."
        lines = [f"{C.RED_B}Pending Jobs:{C.RESET}"]
        for j in job_list:
            lines.append(
                f"  {C.WHITE_B}{j['job_name']}{C.RESET}  "
                f"({j['completed_count']}/{j['task_count']} tasks)"
                + (f" — {j['goal']}" if j['goal'] else "")
            )
        active = ctx.get("_active_job_path")
        lines.append(f"Active job: {Path(active).stem if active else '(none)'}")
        return True, "\n".join(lines)

    elif cmd == "/jobstart":
        if not arg:
            return True, "Usage: /jobstart <job_name>"
        picked = jobs_lib.get_job_path(ctx["_jobs_dir"], arg.strip())
        if not picked:
            return True, f"No job named '{arg.strip()}' found in jobs/."
        doc = jobs_lib.load_job(picked)
        if not doc:
            return True, f"[ERROR] Could not load {picked.name} as BEJSON."
        ctx["_active_job_path"] = picked
        ctx["_active_job_doc"] = doc
        return True, f"Started job: {picked.stem}"

    elif cmd == "/amnesia":
        # Amnesia: compression + forgetting is unconditional whenever this
        # command runs. Rebirth (feeding the recap back in immediately) is
        # config-gated via auto_amnesia_memory_retrieval -- off, and the
        # recap just waits on disk for a manual /rebirth instead.
        #
        # Scope is deliberately narrow: this NEVER touches the on-disk
        # transcript logger. Nothing is deleted from logs/ -- the full
        # conversation stays there for the user's own reference; only the
        # agent's live prompting memory is touched.
        #
        # Fails closed: history is only cleared if a real recap comes back.
        # A failed/empty compression call leaves history completely
        # untouched -- an unlucky network error must never be able to wipe
        # a session with nothing to show for it.
        history = ctx["history"]
        if not history:
            return True, "Nothing to compress -- history is already empty."
        # rest_prompter.prompt() is a blocking network call; run it off the
        # event loop thread so background execs / TUI refresh don't stall
        # for however long the compression request takes.
        recap = await asyncio.to_thread(
            context_bubble.run_full_session_compression, history, ctx["_rest_prompter"],
        )
        if not recap:
            return True, "[ERROR] Compression call failed or returned nothing -- history left untouched."
        context_bubble.save_amnesia_recap(ctx["_context_dir"], recap)
        auto_rebirth = ctx["config"].get("auto_amnesia_memory_retrieval", True)
        if auto_rebirth:
            context_bubble.seed_history_with_recap(history, recap)
            return True, f"Amnesia complete, recap reborn immediately ({len(recap)} chars). Agent memory reset; on-disk logs untouched."
        else:
            history.clear()
            return True, f"Amnesia complete -- true blank slate ({len(recap)} chars of recap saved). Run /rebirth when ready to retrieve it. On-disk logs untouched."

    elif cmd == "/rebirth":
        recap = context_bubble.load_amnesia_recap(ctx["_context_dir"])
        if not recap:
            return True, "No compressed recap available -- run /amnesia first."
        context_bubble.seed_history_with_recap(ctx["history"], recap)
        return True, f"Rebirth complete -- recap ({len(recap)} chars) fed back into memory."

    return False, None
