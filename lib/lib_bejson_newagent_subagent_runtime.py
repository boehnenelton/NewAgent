"""
Library:        lib_bejson_newagent_subagent_runtime.py
Family:         NewAgent (subagent family)
Description:    Turns a durable subagent_sessions.py record into an actual
                running turn: builds history + system prompt from the
                session's profile (subagent_profiles.py), calls the real
                REST engine (lib_bejson_newagent_engine_rest.RestPrompter
                -- the exact class agent.py/cliagent.py/webagent.py all
                already use, not a re-implementation), runs any action
                tags through the real action queue
                (lib_bejson_newagent_actions.run_action_queue -- same
                do_exec/do_read_file/etc. every other engine uses), and
                persists the result back through subagent_sessions.py.
                dispatch_subagent() is the "scale-to-zero" entry point:
                create a session and drive it turn-by-turn to completion
                (or until it parks itself waiting on a signal) in one call.

                Inspired by Cognitive_Core's mfdb_agent_coordinator.py +
                lib_bejson_agentic_deploy.py, but with one fundamental
                difference: Cognitive_Core's coordinator was a hardcoded
                if/elif state machine over fixed step names ("START" ->
                "AUDITING" -> "PAUSED" -> "STAGING" -> "COMPLETED") written
                to demonstrate ONE specific onboarding flow -- every new
                task type would need its own hand-written coordinator.
                This runtime is task-agnostic: the "step logic" is
                whatever the LLM does with a profile's system prompt on
                each turn, the same way agent.py's own main loop is task-
                agnostic. What's carried over structurally is the
                durable-session-plus-signal-mailbox shape and the BUSY
                guard (deploy_local_runtime's "if session.get('status') ==
                'BUSY': refuse" pattern, preventing two concurrent
                run_subagent_turn calls on the same session from
                interleaving) and the scale-to-zero idea itself: nothing
                here keeps a process running between turns -- a session
                sits inert on disk until something calls run_subagent_turn
                or dispatch_subagent again.

                PAUSE-AND-WAIT-FOR-SIGNAL CONVENTION: since a sub-agent's
                own action tags (do_exec, do_read_file, etc., defined in
                lib_bejson_newagent_actions.py) have no concept of sub-
                agent sessions or signals, pausing is driven by a small
                text convention scanned out of the model's own response
                text (never inside <exec>/<read_file>/etc., and never
                passed to actions.parse_actions -- see
                _extract_await_signal): a profile's system prompt can
                instruct the model to emit a line like
                    <await_signal type="approval_granted"/>
                to end its turn parked in STATUS_WAITING_SIGNAL for a
                signal of that type, instead of Cognitive_Core's approach
                of hardcoding the pause condition into the coordinator's
                own Python (`if leaks_found: ... status="WAITING"`) for
                one specific task. A caller that wants Cognitive_Core-
                style hardcoded pause conditions instead of relying on the
                model to emit the tag can still do so -- just call
                subagent_sessions.update_session(..., status=
                STATUS_WAITING_SIGNAL, awaiting_signal_types=[...]) 
                directly between calls to run_subagent_turn.
Version:        1.1.0
Date:           2026-09-29
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  3789aa6f-e6a8-42de-93e8-ce397ac1783b

CHANGELOG:
- 1.1.0 (2026-09-29): Remediation pass, audit finding #7. Moved the
  profiles.load_profile() call up to immediately after the early-return
  status checks, before the signal-handling branch -- it previously
  loaded AFTER that branch, so the signal-received append_history() call
  had no char-budget trim available to it at all (profile.get(
  "max_history_chars") didn't exist yet at that point in the function).
  Preserved the original profile-missing error handling (marks the
  session STATUS_ERROR with a result, rather than just returning) when
  moving it. All 4 append_history() call sites in this file now pass
  max_history_chars=history_char_budget (pulled once from the profile,
  falling back to profiles.DEFAULT_MAX_HISTORY_CHARS). See
  subagent_sessions.py 1.1.0 for the trim logic itself. Verified:
  py_compile clean; real end-to-end create_session()/update_session()
  run confirms the budget applies correctly through this call path.
- 1.0.0 (2026-09-12): Initial version.
"""

import asyncio
import re
from pathlib import Path
from typing import Optional

