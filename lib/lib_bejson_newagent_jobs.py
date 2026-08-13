"""
Library:        lib_bejson_newagent_jobs.py
Family:         NewAgent
Description:    Job Creation System — scans the jobs/ folder for JobMaker.py-authored
                BEJSON 104a job schemas, injects active-job context into the agent's
                system prompt, marks tasks completed via the Field Map Cache, and
                moves/prunes completed jobs.
Version:        1.0.0
Date:           2026-08-08
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  b6e2f0b1-6d0a-4a1a-9c2e-4f0d8b1a2e33
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_atomic_write,
    bejson_core_get_field_map,
)

VERSION = "1.0.0"

# Completed jobs older than this are scheduled for deletion (per spec: "if the
# completion date is over a week old, it will be scheduled for deletion").
JOB_COMPLETE_STALE_SECONDS = 7 * 86400


def ensure_job_dirs(jobs_dir: Path) -> None:
    """Create jobs/ and jobs/complete/ if missing. Call once at agent bootstrap."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "complete").mkdir(parents=True, exist_ok=True)


def scan_jobs(jobs_dir: Path) -> list[dict]:
    """
    Scan jobs_dir (non-recursive, excludes complete/) for BEJSON 104a job
    schemas and return a summary list: [{filename, job_name, goal, task_count,
    completed_count}]. Malformed files are skipped, not raised.
    """
    out = []
    if not jobs_dir.exists():
        return out
    for f in sorted(jobs_dir.glob("*.bejson")):
        if not f.is_file():
            continue
        doc = bejson_core_load_file(str(f))
        if not isinstance(doc, dict) or doc.get("Job_Complete") is True:
            continue
        fmap = bejson_core_get_field_map(doc)
        completed_idx = fmap.get("task_completed")
        rows = doc.get("Values", [])
        completed_count = 0
        if completed_idx is not None:
            completed_count = sum(
                1 for r in rows if len(r) > completed_idx and r[completed_idx] is True
            )
        out.append({
            "filename": f.name,
            "job_name": f.stem,
            "goal": doc.get("Job_Goal", ""),
            "task_count": len(rows),
            "completed_count": completed_count,
        })
    return out


def format_job_announcement(jobs_dir: Path) -> Optional[str]:
    """Human-readable startup announcement. Returns None if no pending jobs."""
    jobs = scan_jobs(jobs_dir)
    if not jobs:
        return None
    lines = [f"Found {len(jobs)} pending job(s) in jobs/:"]
    for j in jobs:
        lines.append(
            f"  - {j['job_name']}  ({j['completed_count']}/{j['task_count']} tasks done)"
            + (f"  — {j['goal']}" if j['goal'] else "")
        )
    lines.append("Start one now? Enter a job name, or press Enter to skip for now.")
    return "\n".join(lines)


def get_job_path(jobs_dir: Path, name_or_filename: str) -> Optional[Path]:
    """Resolve a job by bare name (stem) or exact filename, in jobs_dir only
    (never jobs/complete/ — a job selected to "start" must still be active)."""
    name_or_filename = name_or_filename.strip()
    if not name_or_filename:
        return None
    candidate = jobs_dir / name_or_filename
    if candidate.is_file():
        return candidate
    candidate = jobs_dir / f"{name_or_filename}.bejson"
    if candidate.is_file():
        return candidate
    return None


def load_job(job_path: Path) -> Optional[dict]:
    doc = bejson_core_load_file(str(job_path))
    return doc if isinstance(doc, dict) else None


