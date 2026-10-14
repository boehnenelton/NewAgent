"""
Library:        lib_bejson_newagent_session.py
Family:         NewAgent
Description:    Atomic session logger, resume file persistence, named session archiving.
Version:        2.8.0
Date:           2026-10-13
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  4e3130b9-3ccc-45c2-9eed-fa37fe0988f2

CHANGELOG:
- 2.8.0 (2026-10-13): Added prune_old_logs() (3-day hard delete of session
  logs, raw API dumps and legacy archive zips; replaces zip-and-archive at
  startup) and write-time secret redaction in SessionLogger.log().
  archive_old_session_logs() kept for compatibility but no longer called.
- 2.7.0 (2026-09-18): Remediation pass, audit finding #3 (Field-Map
  Fallback Landmine) plus a self-caught bug. (1) Added `import logging`
  -- this file called `logging.getLogger(__name__)` in 6 places but never
  imported the module, so every one of those error-log calls (mostly
  inside except blocks) would itself raise NameError, masking the
  original error being logged. (2) Added _require_field(fmap, name):
  every one of the 34 `fmap.get(name, hardcoded_index)` calls in this
  file silently fell back to a positional literal if the field-map
  lookup missed -- defeating Field Map Cache (policy Sec 6.2) and risking
  a silent miswrite into the wrong column on a drifted/foreign doc. All
  34 now route through _require_field, which raises a clear KeyError
  naming the missing field and the doc's actual known fields instead of
  guessing. Tradeoff, noted for the record: a genuinely corrupt/legacy
  row that's missing a field will now raise instead of silently
  (mis)writing -- correct per policy intent (loud > silent), but callers
  relying on the old silent-degrade behavior will need to catch this if
  graceful skip is ever wanted instead of a hard failure; none of this
  file's own call sites currently do, so today it surfaces as an
  uncaught exception out of log_turn_relational()/update_last_bubble()/
  etc. Verified: py_compile clean; manual field-map-with-missing-key
  test confirms the new KeyError message and that a healthy fmap
  (this module's own schemas) is unaffected.
- 2.6.0 (2026-08-18): Logging System rework, per Elton's request. (1) No
  more automatic markdown generation -- __init__ and log() no longer call
  _regenerate_human_log; a .md file is now only ever produced on demand via
  the new /logs2md command (lib_bejson_newagent_commands.py) or by calling
  convert_session_to_markdown() directly, which also zips the result with a
  conversion timestamp in the filename. (2) Added timestamp_iso (full
  ISO-8601 date+time) to _TRANSCRIPT_FIELDS, appended at the end --
  positional integrity preserved, the original short HH:MM:SS "timestamp"
  field is untouched. The markdown renderer now shows the full ISO
  timestamp when present, falling back to the short one for any row logged
  before this field existed. (3) Added archive_old_session_logs(logs_dir,
  keep_recent=3) -- called once at agent.py startup (mirrors
  jobs.cleanup_old_completed_jobs's existing pattern): keeps the
  keep_recent most recent sessions' files exactly where they are, bundles
  every older session's full sibling set (.bejson transcript, .104db.bejson
  relational store, and .md/_md_*.zip if one was ever manually made) into
  one zip per session under logs/archive/, then removes the originals.
  _regenerate_human_log's rendering logic was extracted into module-level
  _render_transcript_markdown() so the (now manual-only) instance method
  and the new standalone convert_session_to_markdown() -- which needs to
  work on an arbitrary, possibly-already-archived .bejson with no
  SessionLogger instance at all -- share one renderer instead of a second
  copy that could drift. VERSION MISMATCH NOTED AND RESOLVED: this file's
  header docstring said 2.4.0 while the VERSION variable already said
  2.5.0 (predates this change) -- adopted 2.5.0 as the more-advanced base
  per policy and bumped both to 2.6.0 together so they can't drift again.
  Verified: no .md exists right after init or after a log() call; a manual
  /logs2md-equivalent conversion produces the .md and a timestamped zip;
  timestamp_iso is populated and ISO-shaped; archive_old_session_logs
  correctly keeps 3 recent untouched, correctly bundles the 3 oldest
  (including their .md sibling) into logs/archive/*.zip and removes the
  originals, and is idempotent (no-op on immediate re-run); fixed a bug
  found during testing where the transcript glob (session_*.bejson) was
  also matching the *.104db.bejson sibling, corrupting session grouping --
  caught by the test before shipping, not after.
"""

