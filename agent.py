"""
Name:         agent.py
Family:       NewAgent
Description:  Lean orchestrator and async main event loop dispatcher.
              Switches dynamically between REST and Interactions engines and
              delegates bootstrap, tool-map construction, autonomy/loop-guard
              state, and exception classification through gated modular service
              abstraction layers (lib_bejson_newagent_service_gates.py).
Version:      2.24.0
Date:         2026-11-12
Author:       Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:      PolyForm-Noncommercial-1.0.0
RELATIONAL_ID: 7b4e1a82-9c3d-4f6b-8e2a-1d5c9f3a7b40

CHANGELOG:
- 2.24.0 (2026-11-12): Audited taxonomies (<hierarchy>_<group>_<purpose>), eliminated
  single-letter and cryptic variable identifiers, and separated runtime lifecycle,
  native tool dispatch map construction, autonomy/auto-continue loop guard, and
  circuit-breaker exception classification into gated modular service abstractions
  (ServiceGateAgentRuntimeController and AgentAutonomyGateState in
  lib_bejson_newagent_service_gates.py).
- 2.23.0 (2026-10-17): Guard mid-turn `network_error_auto_retry` when running in Interactions
  mode so turns that already executed mutating tool calls (`turn_had_side_effects == True`)
  are not re-dispatched from step 0 after a transient connection drop. Also expand
  `is_network_error` to match aiohttp `"Connection error:"` and `"Request timed out"` strings.
- 2.22.0 (2026-10-16): Auto-continue guard. Stops on echo-only batches, identical repeated
  batches, or max_auto_continue_turns (default 12) consecutive auto-continues.
- 2.21.0 (2026-10-14): Added provider routing safety check to turn execution loop,
  ensuring non-Gemini models route via REST engine even if engine_mode is set to interactions.
- 2.20.0 (2026-10-10): Integrated OpenRouter routing capability into engine_rest.py and
  enabled strict KeyRegistry SHA-256 ledger validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Insert lib/ directory into path to resolve lib_bejson_newagent_* correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_backup as backup
import lib_bejson_newagent_commands as commands
import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_engine_interactions as interactions
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_env as newagent_env
import lib_bejson_newagent_errors as errors
import lib_bejson_newagent_input as input_lib
import lib_bejson_newagent_jobs as jobs
import lib_bejson_newagent_session as session
import lib_bejson_newagent_startup as startup
import lib_bejson_newagent_subagent_sessions as subagent_sessions
import lib_bejson_newagent_tui as tui
from lib_bejson_newagent_service_gates import (
    AgentAutonomyGateState,
    ServiceGateAgentRuntimeController,
)

VERSION = "2.24.0"
RELATIONAL_ID = "7b4e1a82-9c3d-4f6b-8e2a-1d5c9f3a7b40"

# Directories configuration
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"
BACKUPS_DIR = BASE_DIR / "backups"
CONTEXT_DIR = BASE_DIR / "Context"
JOBS_DIR = BASE_DIR / "jobs"
SUBAGENTS_DIR = BASE_DIR / "subagents"

# Registry file paths
KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"
CONFIG_PATH = CONFIG_DIR / "config.json"
RESUME_PATH = CONFIG_DIR / "session_resume.json"
NATIVE_RESUME_PATH = CONFIG_DIR / "native_resume.json"
SNIPPETS_PATH = CONFIG_DIR / "snippets.bejson"


def _prompt_resume_yes_no(prompt_label_text: str) -> bool:
    """Safely prompt the user to resume a prior session, defaulting to False on EOF/interrupt."""
    print(prompt_label_text, end="")
    try:
        user_answer_text = input().strip().lower()
        return user_answer_text in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\n[No input available -- defaulting to 'No'.]")
        return False


async def main() -> None:
    running_event_loop = asyncio.get_running_loop()
    current_main_task = asyncio.current_task()
    ServiceGateAgentRuntimeController.gate_register_sigterm_cancellation(
        running_event_loop, current_main_task
    )

    # 1. Setup Directories & Back up registries via gated bootstrap controller
    ServiceGateAgentRuntimeController.gate_bootstrap_directories_and_registries(
        config_dir_path=CONFIG_DIR,
        logs_dir_path=LOGS_DIR,
        backups_dir_path=BACKUPS_DIR,
        jobs_dir_path=JOBS_DIR,
        subagents_dir_path=SUBAGENTS_DIR,
        keys_file_path=KEYS_PATH,
        models_file_path=MODELS_PATH,
        model_catalog_file_path=MODEL_CATALOG_PATH,
    )

    # 2. Initialize configuration and key/model registries
    try:
        runtime_config_map = config_lib.init_config(CONFIG_PATH)
        _, env_sync_diagnostic_detail = rest.sync_keys_from_env_sources(
            KEYS_PATH, runtime_config_map
        )
        key_registry_instance = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
        model_registry_instance = rest.ModelRegistry(MODELS_PATH)
    except errors.NewAgentFatalError:
        raise
    except Exception as registry_init_exception:
        raise errors.RegistryAccessError(
            f"key_reg/model_reg/config could not be established: {registry_init_exception}"
        ) from registry_init_exception

    # Configure Python logging
    configured_log_level = getattr(
        logging, runtime_config_map.get("log_level", "INFO"), logging.INFO
    )
    logging.basicConfig(
        level=configured_log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    backup.init_backup(BACKUPS_DIR)
    input_lib.init_input(SNIPPETS_PATH)
    bubble.init_context_bubble(CONTEXT_DIR, CONFIG_DIR, LOGS_DIR)

    # Display startup banner
    startup.show_startup(
        agent_version=VERSION,
        key_count=len(key_registry_instance.keys),
        model=model_registry_instance.active,
    )

    try:
        # 3. Setup Runtime Context dictionary
        conversation_history_list: list[dict] = []
        turn_exec_results_list: list = []
        session_stats_tracker = tui.SessionStats(
            key_total=len(key_registry_instance.keys),
            engine=runtime_config_map.get("engine_mode", "rest"),
        )

        runtime_context_map = {
            "config": runtime_config_map,
            "history": conversation_history_list,
            "stats": session_stats_tracker,
            "key_reg": key_registry_instance,
            "model_reg": model_registry_instance,
            "key_call_counts": {},
            "exec_results": turn_exec_results_list,
            "trigger_cooldowns": {},
            "_cwd": str(Path.cwd()),
            "_shell_env": None,
            "_start_time": time.time(),
            "_consecutive_turn_failures": 0,
            "_max_consecutive_turn_failures": 3,
            "_exit_requested": False,
            "_continue_requested": False,
            "_backups_dir": BACKUPS_DIR,
            "_config_dir": CONFIG_DIR,
            "_context_dir": CONTEXT_DIR,
            "_jobs_dir": JOBS_DIR,
            "_active_job_path": None,
            "_active_job_doc": None,
            "_save_config": lambda: config_lib.save_config(
                CONFIG_PATH, runtime_config_map
            ),
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
            "_rollback_checkpoint": lambda checkpoint_label: actions.rollback_checkpoint(
                checkpoint_label, BACKUPS_DIR
            ),
        }

        # Setup Session Logger
        session_transcript_logger = session.SessionLogger(LOGS_DIR)
        runtime_context_map["_logger"] = session_transcript_logger

        if len(key_registry_instance.keys) == 0:
            session_transcript_logger.log(
                "system",
                f"[EnvSync] Synced 0 keys. {env_sync_diagnostic_detail or newagent_env.describe_env_sources(runtime_config_map)}",
            )

        # 4. Check for Resume Session
        resumed_prior_session = False
        if runtime_config_map.get("engine_mode") == "interactions":
            native_resume_state = session.load_native_resume(NATIVE_RESUME_PATH)
            if native_resume_state:
                if _prompt_resume_yes_no(
                    "\nFound a prior Interactions session. Resume? [y/N]: "
                ):
                    conversation_history_list = [
                        {
                            "role": "user",
                            "content": f"Resuming previous session recap: {native_resume_state.get('recap', '')}",
                        }
                    ]
                    runtime_context_map["history"] = conversation_history_list
                    resumed_prior_session = True
        else:
            saved_rest_history = session.load_resume_session(RESUME_PATH)
            if saved_rest_history:
                if _prompt_resume_yes_no(
                    "\nFound a prior REST session. Resume? [y/N]: "
                ):
                    conversation_history_list = saved_rest_history
                    runtime_context_map["history"] = conversation_history_list
                    resumed_prior_session = True

        if not resumed_prior_session:
            runtime_context_map["_clear_resume"]()

        # 5. Initialize API Prompters
        rest_engine_prompter = rest.RestPrompter(
            key_registry_instance,
            model_registry_instance,
            MODEL_CATALOG_PATH,
            runtime_config_map,
            logs_dir=LOGS_DIR,
        )
        runtime_context_map["_rest_prompter"] = rest_engine_prompter

        if (
            runtime_config_map.get("health_check_on_startup", True)
            and runtime_config_map.get("engine_mode", "rest") == "rest"
        ):
            print("Running startup health check...")
            try:
                health_check_passed, health_check_message = (
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: rest.health_check_ping(rest_engine_prompter)
                    )
                )
            except Exception as health_check_exception:
                health_check_passed = False
                health_check_message = (
                    f"Health check FAILED to run: {health_check_exception}"
                )
            print(health_check_message)
            session_transcript_logger.log(
                "system",
                f"[HEALTH_CHECK] {'OK' if health_check_passed else 'FAILED'}: {health_check_message}",
            )

        # Build native function calling map via gated service controller
        interactions_tool_dispatch_map = (
            ServiceGateAgentRuntimeController.gate_build_interactions_tool_map(
                runtime_context_map=runtime_context_map,
                runtime_config_map=runtime_config_map,
                backups_dir_path=BACKUPS_DIR,
            )
        )

        interactions_engine_prompter = interactions.InteractionsPrompter(
            key_registry_instance,
            model_registry_instance,
            interactions_tool_dispatch_map,
            tool_scope=runtime_config_map.get("native_tools_scope", "all"),
            max_rounds=runtime_config_map.get("interactions_max_rounds", 10),
        )

        if (
            runtime_config_map.get("engine_mode") == "interactions"
            and resumed_prior_session
        ):
            native_resume_state = session.load_native_resume(NATIVE_RESUME_PATH)
            if native_resume_state:
                interactions_engine_prompter._prev_id = native_resume_state.get(
                    "interaction_id"
                )

        def _rebind_active_engine() -> None:
            session_stats_tracker.engine = runtime_config_map.get(
                "engine_mode", "rest"
            )
            if session_stats_tracker.engine == "interactions":
                runtime_context_map["prompter"] = interactions_engine_prompter
            else:
                runtime_context_map["prompter"] = rest_engine_prompter

        runtime_context_map["_init_engine"] = _rebind_active_engine
        _rebind_active_engine()

        # 6. Main Interactive TUI Event Loop
        tui.refresh_ui(
            history=conversation_history_list,
            exec_results=turn_exec_results_list,
            stats=session_stats_tracker,
            cwd=runtime_context_map["_cwd"],
            input_mode=runtime_config_map.get("input_mode", 0),
            dryrun=runtime_config_map.get("dryrun_mode", False),
            context_bloat=runtime_context_map.get("_context_bloat", False),
            agent_version=VERSION,
        )

        autonomy_gate_state = AgentAutonomyGateState()

        while not runtime_context_map["_exit_requested"]:
            turn_start_epoch_seconds = time.time()

            # Synchronize key registry totals in session stats
            session_stats_tracker.key_slot = key_registry_instance.active_slot
            session_stats_tracker.key_total = len(key_registry_instance.keys)

            # Autonomy countdown check
            if (
                autonomy_gate_state.autonomy_mode_active_flag
                and autonomy_gate_state.autonomy_turns_remaining_count <= 0
            ):
                autonomy_gate_state.autonomy_mode_active_flag = False
                autonomy_gate_state.auto_continuing_next_turn_flag = False
                tui.refresh_ui(
                    history=conversation_history_list,
                    exec_results=turn_exec_results_list,
                    stats=session_stats_tracker,
                    cwd=runtime_context_map["_cwd"],
                    input_mode=runtime_config_map.get("input_mode", 0),
                    dryrun=runtime_config_map.get("dryrun_mode", False),
                    context_bloat=runtime_context_map.get("_context_bloat", False),
                    status="Autonomy turn limit reached. Press Enter to proceed.",
                    agent_version=VERSION,
                )

            # Prompt for user input when manual gate is active
            if (
                not autonomy_gate_state.autonomy_mode_active_flag
                and not autonomy_gate_state.auto_continuing_next_turn_flag
            ):
                session_stats_tracker.key_slot = key_registry_instance.active_slot
                user_prompt_text = input_lib.get_input(
                    prompt="> ",
                    mode=runtime_config_map.get("input_mode", 0),
                    multi_line=runtime_config_map.get("multi_line_mode", False),
                )

                if not user_prompt_text:
                    continue

                # Slash command execution
                if user_prompt_text.strip().startswith("/"):
                    command_was_handled, slash_command_output = (
                        await commands.handle_slash_commands(
                            user_prompt_text, runtime_context_map
                        )
                    )
                    if command_was_handled:
                        if runtime_context_map["_exit_requested"]:
                            break
                        tui.refresh_ui(
                            history=conversation_history_list,
                            exec_results=turn_exec_results_list,
                            stats=session_stats_tracker,
                            cwd=runtime_context_map["_cwd"],
                            input_mode=runtime_config_map.get("input_mode", 0),
                            dryrun=runtime_config_map.get("dryrun_mode", False),
                            context_bloat=runtime_context_map.get(
                                "_context_bloat", False
                            ),
                            status=slash_command_output or "",
                            agent_version=VERSION,
                        )
                        continue

                turn_timestamp_hms = datetime.now().strftime("%H:%M:%S")
                conversation_history_list.append(
                    {
                        "role": "user",
                        "content": user_prompt_text,
                        "_ts": turn_timestamp_hms,
                    }
                )
                session_transcript_logger.log("user", user_prompt_text)
                autonomy_gate_state.reset_manual_turn_counters()
            else:
                if autonomy_gate_state.auto_continuing_next_turn_flag:
                    autonomy_gate_state.auto_continuing_next_turn_flag = False
                if autonomy_gate_state.autonomy_mode_active_flag:
                    autonomy_gate_state.autonomy_turns_remaining_count -= 1

            # Clear execution results for fresh turn display
            turn_exec_results_list.clear()

            tui.refresh_ui(
                history=conversation_history_list,
                exec_results=turn_exec_results_list,
                stats=session_stats_tracker,
                cwd=runtime_context_map["_cwd"],
                input_mode=runtime_config_map.get("input_mode", 0),
                dryrun=runtime_config_map.get("dryrun_mode", False),
                context_bloat=runtime_context_map.get("_context_bloat", False),
                status="Awaiting response...",
                agent_version=VERSION,
            )

            # Context Bubble assembly
            active_user_prompt_text = (
                conversation_history_list[-1]["content"]
                if conversation_history_list
                else ""
            )
            try:
                assembled_bubble_result = bubble.assemble_bubble(
                    CONTEXT_DIR,
                    CONFIG_DIR,
                    active_user_prompt_text,
                    turn=session_stats_tracker.turns + 1,
                    cooldown_state=runtime_context_map["trigger_cooldowns"],
                    cwd=runtime_context_map["_cwd"],
                    env_file_paths=[
                        str(env_source_path)
                        for env_source_path in newagent_env.resolve_env_bejson_sources(
                            runtime_config_map
                        )
                    ],
                    config=runtime_config_map,
                )
            except errors.ContextInjectionError as context_injection_exception:
                session_transcript_logger.log(
                    "system",
                    f"[RECOVERABLE] {type(context_injection_exception).__name__}: {context_injection_exception} — using minimal context for this turn.",
                )
                assembled_bubble_result = bubble.build_minimal_bubble(
                    CONTEXT_DIR, CONFIG_DIR
                )

            assembled_bubble_text = assembled_bubble_result["text"]
            observer_compression_note = ""

            if (
                assembled_bubble_result["observer_enabled"]
                and (session_stats_tracker.turns + 1)
                % max(assembled_bubble_result["observer_refinement_interval"], 1)
                == 0
                and len(assembled_bubble_text)
                // assembled_bubble_result["chars_per_token"]
                > assembled_bubble_result["max_context_tokens"]
            ):
                compressed_bubble_segments = bubble.run_observer_compression(
                    keyword_text="",
                    knowledge_text=assembled_bubble_text,
                    rest_prompter=rest_engine_prompter,
                )
                if compressed_bubble_segments:
                    assembled_bubble_text = (
                        f"## Compressed Context\n{compressed_bubble_segments[0]}"
                    )
                    observer_compression_note = "compressed (over budget)"

            runtime_context_map["_context_bloat"] = (
                len(assembled_bubble_text)
                // assembled_bubble_result["chars_per_token"]
            ) > assembled_bubble_result["max_context_tokens"]

            session_transcript_logger.update_last_bubble(
                bubble_content=assembled_bubble_text,
                policy_tokens=assembled_bubble_result["policy_tokens"],
                active_tasks_tokens=assembled_bubble_result["active_tasks_tokens"],
                env_file_tokens=assembled_bubble_result["env_file_tokens"],
                cwd_tokens=assembled_bubble_result["cwd_tokens"],
                keyword_tokens=assembled_bubble_result["keyword_tokens"],
                knowledge_tokens=assembled_bubble_result["knowledge_tokens"],
                observer_note=observer_compression_note,
            )

            compiled_system_instruction = actions.build_system_prompt(
                runtime_context_map["_cwd"],
                assembled_bubble_text,
                active_job=jobs.build_job_context_block(
                    runtime_context_map.get("_active_job_doc")
                ),
            )

            # Dispatch turn to selected engine
            model_response_text = ""
            interactions_call_log: list[dict] = []
            try:
                session_stats_tracker.turns_sent += 1
                catalog_record_rows = rest.load_model_catalog(MODEL_CATALOG_PATH)
                active_model_provider = rest_engine_prompter._resolve_provider(
                    catalog_record_rows, model_registry_instance.active
                )
                if (
                    session_stats_tracker.engine == "interactions"
                    and active_model_provider == "gemini"
                ):
                    (
                        interactions_response_text,
                        interactions_usage_metadata,
                        interactions_call_log,
                    ) = await interactions_engine_prompter.run_turn(
                        user_input=conversation_history_list[-1]["content"],
                        system_instruction=compiled_system_instruction,
                        denylist=runtime_config_map.get("exec_denylist"),
                        dryrun=runtime_config_map.get("dryrun_mode", False),
                    )
                    model_response_text = interactions_response_text
                    for call_log_entry in interactions_call_log:
                        turn_exec_results_list.append(
                            tui.ExecResult(
                                action_type=call_log_entry["name"],
                                source=json.dumps(call_log_entry["args"]),
                                output=call_log_entry["result"],
                                exit_code=0 if call_log_entry["ok"] else -1,
                            )
                        )
                    session_stats_tracker.input_tokens = (
                        interactions_usage_metadata.get("total_input_tokens", 0)
                    )
                    session_stats_tracker.output_tokens = (
                        interactions_usage_metadata.get("total_output_tokens", 0)
                    )
                else:
                    rest_response_text, rest_usage_metadata = (
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: rest_engine_prompter.prompt(
                                conversation_history_list,
                                compiled_system_instruction,
                            ),
                        )
                    )
                    model_response_text = rest_response_text
                    session_stats_tracker.input_tokens = rest_usage_metadata.get(
                        "promptTokenCount", 0
                    )
                    session_stats_tracker.output_tokens = rest_usage_metadata.get(
                        "candidatesTokenCount", 0
                    )

                used_api_key_value = key_registry_instance.keys[
                    (key_registry_instance._index - 1)
                    % len(key_registry_instance.keys)
                ]
                runtime_context_map["key_call_counts"][used_api_key_value] = (
                    runtime_context_map["key_call_counts"].get(used_api_key_value, 0)
                    + 1
                )
                session_stats_tracker.turns += 1
                runtime_context_map["_consecutive_turn_failures"] = 0

            except errors.NewAgentFatalError as fatal_turn_exception:
                session_transcript_logger.log(
                    "system",
                    f"[FATAL] {type(fatal_turn_exception).__name__} (code {fatal_turn_exception.error_code}): {fatal_turn_exception}",
                )
                try:
                    backup.init_backup(BACKUPS_DIR)
                except Exception:
                    pass
                tui.refresh_ui(
                    history=conversation_history_list,
                    exec_results=turn_exec_results_list,
                    stats=session_stats_tracker,
                    cwd=runtime_context_map["_cwd"],
                    input_mode=runtime_config_map.get("input_mode", 0),
                    dryrun=runtime_config_map.get("dryrun_mode", False),
                    context_bloat=runtime_context_map.get("_context_bloat", False),
                    status=f"[FATAL] {fatal_turn_exception} — shutting down.",
                    agent_version=VERSION,
                )
                runtime_context_map["_exit_requested"] = True
                break

            except Exception as recoverable_turn_exception:
                runtime_context_map["_consecutive_turn_failures"] += 1
                session_transcript_logger.log(
                    "system",
                    f"[RECOVERABLE] {type(recoverable_turn_exception).__name__}: {recoverable_turn_exception} (consecutive: {runtime_context_map['_consecutive_turn_failures']})",
                )

                is_network_error, mid_turn_mutated, failure_reason_summary = (
                    ServiceGateAgentRuntimeController.gate_classify_turn_exception(
                        caught_turn_exception=recoverable_turn_exception,
                        active_engine_mode=session_stats_tracker.engine,
                        interactions_prompter_instance=interactions_engine_prompter,
                    )
                )

                if (
                    runtime_context_map["_consecutive_turn_failures"]
                    >= runtime_context_map["_max_consecutive_turn_failures"]
                ):
                    session_transcript_logger.log(
                        "system",
                        f"[FATAL] {runtime_context_map['_consecutive_turn_failures']} consecutive turn failures — circuit breaker tripped.",
                    )
                    try:
                        backup.init_backup(BACKUPS_DIR)
                    except Exception:
                        pass
                    tui.refresh_ui(
                        history=conversation_history_list,
                        exec_results=turn_exec_results_list,
                        stats=session_stats_tracker,
                        cwd=runtime_context_map["_cwd"],
                        input_mode=runtime_config_map.get("input_mode", 0),
                        dryrun=runtime_config_map.get("dryrun_mode", False),
                        context_bloat=runtime_context_map.get(
                            "_context_bloat", False
                        ),
                        status=f"[FATAL] {runtime_context_map['_consecutive_turn_failures']} consecutive failures ({recoverable_turn_exception}) — shutting down.",
                        agent_version=VERSION,
                    )
                    runtime_context_map["_exit_requested"] = True
                    break

                # Rebuild REST prompter instance for stateful recovery
                try:
                    rest_engine_prompter = rest.RestPrompter(
                        key_registry_instance,
                        model_registry_instance,
                        MODEL_CATALOG_PATH,
                        runtime_config_map,
                        logs_dir=LOGS_DIR,
                    )
                    runtime_context_map["_rest_prompter"] = rest_engine_prompter
                    _rebind_active_engine()
                except Exception:
                    pass

                print("\a", end="", flush=True)

                if (
                    is_network_error
                    and runtime_config_map.get("network_error_auto_retry", True)
                    and not mid_turn_mutated
                ):
                    tui.refresh_ui(
                        history=conversation_history_list,
                        exec_results=turn_exec_results_list,
                        stats=session_stats_tracker,
                        cwd=runtime_context_map["_cwd"],
                        input_mode=runtime_config_map.get("input_mode", 0),
                        dryrun=runtime_config_map.get("dryrun_mode", False),
                        context_bloat=runtime_context_map.get(
                            "_context_bloat", False
                        ),
                        status=(
                            f"MESSAGE FAILED TO SEND ({runtime_context_map['_consecutive_turn_failures']}/{runtime_context_map['_max_consecutive_turn_failures']}): "
                            f"{failure_reason_summary} Reason: {recoverable_turn_exception} — auto-retrying same message..."
                        ),
                        agent_version=VERSION,
                    )
                    await asyncio.sleep(
                        runtime_config_map.get(
                            "network_error_retry_backoff_seconds", 3.0
                        )
                    )
                    autonomy_gate_state.auto_continuing_next_turn_flag = True
                    continue

                tui.refresh_ui(
                    history=conversation_history_list,
                    exec_results=turn_exec_results_list,
                    stats=session_stats_tracker,
                    cwd=runtime_context_map["_cwd"],
                    input_mode=runtime_config_map.get("input_mode", 0),
                    dryrun=runtime_config_map.get("dryrun_mode", False),
                    context_bloat=runtime_context_map.get("_context_bloat", False),
                    status=(
                        f"MESSAGE FAILED TO SEND ({runtime_context_map['_consecutive_turn_failures']}/{runtime_context_map['_max_consecutive_turn_failures']}): "
                        f"{failure_reason_summary} Reason: {recoverable_turn_exception} — please resend."
                    ),
                    agent_version=VERSION,
                )
                continue

            # Append model response to history and transcript
            turn_timestamp_hms = datetime.now().strftime("%H:%M:%S")
            conversation_history_list.append(
                {
                    "role": "model",
                    "content": model_response_text,
                    "_ts": turn_timestamp_hms,
                }
            )
            session_transcript_logger.log("model", model_response_text)

            # In REST mode, parse and execute XML action tags
            turn_emitted_actionable_tags = False
            executed_turn_actions_list: list = []
            if session_stats_tracker.engine == "rest":
                parsed_actions = actions.parse_actions(model_response_text)
                turn_emitted_actionable_tags = bool(parsed_actions)
                if parsed_actions:
                    executed_queue_results = await actions.run_action_queue(
                        parsed_actions, runtime_context_map
                    )
                    turn_exec_results_list.extend(executed_queue_results)
                    executed_turn_actions_list = executed_queue_results

                    compiled_results_xml_payload = actions.assemble_results_payload(
                        executed_queue_results
                    )
                    conversation_history_list.append(
                        {
                            "role": "user",
                            "content": compiled_results_xml_payload,
                            "_ts": turn_timestamp_hms,
                        }
                    )
                    session_transcript_logger.log(
                        "user_system", compiled_results_xml_payload
                    )

                    if runtime_config_map.get("auto_continue_enabled", True):
                        autonomy_gate_state.auto_continuing_next_turn_flag = True

                    if autonomy_gate_state.auto_continuing_next_turn_flag:
                        configured_max_auto_continue = int(
                            runtime_config_map.get("max_auto_continue_turns", 12)
                            or 0
                        )
                        _announcement_only_flag = actions.is_announcement_only(parsed_actions)
                        loop_guard_stop_reason = (
                            autonomy_gate_state.evaluate_auto_continue_guard(
                                parsed_actions_list=parsed_actions,
                                max_auto_continue_turns_cap=configured_max_auto_continue,
                            )
                        )
                        if loop_guard_stop_reason:
                            session_transcript_logger.log(
                                "system",
                                f"[AUTO-CONTINUE STOPPED] {loop_guard_stop_reason}",
                            )
                            tui.refresh_ui(
                                history=conversation_history_list,
                                exec_results=turn_exec_results_list,
                                stats=session_stats_tracker,
                                cwd=runtime_context_map["_cwd"],
                                input_mode=runtime_config_map.get("input_mode", 0),
                                dryrun=runtime_config_map.get("dryrun_mode", False),
                                context_bloat=runtime_context_map.get(
                                    "_context_bloat", False
                                ),
                                status=f"Auto-continue stopped: {loop_guard_stop_reason}. Awaiting input.",
                                agent_version=VERSION,
                            )
            else:
                executed_turn_actions_list = (
                    turn_exec_results_list[-len(interactions_call_log) :]
                    if interactions_call_log
                    else []
                )

            # Record relational 104db turn telemetry
            session_transcript_logger.log_turn_relational(
                model_used=model_registry_instance.active,
                prompt_text=active_user_prompt_text,
                response_text=model_response_text,
                input_tokens=session_stats_tracker.input_tokens,
                output_tokens=session_stats_tracker.output_tokens,
                duration_ms=(time.time() - turn_start_epoch_seconds) * 1000.0,
                actions_list=executed_turn_actions_list,
            )

            # Process autonomy activation / deactivation
            if runtime_context_map.get("_continue_requested"):
                runtime_context_map["_continue_requested"] = False
                autonomy_gate_state.autonomy_mode_active_flag = True
                autonomy_gate_state.autonomy_turns_remaining_count = (
                    runtime_config_map.get("max_autonomy_turns", 20)
                )
            elif (
                autonomy_gate_state.autonomy_mode_active_flag
                and not turn_emitted_actionable_tags
            ):
                autonomy_gate_state.autonomy_mode_active_flag = False
                autonomy_gate_state.autonomy_turns_remaining_count = 0

            # Enforce max_history_turns cap
            bubble.trim_history(
                conversation_history_list,
                runtime_config_map.get("max_history_turns", 20),
            )

            # Persist session state for resume
            if session_stats_tracker.engine == "interactions":
                session.save_native_resume(
                    NATIVE_RESUME_PATH,
                    interactions_engine_prompter.previous_interaction_id or "",
                    recap=tui.truncate_string(model_response_text, 100),
                )
            else:
                session.save_resume_session(RESUME_PATH, conversation_history_list)

            # Repaint TUI for completed turn
            tui.refresh_ui(
                history=conversation_history_list,
                exec_results=turn_exec_results_list,
                stats=session_stats_tracker,
                cwd=runtime_context_map["_cwd"],
                input_mode=runtime_config_map.get("input_mode", 0),
                dryrun=runtime_config_map.get("dryrun_mode", False),
                context_bloat=runtime_context_map.get("_context_bloat", False),
                agent_version=VERSION,
            )

    except asyncio.CancelledError:
        print(
            "\n[SIGTERM] Shutdown requested -- session left resumable, no archive prompt."
        )
        try:
            session_transcript_logger.log(
                "system",
                "[SIGTERM] Process cancelled; last completed turn's resume state left on disk.",
            )
        except Exception:
            pass
        return

    # 7. Post-execution Cleanup & Optional Session Archive
    print("\nSession finished.")
    try:
        print(
            "Archive this named session? (Enter label to save, or press Enter to skip): ",
            end="",
        )
        archive_session_label = input().strip()
        if archive_session_label:
            session.archive_named_session(
                LOGS_DIR / "sessions" / "session_index.bejson",
                archive_session_label,
                session_transcript_logger.log_path,
            )
            print(f"Session archived with label: {archive_session_label}")
    except EOFError:
        pass

    runtime_context_map["_clear_resume"]()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nExited via KeyboardInterrupt/SIGTERM.")
    except errors.NewAgentFatalError as fatal_startup_exception:
        print(
            f"\n[FATAL] {type(fatal_startup_exception).__name__} (code {fatal_startup_exception.error_code}): {fatal_startup_exception}"
        )
        print(
            "NewAgent could not establish a working environment. See logs/ for details."
        )
