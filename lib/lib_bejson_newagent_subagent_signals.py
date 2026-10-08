"""
Library:        lib_bejson_newagent_subagent_signals.py
Family:         NewAgent (subagent family)
Description:    Cross-agent signal mailbox -- one BEJSON 104 table
                (subagents/signals.bejson) of {signal_id, session_id_fk,
                signal_type, payload, consumed, dispatched_at} records.
                Lets the main agent (or one sub-agent) wake a session
                parked in STATUS_WAITING_SIGNAL by sending it a named
                signal with an arbitrary JSON-able payload; subagent_
                runtime.py's resume path polls and consumes these.

                Inspired by Cognitive_Core's lib_bejson_agentic_core.py
                bejson_agentic_signal_send/_poll/_consume -- same shape
                (send/poll/consume, unconsumed-only polling, a filterable
                signal_type), same race-safety upgrade as sessions.py:
                every write here goes through subagent_common.
                with_file_lock() instead of an uncoordinated load->mutate->
                atomic_write, and every row is built through dict_to_row()
                against the doc's live Fields order rather than a
                positional list literal.
Version:        1.0.0
Date:           2026-09-12
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  c6d7e8f9-a0b1-4243-d5e6-f7a8b9c0d1e2

CHANGELOG:
- 1.0.0 (2026-09-12): Initial version.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import bejson_core_create_104
from lib_bejson_newagent_subagent_common import (
    signals_path,
    row_to_dict,
    dict_to_row,
    with_file_lock,
)

VERSION = "1.0.0"

_SIGNAL_FIELDS = [
    {"name": "signal_id", "type": "string"},
    {"name": "session_id_fk", "type": "string"},
    {"name": "signal_type", "type": "string"},
    {"name": "payload", "type": "object"},
    {"name": "consumed", "type": "boolean"},
    {"name": "dispatched_at", "type": "string"},
]


def _empty_doc() -> dict:
    return bejson_core_create_104("SubagentSignal", list(_SIGNAL_FIELDS), [])


def send_signal(subagents_dir: Path, session_id: str, signal_type: str, payload: Optional[dict] = None) -> str:
    """Deposits a signal into session_id's mailbox and returns the new
    signal_id. Does NOT itself wake the session -- subagent_runtime.py's
    caller is expected to follow this with resume_if_signaled(session_id)
    (or its own equivalent poll) if it wants the wake to happen
    immediately rather than on the next natural check."""
    path = signals_path(subagents_dir)
    signal_id = str(uuid.uuid4())

    def mutate(doc):
        record = {
            "signal_id": signal_id,
            "session_id_fk": session_id,
            "signal_type": signal_type,
            "payload": payload or {},
            "consumed": False,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }
        doc["Values"].append(dict_to_row(doc, record))
        return True, signal_id

    with_file_lock(path, mutate, _empty_doc)
    return signal_id


def poll_signals(subagents_dir: Path, session_id: str, signal_type: Optional[str] = None) -> list[dict]:
    """Returns unconsumed signals for session_id, optionally filtered to
    one signal_type. Does not mark them consumed -- call consume_signal()
    per signal_id once the caller has actually acted on it, same
    poll-then-consume-explicitly contract as Cognitive_Core's version."""
    path = signals_path(subagents_dir)

    def mutate(doc):
        out = []
        for row in doc["Values"]:
            record = row_to_dict(doc, row)
            if record.get("session_id_fk") != session_id or record.get("consumed"):
                continue
            if signal_type is not None and record.get("signal_type") != signal_type:
                continue
            out.append(record)
        return False, out

    return with_file_lock(path, mutate, _empty_doc)


def consume_signal(subagents_dir: Path, signal_id: str) -> bool:
    path = signals_path(subagents_dir)

    def mutate(doc):
        for idx, row in enumerate(doc["Values"]):
            record = row_to_dict(doc, row)
            if record.get("signal_id") != signal_id:
                continue
            record["consumed"] = True
            doc["Values"][idx] = dict_to_row(doc, record)
            return True, True
        return False, False

    return with_file_lock(path, mutate, _empty_doc)
