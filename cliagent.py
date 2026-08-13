#!/data/data/com.termux/files/usr/bin/python3
"""
Name:         cliagent.py
Family:       NewAgent
Description:  CLI interface to run prompts against NewAgent engine (REST/Interactions) non-interactively or from scripts.
Version:      1.2.0
Date:         2026-08-05
Author:       Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID: 822614cf-fe8b-445d-90ad-7c129b27179c
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Add lib/ to sys.path
SCRIPT_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_PATH / "lib"))

import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_engine_interactions as interactions
import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_errors as errors

VERSION = "1.2.0"

CONFIG_DIR = SCRIPT_PATH / "config"
LOGS_DIR = SCRIPT_PATH / "logs"
BACKUPS_DIR = SCRIPT_PATH / "backups"
CONTEXT_DIR = SCRIPT_PATH / "Context"
KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"
# CONFIG_PATH stays the shared config.json (engine_mode, gen_*, env_file_path,
# exec_timeout_seconds, etc.) -- those are genuinely cross-tool infra
# settings, same as agent.py/webagent.py. CLI_CONFIG_PATH is cliagent's own,
# separate file for settings specific to non-interactive/scripted usage,
# so a person tuning "does cliagent default to --json" doesn't touch the
# TUI's settings and vice versa.
CONFIG_PATH = CONFIG_DIR / "config.json"
CLI_CONFIG_PATH = CONFIG_DIR / "cliagent_config.json"
CLI_POLICY_PATH = CONTEXT_DIR / "CLIAgent_Persistent_Policy.md"
CLI_INVOCATIONS_LOG = LOGS_DIR / "cliagent_invocations.md"

# cliagent's own persistent settings -- same (name, default, description)
# schema lib_bejson_newagent_config.py already uses, just a different file
# and a different set of defaults tailored to scripted/non-interactive use.
CLI_DEFAULT_CONFIG: list[tuple] = [
    ("json_output_default", False, "Default to --json output even when the flag isn't passed"),
    ("execute_default", False, "Default to --execute (auto-run XML tool actions) even when the flag isn't passed"),
    ("include_persistent_policy", True, "Prepend Context/CLIAgent_Persistent_Policy.md to every call's system instruction unless --no-context is passed"),
    ("log_invocations", True, "Append a one-line record of every call to logs/cliagent_invocations.md"),
    ("cli_max_retries", 3, "REST engine max_retries for cliagent calls specifically"),
    ("cli_timeout_seconds", 90, "REST engine per-request timeout (seconds) for cliagent calls specifically"),
]

_DEFAULT_CLI_POLICY_TEXT = (
    "You are cliagent, the non-interactive scripted entry point for NewAgent "
    "(Elton Boehnen). You are typically invoked from a script, pipe, or "
    "one-shot terminal command rather than a live conversation -- there is "
    "no back-and-forth to clarify ambiguity, so state assumptions briefly "
    "rather than asking a question that won't be seen. Respond concisely "
    "and directly, without conversational filler, since output may be "
    "captured, parsed, or piped into another command. Prefer surgical, "
    "minimal changes. Always test edits before declaring them done. Credit "
    "Elton Boehnen in files you create or modify."
)


def ensure_cli_persistent_policy(path: Path) -> str:
    """Create CLIAgent_Persistent_Policy.md with sensible defaults if it
    doesn't exist yet (never overwrites an existing one -- same
    create-if-missing pattern context_bubble.py already uses for the TUI's
    own Persistent_Policy.md), then return its current text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_DEFAULT_CLI_POLICY_TEXT, encoding="utf-8")
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return _DEFAULT_CLI_POLICY_TEXT


def build_cli_system_instruction(base_policy: str, per_call_system: str) -> str:
    """Persistent base chunk (identity + house rules) always first, then
    whatever task-specific --system text this particular call supplied, so
    a scripted caller still gets NewAgent's standing behavior even on a
    call that never passes --system at all."""
    if per_call_system:
        return f"{base_policy}\n\n{per_call_system}"
    return base_policy