def build_job_context_block(doc: Optional[dict]) -> str:
    """Render the active job's goal + incomplete tasks for system-prompt
    injection. Returns "" (falsy) when no job is active, so callers can
    omit the section entirely rather than print an empty header."""
    if not doc:
        return ""
    fmap = bejson_core_get_field_map(doc)
    id_idx = fmap.get("task_id", 0)
    name_idx = fmap.get("task_name", 2)
    desc_idx = fmap.get("task_description", 3)
    completed_idx = fmap.get("task_completed", 4)
    order_idx = fmap.get("task_order")

    rows = list(doc.get("Values", []))
    if order_idx is not None:
        rows.sort(key=lambda r: r[order_idx] if len(r) > order_idx else 0)

    lines = [f"ACTIVE JOB: {doc.get('Job_Goal', '(no goal set)')}"]
    for r in rows:
        done = len(r) > completed_idx and r[completed_idx] is True
        tid = r[id_idx] if len(r) > id_idx else "?"
        name = r[name_idx] if len(r) > name_idx else ""
        desc = r[desc_idx] if len(r) > desc_idx else ""
        marker = "x" if done else " "
        lines.append(f"  [{marker}] task_id={tid} {name} — {desc}")
    lines.append(
        "Execute one incomplete task at a time. Use <job_task_done id=\"...\"/> "
        "to mark a task complete (by its task_id) once you've actually finished it."
    )
    return "\n".join(lines)


def mark_task_completed(jobs_dir: Path, job_filename: str, task_id: str) -> tuple[bool, str]:
    """
    Mark task_id's task_completed=True in job_filename (must live directly in
    jobs_dir, not jobs/complete/). If every task is now complete, sets the
    Job_Complete / Completion_Date custom headers and moves the file to
    jobs/complete/.
    """
    job_path = jobs_dir / job_filename
    if not job_path.is_file():
        return False, f"[ERROR] Job file not found: {job_filename}"

    doc = bejson_core_load_file(str(job_path))
    if not isinstance(doc, dict):
        return False, f"[ERROR] Could not load {job_filename} as BEJSON."

    fmap = bejson_core_get_field_map(doc)
    id_idx = fmap.get("task_id")
    completed_idx = fmap.get("task_completed")
    if id_idx is None or completed_idx is None:
        return False, f"[ERROR] {job_filename} is missing task_id/task_completed fields."

    rows = doc.get("Values", [])
    found = False
    for row in rows:
        if len(row) > id_idx and str(row[id_idx]) == str(task_id):
            row[completed_idx] = True
            found = True
            break
    if not found:
        return False, f"[ERROR] No task with task_id '{task_id}' in {job_filename}."

    all_done = all(
        len(r) > completed_idx and r[completed_idx] is True for r in rows
    )

    moved_note = ""
    if all_done:
        doc["Job_Complete"] = True
        doc["Completion_Date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dest = jobs_dir / "complete" / job_filename
        if not bejson_core_atomic_write(str(job_path), doc):
            return False, f"[ERROR] Failed to save {job_filename} before completion move."
        dest.parent.mkdir(parents=True, exist_ok=True)
        job_path.replace(dest)
        moved_note = " Job complete — moved to jobs/complete/."
    else:
        if not bejson_core_atomic_write(str(job_path), doc):
            return False, f"[ERROR] Failed to save {job_filename}."

    return True, f"Task {task_id} marked complete in {job_filename}.{moved_note}"


def cleanup_old_completed_jobs(jobs_dir: Path) -> list[str]:
    """Delete completed jobs in jobs/complete/ whose Completion_Date is more
    than JOB_COMPLETE_STALE_SECONDS old. Returns filenames deleted."""
    complete_dir = jobs_dir / "complete"
    if not complete_dir.exists():
        return []
    deleted = []
    now = time.time()
    for f in complete_dir.glob("*.bejson"):
        doc = bejson_core_load_file(str(f))
        completion_date = doc.get("Completion_Date") if isinstance(doc, dict) else None
        age_seconds = now - f.stat().st_mtime
        if completion_date:
            try:
                completed_ts = datetime.strptime(completion_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                ).timestamp()
                age_seconds = now - completed_ts
            except ValueError:
                pass  # fall back to mtime-based age above
        if age_seconds > JOB_COMPLETE_STALE_SECONDS:
            try:
                f.unlink()
                deleted.append(f.name)
            except OSError:
                pass
    return deleted