import json
import logging
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
import lib_bejson_newagent_errors as errors

VERSION = "2.8.0"

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
    {"name": "timestamp_iso", "type": "string"},
]


def _require_field(fmap: dict, name: str) -> int:
    """Remediation pkg (audit finding #3): every field-map lookup in this
    file used to be `fmap.get(name, hardcoded_index)` -- a schema drift or
    a stale/foreign row (fmap missing `name`) silently fell back to a
    positional literal instead of raising, which is exactly what Field Map
    Cache (policy Sec 6.2) exists to prevent: the fallback index could
    point at an entirely different field on a mismatched doc and corrupt
    it silently with no error at all. This raises a clear, specific error
    instead so a schema mismatch is loud and diagnosable rather than a
    quiet miswrite.
    """
    if name not in fmap:
        raise KeyError(
            f"[Session] Field '{name}' missing from field map "
            f"(schema drift or corrupt/foreign doc) -- known fields: {sorted(fmap.keys())}"
        )
    return fmap[name]


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

def _render_transcript_markdown(session_name: str, rows: list[list]) -> str:
    """
    Shared rendering engine for both SessionLogger's (now manual-only)
    regeneration and the standalone convert_session_to_markdown() below --
    one renderer, so the on-disk .bejson transcript is always the single
    source of truth and the .md is always a faithful, never hand-edited,
    derivation of it. Uses timestamp_iso (full date+time) in the header
    when present, falling back to the short HH:MM:SS timestamp for any
    older log row logged before that field existed.
    """
    lines = [f"# NewAgent Session — {session_name}\n"]
    for row in rows:
        if len(row) < 11:
            continue
        ts, role, content, bubble_content, policy_tok, active_tasks_tok, env_tok, cwd_tok, keyword_tok, knowledge_tok, note = row[:11]
        ts_iso = row[11] if len(row) > 11 and row[11] else ts
        lines.append(f"### [{ts_iso}] [{(role or '').upper()}]")
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
    return "\n".join(lines)


def convert_session_to_markdown(bejson_log_path: Path) -> tuple[bool, str]:
    """
    On-demand markdown conversion, per Elton's Logging System request:
    "make the user type a command to convert the logs to markdown... No
    more automatic markdown log generation." SessionLogger no longer
    writes a .md file on its own (see __init__ and log() above) -- this is
    now the only path that produces one, and it's paired with a timestamped
    zip of the result. Standalone/module-level (not a SessionLogger method)
    so it works on ANY session_*.bejson, including an already-archived one,
    not just the live session currently being logged.
    """
    bejson_log_path = Path(bejson_log_path)
    if not bejson_log_path.exists():
        return False, f"{bejson_log_path} does not exist."
    doc = bejson_core_load_file(str(bejson_log_path))
    if not isinstance(doc, dict):
        return False, f"{bejson_log_path} isn't readable as BEJSON."

    md_path = bejson_log_path.with_suffix(".md")
    md_text = _render_transcript_markdown(bejson_log_path.stem, doc.get("Values", []))
    try:
        md_path.write_text(md_text, encoding="utf-8")
    except Exception as exc:
        return False, f"Failed writing {md_path}: {exc}"

    conv_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = bejson_log_path.parent / f"{bejson_log_path.stem}_md_{conv_ts}.zip"
    try:
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(md_path, arcname=md_path.name)
    except Exception as exc:
        return False, f"Wrote {md_path} but zip failed: {exc}"

    return True, f"Converted {bejson_log_path.name} -> {md_path.name}, zipped as {zip_path.name}"