import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_subagent_profiles as profiles
import lib_bejson_newagent_subagent_sessions as sessions
import lib_bejson_newagent_subagent_signals as signals
import lib_bejson_newagent_tui as tui

VERSION = "1.1.0"

_AWAIT_SIGNAL_RE = re.compile(r'<await_signal\s+type="([^"]+)"\s*/?>')


class _ScopedModelRegistry:
    """A throwaway stand-in for rest.ModelRegistry exposing only the
    `.active` attribute RestPrompter.prompt() actually reads. Needed
    because a profile's model_override must NOT go through
    ModelRegistry.set_active() -- that call persists the override to
    models.bejson, which is the process-wide active model every other
    engine (agent.py's interactive session, cliagent.py, webagent.py)
    also reads. Concurrent sub-agent turns using different profiles'
    model_override values would stomp on each other's persisted choice,
    and on the main agent's own choice, if they shared the real registry
    object. This never touches disk and is never shared past one turn."""
    def __init__(self, active_model: str):
        self.active = active_model


def _extract_await_signal(response_text: str) -> Optional[str]:
    """Returns the signal_type from a trailing <await_signal type="..."/>
    marker in the model's response, or None. Only the FIRST match is
    honored -- a sub-agent waits on one signal type at a time per pause;
    a profile wanting to wait on several should have the model emit one
    tag per desired type, since awaiting_signal_types is a list and
    run_subagent_turn's resume check already treats it as "any of these"."""
    match = _AWAIT_SIGNAL_RE.search(response_text)
    return match.group(1) if match else None


def _strip_await_signal(response_text: str) -> str:
    return _AWAIT_SIGNAL_RE.sub("", response_text).strip()


