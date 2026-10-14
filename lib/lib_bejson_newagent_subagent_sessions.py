"""
Library:        lib_bejson_newagent_subagent_sessions.py
Family:         NewAgent (subagent family)
Description:    Durable sub-agent session state -- one BEJSON 104 table
                (subagents/sessions.bejson) holding every sub-agent
                session ever dispatched: which profile it's running as,
                its status/step, its own cwd, a trimmed turn history, any
                signal types it's currently blocked waiting on, and free-
                form metadata. This is the record lib_bejson_newagent_
                subagent_runtime.py's dispatch/resume functions read and
                write on every turn.

                Inspired by Cognitive_Core's lib_bejson_agentic_core.py
                bejson_agentic_session_create/_load/_update. Genuinely
                different in two ways, both learned the hard way while
                fixing lib_bejson_newagent_config.py 1.14.0's boot race:

                1. Every write here goes through subagent_common.
                   with_file_lock() instead of Cognitive_Core's plain
                   bejson_core_load_file -> mutate -> bejson_core_atomic_
                   write. That pattern is fine for a single-process demo
                   but loses updates under real concurrency -- and
                   concurrent sub-agent sessions writing the SAME shared
                   sessions.bejson (one dispatching a child, one polling
                   its own status, one being resumed by a signal) is
                   exactly the scenario, not a hypothetical one.

                2. Cognitive_Core's session_create() builds its row as a
                   positional list literal (`[session_id, agent_name,
                   initial_step, "ACTIVE", metadata or {}, [], now]`) --
                   correct only as long as nobody ever reorders Fields.
                   Every row here is built through subagent_common.
                   dict_to_row() against the doc's actual current Fields
                   order, per Elton's Field-Map-Cache-is-mandatory /
                   positional-lookups-are-prohibited rule (policy §6.2).

                "current_step" is kept as an open string (not an enum) the
                same way Cognitive_Core used it, since sub-agent tasks are
                arbitrary and the runtime doesn't dictate a fixed state
                machine -- only "status" is a closed set the runtime
                itself depends on (see STATUS_* constants).
Version:        1.2.0
Date:           2026-09-29
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  cd3ba553-b938-40ab-8cbb-aea860e9708d

CHANGELOG:
- 1.2.0 (2026-10-13): Added cleanup_old_sessions() -- 3-day auto-prune of
  COMPLETED/ERROR sessions, their signals, consumed signals and loose
  subagents/logs files.
- 1.1.0 (2026-09-29): Remediation pass, audit finding #7. update_session()
  gained a second trim pass, max_history_chars, run after the existing
  max_history_turns trim: max_history_turns only ever bounded entry COUNT
  (and per the audit, nothing in the codebase even passed it, so in
  practice history was unbounded either way), but a single large
  tool-output entry could still blow the model's context window well
  before any turn-count cap was reached. Trims oldest-first by cumulative
  json.dumps() size until under budget, but always keeps at least the
  single most recent entry even if it alone exceeds the budget -- losing
  the thing that just happened is worse than briefly running over by one
  entry. Added `import json` for the size measurement. Verified: 3
  standalone scenarios (oversized single entry survives alone,
  many-small-entries trims from the front to fit, under-budget is a
  no-op) plus a real end-to-end run through create_session()/
  update_session() against an actual file on disk -- all pass; py_compile
  clean.
- 1.0.0 (2026-09-12): Initial version.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import bejson_core_create_104
from lib_bejson_newagent_subagent_common import (
    sessions_path,
    row_to_dict,
    dict_to_row,
    with_file_lock,
)

VERSION = "1.2.0"

# Closed set the runtime itself branches on (subagent_runtime.py). Anything
# else (current_step) is the caller's own free-form label for where a task
# is, same role as Cognitive_Core's step strings ("START"/"AUDITING"/...).
STATUS_ACTIVE = "ACTIVE"                # runnable, not currently mid-turn
STATUS_BUSY = "BUSY"                    # a turn is in flight right now
STATUS_WAITING_SIGNAL = "WAITING_SIGNAL"  # parked until a named signal arrives
STATUS_COMPLETED = "COMPLETED"
STATUS_ERROR = "ERROR"

_SESSION_FIELDS = [
    {"name": "session_id", "type": "string"},
    {"name": "profile_name", "type": "string"},
    {"name": "parent_session_id", "type": "string"},   # "" if top-level (dispatched directly, not by another sub-agent)
    {"name": "task_description", "type": "string"},
    {"name": "status", "type": "string"},
    {"name": "current_step", "type": "string"},
    {"name": "cwd", "type": "string"},
    {"name": "history", "type": "array"},              # [{"role": "user"|"model", "content": str}, ...], trimmed
    {"name": "awaiting_signal_types", "type": "array"},  # signal_type strings this session is parked on; [] if none
    {"name": "metadata", "type": "object"},
    {"name": "turn_count", "type": "integer"},
    {"name": "result", "type": "object"},              # {} until COMPLETED/ERROR, then the final output
    {"name": "created_at", "type": "string"},
    {"name": "last_updated", "type": "string"},
]


def _empty_doc() -> dict:
    return bejson_core_create_104("SubagentSession", list(_SESSION_FIELDS), [])


def create_session(
    subagents_dir: Path,
    profile_name: str,
    task_description: str,
    cwd: str,
    parent_session_id: str = "",
    metadata: Optional[dict] = None,
) -> str:
    """Creates a new durable session and returns its session_id. Starts in
    STATUS_ACTIVE, current_step="START" -- subagent_runtime.dispatch_
    subagent() is the usual caller, immediately followed by run_subagent_
    turn() on the returned id."""
    path = sessions_path(subagents_dir)
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    def mutate(doc):
        record = {
            "session_id": session_id,
            "profile_name": profile_name,
            "parent_session_id": parent_session_id,
            "task_description": task_description,
            "status": STATUS_ACTIVE,
            "current_step": "START",
            "cwd": cwd,
            "history": [],
            "awaiting_signal_types": [],
            "metadata": metadata or {},
            "turn_count": 0,
            "result": {},
            "created_at": now,
            "last_updated": now,
        }
        doc["Values"].append(dict_to_row(doc, record))
        return True, session_id

    with_file_lock(path, mutate, _empty_doc)
    return session_id


def load_session(subagents_dir: Path, session_id: str) -> Optional[dict]:
    path = sessions_path(subagents_dir)

    def mutate(doc):
        for row in doc["Values"]:
            record = row_to_dict(doc, row)
            if record.get("session_id") == session_id:
                return False, record
        return False, None

    return with_file_lock(path, mutate, _empty_doc)


def list_sessions(subagents_dir: Path, status: Optional[str] = None, parent_session_id: Optional[str] = None) -> list[dict]:
    """Lists sessions, optionally filtered by status and/or parent_session_id
    (e.g. "every child a given session has dispatched")."""
    path = sessions_path(subagents_dir)

    def mutate(doc):
        out = []
        for row in doc["Values"]:
            record = row_to_dict(doc, row)
            if status is not None and record.get("status") != status:
                continue
            if parent_session_id is not None and record.get("parent_session_id") != parent_session_id:
                continue
            out.append(record)
        return False, out

    return with_file_lock(path, mutate, _empty_doc)


def update_session(
    subagents_dir: Path,
    session_id: str,
    *,
    status: Optional[str] = None,
    current_step: Optional[str] = None,
    cwd: Optional[str] = None,
    append_history: Optional[list] = None,
    max_history_turns: Optional[int] = None,
    max_history_chars: Optional[int] = None,
    awaiting_signal_types: Optional[list] = None,
    metadata_delta: Optional[dict] = None,
    increment_turn_count: bool = False,
    result: Optional[dict] = None,
) -> Optional[dict]:
    """Applies a partial update to one session record and returns the
    updated record, or None if session_id doesn't exist. Only the fields
    passed are touched -- omit an argument (leave it None/False) to leave
    that field alone, same convention as config_lib.update-style helpers
    and Cognitive_Core's own session_update signature.

    append_history extends the history array (not replaces it); if
    max_history_turns is also given, the array is trimmed to that many
    most-recent entries afterward -- mirrors context_bubble.trim_history's
    role for the main agent's own conversation history, applied here per-
    session instead of globally.

    max_history_chars (Remediation pkg, audit finding #7) is a second,
    independent trim pass by total serialized size, applied after the
    turn-count trim: max_history_turns bounds entry COUNT, but a single
    large tool-output entry (e.g. a big file read) could still blow the
    model's context window well before the turn count limit is reached --
    exactly the gap the audit named. Trims from the front (oldest first,
    same direction as the turn-count trim) until the remaining entries'
    combined size fits the budget, but always keeps at least the single
    most recent entry even if it alone exceeds the budget -- losing the
    thing that just happened is worse than briefly going over budget by
    one entry, and the next turn's trim will catch up once older entries
    exist to drop instead.
    """
    path = sessions_path(subagents_dir)

    def mutate(doc):
        for idx, row in enumerate(doc["Values"]):
            record = row_to_dict(doc, row)
            if record.get("session_id") != session_id:
                continue

            if status is not None:
                record["status"] = status
            if current_step is not None:
                record["current_step"] = current_step
            if cwd is not None:
                record["cwd"] = cwd
            if append_history:
                history = list(record.get("history") or [])
                history.extend(append_history)
                if max_history_turns is not None and len(history) > max_history_turns:
                    history = history[-max_history_turns:]
                if max_history_chars is not None and history:
                    sizes = [len(json.dumps(entry, default=str)) for entry in history]
                    total = sum(sizes)
                    start = 0
                    while start < len(history) - 1 and total > max_history_chars:
                        total -= sizes[start]
                        start += 1
                    history = history[start:]
                record["history"] = history
            if awaiting_signal_types is not None:
                record["awaiting_signal_types"] = list(awaiting_signal_types)
            if metadata_delta:
                merged = dict(record.get("metadata") or {})
                merged.update(metadata_delta)
                record["metadata"] = merged
            if increment_turn_count:
                record["turn_count"] = int(record.get("turn_count") or 0) + 1
            if result is not None:
                record["result"] = result
            record["last_updated"] = datetime.now(timezone.utc).isoformat()

            doc["Values"][idx] = dict_to_row(doc, record)
            return True, record

        return False, None

    return with_file_lock(path, mutate, _empty_doc)


def cleanup_old_sessions(subagents_dir: Path, max_age_days: float = 3) -> dict:
    """Auto-prune (Elton, 2026-10-13: "three days old gone"). Removes every
    COMPLETED/ERROR session whose last_updated (falling back to created_at)
    is older than max_age_days, every signal belonging to a removed session,
    any consumed signal older than the cutoff, and loose files under
    subagents/logs/ older than the cutoff. ACTIVE/BUSY/WAITING_SIGNAL
    sessions are never removed. Returns counts. Never raises."""
    import time
    from lib_bejson_newagent_subagent_common import signals_path
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    stats = {"sessions": 0, "signals": 0, "files": 0}

    def _ts(value) -> Optional[float]:
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (TypeError, ValueError):
            return None

    removed_ids: set = set()

    def prune_sessions(doc):
        keep = []
        for row in doc["Values"]:
            rec = row_to_dict(doc, row)
            ts = _ts(rec.get("last_updated")) or _ts(rec.get("created_at"))
            if rec.get("status") in (STATUS_COMPLETED, STATUS_ERROR) and ts is not None and ts < cutoff:
                removed_ids.add(rec.get("session_id"))
            else:
                keep.append(row)
        changed = len(keep) != len(doc["Values"])
        doc["Values"] = keep
        return changed, None

    try:
        if sessions_path(subagents_dir).exists():
            with_file_lock(sessions_path(subagents_dir), prune_sessions, _empty_doc)
        stats["sessions"] = len(removed_ids)

        def prune_signals(doc):
            keep = []
            for row in doc["Values"]:
                rec = row_to_dict(doc, row)
                ts = _ts(rec.get("dispatched_at"))
                orphan = rec.get("session_id_fk") in removed_ids
                stale_consumed = bool(rec.get("consumed")) and ts is not None and ts < cutoff
                if not (orphan or stale_consumed):
                    keep.append(row)
            changed = len(keep) != len(doc["Values"])
            stats["signals"] = len(doc["Values"]) - len(keep)
            doc["Values"] = keep
            return changed, None

        if signals_path(subagents_dir).exists():
            from lib_bejson_newagent_subagent_signals import _empty_doc as _empty_signals
            with_file_lock(signals_path(subagents_dir), prune_signals, _empty_signals)

        logs = Path(subagents_dir) / "logs"
        if logs.is_dir():
            for f in logs.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    stats["files"] += 1
    except Exception as exc:  # pruning must never block startup
        import logging
        logging.getLogger(__name__).error("[Subagents] cleanup_old_sessions failed: %s", exc)
    return stats


def delete_session(subagents_dir: Path, session_id: str) -> bool:
    """Removes a session record outright. Sessions aren't auto-pruned by
    this library (unlike jobs.py's stale-completion sweep) -- a caller
    that wants that policy applies it explicitly, e.g. a periodic cleanup
    that lists COMPLETED sessions older than N days and deletes them."""
    path = sessions_path(subagents_dir)

    def mutate(doc):
        for i, row in enumerate(doc["Values"]):
            record = row_to_dict(doc, row)
            if record.get("session_id") == session_id:
                del doc["Values"][i]
                return True, True
        return False, False

    return with_file_lock(path, mutate, _empty_doc)
