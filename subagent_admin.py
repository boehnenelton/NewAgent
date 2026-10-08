#!/data/data/com.termux/files/usr/bin/python3
"""
Name:         subagent_admin.py
Family:       NewAgent (subagent family)
Description:  Standalone CLI for the sub-agent system: create/list/show/
              delete profiles, list/show sessions, send signals, and
              actually dispatch or resume a sub-agent (reusing the exact
              same key/model registry bootstrap cliagent.py uses, so a
              dispatch here runs against real credentials the same way a
              cliagent.py call would). This is the convenience glue the
              subagent library family (lib_bejson_newagent_subagent_*.py)
              itself deliberately doesn't provide -- those are libraries,
              not entry points, the same relationship cliagent.py has to
              lib_bejson_newagent_engine_rest.py.

              Every dispatch/resume command checks config.json's
              "subagents_enabled" gate itself before bootstrapping
              anything, rather than relying solely on the library's own
              gate check, so a person running this CLI with the feature
              off gets a clear, immediate message instead of a bootstrap
              that then fails deep inside dispatch_subagent().
Version:      1.1.0
Date:         2026-09-29
Author:       Elton Boehnen — eltonboehnen@gmail.com
Contact:      eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 15c5298d-76b3-4c9a-b918-7862a1b07166

CHANGELOG:
- 1.1.0 (2026-09-29): Remediation pass, audit finding #7. Added
  --max-history-chars flag to `profile create`, matching --max-turns'
  existing pattern, wired through to profiles.make_profile_doc(). Default
  is profiles.DEFAULT_MAX_HISTORY_CHARS.
- 1.0.0 (2026-09-12): Initial version.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_PATH / "lib"))

import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_subagent_common as common
import lib_bejson_newagent_subagent_profiles as profiles
import lib_bejson_newagent_subagent_sessions as sessions
import lib_bejson_newagent_subagent_signals as signals
import lib_bejson_newagent_subagent_runtime as runtime

VERSION = "1.1.0"

CONFIG_DIR = SCRIPT_PATH / "config"
LOGS_DIR = SCRIPT_PATH / "logs"
BACKUPS_DIR = SCRIPT_PATH / "backups"
JOBS_DIR = SCRIPT_PATH / "jobs"
SUBAGENTS_DIR = SCRIPT_PATH / "subagents"

CONFIG_PATH = CONFIG_DIR / "config.json"
KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"


def _bootstrap_engine(config: dict):
    """Same bootstrap sequence cliagent.py's main() uses for its own
    key/model registries -- duplicated here rather than imported from
    cliagent.py since cliagent.py doesn't expose it as a function (it's
    inline in main()), and reaching into another entry point's main() to
    steal a few lines would be worse than four lines of duplication."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    rest.build_default_keys_bejson(KEYS_PATH)
    rest.build_default_models_bejson(MODELS_PATH)
    rest.build_default_model_catalog(MODEL_CATALOG_PATH)
    rest.backfill_model_catalog_api_profile(MODEL_CATALOG_PATH)
    rest.backfill_model_catalog_provider(MODEL_CATALOG_PATH)
    rest.sync_keys_from_env_sources(KEYS_PATH, config)
    key_reg = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
    model_reg = rest.ModelRegistry(MODELS_PATH)
    return key_reg, model_reg


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_create_profile(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    allowed = args.allowed_actions.split(",") if args.allowed_actions else ["*"]
    denylist = args.exec_denylist_override.split(",") if args.exec_denylist_override else []
    doc = profiles.make_profile_doc(
        args.name,
        role_description=args.role or "",
        system_prompt=args.system_prompt or "",
        model_override=args.model or "",
        allowed_actions=allowed,
        exec_denylist_override=denylist,
        max_turns=args.max_turns,
        max_history_chars=args.max_history_chars,
    )
    if not profiles.save_profile(SUBAGENTS_DIR, args.name, doc):
        print(f"[ERROR] Failed to write profile '{args.name}'")
        return 1
    print(f"Profile '{args.name}' saved.")
    return 0


def cmd_list_profiles(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    _print_json(profiles.list_profiles(SUBAGENTS_DIR))
    return 0


def cmd_show_profile(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    profile = profiles.load_profile(SUBAGENTS_DIR, args.name)
    if profile is None:
        print(f"[ERROR] No such profile: {args.name}")
        return 1
    _print_json(profile)
    return 0


def cmd_delete_profile(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    if profiles.delete_profile(SUBAGENTS_DIR, args.name):
        print(f"Profile '{args.name}' deleted.")
        return 0
    print(f"[ERROR] No such profile: {args.name}")
    return 1


def cmd_list_sessions(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    _print_json(sessions.list_sessions(SUBAGENTS_DIR, status=args.status, parent_session_id=args.parent))
    return 0


def cmd_show_session(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    session = sessions.load_session(SUBAGENTS_DIR, args.id)
    if session is None:
        print(f"[ERROR] No such session: {args.id}")
        return 1
    _print_json(session)
    return 0


def cmd_send_signal(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    payload = json.loads(args.payload) if args.payload else {}
    signal_id = signals.send_signal(SUBAGENTS_DIR, args.session, args.type, payload)
    print(f"Signal '{args.type}' sent to session {args.session} (signal_id={signal_id}).")
    print("Note: this only deposits the signal -- run 'resume' on the session to actually act on it.")
    return 0


def _require_subagents_enabled(config: dict) -> bool:
    if config.get("subagents_enabled"):
        return True
    print(
        "[DISABLED] Sub-agent system is off. Set \"subagents_enabled\": true in "
        f"{CONFIG_PATH} to use dispatch/resume."
    )
    return False


def cmd_dispatch(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    config = config_lib.init_config(CONFIG_PATH)
    if not _require_subagents_enabled(config):
        return 1
    key_reg, model_reg = _bootstrap_engine(config)
    cwd = args.cwd or str(SCRIPT_PATH)
    metadata = json.loads(args.metadata) if args.metadata else None
    result = asyncio.run(runtime.dispatch_subagent(
        SUBAGENTS_DIR, args.profile, args.task, cwd, config,
        key_reg, model_reg, MODEL_CATALOG_PATH,
        parent_session_id=args.parent or "", metadata=metadata,
        backups_dir=BACKUPS_DIR, config_dir=CONFIG_DIR, jobs_dir=JOBS_DIR, logs_dir=LOGS_DIR,
    ))
    _print_json(result)
    return 0 if result.get("status") in ("completed", "waiting", "active") else 1


def cmd_resume(args) -> int:
    common.ensure_subagent_dirs(SUBAGENTS_DIR)
    config = config_lib.init_config(CONFIG_PATH)
    if not _require_subagents_enabled(config):
        return 1
    key_reg, model_reg = _bootstrap_engine(config)
    result = asyncio.run(runtime.resume_subagent(
        SUBAGENTS_DIR, args.id, config, key_reg, model_reg, MODEL_CATALOG_PATH,
        backups_dir=BACKUPS_DIR, config_dir=CONFIG_DIR, jobs_dir=JOBS_DIR, logs_dir=LOGS_DIR,
    ))
    _print_json(result)
    return 0 if result.get("status") in ("completed", "waiting", "active") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="NewAgent sub-agent admin CLI")
    p.add_argument("--version", action="version", version=f"subagent_admin.py {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("create-profile", help="Create or overwrite a sub-agent profile")
    sp.add_argument("--name", required=True)
    sp.add_argument("--role", default="")
    sp.add_argument("--system-prompt", default="")
    sp.add_argument("--model", default="", help="Model override for this profile (blank = caller's active model)")
    sp.add_argument("--allowed-actions", default="", help="Comma-separated action tags, or omit for all (*)")
    sp.add_argument("--exec-denylist-override", default="", help="Comma-separated denylist strings")
    sp.add_argument("--max-turns", type=int, default=profiles.DEFAULT_MAX_TURNS)
    sp.add_argument("--max-history-chars", type=int, default=profiles.DEFAULT_MAX_HISTORY_CHARS,
                     help="Char budget for this profile's session history (Remediation pkg, audit #7)")
    sp.set_defaults(func=cmd_create_profile)

    sp = sub.add_parser("list-profiles")
    sp.set_defaults(func=cmd_list_profiles)

    sp = sub.add_parser("show-profile")
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_show_profile)

    sp = sub.add_parser("delete-profile")
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_delete_profile)

    sp = sub.add_parser("list-sessions")
    sp.add_argument("--status", default=None)
    sp.add_argument("--parent", default=None)
    sp.set_defaults(func=cmd_list_sessions)

    sp = sub.add_parser("show-session")
    sp.add_argument("--id", required=True)
    sp.set_defaults(func=cmd_show_session)

    sp = sub.add_parser("send-signal")
    sp.add_argument("--session", required=True)
    sp.add_argument("--type", required=True)
    sp.add_argument("--payload", default="", help="JSON object string")
    sp.set_defaults(func=cmd_send_signal)

    sp = sub.add_parser("dispatch", help="Create and run a new sub-agent session to completion/wait/cap")
    sp.add_argument("--profile", required=True)
    sp.add_argument("--task", required=True)
    sp.add_argument("--cwd", default="")
    sp.add_argument("--parent", default="")
    sp.add_argument("--metadata", default="", help="JSON object string")
    sp.set_defaults(func=cmd_dispatch)

    sp = sub.add_parser("resume", help="Push an existing session forward (e.g. after send-signal)")
    sp.add_argument("--id", required=True)
    sp.set_defaults(func=cmd_resume)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