async def run_subagent_turn(
    subagents_dir: Path,
    session_id: str,
    config: dict,
    key_reg: "rest.KeyRegistry",
    model_reg: "rest.ModelRegistry",
    catalog_path: Path,
    *,
    backups_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    jobs_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    timeout: int = 90,
    max_retries: int = 3,
) -> dict:
    """Runs exactly one turn (one model call, plus any actions it
    requests) for session_id and persists the result. Returns a status
    dict: {"status": "active"|"completed"|"error"|"waiting", ...}.

    Refuses immediately with {"status": "disabled", ...} and touches
    nothing on disk if config.get("subagents_enabled") is not True --
    see lib_bejson_newagent_config.py's "subagents_enabled" entry (default
    False). Checked here too, not just in dispatch_subagent, so a session
    created before the gate was flipped off can't be pushed forward by a
    direct run_subagent_turn call that skips dispatch.
    """
    if not config.get("subagents_enabled"):
        return {"status": "disabled", "error": "Sub-agent system is disabled (config.subagents_enabled is not true)."}

    session = sessions.load_session(subagents_dir, session_id)
    if session is None:
        return {"status": "error", "error": f"No such sub-agent session: {session_id}"}

    if session["status"] == sessions.STATUS_BUSY:
        return {"status": "error", "error": "Session is already mid-turn (BUSY)."}

    if session["status"] in (sessions.STATUS_COMPLETED, sessions.STATUS_ERROR):
        return {"status": session["status"].lower(), "session_id": session_id, "result": session.get("result")}

    # FIX (Remediation pkg, audit finding #7 -- token/char budgeting on
    # sub-agent history): moved up from just after the signal-handling
    # branch below so max_history_chars is available for EVERY
    # append_history call in this function, that branch's included --
    # previously the signal-received append had no char-budget trim at
    # all since the profile hadn't been loaded yet at that point.
    profile = profiles.load_profile(subagents_dir, session["profile_name"])
    if profile is None:
        sessions.update_session(
            subagents_dir, session_id, status=sessions.STATUS_ERROR,
            result={"error": f"Profile '{session['profile_name']}' no longer exists."},
        )
        return {"status": "error", "error": "profile missing"}
    history_char_budget = profile.get("max_history_chars") or profiles.DEFAULT_MAX_HISTORY_CHARS

    if session["status"] == sessions.STATUS_WAITING_SIGNAL:
        awaited = session.get("awaiting_signal_types") or []
        hit = None
        for sig_type in awaited:
            matches = signals.poll_signals(subagents_dir, session_id, sig_type)
            if matches:
                hit = matches[0]
                break
        if hit is None:
            return {"status": "waiting", "session_id": session_id, "awaiting_signal_types": awaited}
        signals.consume_signal(subagents_dir, hit["signal_id"])
        session = sessions.update_session(
            subagents_dir, session_id,
            status=sessions.STATUS_ACTIVE,
            awaiting_signal_types=[],
            metadata_delta={"_last_signal_received": {"signal_type": hit["signal_type"], "payload": hit["payload"]}},
            append_history=[{"role": "user", "content": f"[signal received: {hit['signal_type']}] payload={hit['payload']}"}],
            max_history_chars=history_char_budget,
        )

    max_turns = profile.get("max_turns") or profiles.DEFAULT_MAX_TURNS
    if session.get("turn_count", 0) >= max_turns:
        sessions.update_session(
            subagents_dir, session_id, status=sessions.STATUS_COMPLETED,
            result={"note": f"Stopped: hit max_turns ({max_turns}) without a final answer."},
        )
        return {"status": "completed", "session_id": session_id, "hit_max_turns": True}

    sessions.update_session(subagents_dir, session_id, status=sessions.STATUS_BUSY)

    try:
        history = list(session.get("history") or [])
        if not history:
            history = [{"role": "user", "content": session["task_description"]}]

        # Sub-agents run unattended (no TTY to answer an input() prompt),
        # so the confirmation gate -- which run_action_queue would
        # otherwise trigger for "exec"/"delete_file" tags -- is always
        # off here regardless of the caller's own config. A profile that
        # genuinely needs exec/delete_file restricted should say so via
        # allowed_actions, not rely on a gate that would just hang.
        turn_config = dict(config)
        turn_config["confirmation_gate"] = False
        if profile.get("exec_denylist_override"):
            turn_config["exec_denylist"] = profile["exec_denylist_override"]

        model_registry = _ScopedModelRegistry(profile["model_override"] or model_reg.active)
        prompter = rest.RestPrompter(
            key_reg, model_registry, catalog_path, turn_config,
            timeout=timeout, max_retries=max_retries, logs_dir=logs_dir,
        )

        response_text, _usage = await asyncio.get_event_loop().run_in_executor(
            None, lambda: prompter.prompt(history, system_instruction=profile.get("system_prompt") or "")
        )

        await_signal_type = _extract_await_signal(response_text)
        clean_response = _strip_await_signal(response_text)

        new_history = [{"role": "model", "content": clean_response}]
        turn_ctx = {
            "config": turn_config,
            "_cwd": session["cwd"],
            "stats": tui.SessionStats(engine="subagent"),
            "_shell_env": None,
            "_backups_dir": backups_dir,
            "_config_dir": config_dir,
            "_jobs_dir": jobs_dir,
            "_active_job_path": None,
            "_active_job_doc": None,
        }

        parsed_actions = actions.parse_actions(clean_response)
        allowed = [a for a in parsed_actions if profiles.action_allowed(profile, a["tag"])]
        denied_count = len(parsed_actions) - len(allowed)

        exec_results = []
        if allowed:
            exec_results = await actions.run_action_queue(allowed, turn_ctx)
            payload = actions.assemble_results_payload(exec_results)
            if denied_count:
                payload += f"\n[{denied_count} action(s) skipped: not in this sub-agent's allowed_actions]"
            new_history.append({"role": "user", "content": payload})
        elif denied_count:
            new_history.append({
                "role": "user",
                "content": f"[{denied_count} action(s) skipped: not in this sub-agent's allowed_actions]",
            })

        new_cwd = turn_ctx["_cwd"]

        if await_signal_type:
            session = sessions.update_session(
                subagents_dir, session_id,
                status=sessions.STATUS_WAITING_SIGNAL,
                cwd=new_cwd,
                append_history=new_history,
                max_history_chars=history_char_budget,
                awaiting_signal_types=[await_signal_type],
                increment_turn_count=True,
            )
            return {"status": "waiting", "session_id": session_id, "awaiting_signal_types": [await_signal_type]}

        if not parsed_actions:
            # No actions requested this turn -- the model's response is
            # treated as the sub-agent's final answer, same convention
            # webagent.py's api_chat uses for "hit_iteration_cap ==
            # false and no actionable tags" to mean the turn loop is
            # naturally finished.
            session = sessions.update_session(
                subagents_dir, session_id,
                status=sessions.STATUS_COMPLETED,
                cwd=new_cwd,
                append_history=new_history,
                max_history_chars=history_char_budget,
                increment_turn_count=True,
                result={"output": clean_response},
            )
            return {"status": "completed", "session_id": session_id, "result": {"output": clean_response}}

        session = sessions.update_session(
            subagents_dir, session_id,
            status=sessions.STATUS_ACTIVE,
            cwd=new_cwd,
            append_history=new_history,
            max_history_chars=history_char_budget,
            increment_turn_count=True,
        )
        return {"status": "active", "session_id": session_id, "turn_count": session["turn_count"]}

    except Exception as exc:  # noqa: BLE001 -- a sub-agent turn failing must
        # never leave the session stuck in BUSY forever (the exact
        # "hung coordinator" failure mode lib_bejson_agentic_deploy.py's
        # own FIX comment for subprocess.TimeoutExpired called out) --
        # always land in a terminal, re-runnable-from-scratch state.
        sessions.update_session(
            subagents_dir, session_id, status=sessions.STATUS_ERROR,
            result={"error": str(exc)},
        )
        return {"status": "error", "session_id": session_id, "error": str(exc)}