def log_cli_invocation(log_path: Path, engine: str, model: str, prompt_text: str, executed_actions: list) -> None:
    """Best-effort one-line append per call. Never raises -- a logging
    failure must not break the actual CLI output the caller is relying on."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        prompt_snippet = prompt_text.replace("\n", " ").strip()[:120]
        actions_str = ",".join(executed_actions) if executed_actions else "-"
        line = f"- {ts} | engine={engine} model={model} actions=[{actions_str}] | {prompt_snippet}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            if log_path.stat().st_size == 0:
                f.write("# cliagent Invocation Log\n\nOne line per call: timestamp, engine, model, executed actions, prompt snippet.\n\n")
            f.write(line)
    except Exception:
        pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="cliagent: Run prompts via NewAgent engine non-interactively from scripts or terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cliagent "What is the capital of France?"
  echo "Explain Python asyncio" | cliagent -
  cliagent --model gemini-3.6-flash --engine rest "Analyze system logs"
  cliagent --engine interactions --execute "Create a test.txt file containing hello"
  cliagent --json "Summarize this data"
"""
    )
    parser.add_argument("prompt", nargs="?", help="Prompt text to send. Pass '-' to read from stdin.")
    parser.add_argument("-e", "--engine", choices=["rest", "interactions"], help="Override engine mode (default: config.json setting or 'rest').")
    parser.add_argument("-m", "--model", help="Override target model (e.g. gemini-3.6-flash, gemini-3.1-pro).")
    parser.add_argument("-s", "--system", default="", help="Custom system instruction for this turn.")
    parser.add_argument("-x", "--execute", action="store_true", help="Execute XML tool actions returned by REST engine automatically.")
    parser.add_argument("--json", action="store_true", help="Output result as JSON containing text, usage, engine, and model.")
    parser.add_argument("--no-context", action="store_true", help="Skip prepending Context/CLIAgent_Persistent_Policy.md -- send only --system (or nothing) as the system instruction.")
    parser.add_argument("--version", action="version", version=f"cliagent {VERSION}")
    return parser.parse_args()