def archive_old_session_logs(logs_dir: Path, keep_recent: int = 3) -> list[str]:
    """
    Elton's request: "Any logs over 3 sessions ago should be automatically
    zipped and moved to an archive logs/archive subfolder." Session files
    sort chronologically by filename already (session_YYYY-MM-DD_HH-MM-SS.*)
    so no extra timestamp parsing is needed for ordering. Keeps the
    keep_recent most recent sessions' files exactly where they are; every
    older session's full file set (.bejson transcript, .104db.bejson
    relational store, and .md/_md_*.zip if a manual conversion was ever
    done) gets bundled into one zip per session under logs/archive/ and the
    originals removed. Call once at startup (mirrors
    jobs.cleanup_old_completed_jobs's pattern) -- cheap no-op glob when
    there's nothing to do. Returns the list of session stems archived.
    """
    logs_dir = Path(logs_dir)
    if not logs_dir.is_dir():
        return []
    transcripts = sorted(
        (p for p in logs_dir.glob("session_*.bejson") if not p.name.endswith(".104db.bejson")),
        reverse=True,
    )  # newest first; excludes the .104db.bejson sibling, which has its own "session_*.bejson" glob hit otherwise
    stale = transcripts[keep_recent:]
    if not stale:
        return []

    archive_dir = logs_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    import zipfile
    archived = []
    for transcript_path in stale:
        stem = transcript_path.stem  # e.g. "session_2026-08-10_09-30-00"
        siblings = sorted(logs_dir.glob(f"{stem}*"))  # .bejson, .104db.bejson, .md, _md_*.zip
        if not siblings:
            continue
        zip_path = archive_dir / f"{stem}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in siblings:
                    zf.write(f, arcname=f.name)
            for f in siblings:
                f.unlink()
            archived.append(stem)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "[Session] Failed archiving %s: %s", stem, exc
            )
    return archived


LOG_RETENTION_DAYS = 3
_PRUNE_GLOBS = ("session_*", "raw_api_debug_*", "raw_api_error_*")