async def dispatch_subagent(
    subagents_dir: Path,
    profile_name: str,
    task_description: str,
    cwd: str,
    config: dict,
    key_reg: "rest.KeyRegistry",
    model_reg: "rest.ModelRegistry",
    catalog_path: Path,
    *,
    parent_session_id: str = "",
    metadata: Optional[dict] = None,
    backups_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    jobs_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    timeout: int = 90,
    max_retries: int = 3,
) -> dict:
    """Creates a session for profile_name and drives it turn-by-turn
    (run_subagent_turn, in a loop) until it reaches STATUS_COMPLETED,
    STATUS_ERROR, or STATUS_WAITING_SIGNAL -- the "scale to zero"
    dispatch entry point: one call either finishes the task, fails it, or
    parks it waiting on a signal, and returns either way instead of
    leaving a process running. A caller that later wants to push a parked
    session forward again calls run_subagent_turn (or dispatch_subagent's
    sibling resume_subagent, identical but named for clarity) on the same
    session_id once it's sent the awaited signal.
    """
    if not config.get("subagents_enabled"):
        return {"status": "disabled", "error": "Sub-agent system is disabled (config.subagents_enabled is not true)."}

    profile = profiles.load_profile(subagents_dir, profile_name)
    if profile is None:
        return {"status": "error", "error": f"Unknown sub-agent profile '{profile_name}'"}

    session_id = sessions.create_session(
        subagents_dir, profile_name, task_description, cwd,
        parent_session_id=parent_session_id, metadata=metadata,
    )

    return await resume_subagent(
        subagents_dir, session_id, config, key_reg, model_reg, catalog_path,
        backups_dir=backups_dir, config_dir=config_dir, jobs_dir=jobs_dir,
        logs_dir=logs_dir, timeout=timeout, max_retries=max_retries,
    )


async def resume_subagent(
    subagents_dir: Path,
    session_id: str,
    config: dict,
    key_reg: "rest.KeyRegistry",
    model_reg: "rest.ModelRegistry",
    catalog_path: Path,
    *,
    backups_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    jobs_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    timeout: int = 90,
    max_retries: int = 3,
) -> dict:
    """Drives an existing session forward turn-by-turn until it reaches a
    terminal or parked state. This is dispatch_subagent's own loop body,
    exposed separately so a caller resuming a WAITING_SIGNAL session after
    sending its signal doesn't need to re-create a session to keep
    driving it -- same run_subagent_turn underneath either way.
    """
    result = {"status": "active", "session_id": session_id}
    while result.get("status") == "active":
        result = await run_subagent_turn(
            subagents_dir, session_id, config, key_reg, model_reg, catalog_path,
            backups_dir=backups_dir, config_dir=config_dir, jobs_dir=jobs_dir,
            logs_dir=logs_dir, timeout=timeout, max_retries=max_retries,
        )
    return result