async def run_cliagent():
    args = parse_args()

    # Get prompt text
    prompt_text = ""
    if args.prompt == "-":
        prompt_text = sys.stdin.read().strip()
    elif args.prompt:
        prompt_text = args.prompt.strip()
    else:
        if not sys.stdin.isatty():
            prompt_text = sys.stdin.read().strip()

    if not prompt_text:
        print("[ERROR] No prompt provided. Use positional prompt argument or pipe input via stdin.", file=sys.stderr)
        sys.exit(1)

    # Initialize environment & registries
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    rest.build_default_keys_bejson(KEYS_PATH)
    rest.build_default_models_bejson(MODELS_PATH)
    rest.build_default_model_catalog(MODEL_CATALOG_PATH)
    rest.backfill_model_catalog_api_profile(MODEL_CATALOG_PATH)
    rest.backfill_model_catalog_provider(MODEL_CATALOG_PATH)

    config = config_lib.init_config(CONFIG_PATH)
    cli_config = config_lib.init_config(CLI_CONFIG_PATH, schema=CLI_DEFAULT_CONFIG)
    rest.sync_keys_from_env_file(KEYS_PATH, Path(config.get("env_file_path", "")))

    key_reg = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
    model_reg = rest.ModelRegistry(MODELS_PATH)

    if args.model:
        model_reg.set_active(args.model)

    engine_mode = args.engine if args.engine else config.get("engine_mode", "rest")
    do_json = args.json or cli_config.get("json_output_default", False)
    do_execute = args.execute or cli_config.get("execute_default", False)

    # Persistent context bubble base chunk: identity + house rules that
    # apply to every scripted call, not just this one -- own file, separate
    # from the interactive TUI's Context/Persistent_Policy.md, since a
    # scripted caller's default behavior (terse, no back-and-forth) is
    # deliberately different from the live-conversation agent's.
    if args.no_context:
        system_instruction = args.system
    else:
        base_policy = ensure_cli_persistent_policy(CLI_POLICY_PATH)
        if not cli_config.get("include_persistent_policy", True):
            system_instruction = args.system
        else:
            system_instruction = build_cli_system_instruction(base_policy, args.system)

    # Disable verbosity for clean output unless debug logging is set
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s: %(message)s")

    cwd = str(Path.cwd())
    exec_results = []
    executed_actions = []

    if engine_mode == "rest":
        rest_prompter = rest.RestPrompter(
            key_reg, model_reg, MODEL_CATALOG_PATH, config, logs_dir=LOGS_DIR,
            timeout=cli_config.get("cli_timeout_seconds", 90),
            max_retries=cli_config.get("cli_max_retries", 3),
        )
        history = [{"role": "user", "content": prompt_text}]

        response_text, usage = await asyncio.get_event_loop().run_in_executor(
            None, lambda: rest_prompter.prompt(history, system_instruction=system_instruction)
        )

        if do_execute:
            parsed_actions = actions.parse_xml_actions(response_text)
            if parsed_actions:
                ctx = {
                    "config": config,
                    "cwd": cwd,
                    "exec_results": exec_results,
                    "_shell_env": None,
                    "_backups_dir": BACKUPS_DIR,
                    "_config_dir": CONFIG_DIR,
                }
                res_output, updated_cwd, _ = await actions.run_action_queue(parsed_actions, ctx)
                cwd = updated_cwd
                executed_actions = [a.get("tag") for a in parsed_actions]

    else:
        # Engine Interactions
        async def async_run_exec(command: str) -> str:
            code, out, new_cwd, _ = await actions.do_exec(
                command, cwd, config.get("exec_timeout_seconds", 60), live_feed=False
            )
            return out

        do_map = {
            "do_exec": async_run_exec,
            "do_read_file": lambda path: actions.do_read_file(path, cwd),
            "do_write_file": lambda path, content: actions.do_write_file(path, content, cwd),
            "do_edit_file": lambda path, old_text, new_text: actions.do_edit_file(path, old_text, new_text, cwd),
            "do_list_dir": lambda path: actions.do_list_dir(path, cwd),
            "do_tree_view": lambda path, depth=3: actions.do_tree_view(path, cwd, depth=depth),
            "do_make_dir": lambda path: actions.do_make_dir(path, cwd),
            "do_delete_file": lambda path: actions.do_delete_file(path, cwd),
            "do_copy_file": lambda src, dst: actions.do_copy_file(src, dst, cwd),
            "do_diff_file": lambda path: actions.do_diff_file(path, cwd),
            "do_restore_file": actions.do_restore_file,
            "do_http_get": actions.do_http_get,
            "do_find_files": lambda pattern, base=".": actions.do_find_files(pattern, base, cwd),
            "do_search_text": lambda pattern, path=".": actions.do_search_text(pattern, path, cwd),
            "do_fuzzy_find": lambda query: actions.do_fuzzy_find(query, cwd),
            "do_env_get": actions.do_env_get,
            "do_speak": actions.do_speak,
            "do_checkpoint": lambda label: actions.do_checkpoint(label, BACKUPS_DIR),
        }

        int_prompter = interactions.InteractionsPrompter(
            key_reg, model_reg, do_map,
            tool_scope=config.get("native_tools_scope", "all"),
            max_rounds=config.get("interactions_max_rounds", 10),
        )

        response_text, usage, call_log = await int_prompter.run_turn(
            user_input=prompt_text, system_instruction=system_instruction
        )
        executed_actions = [c.get("name") for c in call_log]

    if cli_config.get("log_invocations", True):
        log_cli_invocation(CLI_INVOCATIONS_LOG, engine_mode, model_reg.active, prompt_text, executed_actions)

    if do_json:
        out_obj = {
            "engine": engine_mode,
            "model": model_reg.active,
            "response": response_text,
            "usage": usage,
            "executed_actions": executed_actions,
            "exec_results": [r.__dict__ for r in exec_results] if exec_results else []
        }
        print(json.dumps(out_obj, indent=2))
    else:
        print(response_text)
        if exec_results:
            print("\n--- Executed Tool Results ---")
            for r in exec_results:
                print(f"[{r.tag}] {r.command or r.path or ''}\n{r.output}\n")

def main():
    try:
        asyncio.run(run_cliagent())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
