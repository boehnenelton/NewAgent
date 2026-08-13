"""
Library:        lib_bejson_newagent_session.py
Family:         NewAgent
Description:    Atomic session logger, resume file persistence, named session archiving.
Version:        2.4.0
Date:           2026-07-25
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  cbbe0ec2-4c3d-4bac-aeca-00d3c89e171c
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson

VERSION = "2.5.0"

_SESSION_INDEX_FIELDS = [
    {"name": "label", "type": "string"},
    {"name": "log_path", "type": "string"},
    {"name": "saved_at", "type": "string"},
]

_TRANSCRIPT_FIELDS = [
    {"name": "timestamp", "type": "string"},
    {"name": "role", "type": "string"},
    {"name": "content", "type": "string"},
    {"name": "bubble_content", "type": "string"},
    {"name": "policy_tokens", "type": "integer"},
    {"name": "active_tasks_tokens", "type": "integer"},
    {"name": "env_file_tokens", "type": "integer"},
    {"name": "cwd_tokens", "type": "integer"},
    {"name": "keyword_tokens", "type": "integer"},
    {"name": "knowledge_tokens", "type": "integer"},
    {"name": "observer_note", "type": "string"},
]

# ── BEJSON 104db Relational Schemas ──────────────────────────────────────────

_104DB_RECORDS_TYPES = ["Session", "Turn", "Action"]

_104DB_FIELDS = [
    {"name": "Record_Type_Parent", "type": "string"},
    # Entity: Session
    {"name": "session_guid", "type": "string", "Record_Type_Parent": "Session"},
    {"name": "created_at", "type": "string", "Record_Type_Parent": "Session"},
    {"name": "model_used", "type": "string", "Record_Type_Parent": "Session"},
    {"name": "total_input_tokens", "type": "integer", "Record_Type_Parent": "Session"},
    {"name": "total_output_tokens", "type": "integer", "Record_Type_Parent": "Session"},
    {"name": "total_turns", "type": "integer", "Record_Type_Parent": "Session"},
    # Entity: Turn
    {"name": "turn_id", "type": "string", "Record_Type_Parent": "Turn"},
    {"name": "session_fk", "type": "string", "Record_Type_Parent": "Turn"},
    {"name": "turn_index", "type": "integer", "Record_Type_Parent": "Turn"},
    {"name": "prompt_text", "type": "string", "Record_Type_Parent": "Turn"},
    {"name": "response_text", "type": "string", "Record_Type_Parent": "Turn"},
    {"name": "input_tokens", "type": "integer", "Record_Type_Parent": "Turn"},
    {"name": "output_tokens", "type": "integer", "Record_Type_Parent": "Turn"},
    {"name": "duration_ms", "type": "number", "Record_Type_Parent": "Turn"},
    {"name": "timestamp_turn", "type": "string", "Record_Type_Parent": "Turn"},
    # Entity: Action
    {"name": "action_id", "type": "string", "Record_Type_Parent": "Action"},
    {"name": "turn_fk", "type": "string", "Record_Type_Parent": "Action"},
    {"name": "action_type", "type": "string", "Record_Type_Parent": "Action"},
    {"name": "action_source", "type": "string", "Record_Type_Parent": "Action"},
    {"name": "exit_code", "type": "integer", "Record_Type_Parent": "Action"},
    {"name": "output_bytes", "type": "integer", "Record_Type_Parent": "Action"},
    {"name": "timestamp_action", "type": "string", "Record_Type_Parent": "Action"},
]

class SessionLogger:
    """
    Crash-safe session transcript, one BEJSON row per logged message.

    Context Bubble data (bubble_content, per-category token counts,
    observer_note) lives as columns on the SAME row as the prompt it went
    out with — not a separate context_logs.bejson file — so a single record
    ties a message directly to the context that accompanied it. Only rows
    for outgoing prompts carry bubble data; model response rows leave those
    columns empty since no bubble is sent with a response.

    Trade-off, stated plainly: every log() call now does a full read +
    atomic rewrite of the transcript so far, not an O(1) append like the old
    plain-text format. Fine for normal session lengths; a session running
    into the many thousands of turns will feel this. Unlike
    context_logs.bejson, this table is NOT row-capped — it's the session's
    actual record, not disposable telemetry, so nothing gets silently
    dropped from it.
    """

    def __init__(self, logs_dir: Path) -> None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = logs_dir / f"session_{ts}.bejson"
        self.db_path = logs_dir / f"session_{ts}.104db.bejson"
        self.human_log_path = logs_dir / f"session_{ts}.md"
        self._lock = threading.Lock()
        
        # 1. Init 104a transcript
        doc = bejson_core_create_104a("Transcript", list(_TRANSCRIPT_FIELDS), [])
        bejson_core_atomic_write(str(self.log_path), doc)
        self._regenerate_human_log([])

        # 2. Init 104db relational store
        import uuid
        self.session_guid = f"sess_{uuid.uuid4().hex[:12]}"
        self._turn_counter = 0
        self._current_session_row = [
            "Session",
            self.session_guid,
            datetime.now().isoformat(),
            "", # model_used (updated on first turn)
            0,  # total_input_tokens
            0,  # total_output_tokens
            0,  # total_turns
            None, None, None, None, None, None, None, None, None, # Turn null padding
            None, None, None, None, None, None, None,             # Action null padding
        ]
        db_doc = {
            "Format": "BEJSON",
            "Format_Version": "104db",
            "Format_Creator": "Elton Boehnen",
            "Records_Type": list(_104DB_RECORDS_TYPES),
            "Fields": list(_104DB_FIELDS),
            "Values": [self._current_session_row],
        }
        bejson_core_atomic_write(str(self.db_path), db_doc)

    def _regenerate_human_log(self, rows: list[list]) -> None:
        """
        The BEJSON table is the queryable source of truth; this is a plain,
        skimmable rendering of it, fully rebuilt from those same rows every
        time — never hand-maintained separately, so it can't drift out of
        sync with the data it's derived from.
        """
        lines = [f"# NewAgent Session — {self.log_path.stem}\n"]
        for row in rows:
            if len(row) < 11:
                continue
            ts, role, content, bubble_content, policy_tok, active_tasks_tok, env_tok, cwd_tok, keyword_tok, knowledge_tok, note = row[:11]
            lines.append(f"### [{ts}] [{(role or '').upper()}]")
            lines.append(content or "")
            if bubble_content:
                lines.append("")
                lines.append(
                    f"<details><summary>Context Bubble — "
                    f"policy:{policy_tok} tasks:{active_tasks_tok} env:{env_tok} cwd:{cwd_tok} keyword:{keyword_tok} knowledge:{knowledge_tok}"
                    f"{f' — {note}' if note else ''}</summary>\n"
                )
                lines.append("```")
                lines.append(bubble_content)
                lines.append("```")
                lines.append("</details>")
            lines.append("\n---\n")
        try:
            self.human_log_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "[Session] Failed to write human-readable log %s: %s", self.human_log_path, exc
            )

    def log(
        self,
        role: str,
        content: str,
        ts: Optional[str] = None,
        bubble_content: str = "",
        policy_tokens: int = 0,
        active_tasks_tokens: int = 0,
        env_file_tokens: int = 0,
        cwd_tokens: int = 0,
        keyword_tokens: int = 0,
        knowledge_tokens: int = 0,
        observer_note: str = "",
    ) -> None:
        ts = ts or datetime.now().strftime("%H:%M:%S")
        with self._lock:
            rows = []
            if self.log_path.exists():
                doc = bejson_core_load_file(str(self.log_path))
                if isinstance(doc, dict):
                    rows = doc.get("Values", [])
            rows.append([
                ts, role, content, bubble_content,
                policy_tokens, active_tasks_tokens, env_file_tokens, cwd_tokens, keyword_tokens, knowledge_tokens, observer_note,
            ])
            new_doc = bejson_core_create_104a("Transcript", list(_TRANSCRIPT_FIELDS), rows)
            if not bejson_core_atomic_write(str(self.log_path), new_doc):
                import logging
                logging.getLogger(__name__).error(
                    "[Session] Atomic write failed for %s", self.log_path
                )
            self._regenerate_human_log(rows)

    def log_turn_relational(
        self,
        model_used: str,
        prompt_text: str,
        response_text: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float = 0.0,
        actions_list: Optional[list] = None,
    ) -> str:
        """
        Appends relational Turn and Action entities into the 104db store,
        updating the top-level Session entity metrics in real-time.
        """
        import uuid
        with self._lock:
            self._turn_counter += 1
            turn_id = f"turn_{self.session_guid}_{self._turn_counter}"
            now_iso = datetime.now().isoformat()

            # 1. Read existing 104db file
            db_doc = bejson_core_load_file(str(self.db_path))
            if not isinstance(db_doc, dict):
                return ""

            rows = db_doc.get("Values", [])
            fmap = bejson_core_get_field_map(db_doc)

            # 2. Update Session entity row (row 0)
            if rows and rows[0][0] == "Session":
                sess_row = rows[0]
                sess_row[fmap.get("model_used", 3)] = model_used
                sess_row[fmap.get("total_input_tokens", 4)] = (sess_row[fmap.get("total_input_tokens", 4)] or 0) + input_tokens
                sess_row[fmap.get("total_output_tokens", 5)] = (sess_row[fmap.get("total_output_tokens", 5)] or 0) + output_tokens
                sess_row[fmap.get("total_turns", 6)] = self._turn_counter

            # 3. Create Turn entity row
            turn_row = [None] * len(_104DB_FIELDS)
            turn_row[0] = "Turn"
            turn_row[fmap.get("turn_id", 7)] = turn_id
            turn_row[fmap.get("session_fk", 8)] = self.session_guid
            turn_row[fmap.get("turn_index", 9)] = self._turn_counter
            turn_row[fmap.get("prompt_text", 10)] = prompt_text[:2000]
            turn_row[fmap.get("response_text", 11)] = response_text[:5000]
            turn_row[fmap.get("input_tokens", 12)] = input_tokens
            turn_row[fmap.get("output_tokens", 13)] = output_tokens
            turn_row[fmap.get("duration_ms", 14)] = round(duration_ms, 2)
            turn_row[fmap.get("timestamp_turn", 15)] = now_iso
            rows.append(turn_row)

            # 4. Create Action entity rows
            if actions_list:
                for idx, act in enumerate(actions_list, 1):
                    act_id = f"act_{turn_id}_{idx}"
                    act_type = getattr(act, "action_type", act.get("action_type") if isinstance(act, dict) else "unknown")
                    act_source = getattr(act, "source", act.get("source") if isinstance(act, dict) else "")
                    exit_code = getattr(act, "exit_code", act.get("exit_code") if isinstance(act, dict) else 0)
                    output_str = getattr(act, "output", act.get("output") if isinstance(act, dict) else "")

                    act_row = [None] * len(_104DB_FIELDS)
                    act_row[0] = "Action"
                    act_row[fmap.get("action_id", 16)] = act_id
                    act_row[fmap.get("turn_fk", 17)] = turn_id
                    act_row[fmap.get("action_type", 18)] = str(act_type)
                    act_row[fmap.get("action_source", 19)] = str(act_source)[:1000]
                    act_row[fmap.get("exit_code", 20)] = int(exit_code or 0)
                    act_row[fmap.get("output_bytes", 21)] = len(str(output_str or "").encode("utf-8"))
                    act_row[fmap.get("timestamp_action", 22)] = now_iso
                    rows.append(act_row)

            db_doc["Values"] = rows
            bejson_core_atomic_write(str(self.db_path), db_doc)
            return turn_id

    def get_entry(self, index_from_end: int = 1) -> Optional[dict]:
        """Context Button lookup: the Nth-from-end row in THIS session's
        transcript, with its tied-back bubble data."""
        if not self.log_path.exists():
            return None
        doc = bejson_core_load_file(str(self.log_path))
        if not isinstance(doc, dict):
            return None
        fmap = bejson_core_get_field_map(doc)
        rows = doc.get("Values", [])
        if index_from_end < 1 or index_from_end > len(rows):
            return None
        row = rows[-index_from_end]
        return {name: row[idx] for name, idx in fmap.items() if idx < len(row)}

    def update_last_bubble(
        self,
        bubble_content: str,
        policy_tokens: int,
        keyword_tokens: int,
        knowledge_tokens: int,
        active_tasks_tokens: int = 0,
        env_file_tokens: int = 0,
        cwd_tokens: int = 0,
        observer_note: str = "",
    ) -> None:
        """
        Patches the context-bubble columns onto the row that was just logged
        for the outgoing prompt — ties bubble data to the same record without
        either a duplicate row or a data-loss window (the prompt itself is
        always logged immediately at append time, before the bubble exists;
        this fills in the remaining columns once assembly finishes).
        """
        with self._lock:
            if not self.log_path.exists():
                return
            doc = bejson_core_load_file(str(self.log_path))
            if not isinstance(doc, dict):
                return
            fmap = bejson_core_get_field_map(doc)
            rows = doc.get("Values", [])
            if not rows:
                return
            bubble_idx = fmap.get("bubble_content", 3)
            policy_idx = fmap.get("policy_tokens", 4)
            active_tasks_idx = fmap.get("active_tasks_tokens", 5)
            env_file_idx = fmap.get("env_file_tokens", 6)
            cwd_idx = fmap.get("cwd_tokens", 7)
            keyword_idx = fmap.get("keyword_tokens", 8)
            knowledge_idx = fmap.get("knowledge_tokens", 9)
            note_idx = fmap.get("observer_note", 10)
            row = rows[-1]
            row[bubble_idx] = bubble_content
            row[policy_idx] = policy_tokens
            row[active_tasks_idx] = active_tasks_tokens
            row[env_file_idx] = env_file_tokens
            row[cwd_idx] = cwd_tokens
            row[keyword_idx] = keyword_tokens
            row[knowledge_idx] = knowledge_tokens
            row[note_idx] = observer_note
            new_doc = bejson_core_create_104a("Transcript", list(_TRANSCRIPT_FIELDS), rows)
            if not bejson_core_atomic_write(str(self.log_path), new_doc):
                import logging
                logging.getLogger(__name__).error(
                    "[Session] Atomic write failed for %s", self.log_path
                )
            self._regenerate_human_log(rows)

def save_resume_session(resume_path: Path, history: list[dict]) -> None:
    data = {"saved_at": time.time(), "history": history}
    _atomic_write(resume_path, data)

def load_resume_session(resume_path: Path) -> Optional[list[dict]]:
    if not resume_path.exists():
        return None
    try:
        raw = json.loads(resume_path.read_text("utf-8"))
        return raw.get("history")
    except Exception:
        return None

def clear_resume_session(resume_path: Path) -> None:
    resume_path.unlink(missing_ok=True)

def save_native_resume(resume_path: Path, interaction_id: str, recap: str) -> None:
    data = {
        "saved_at": time.time(),
        "interaction_id": interaction_id,
        "recap": recap,
    }
    _atomic_write(resume_path, data)

def load_native_resume(resume_path: Path) -> Optional[dict]:
    if not resume_path.exists():
        return None
    try:
        return json.loads(resume_path.read_text("utf-8"))
    except Exception:
        return None

def clear_native_resume(resume_path: Path) -> None:
    resume_path.unlink(missing_ok=True)

def archive_named_session(index_path: Path, label: str, log_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    label_idx = 0
    if index_path.exists():
        doc = bejson_core_load_file(str(index_path))
        if isinstance(doc, dict):
            result = validate_bejson(doc, is_file=False)
            if not result.valid:
                import logging
                logging.getLogger(__name__).warning(
                    "[Session] %s failed structural validation: %s", index_path, result.errors
                )
            fmap = bejson_core_get_field_map(doc)
            label_idx = fmap.get("label", 0)
            rows = doc.get("Values", [])

    rows = [r for r in rows if len(r) <= label_idx or r[label_idx] != label]
    rows.append([label, str(log_path), datetime.now().isoformat()])

    doc = bejson_core_create_104a("NamedSession", list(_SESSION_INDEX_FIELDS), rows)
    if not bejson_core_atomic_write(str(index_path), doc):
        import logging
        logging.getLogger(__name__).error("[Session] Atomic write failed for %s", index_path)

def list_named_sessions(index_path: Path) -> list[dict]:
    if not index_path.exists():
        return []
    doc = bejson_core_load_file(str(index_path))
    if not isinstance(doc, dict):
        return []
    fmap = bejson_core_get_field_map(doc)
    label_idx = fmap.get("label", 0)
    log_idx = fmap.get("log_path", 1)
    saved_idx = fmap.get("saved_at", 2)
    out = []
    for row in doc.get("Values", []):
        if len(row) <= max(label_idx, log_idx, saved_idx):
            continue
        out.append({
            "label": row[label_idx],
            "log_path": row[log_idx],
            "saved_at": row[saved_idx] or "",
        })
    return out

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
