"""
Name:         agent.py
Family:       NewAgent
Description:  Lean orchestrator and async main event loop dispatcher.
              Switches dynamically between REST and Interactions engines.
Version:      2.15.0
Date:         2026-08-09
Author:       Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID: 5d7f9a1c-3b5e-4a7f-9c1d-2e4f6b8a0c35

CHANGELOG:
- 2.15.0 (2026-08-09): commands.handle_slash_commands is now async (needed
  for the new /compress command's blocking compression call, run via
  asyncio.to_thread so it doesn't stall this event loop) -- its one call
  site here is now awaited. Also wired ctx["_rest_prompter"] alongside the
  existing ctx["history"] sync pattern: set right after rest_prompter's
  initial construction and re-synced at its one other rebind point (the
  post-failure stateful-recovery rebuild), so /compress always operates
  on the live prompter object, never a stale one.
- 2.14.0 (2026-08-09): Removed the startup job announcement/prompt per
  Elton's direct instruction -- the agent no longer scans jobs/ and asks
  at boot; ensure_job_dirs/cleanup_old_completed_jobs still run silently.
  Starting a job is now purely a user-initiated action via /jobstart
  (commands.py), same as before, with no AI-mediated "here's what's
  pending" step in between. ctx["_active_job_path"/"_active_job_doc"]
  now always start None.
- 2.13.0 (2026-08-08): Wired the Job Creation System. jobs/ and jobs/complete/
  are created at bootstrap (jobs.ensure_job_dirs) and pruned of stale
  completed jobs (jobs.cleanup_old_completed_jobs, >7 days). On startup,
  after the splash, announces any pending jobs and offers to start one
  (jobs.format_job_announcement); ctx["_active_job_path"]/["_active_job_doc"]
  carry the selection through to build_system_prompt()'s new active_job
  param every turn. /jobstart <name> (commands.py 1.14.0) lets a job be
  started explicitly at any later point instead, per spec ("ignore jobs
  until the user explicitly requests to start them").
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Insert lib/ directory into path to resolve lib_bejson_newagent_* correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import lib_bejson_newagent_tui as tui
import lib_bejson_newagent_startup as startup
import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_backup as backup
import lib_bejson_newagent_session as session
import lib_bejson_newagent_input as input_lib
import lib_bejson_newagent_commands as commands
import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_engine_interactions as interactions
import lib_bejson_newagent_errors as errors
import lib_bejson_newagent_jobs as jobs

VERSION = "2.15.0"

# Directories configuration
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"
BACKUPS_DIR = BASE_DIR / "backups"
CONTEXT_DIR = BASE_DIR / "Context"
JOBS_DIR = BASE_DIR / "jobs"

# Registry file paths
KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"
CONFIG_PATH = CONFIG_DIR / "config.json"
RESUME_PATH = CONFIG_DIR / "session_resume.json"
NATIVE_RESUME_PATH = CONFIG_DIR / "native_resume.json"
SNIPPETS_PATH = CONFIG_DIR / "snippets.bejson"

async def main() -> None:
    # 1. Setup Directories & Back up registries
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        jobs.ensure_job_dirs(JOBS_DIR)
        jobs.cleanup_old_completed_jobs(JOBS_DIR)

        rest.build_default_keys_bejson(KEYS_PATH)
        rest.build_default_models_bejson(MODELS_PATH)
        rest.build_default_model_catalog(MODEL_CATALOG_PATH)
        rest.backfill_model_catalog_api_profile(MODEL_CATALOG_PATH)
        rest.backfill_model_catalog_provider(MODEL_CATALOG_PATH)
    except errors.NewAgentFatalError:
        raise
    except Exception as exc:
        raise errors.BootstrapFailureError(
            f"Directory/registry-file setup failed: {exc}"
        ) from exc

    # 2. Init components
    try:
        config = config_lib.init_config(CONFIG_PATH)
        rest.sync_keys_from_env_file(KEYS_PATH, Path(config.get("env_file_path", "")))
        key_reg = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
        model_reg = rest.ModelRegistry(MODELS_PATH)
    except errors.NewAgentFatalError:
        raise
    except Exception as exc:
        raise errors.RegistryAccessError(
            f"key_reg/model_reg/config could not be established: {exc}"
        ) from exc

    # Configure Python logging
    log_level = getattr(logging, config.get("log_level", "INFO"), logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    backup.init_backup(BACKUPS_DIR)
    input_lib.init_input(SNIPPETS_PATH)
    bubble.init_context_bubble(CONTEXT_DIR, CONFIG_DIR, LOGS_DIR)

    # Show POWERED BY BEJSON intro splash
    startup.show_startup(
        agent_version=VERSION,
        key_count=len(key_reg.keys),
        model=model_reg.active,
    )

    # 3. Setup Context dictionary
    history = []
    exec_results = []
    stats = tui.SessionStats(
        key_total=len(key_reg.keys),
        engine=config.get("engine_mode", "rest"),
    )
    
    ctx = {
        "config": config,
        "history": history,
        "stats": stats,
        "key_reg": key_reg,
        "model_reg": model_reg,
        "key_call_counts": {},
        "exec_results": exec_results,
        "trigger_cooldowns": {},
        "_cwd": str(Path.cwd()),
        "_shell_env": None,  # Global Environment Dictionary — audit Part 1/II
        "_start_time": time.time(),  # uptime source for /status
        "_consecutive_turn_failures": 0,  # circuit breaker state, mirrored for /status
        "_max_consecutive_turn_failures": 3,
        "_exit_requested": False,
        "_continue_requested": False,
        "_backups_dir": BACKUPS_DIR,
        "_config_dir": CONFIG_DIR,
        "_context_dir": CONTEXT_DIR,
        "_jobs_dir": JOBS_DIR,
        "_active_job_path": None,
        "_active_job_doc": None,
        
        "_save_config": lambda: config_lib.save_config(CONFIG_PATH, config),
        "_clear_resume": lambda: (
            session.clear_resume_session(RESUME_PATH),
            session.clear_native_resume(NATIVE_RESUME_PATH),
        ),
        "_list_snippets": input_lib.list_snippets,
        "_add_snippet": input_lib.add_snippet,
        "_delete_snippet": input_lib.delete_snippet,
        "_toggle_snippet": input_lib.toggle_snippet,
        "_list_backups": backup.list_backups,
        "_restore_backup": backup.restore_backup,
        "_rollback_checkpoint": lambda label: actions.rollback_checkpoint(label, BACKUPS_DIR),
    }

    # Setup Session Logger
    logger = session.SessionLogger(LOGS_DIR)
    ctx["_logger"] = logger

    # 4. Check for Resume Session
    resume_found = False
    if config.get("engine_mode") == "interactions":
        native_state = session.load_native_resume(NATIVE_RESUME_PATH)
        if native_state:
            print("\nFound a prior Interactions session. Resume? [y/N]: ", end="")
            ans = input().strip().lower()
            if ans in ("y", "yes"):
                history = [{"role": "user", "content": f"Resuming previous session recap: {native_state.get('recap', '')}"}]
                ctx["history"] = history
                resume_found = True
    else:
        saved_history = session.load_resume_session(RESUME_PATH)
        if saved_history:
            print("\nFound a prior REST session. Resume? [y/N]: ", end="")
            ans = input().strip().lower()
            if ans in ("y", "yes"):
                history = saved_history
                ctx["history"] = history
                resume_found = True

    if not resume_found:
        ctx["_clear_resume"]()

    # 5. Initialize API Prompters
    rest_prompter = rest.RestPrompter(key_reg, model_reg, MODEL_CATALOG_PATH, config, logs_dir=LOGS_DIR)
    ctx["_rest_prompter"] = rest_prompter

    if config.get("health_check_on_startup", True) and config.get("engine_mode", "rest") == "rest":
        print("Running startup health check...")
        try:
            hc_ok, hc_msg = await asyncio.get_event_loop().run_in_executor(
                None, lambda: rest.health_check_ping(rest_prompter)
            )
        except Exception as hc_exc:
            hc_ok, hc_msg = False, f"Health check FAILED to run: {hc_exc}"
        print(hc_msg)
        logger.log("system", f"[HEALTH_CHECK] {'OK' if hc_ok else 'FAILED'}: {hc_msg}")

    # Setup native function calling mapping
    async def async_run_exec(command: str) -> str:
        code, out, new_cwd, new_env = await actions.do_exec(
            command, ctx["_cwd"],
            config.get("exec_timeout_seconds", 60),
            config.get("live_feed_output", False),
            shell_env=ctx.get("_shell_env"),
        )
        ctx["_cwd"] = new_cwd
        if new_env is not None:
            ctx["_shell_env"] = new_env
        return out

    # Maps Interactions API names to do_* functions in actions module
    do_map = {
        "do_exec": async_run_exec,
        "do_read_file": lambda path: actions.do_read_file(path, ctx["_cwd"]),
        "do_write_file": lambda path, content: actions.do_write_file(path, content, ctx["_cwd"]),
        "do_edit_file": lambda path, old_text, new_text: actions.do_edit_file(path, old_text, new_text, ctx["_cwd"]),
        "do_list_dir": lambda path: actions.do_list_dir(path, ctx["_cwd"]),
        "do_tree_view": lambda path, depth=3: actions.do_tree_view(path, ctx["_cwd"], depth=depth),
        "do_make_dir": lambda path: actions.do_make_dir(path, ctx["_cwd"]),
        "do_delete_file": lambda path: actions.do_delete_file(path, ctx["_cwd"]),
        "do_copy_file": lambda src, dst: actions.do_copy_file(src, dst, ctx["_cwd"]),
        "do_diff_file": lambda path: actions.do_diff_file(path, ctx["_cwd"]),
        "do_restore_file": actions.do_restore_file,
        "do_http_get": actions.do_http_get,
        "do_find_files": lambda pattern, base=".": actions.do_find_files(pattern, base, ctx["_cwd"]),
        "do_search_text": lambda pattern, path=".": actions.do_search_text(pattern, path, ctx["_cwd"]),
        "do_fuzzy_find": lambda query: actions.do_fuzzy_find(query, ctx["_cwd"]),
        "do_env_get": actions.do_env_get,
        "do_speak": actions.do_speak,
        "do_checkpoint": lambda label: actions.do_checkpoint(label, BACKUPS_DIR),
        "do_exec_bg": lambda command: f"[SUCCESS] Background task spawned with ID: {actions._GLOBAL_TASK_MANAGER.spawn_task(command, ctx['_cwd'], shell_env=ctx.get('_shell_env'))}",
        "do_task_status": lambda task_id: actions._GLOBAL_TASK_MANAGER.get_status(task_id),
        "do_task_kill": lambda task_id: actions._GLOBAL_TASK_MANAGER.kill_task(task_id),
        "do_task_list": lambda: actions._GLOBAL_TASK_MANAGER.list_tasks(),
    }

    int_prompter = interactions.InteractionsPrompter(
        key_reg, model_reg, do_map,
        tool_scope=config.get("native_tools_scope", "all"),
        max_rounds=config.get("interactions_max_rounds", 10),
    )

    if config.get("engine_mode") == "interactions" and resume_found:
        # Link previous interaction ID if we resumed
        native_state = session.load_native_resume(NATIVE_RESUME_PATH)
        if native_state:
            int_prompter._prev_id = native_state.get("interaction_id")

    def init_engine():
        stats.engine = config.get("engine_mode", "rest")
        if stats.engine == "interactions":
            ctx["prompter"] = int_prompter
        else:
            ctx["prompter"] = rest_prompter

    ctx["_init_engine"] = init_engine
    init_engine()

    # 6. Main Interactive TUI Event Loop
    tui.refresh_ui(
        history=history, exec_results=exec_results, stats=stats,
        cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
        dryrun=config.get("dryrun_mode", False),
        context_bloat=ctx.get("_context_bloat", False),
        agent_version=VERSION,
    )

    autonomy_active = False
    autonomy_turns_remaining = 0
    auto_continuing = False
    # Circuit breaker (audit Part 1/I): 3 consecutive failed turns triggers a
    # clean shutdown instead of looping indefinitely against a broken state.

    while not ctx["_exit_requested"]:
        turn_start_time = time.time()  # Audit fix: enables real duration_ms in log_turn_relational

        # Update key registry totals in stats
        stats.key_slot = key_reg.active_slot
        stats.key_total = len(key_reg.keys)

        # Autonomy check
        if autonomy_active and autonomy_turns_remaining <= 0:
            autonomy_active = False
            auto_continuing = False
            tui.refresh_ui(
                history=history, exec_results=exec_results, stats=stats,
                cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                dryrun=config.get("dryrun_mode", False),
        context_bloat=ctx.get("_context_bloat", False),
                status="Autonomy turn limit reached. Press Enter to proceed.",
                agent_version=VERSION,
            )

        # Get Input if manual gate is active
        if not autonomy_active and not auto_continuing:
            # Sync key slot before getting input
            stats.key_slot = key_reg.active_slot
            user_msg = input_lib.get_input(
                prompt="> ",
                mode=config.get("input_mode", 0),
                multi_line=config.get("multi_line_mode", False),
            )
            
            if not user_msg:
                continue

            # Command execution
            if user_msg.strip().startswith("/"):
                processed, cmd_out = await commands.handle_slash_commands(user_msg, ctx)
                if processed:
                    if ctx["_exit_requested"]:
                        break
                    tui.refresh_ui(
                        history=history, exec_results=exec_results, stats=stats,
                        cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                        dryrun=config.get("dryrun_mode", False),
        context_bloat=ctx.get("_context_bloat", False),
                        status=cmd_out or "",
                        agent_version=VERSION,
                    )
                    continue

            # Add to conversation history; log immediately so nothing is lost
            # even if this message never becomes an active prompt (bubble
            # columns get patched onto this same row once assembled, below)
            ts = datetime.now().strftime("%H:%M:%S")
            history.append({"role": "user", "content": user_msg, "_ts": ts})
            logger.log("user", user_msg)
        else:
            # Under autonomy, we construct automatic payload
            if auto_continuing:
                auto_continuing = False
            if autonomy_active:
                autonomy_turns_remaining -= 1

        # Clear exec_results for the fresh turn display
        exec_results.clear()

        # Update TUI for thinking status
        tui.refresh_ui(
            history=history, exec_results=exec_results, stats=stats,
            cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
            dryrun=config.get("dryrun_mode", False),
        context_bloat=ctx.get("_context_bloat", False),
            status="Awaiting response...",
            agent_version=VERSION,
        )

        # Context Bubble assembly (pkg015 — Parts 1-3, Part 5 pkg019)
        user_msg = history[-1]["content"] if history else ""
        try:
            bubble_result = bubble.assemble_bubble(
                CONTEXT_DIR, CONFIG_DIR, user_msg,
                turn=stats.turns + 1, cooldown_state=ctx["trigger_cooldowns"],
                cwd=ctx["_cwd"], env_file_path=config.get("env_file_path", ""),
            )
        except errors.ContextInjectionError as exc:
            logger.log("system", f"[RECOVERABLE] {type(exc).__name__}: {exc} — using minimal context for this turn.")
            bubble_result = bubble.build_minimal_bubble(CONTEXT_DIR, CONFIG_DIR)
        bubble_text = bubble_result["text"]
        observer_note = ""

        # Observer compression (Part 4 — compression only, toggled off by default)
        if (
            bubble_result["observer_enabled"]
            and (stats.turns + 1) % max(bubble_result["observer_refinement_interval"], 1) == 0
            and len(bubble_text) // bubble_result["chars_per_token"] > bubble_result["max_context_tokens"]
        ):
            compressed = bubble.run_observer_compression(
                keyword_text="", knowledge_text=bubble_text, rest_prompter=rest_prompter,
            )
            if compressed:
                bubble_text = f"## Compressed Context\n{compressed[0]}"
                observer_note = "compressed (over budget)"

        ctx["_context_bloat"] = (len(bubble_text) // bubble_result["chars_per_token"]) > bubble_result["max_context_tokens"]

        # Ties this bubble to the SAME transcript row as the prompt it went
        # out with — patches columns onto the row logged above, no duplicate.
        logger.update_last_bubble(
            bubble_content=bubble_text,
            policy_tokens=bubble_result["policy_tokens"],
            active_tasks_tokens=bubble_result["active_tasks_tokens"],
            env_file_tokens=bubble_result["env_file_tokens"],
            cwd_tokens=bubble_result["cwd_tokens"],
            keyword_tokens=bubble_result["keyword_tokens"],
            knowledge_tokens=bubble_result["knowledge_tokens"],
            observer_note=observer_note,
        )

        system_instruction = actions.build_system_prompt(
            ctx["_cwd"], bubble_text,
            active_job=jobs.build_job_context_block(ctx.get("_active_job_doc")),
        )

        # Call the selected engine
        response_text = ""
        try:
            stats.turns_sent += 1
            if stats.engine == "interactions":
                # Interactions native function loop
                # This executes all native tool requests directly inline
                resp_text, usage, call_log = await int_prompter.run_turn(
                    user_input=history[-1]["content"],
                    system_instruction=system_instruction,
                    denylist=config.get("exec_denylist"),
                    dryrun=config.get("dryrun_mode", False),
                )
                response_text = resp_text
                # Convert Interactions call_log to ExecResults for display
                for log_item in call_log:
                    exec_results.append(tui.ExecResult(
                        action_type=log_item["name"],
                        source=json.dumps(log_item["args"]),
                        output=log_item["result"],
                        exit_code=0 if log_item["ok"] else -1,
                    ))
                # Update tokens
                stats.input_tokens = usage.get("total_input_tokens", 0)
                stats.output_tokens = usage.get("total_output_tokens", 0)
            else:
                # REST mode (tag parsing)
                resp_text, usage = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: rest_prompter.prompt(history, system_instruction)
                )
                response_text = resp_text
                stats.input_tokens = usage.get("promptTokenCount", 0)
                stats.output_tokens = usage.get("candidatesTokenCount", 0)

            # Record turn call counts
            active_key = key_reg.keys[(key_reg._index - 1) % len(key_reg.keys)]
            ctx["key_call_counts"][active_key] = ctx["key_call_counts"].get(active_key, 0) + 1
            stats.turns += 1
            ctx["_consecutive_turn_failures"] = 0  # reset circuit breaker on any success

        except errors.NewAgentFatalError as exc:
            # Fatal: log the crash, snapshot a final backup, exit cleanly
            # rather than continue on state we no longer trust.
            logger.log("system", f"[FATAL] {type(exc).__name__} (code {exc.error_code}): {exc}")
            try:
                backup.init_backup(BACKUPS_DIR)
            except Exception:
                pass  # best-effort — do not let the shutdown path itself crash
            tui.refresh_ui(
                history=history, exec_results=exec_results, stats=stats,
                cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                dryrun=config.get("dryrun_mode", False),
                context_bloat=ctx.get("_context_bloat", False),
                status=f"[FATAL] {exc} — shutting down.",
                agent_version=VERSION,
            )
            ctx["_exit_requested"] = True
            break

        except Exception as exc:
            # Recoverable (includes NewAgentRecoverableError and any other
            # exception the engine call can raise): count it toward the
            # circuit breaker, reset the prompter instance, log, warn, and
            # stay on the current turn's input for retry.
            ctx["_consecutive_turn_failures"] += 1
            logger.log("system", f"[RECOVERABLE] {type(exc).__name__}: {exc} (consecutive: {ctx["_consecutive_turn_failures"]})")

            # Plain-language failure reason. The raw exception text buries
            # "did your message even go through" under a RuntimeError/stack
            # string that's easy to miss in a single status line, especially
            # for a person dictating input by voice and not staring at the
            # screen. Rate-limit and network failures are the common,
            # recoverable case — call them out explicitly rather than making
            # the person infer it from "API Error: RuntimeError: ...".
            exc_str = str(exc)
            is_network_error = "No address associated with hostname" in exc_str or "urlopen error" in exc_str
            if "Rate-limited" in exc_str or "429" in exc_str:
                fail_reason = "RATE LIMITED — your message was NOT sent to the model."
            elif is_network_error:
                fail_reason = "NETWORK ERROR — your message was NOT sent (no connection)."
            elif "Auth error" in exc_str:
                fail_reason = "AUTH ERROR on API key — your message was NOT sent."
            elif "Server error" in exc_str:
                fail_reason = "SERVER ERROR from provider — your message was NOT sent."
            else:
                fail_reason = "your message was NOT sent."

            if ctx["_consecutive_turn_failures"] >= ctx["_max_consecutive_turn_failures"]:
                logger.log("system", f"[FATAL] {ctx['_consecutive_turn_failures']} consecutive turn failures — circuit breaker tripped.")
                try:
                    backup.init_backup(BACKUPS_DIR)
                except Exception:
                    pass
                tui.refresh_ui(
                    history=history, exec_results=exec_results, stats=stats,
                    cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                    dryrun=config.get("dryrun_mode", False),
                    context_bloat=ctx.get("_context_bloat", False),
                    status=f"[FATAL] {ctx['_consecutive_turn_failures']} consecutive failures ({exc}) — shutting down.",
                    agent_version=VERSION,
                )
                ctx["_exit_requested"] = True
                break

            # Stateful recovery: rebuild the REST prompter instance so a
            # single bad response/connection object doesn't keep poisoning
            # every subsequent turn.
            try:
                rest_prompter = rest.RestPrompter(key_reg, model_reg, MODEL_CATALOG_PATH, config, logs_dir=LOGS_DIR)
                ctx["_rest_prompter"] = rest_prompter
                init_engine()
            except Exception:
                pass  # best-effort reset — original error still reported below

            # Terminal bell (\a) so a failed send is noticeable even if the
            # person isn't looking at the screen (e.g. mid voice-to-text
            # dictation).
            print("\a", end="", flush=True)

            # Network-layer failures (dropped connection, no route) say
            # nothing about the message content, the model, or the keys —
            # the same turn is safe to auto-resend rather than leaving it
            # dead in history waiting on the person to notice and manually
            # retype it (audit: previously required manual resend, which
            # read as the agent silently ignoring the person mid-outage).
            # Other failure types (rate-limit, auth, server error) still
            # require a manual resend since retrying identically won't help.
            if is_network_error and config.get("network_error_auto_retry", True):
                tui.refresh_ui(
                    history=history, exec_results=exec_results, stats=stats,
                    cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                    dryrun=config.get("dryrun_mode", False),
                    context_bloat=ctx.get("_context_bloat", False),
                    status=(
                        f"MESSAGE FAILED TO SEND ({ctx['_consecutive_turn_failures']}/{ctx['_max_consecutive_turn_failures']}): "
                        f"{fail_reason} Reason: {exc} — auto-retrying same message..."
                    ),
                    agent_version=VERSION,
                )
                await asyncio.sleep(config.get("network_error_retry_backoff_seconds", 3.0))
                auto_continuing = True
                continue

            # Update TUI with warning state, stay on input.
            tui.refresh_ui(
                history=history, exec_results=exec_results, stats=stats,
                cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
                dryrun=config.get("dryrun_mode", False),
                context_bloat=ctx.get("_context_bloat", False),
                status=(
                    f"MESSAGE FAILED TO SEND ({ctx['_consecutive_turn_failures']}/{ctx['_max_consecutive_turn_failures']}): "
                    f"{fail_reason} Reason: {exc} — please resend."
                ),
                agent_version=VERSION,
            )
            continue

        # Add Gemini response to history
        ts = datetime.now().strftime("%H:%M:%S")
        history.append({"role": "model", "content": response_text, "_ts": ts})
        logger.log("model", response_text)

        # In REST mode, parse and run tags
        newagent_had_actionable_tags = False
        turn_actions = []
        if stats.engine == "rest":
            parsed_actions = actions.parse_actions(response_text)
            newagent_had_actionable_tags = bool(parsed_actions)
            if parsed_actions:
                # Execute queue of action tags
                results = await actions.run_action_queue(parsed_actions, ctx)
                exec_results.extend(results)
                turn_actions = results

                # Build XML payload of results
                payload = actions.assemble_results_payload(results)
                history.append({"role": "user", "content": payload, "_ts": ts})
                logger.log("user_system", payload)

                # Set auto continue
                if config.get("auto_continue_enabled", True):
                    auto_continuing = True
        else:
            turn_actions = exec_results[-len(call_log):] if 'call_log' in locals() and call_log else []

        # Log relational 104db records
        logger.log_turn_relational(
            model_used=model_reg.active,
            prompt_text=user_msg,
            response_text=response_text,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            duration_ms=(time.time() - turn_start_time) * 1000.0 if 'turn_start_time' in locals() else 0.0,
            actions_list=turn_actions,
        )

        # Process autonomy activation (applies to both engines if request_continue emitted)
        if ctx.get("_continue_requested"):
            ctx["_continue_requested"] = False
            autonomy_active = True
            autonomy_turns_remaining = config.get("max_autonomy_turns", 20)
        elif autonomy_active and not newagent_had_actionable_tags:
            # BUGFIX pkg030 (2026-07-23): a turn under autonomy that emits no
            # action tags (e.g. plain prose asking the user a question) has
            # nothing left for the agent to auto-drive. Previously autonomy
            # stayed active with no new history appended, so the loop kept
            # re-prompting the model against unchanged/stale history every
            # ~5s until max_autonomy_turns was exhausted (see
            # logs/session_2026-07-23_04-45-18.md, 04:51:45 onward). Stop
            # autonomy here instead and return control to the user.
            autonomy_active = False
            autonomy_turns_remaining = 0

        # Save session for resume
        if stats.engine == "interactions":
            session.save_native_resume(
                NATIVE_RESUME_PATH,
                int_prompter.previous_interaction_id or "",
                recap=tui.truncate_string(response_text, 100),
            )
        else:
            session.save_resume_session(RESUME_PATH, history)

        # Final screen repaint for this turn
        tui.refresh_ui(
            history=history, exec_results=exec_results, stats=stats,
            cwd=ctx["_cwd"], input_mode=config.get("input_mode", 0),
            dryrun=config.get("dryrun_mode", False),
        context_bloat=ctx.get("_context_bloat", False),
            agent_version=VERSION,
        )

    # 7. Post-execution Cleanup & Save session
    print("\nSession finished.")
    try:
        print("Archive this named session? (Enter label to save, or press Enter to skip): ", end="")
        label = input().strip()
        if label:
            session.archive_named_session(LOGS_DIR / "sessions" / "session_index.bejson", label, logger.log_path)
            print(f"Session archived with label: {label}")
    except EOFError:
        pass  # Non-interactive / piped input — skip archive prompt

    ctx["_clear_resume"]()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited via KeyboardInterrupt.")
    except errors.NewAgentFatalError as fatal_exc:
        print(f"\n[FATAL] {type(fatal_exc).__name__} (code {fatal_exc.error_code}): {fatal_exc}")
        print("NewAgent could not establish a working environment. See logs/ for details.")