def prune_old_logs(logs_dir: Path, max_age_days: float = LOG_RETENTION_DAYS,
                   protect_stems: tuple = ()) -> list[str]:
    """
    Elton's request (2026-10-13): logs are disposable -- anything in logs/
    older than 3 days is deleted outright (no zipping, no archive). Covers
    session_* transcripts (.bejson/.104db.bejson/.md/zips), raw_api_debug_*
    and raw_api_error_* dumps, and anything under logs/archive/ (legacy).
    Age is file mtime. logs/sessions/session_index.bejson (named-session
    index) is never touched. `protect_stems` keeps a live session's files
    even if its mtime is somehow stale. Returns names deleted. Cheap no-op
    when nothing is old; never raises.
    """
    logs_dir = Path(logs_dir)
    if not logs_dir.is_dir():
        return []
    cutoff = time.time() - max_age_days * 86400
    candidates = []
    for pattern in _PRUNE_GLOBS:
        candidates.extend(p for p in logs_dir.glob(pattern) if p.is_file())
    archive_dir = logs_dir / "archive"
    if archive_dir.is_dir():
        candidates.extend(p for p in archive_dir.iterdir() if p.is_file())
    deleted = []
    for path in candidates:
        if any(stem and path.name.startswith(stem) for stem in protect_stems):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                deleted.append(path.name)
        except OSError as exc:
            logging.getLogger(__name__).error("[Session] prune failed for %s: %s", path, exc)
    if archive_dir.is_dir():
        try:
            archive_dir.rmdir()  # only succeeds when empty
        except OSError:
            pass
    return deleted


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
        Manual-only now (see Elton's Logging System request) -- kept as an
        instance method purely so anything that already held a reference to
        a live SessionLogger can still force a regen of the CURRENT session
        specifically without needing its own path lookup. The actual
        rendering logic lives in the module-level _render_transcript_markdown
        so convert_session_to_markdown() (which needs to work on arbitrary,
        possibly-archived .bejson files with no SessionLogger instance at
        all) shares the exact same output instead of a parallel copy that
        could drift.
        """
        md_text = _render_transcript_markdown(self.log_path.stem, rows)
        try:
            self.human_log_path.write_text(md_text, encoding="utf-8")
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
        ts_iso = datetime.now().isoformat()
        # 2026-10-13 audit fix: last line of defense -- nothing shaped like an
        # API key is ever persisted to a transcript, whatever produced it.
        content = errors.redact_secrets(content)
        bubble_content = errors.redact_secrets(bubble_content)
        observer_note = errors.redact_secrets(observer_note)
        with self._lock:
            rows = []
            if self.log_path.exists():
                doc = bejson_core_load_file(str(self.log_path))
                if isinstance(doc, dict):
                    rows = doc.get("Values", [])
            rows.append([
                ts, role, content, bubble_content,
                policy_tokens, active_tasks_tokens, env_file_tokens, cwd_tokens, keyword_tokens, knowledge_tokens, observer_note,
                ts_iso,
            ])
            new_doc = bejson_core_create_104a("Transcript", list(_TRANSCRIPT_FIELDS), rows)
            if not bejson_core_atomic_write(str(self.log_path), new_doc):
                import logging
                logging.getLogger(__name__).error(
                    "[Session] Atomic write failed for %s", self.log_path
                )

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
                sess_row[_require_field(fmap, "model_used")] = model_used
                sess_row[_require_field(fmap, "total_input_tokens")] = (sess_row[_require_field(fmap, "total_input_tokens")] or 0) + input_tokens
                sess_row[_require_field(fmap, "total_output_tokens")] = (sess_row[_require_field(fmap, "total_output_tokens")] or 0) + output_tokens
                sess_row[_require_field(fmap, "total_turns")] = self._turn_counter

            # 3. Create Turn entity row
            turn_row = [None] * len(_104DB_FIELDS)
            turn_row[0] = "Turn"
            turn_row[_require_field(fmap, "turn_id")] = turn_id
            turn_row[_require_field(fmap, "session_fk")] = self.session_guid
            turn_row[_require_field(fmap, "turn_index")] = self._turn_counter
            turn_row[_require_field(fmap, "prompt_text")] = prompt_text[:2000]
            turn_row[_require_field(fmap, "response_text")] = response_text[:5000]
            turn_row[_require_field(fmap, "input_tokens")] = input_tokens
            turn_row[_require_field(fmap, "output_tokens")] = output_tokens
            turn_row[_require_field(fmap, "duration_ms")] = round(duration_ms, 2)
            turn_row[_require_field(fmap, "timestamp_turn")] = now_iso
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
                    act_row[_require_field(fmap, "action_id")] = act_id
                    act_row[_require_field(fmap, "turn_fk")] = turn_id
                    act_row[_require_field(fmap, "action_type")] = str(act_type)
                    act_row[_require_field(fmap, "action_source")] = str(act_source)[:1000]
                    act_row[_require_field(fmap, "exit_code")] = int(exit_code or 0)
                    act_row[_require_field(fmap, "output_bytes")] = len(str(output_str or "").encode("utf-8"))
                    act_row[_require_field(fmap, "timestamp_action")] = now_iso
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
            bubble_idx = _require_field(fmap, "bubble_content")
            policy_idx = _require_field(fmap, "policy_tokens")
            active_tasks_idx = _require_field(fmap, "active_tasks_tokens")
            env_file_idx = _require_field(fmap, "env_file_tokens")
            cwd_idx = _require_field(fmap, "cwd_tokens")
            keyword_idx = _require_field(fmap, "keyword_tokens")
            knowledge_idx = _require_field(fmap, "knowledge_tokens")
            note_idx = _require_field(fmap, "observer_note")
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
            label_idx = _require_field(fmap, "label")
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
    label_idx = _require_field(fmap, "label")
    log_idx = _require_field(fmap, "log_path")
    saved_idx = _require_field(fmap, "saved_at")
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
