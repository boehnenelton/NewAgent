"""
Library:        lib_bejson_newagent_actions.py
Family:         NewAgent
Description:    Model action execution tools, XML tag parser, action queue dispatcher, and TaskManager.
Version:        2.1.0
Date:           2026-08-08
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  4c1a7e9d-2b3f-4a5e-9d6c-7f8e0a1b2c3d

CHANGELOG:
- 2.1.0 (2026-08-08): Added the Job Creation System's <job_task_done id="..."/>
  action tag (self-closing, dispatched via lib_bejson_newagent_jobs), and an
  active_job param on build_system_prompt() that injects the running job's
  goal + incomplete tasks (via jobs.build_job_context_block) into the system
  prompt only when a job has actually been started (empty otherwise, so
  nothing changes for sessions with no active job).
"""

import asyncio
import difflib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional, Callable
from lib_bejson_newagent_tui import ExecResult
from lib_bejson_newagent_backup import record_backup, restore_backup, get_live_backup_ids
from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson
import lib_bejson_newagent_jobs as jobs

_CHECKPOINT_FIELDS = [
    {"name": "label", "type": "string"},
    {"name": "backup_ids", "type": "array"},
    {"name": "created_at", "type": "string"},
]

VERSION = "2.1.0"
_SYSTEM_PROMPT_TEMPLATE = """You are a highly capable terminal agent running on Termux/Android.
You have access to files, shell execution, search tools, and memory.

CWD: {cwd}

CRITICAL RULES:
1. Always test your code edits by executing relevant test suites immediately.
2. Maintain separate single-concern files to keep bloat down.
3. Credit Elton Boehnen (boehnenelton2024@gmail.com) in all files you modify or output.
4. In REST mode, emit your actions inside XML tags. You can chain up to 10 actions per turn.
   Available tags:
     <exec>cmd</exec>
     <read_file>path</read_file>
     <write_file path="...">content</write_file>
     <edit_file path="..."><old>old content</old><new>new content</new></edit_file>
     <list_dir>path</list_dir>
     <tree_view>path</tree_view>
     <make_dir>path</make_dir>
     <delete_file>path</delete_file>
     <copy_file src="..." dst="..."/>
     <diff_file>path</diff_file>
     <restore_file>backup_id</restore_file>
     <http_get>url</http_get>
     <find_files>pattern</find_files>
     <search_text>pattern</search_text>
     <fuzzy_find>query</fuzzy_find>
     <env_get>VAR_NAME</env_get>
     <speak>text</speak>
     <checkpoint>label</checkpoint>
     <checklist_create title="Job name">task one; task two; task three</checklist_create>
     <checklist_check path="checklist_x.bejson" task_id="1"></checklist_check>
     <checklist_add path="checklist_x.bejson">new task</checklist_add>
     <checklist_view path="checklist_x.bejson"></checklist_view>
       (persistent per-job checklists, live in cwd, auto-injected into your
        own context every turn while incomplete, auto-deleted 24h after the
        last task is checked off. Use these for any multi-step job instead
        of tracking steps only in your own head.)
     <html_report title="...">report body text</html_report>
     <html_report_append path="report_x.html">more content</html_report_append>
     <project_log version="v1.2.3">what changed and why</project_log>
       (appends a changelog entry to .bejson_project.json, found by walking
        up from cwd)
     <request_continue>reason</request_continue>
     <bejson_fields>path/to/file.bejson</bejson_fields>
     <bejson_add_field path="...">{{"name":"x","type":"string"}}</bejson_add_field>
     <bejson_delete_field path="...">field_name</bejson_delete_field>
     <bejson_create_record path="...">["val1", 2, true]</bejson_create_record>
     <bejson_delete_record path="..." row="N"></bejson_delete_record>
     <bejson_set_value path="..." row="N" field="name">new_value</bejson_set_value>
     <bejson_set_value path="..." row="N" col="N">new_value</bejson_set_value>
     <bejson_columns path="..." columns="name,status" rows="0-9"></bejson_columns>
       (returns ONLY the requested columns for the requested rows, resolved
        by field name via the field map -- prefer this over read_file for
        large BEJSON files when you only need specific fields, not the
        whole document. rows accepts "N", "N-M", or omit for all rows,
        capped at 200 rows per call.)
     <exec_bg>cmd</exec_bg>
     <task_status>task_id</task_status>
     <task_kill>task_id</task_kill>
     <task_list/>
     <job_task_done id="task_id"/>
       (marks the given task_id complete in the currently active job, see
        ACTIVE JOB below if one is running. Only usable once a job has been
        explicitly started by the user -- never self-start a job.)
{active_job_section}
INJECTED CONTEXT (assembled by the Context Bubble pipeline, budget-capped and logged):
{bubble}
"""

ACTION_PATTERN = re.compile(
    r"<(exec|read_file|write_file|edit_file|list_dir|tree_view|make_dir|delete_file|"
    r"copy_file|diff_file|restore_file|http_get|find_files|search_text|fuzzy_find|env_get|"
    r"speak|checkpoint|checklist_create|checklist_check|checklist_add|checklist_view|"
    r"html_report|html_report_append|project_log|request_continue|"
    r"bejson_fields|bejson_add_field|bejson_delete_field|bejson_create_record|"
    r"bejson_delete_record|bejson_set_value|bejson_columns|"
    r"exec_bg|task_status|task_kill|task_list)(?:\s+([^>]*))?>(.*?)</\1>|<(copy_file|task_list|job_task_done)(?:\s+([^>]*))?\s*/>",
    re.DOTALL | re.IGNORECASE,
)

# ── Background Task Manager Class ───────────────────────────────────────────

class TaskManager:
    """Async background task manager for long-running shell processes."""
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._counter: int = 1

    def spawn_task(
        self, command: str, cwd: str, task_id: Optional[str] = None,
        shell_env: Optional[dict] = None,
    ) -> str:
        if not task_id:
            task_id = f"task-{self._counter}"
            self._counter += 1

        task_info = {
            "task_id": task_id,
            "command": command,
            "cwd": cwd,
            "status": "RUNNING",
            "start_time": time.time(),
            "end_time": None,
            "return_code": None,
            "output_chunks": [],
            "proc": None,
            "async_task": None,
        }
        self._tasks[task_id] = task_info

        async def _runner():
            cmd_to_run = f"cd {shlex.quote(cwd)} && {command}"
            try:
                bash_exec = "/data/data/com.termux/files/usr/bin/bash" if os.path.exists("/data/data/com.termux/files/usr/bin/bash") else (shutil.which("bash") or "/bin/sh")
                proc = await asyncio.create_subprocess_shell(
                    cmd_to_run,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    executable=bash_exec,
                    # Snapshot only, at spawn time — matches the existing
                    # cwd freeze-at-spawn semantics. Not written back to
                    # ctx['_shell_env'] on completion: a background task
                    # can outlive several foreground turns, and writing
                    # back would race the foreground exec loop's own
                    # env updates. Persistence stays foreground-only.
                    env=shell_env,
                )
                task_info["proc"] = proc

                async def read_stream(stream):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        decoded = line.decode("utf-8", errors="replace")
                        task_info["output_chunks"].append(decoded)

                await asyncio.gather(
                    read_stream(proc.stdout),
                    read_stream(proc.stderr),
                )
                rc = await proc.wait()
                task_info["return_code"] = rc
                task_info["status"] = "COMPLETED" if rc == 0 else f"FAILED (exit code {rc})"
            except asyncio.CancelledError:
                task_info["status"] = "CANCELLED"
            except Exception as e:
                task_info["status"] = f"ERROR ({e})"
            finally:
                task_info["end_time"] = time.time()

        task_info["async_task"] = asyncio.create_task(_runner())
        return task_id

    def get_status(self, task_id: str) -> str:
        info = self._tasks.get(task_id)
        if not info:
            return f"[ERROR] Task '{task_id}' not found."
        
        output_str = "".join(info["output_chunks"])
        elapsed = (info["end_time"] or time.time()) - info["start_time"]
        return (
            f"Task ID: {task_id}\n"
            f"Command: {info['command']}\n"
            f"CWD: {info['cwd']}\n"
            f"Status: {info['status']}\n"
            f"Duration: {elapsed:.1f}s\n"
            f"Output ({len(info['output_chunks'])} lines):\n"
            f"{output_str if output_str else '(no output yet)'}"
        )

    def kill_task(self, task_id: str) -> str:
        info = self._tasks.get(task_id)
        if not info:
            return f"[ERROR] Task '{task_id}' not found."
        
        proc = info.get("proc")
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        
        async_task = info.get("async_task")
        if async_task and not async_task.done():
            async_task.cancel()
        
        info["status"] = "KILLED"
        info["end_time"] = time.time()
        return f"[SUCCESS] Task '{task_id}' killed."

    def list_tasks(self) -> str:
        if not self._tasks:
            return "No background tasks registered."
        lines = []
        for tid, info in self._tasks.items():
            elapsed = (info["end_time"] or time.time()) - info["start_time"]
            lines.append(f"[{tid}] {info['status']} ({elapsed:.1f}s) cwd={info['cwd']} — {info['command']}")
        return "\n".join(lines)

# Global task manager instance
_GLOBAL_TASK_MANAGER = TaskManager()


# ── Action Implementations ───────────────────────────────────────────────────

async def run_action_hook(
    action_type: str,
    event: str,
    cwd: str,
    hooks_config_path: str = "config/hooks.bejson",
    shell_env: Optional[dict] = None,
) -> tuple[bool, str]:
    """Execute pre/post action shell hooks configured in config/hooks.bejson.
    Ported from a divergent branch of this file (found on merge/reconciliation
    into pkg040) — a genuinely new, working feature, not a regression source,
    verified wired into run_action_queue below."""
    # Anchor relative hooks_config_path to project root (or initial working directory)
    # rather than dynamic cwd which changes upon `cd` actions.
    if not os.path.isabs(hooks_config_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hpath = Path(base_dir) / hooks_config_path
    else:
        hpath = Path(hooks_config_path)
    if not hpath.exists():
        return True, ""
    try:
        doc = bejson_core_load_file(str(hpath))
        if not isinstance(doc, dict):
            return True, ""
        fmap = bejson_core_get_field_map(doc)
        act_idx = fmap.get("action_type", 0)
        evt_idx = fmap.get("event", 1)
        cmd_idx = fmap.get("command", 2)
        ena_idx = fmap.get("enabled", 3)

        matching_cmds = []
        for row in doc.get("Values", []):
            if len(row) > max(act_idx, evt_idx, cmd_idx, ena_idx):
                if (row[act_idx] in (action_type, "*")) and (row[evt_idx] in (event, "*")) and row[ena_idx]:
                    matching_cmds.append(row[cmd_idx])

        if not matching_cmds:
            return True, ""

        bash_exec = "/data/data/com.termux/files/usr/bin/bash" if os.path.exists("/data/data/com.termux/files/usr/bin/bash") else (shutil.which("bash") or "/bin/sh")
        hook_logs = []
        for cmd in matching_cmds:
            proc = await asyncio.create_subprocess_shell(
                f"cd {shlex.quote(cwd)} && {cmd}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable=bash_exec,
                env=shell_env,
            )
            out_bytes, err_bytes = await proc.communicate()
            if proc.returncode != 0:
                err_text = (err_bytes or out_bytes).decode("utf-8", errors="replace").strip()
                return False, f"[HOOK ERROR] {event.upper()} hook '{cmd}' for '{action_type}' failed (exit {proc.returncode}): {err_text}"
            hook_logs.append(f"[HOOK SUCCESS] '{cmd}' executed.")
        return True, "\n".join(hook_logs)
    except Exception as e:
        return False, f"[HOOK EXCEPTION] {e}"


_ENV_MARKER = "__NEWAGENT_ENV_MARKER__"


async def do_exec(
    command: str,
    cwd: str,
    timeout: int = 60,
    live_feed: bool = False,
    shell_env: Optional[dict] = None,
) -> tuple[int, str, str, Optional[dict]]:
    """Execute shell command asynchronously with optional streaming, CWD
    tracking, and a Global Environment Dictionary (audit Part 1/II — chosen
    over a full PTY session as the lighter option).

    Each <exec> call is still a fresh subprocess (unchanged), but a full
    `env` dump is captured after every successful command and returned as
    new_env. The caller (run_action_queue) persists this in
    ctx['_shell_env'] and passes it back in as shell_env on the next call,
    so `export FOO=bar` in one turn is visible as $FOO in the next turn's
    subprocess environment — without needing a long-lived PTY.

    Known limitation, stated plainly: this captures exported environment
    variables only, not shell state that never becomes an env var (plain
    `alias`, shell functions, non-exported locals). A multi-line exported
    value will not round-trip correctly through the line-based env parse
    below. Full alias/function persistence still needs a PTY (flagged, not
    built, per the audit's PTY-vs-env-dict tradeoff).
    """
    cmd_to_run = (
        f"cd {shlex.quote(cwd)} && {command} && pwd && "
        f"printf '%s\\n' '{_ENV_MARKER}' && env"
    )
    try:
        # BUGFIX (2026-07-23): asyncio.create_subprocess_shell defaults to
        # /bin/sh, not bash. On Termux, /bin/sh lacks the `source` builtin
        # and does not support `alias`/`shopt`, which produced
        # "sh: source: not found" and silently-dropped aliases even though
        # the model's commands were valid bash. Forcing executable=bash
        # makes exec's shell semantics match what the model is prompted to
        # write. Note this does NOT make state (aliases, sourced vars, cwd
        # via `cd`) persist across separate <exec> calls — each call is
        # still a fresh subprocess — only the within-one-call behavior is
        # fixed.
        bash_exec = "/data/data/com.termux/files/usr/bin/bash" if os.path.exists("/data/data/com.termux/files/usr/bin/bash") else (shutil.which("bash") or "/bin/sh")
        proc = await asyncio.create_subprocess_shell(
            cmd_to_run,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable=bash_exec,
            env=shell_env,  # None => inherit parent env (first call / no persisted state yet)
        )

        stdout_chunks = []
        stderr_chunks = []

        async def read_stream(stream, chunks):
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                chunks.append(line)
                if live_feed:
                    print(line, end="", flush=True)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, stdout_chunks),
                    read_stream(proc.stderr, stderr_chunks),
                ),
                timeout=timeout
            )
            exit_code = await proc.wait()
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return -1, "[TIMEOUT] Process killed after timeout limit.", cwd, None

        full_out = "".join(stdout_chunks)
        full_err = "".join(stderr_chunks)

        # Parse CWD + persisted env from stdout: expected tail shape is
        # ...command output... \n <cwd> \n __NEWAGENT_ENV_MARKER__ \n <env dump>
        new_cwd = cwd
        new_env: Optional[dict] = None
        stdout_lines = full_out.splitlines()
        if exit_code == 0 and stdout_lines:
            marker_idx = -1
            for i, line in enumerate(stdout_lines):
                if line.strip() == _ENV_MARKER:
                    marker_idx = i
                    break
            if marker_idx > 0:
                cwd_candidate = stdout_lines[marker_idx - 1].strip()
                if os.path.isdir(cwd_candidate):
                    new_cwd = cwd_candidate
                parsed_env: dict = {}
                for line in stdout_lines[marker_idx + 1:]:
                    if "=" in line:
                        k, _, v = line.partition("=")
                        if k:
                            parsed_env[k] = v
                if parsed_env:
                    new_env = parsed_env
                full_out = "\n".join(stdout_lines[:marker_idx - 1])
                if full_out:
                    full_out += "\n"
            else:
                # Marker not found (e.g. command's own output ate it) — fall
                # back to the pre-env-dict behavior rather than mis-parsing.
                last_line = stdout_lines[-1].strip()
                if os.path.isdir(last_line):
                    new_cwd = last_line
                    full_out = "\n".join(stdout_lines[:-1])
                    if full_out:
                        full_out += "\n"

        output = full_out + full_err
        return exit_code, output, new_cwd, new_env
    except Exception as e:
        return -1, str(e), cwd, None

_CHECKLIST_STALE_SECONDS = 86400  # 24h -- auto-delete completed lists older than this

def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip()).strip("_").lower()
    return slug or "untitled"

def do_checklist_create(title: str, tasks_text: str, cwd: str) -> str:
    """Create a persistent, real checklist file in the current directory --
    not a text list the model has to remember, a BEJSON row per task that
    gets individually checked off and tracked. tasks_text: one task per
    line or semicolon-separated."""
    items = [t.strip() for t in re.split(r"[\n;]+", tasks_text) if t.strip()]
    if not items:
        return "[ERROR] checklist_create needs at least one task (newline or ; separated)."

    now = time.time()
    fname = f"checklist_{_slugify(title)}.bejson"
    fpath = Path(cwd) / fname
    doc = {
        "Format": "BEJSON", "Format_Version": "104", "Format_Creator": "Elton Boehnen",
        "Records_Type": ["ChecklistTask"],
        "Job_Title": title,
        "Created_Ts": now,
        "All_Done_Ts": None,
        "Fields": [
            {"name": "task_id", "type": "string"},
            {"name": "description", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "completed_ts", "type": "number"},
        ],
        "Values": [[str(i + 1), desc, "pending", None] for i, desc in enumerate(items)],
    }
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Failed to write {fname}."
    lines = [f"  [{i+1}] pending — {desc}" for i, desc in enumerate(items)]
    return f"Created {fname} — '{title}' ({len(items)} task(s)):\n" + "\n".join(lines)

def do_checklist_check(path: str, task_id: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] Checklist not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."

    fmap = bejson_core_get_field_map(doc)
    id_idx = fmap.get("task_id", 0)
    status_idx = fmap.get("status", 2)
    ts_idx = fmap.get("completed_ts", 3)

    found = False
    for row in doc.get("Values", []):
        if len(row) > id_idx and str(row[id_idx]) == str(task_id):
            row[status_idx] = "done"
            row[ts_idx] = time.time()
            found = True
            break
    if not found:
        return f"[ERROR] No task with id '{task_id}' in {path}."

    all_done = all(
        len(r) > status_idx and r[status_idx] == "done"
        for r in doc.get("Values", [])
    )
    doc["All_Done_Ts"] = time.time() if all_done else None

    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Failed to save {path}."
    suffix = " — all tasks complete." if all_done else ""
    return f"Task {task_id} checked off in {path}.{suffix}"

def do_checklist_add(path: str, description: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] Checklist not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    if not description.strip():
        return "[ERROR] checklist_add needs a non-empty task description."

    rows = doc.get("Values", [])
    next_id = str(len(rows) + 1)
    rows.append([next_id, description.strip(), "pending", None])
    doc["Values"] = rows
    # A list that was fully done is no longer complete once a task is added --
    # otherwise it could get auto-deleted as "stale" while still having a
    # pending task sitting in it.
    doc["All_Done_Ts"] = None

    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Failed to save {path}."
    return f"Added task {next_id} to {path}: {description.strip()}"

def do_checklist_view(path: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] Checklist not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."

    fmap = bejson_core_get_field_map(doc)
    id_idx = fmap.get("task_id", 0)
    desc_idx = fmap.get("description", 1)
    status_idx = fmap.get("status", 2)

    lines = [f"{path} — '{doc.get('Job_Title', '?')}':"]
    for row in doc.get("Values", []):
        marker = "x" if len(row) > status_idx and row[status_idx] == "done" else " "
        tid = row[id_idx] if len(row) > id_idx else "?"
        desc = row[desc_idx] if len(row) > desc_idx else "?"
        lines.append(f"  [{marker}] {tid}. {desc}")
    if doc.get("All_Done_Ts"):
        lines.append("(All tasks complete.)")
    return "\n".join(lines)

def cleanup_stale_checklists(cwd: str) -> list[str]:
    """Scan the current directory (non-recursive -- 'as we navigate', not a
    full filesystem sweep) for checklist_*.bejson files that are fully
    complete AND older than 24h since completion, and delete them. Called
    from run_action_queue right after cwd actually changes."""
    deleted = []
    try:
        cwd_path = Path(cwd)
        if not cwd_path.is_dir():
            return deleted
        now = time.time()
        for fpath in cwd_path.glob("checklist_*.bejson"):
            try:
                doc = bejson_core_load_file(str(fpath))
                if not isinstance(doc, dict):
                    continue
                all_done_ts = doc.get("All_Done_Ts")
                if all_done_ts and (now - all_done_ts) > _CHECKLIST_STALE_SECONDS:
                    fpath.unlink()
                    deleted.append(str(fpath))
            except Exception:
                continue  # a single unreadable/malformed checklist shouldn't block navigation
    except Exception:
        pass
    return deleted

_HTML_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: 'Inter', Arial, sans-serif; background: #FFFFFF; color: #000000;
         max-width: 860px; margin: 0 auto; padding: 40px 24px; line-height: 1.6; }}
  h1 {{ color: #DE2626; border-bottom: 3px solid #DE2626; padding-bottom: 12px; }}
  h2 {{ color: #000000; border-left: 4px solid #DE2626; padding-left: 12px; margin-top: 32px; }}
  code, pre {{ font-family: 'Source Code Pro', 'Courier New', monospace; background: #f5f5f5; padding: 2px 6px; }}
  .report-meta {{ color: #555555; font-size: 0.85rem; margin-bottom: 24px; }}
  .report-body {{ white-space: pre-wrap; }}
  footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #dddddd;
            font-size: 0.8rem; color: #888888; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="report-meta">Generated {timestamp} — Elton Boehnen</div>
<div class="report-body" id="report-content">{content}</div>
<footer>Elton Boehnen — NewAgent</footer>
</body>
</html>
"""

def do_html_report_create(title: str, content: str, cwd: str) -> str:
    """Fill-in report template: give it a title and content, it produces a
    complete, on-brand (white/black/red, Inter/Source Code Pro) standalone
    HTML file. For a plain quick report, not a replacement for the docx/pptx
    skills when Elton actually wants a Word doc or slide deck."""
    if not title.strip():
        return "[ERROR] html_report needs a non-empty title."
    fname = f"report_{_slugify(title)}.html"
    fpath = Path(cwd) / fname
    rendered_html = _HTML_REPORT_TEMPLATE.format(
        title=html.escape(title),
        timestamp=time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        content=html.escape(content),
    )
    try:
        fpath.write_text(rendered_html, encoding="utf-8")
    except OSError as e:
        return f"[ERROR] Failed to write {fname}: {e}"
    return f"Created {fname} ({len(content)} char(s) of content)."

def do_html_report_append(path: str, content: str, cwd: str) -> str:
    """Append a new section to an existing report created by html_report,
    rather than overwriting it or requiring a whole new file per addition."""
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] Report not found: {path}"
    try:
        existing_html = fpath.read_text(encoding="utf-8")
    except OSError as e:
        return f"[ERROR] Failed to read {path}: {e}"

    marker = '<div class="report-body" id="report-content">'
    idx = existing_html.find(marker)
    if idx == -1:
        return f"[ERROR] {path} doesn't look like an html_report file (missing report-content marker)."
    insert_at = idx + len(marker)
    addition = f"\n\n--- {time.strftime('%Y-%m-%d %H:%M', time.localtime())} ---\n" + html.escape(content)
    new_html = existing_html[:insert_at] + addition + existing_html[insert_at:]
    try:
        fpath.write_text(new_html, encoding="utf-8")
    except OSError as e:
        return f"[ERROR] Failed to save {path}: {e}"
    return f"Appended {len(content)} char(s) to {path}."

def do_project_log(version_label: str, notes: str, cwd: str) -> str:
    """Append a properly-formatted entry to .bejson_project.json -- the
    same manual pattern used to changelog every package this session,
    now a tool instead of hand-written JSON each time. Looks for
    .bejson_project.json starting at cwd and walking up to find the
    project root, matching how a person would expect 'the project
    tracker' to be found regardless of which subdirectory they're in."""
    if not version_label.strip() or not notes.strip():
        return "[ERROR] project_log needs both a version_label and notes."

    search_dir = Path(cwd).resolve()
    tracker_path = None
    for candidate in [search_dir] + list(search_dir.parents):
        p = candidate / ".bejson_project.json"
        if p.exists():
            tracker_path = p
            break
    if tracker_path is None:
        return "[ERROR] No .bejson_project.json found in this directory or any parent."

    doc = bejson_core_load_file(str(tracker_path))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {tracker_path} as BEJSON."

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc.setdefault("Values", []).append([version_label.strip(), ts, notes.strip()])
    if not bejson_core_atomic_write(str(tracker_path), doc):
        return f"[ERROR] Failed to save {tracker_path}."
    return f"Logged '{version_label.strip()}' to {tracker_path} ({len(doc['Values'])} total entries)."

def do_read_file(path: str, cwd: str) -> str:
    fpath = Path(cwd).joinpath(path).resolve()
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        return fpath.read_text("utf-8", errors="replace")[:100000]
    except Exception as e:
        return f"[ERROR] Failed to read: {e}"

def do_write_file(path: str, content: str, cwd: str) -> str:
    fpath = Path(cwd).joinpath(path).resolve()
    try:
        fpath.parent.mkdir(parents=True, exist_ok=True)
        if fpath.exists():
            old = fpath.read_text("utf-8", errors="replace")
            bid = record_backup(str(fpath), old, "write_file_overwrite")
            backup_msg = f" (backed up to {bid})"
        else:
            backup_msg = ""
        fpath.write_text(content, encoding="utf-8")
        return f"[SUCCESS] File written to {path}{backup_msg}"
    except Exception as e:
        return f"[ERROR] Failed to write: {e}"

def do_edit_file(path: str, old_text: str, new_text: str, cwd: str) -> str:
    fpath = Path(cwd).joinpath(path).resolve()
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        content = fpath.read_text("utf-8", errors="replace")
        matches = content.count(old_text)
        if matches == 0:
            return "[ERROR] old_text pattern not found in file."
        if matches > 1:
            return f"[ERROR] old_text pattern found multiple ({matches}) times. Refusing ambiguous edit."

        bid = record_backup(str(fpath), content, "edit_file")
        new_content = content.replace(old_text, new_text)
        fpath.write_text(new_content, encoding="utf-8")
        return f"[SUCCESS] File edited (backup: {bid})"
    except Exception as e:
        return f"[ERROR] Edit failed: {e}"

def do_list_dir(path: str, cwd: str) -> str:
    dpath = Path(cwd).joinpath(path).resolve()
    if not dpath.exists():
        return f"[ERROR] Directory not found: {path}"
    if not dpath.is_dir():
        return f"[ERROR] Path is not a directory: {path}"
    try:
        lines = []
        for entry in sorted(dpath.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            etype = "DIR" if entry.is_dir() else "FILE"
            esize = entry.stat().st_size if entry.is_file() else 0
            lines.append(f"  [{etype}] {entry.name} ({esize} bytes)")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"[ERROR] Failed to list directory: {e}"

def do_tree_view(path: str, cwd: str, depth: int = 3) -> str:
    dpath = Path(cwd).joinpath(path).resolve()
    if not dpath.exists():
        return f"[ERROR] Path not found: {path}"
    
    limit = 200
    count = 0
    lines = []

    def walk(curr: Path, prefix: str, current_depth: int):
        nonlocal count
        if count >= limit or current_depth > depth:
            return
        try:
            entries = sorted(curr.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except Exception:
            return
        
        for i, entry in enumerate(entries):
            count += 1
            if count >= limit:
                lines.append(f"{prefix}└── ... (limit hit)")
                return
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                walk(entry, prefix + ("    " if is_last else "│   "), current_depth + 1)

    lines.append(dpath.name + "/")
    walk(dpath, "", 1)
    return "\n".join(lines)

def do_make_dir(path: str, cwd: str) -> str:
    dpath = Path(cwd).joinpath(path).resolve()
    try:
        dpath.mkdir(parents=True, exist_ok=True)
        return f"[SUCCESS] Created directory: {path}"
    except Exception as e:
        return f"[ERROR] Failed to create: {e}"

def do_delete_file(path: str, cwd: str) -> str:
    fpath = Path(cwd).joinpath(path).resolve()
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    if fpath.is_dir():
        return "[ERROR] Refusing to delete directories via delete_file."
    try:
        old = fpath.read_text("utf-8", errors="replace")
        bid = record_backup(str(fpath), old, "delete_file")
        fpath.unlink()
        return f"[SUCCESS] Deleted file {path} (backed up: {bid})"
    except Exception as e:
        return f"[ERROR] Delete failed: {e}"

def do_copy_file(src: str, dst: str, cwd: str) -> str:
    src_path = Path(cwd).joinpath(src).resolve()
    dst_path = Path(cwd).joinpath(dst).resolve()
    if not src_path.exists():
        return f"[ERROR] Source not found: {src}"
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        backup_msg = ""
        if dst_path.exists():
            old = dst_path.read_text("utf-8", errors="replace")
            bid = record_backup(str(dst_path), old, "copy_overwrite")
            backup_msg = f" (dst backed up: {bid})"
        dst_path.write_bytes(src_path.read_bytes())
        return f"[SUCCESS] Copied {src} to {dst}{backup_msg}"
    except Exception as e:
        return f"[ERROR] Copy failed: {e}"

def do_diff_file(path: str, cwd: str) -> str:
    fpath = Path(cwd).joinpath(path).resolve()
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        backups = [b for b in list_backups() if b["file_path"] == str(fpath)]
        if not backups:
            return "[ERROR] No backup snapshots found for this file."
        # Read last backup content from backup_log Values indirectly
        from lib_bejson_newagent_backup import _read_log
        rows = _read_log()
        target = next((r for r in rows if r[0] == backups[-1]["backup_id"]), None)
        if not target:
            return "[ERROR] Failed to load last backup content."
        
        backup_content = target[2]
        current_content = fpath.read_text("utf-8", errors="replace")

        diff = difflib.unified_diff(
            backup_content.splitlines(),
            current_content.splitlines(),
            fromfile=f"backup:{backups[-1]['backup_id']}",
            tofile="current",
            lineterm="",
        )
        return "\n".join(diff) if diff else "(no difference)"
    except Exception as e:
        return f"[ERROR] Diff failed: {e}"

def do_restore_file(backup_id: str) -> str:
    ok, msg = restore_backup(backup_id)
    return f"[SUCCESS] {msg}" if ok else f"[ERROR] {msg}"

def do_http_get(url: str) -> str:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (NewAgent Terminal Client)"}
        )
        with urllib.request.urlopen(req, timeout=15) as res:
            data = res.read(65536)  # Cap at 64KB
            text = data.decode("utf-8", errors="replace")
            if len(data) == 65536:
                text += "\n... [truncated (64 KB cap hit)]"
            return text
    except Exception as e:
        return f"[ERROR] HTTP request failed: {e}"

def do_find_files(pattern: str, base: str = ".", cwd: str = ".") -> str:
    bpath = Path(cwd).joinpath(base).resolve()
    try:
        # Check if fd is installed
        subprocess.run(["fd", "--version"], capture_output=True, check=True)
        proc = "fd"
    except Exception:
        proc = "find"

    try:
        if proc == "fd":
            cmd = ["fd", "-H", pattern, str(bpath)]
        else:
            cmd = ["find", str(bpath), "-name", f"*{pattern}*"]
        
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return res.stdout.strip() if res.stdout else "No matches found."
    except Exception as e:
        return f"[ERROR] Find failed: {e}"

def do_search_text(pattern: str, path: str = ".", cwd: str = ".") -> str:
    spath = Path(cwd).joinpath(path).resolve()
    try:
        cmd = ["rg", "-n", pattern, str(spath)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return res.stdout.strip() if res.stdout else "No matches found."
    except FileNotFoundError:
        return "[ERROR] ripgrep (rg) tool is not installed."
    except Exception as e:
        return f"[ERROR] Search failed: {e}"

def do_fuzzy_find(query: str, cwd: str) -> str:
    try:
        # Headless fzf filter
        fd_proc = subprocess.Popen(["fd", "-H", "-t", "f", str(cwd)], stdout=subprocess.PIPE)
        fzf_proc = subprocess.Popen(
            ["fzf", "--filter", query],
            stdin=fd_proc.stdout,
            stdout=subprocess.PIPE,
            text=True,
        )
        out, _ = fzf_proc.communicate(timeout=15)
        return out.strip() if out else "No matches found."
    except Exception as e:
        return f"[ERROR] Fuzzy find failed: {e}"

def do_env_get(name: str) -> str:
    val = os.environ.get(name)
    return f"{name}={val}" if val is not None else f"{name}=[not set]"

def do_speak(text: str) -> tuple[bool, str]:
    """
    Returns (success, message). Previously this caught every exception into
    a single generic "[ERROR] TTS speak failed." with no diagnostic info at
    all -- every session log shows this same unhelpful line with no way to
    tell if termux-tts-speak is missing, denied, or just non-zero exit.
    """
    try:
        result = subprocess.run(
            ["termux-tts-speak", text], capture_output=True, timeout=10, text=True,
        )
        if result.returncode == 0:
            return True, "[SUCCESS] Spoken."
        detail = (result.stderr or result.stdout or "").strip()
        return False, f"[ERROR] TTS speak failed (exit {result.returncode}): {detail or '(no output)'}"
    except FileNotFoundError:
        return False, "[ERROR] TTS speak failed: 'termux-tts-speak' not found. Install termux-api (pkg install termux-api) and the Termux:API app."
    except subprocess.TimeoutExpired:
        return False, "[ERROR] TTS speak failed: timed out after 10s."
    except Exception as e:
        return False, f"[ERROR] TTS speak failed: {type(e).__name__}: {e}"

def do_checkpoint(label: str, backups_dir: Path) -> str:
    cp_path = backups_dir / "checkpoints.bejson"
    existing = []
    label_idx = 0
    if cp_path.exists():
        doc = bejson_core_load_file(str(cp_path))
        if isinstance(doc, dict):
            result = validate_bejson(doc, is_file=False)
            if not result.valid:
                import logging
                logging.getLogger(__name__).warning(
                    "[Checkpoint] %s failed structural validation: %s", cp_path, result.errors
                )
            fmap = bejson_core_get_field_map(doc)
            label_idx = fmap.get("label", 0)
            existing = doc.get("Values", [])

    live_bids = get_live_backup_ids()
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    # Append or overwrite named checkpoint
    existing = [r for r in existing if len(r) <= label_idx or r[label_idx] != label]
    existing.append([label, live_bids, created_at])

    doc = bejson_core_create_104a("Checkpoint", list(_CHECKPOINT_FIELDS), existing)
    if not bejson_core_atomic_write(str(cp_path), doc):
        return f"[ERROR] Atomic write failed for {cp_path}"
    return f"[SUCCESS] Checkpoint '{label}' saved with {len(live_bids)} backups."


# ── BEJSON Manipulation Tools ─────────────────────────────────────────────────
# Select/write/delete fields, create/remove records, set values by row+column
# index or row+field name. All name-based lookups go through
# bejson_core_get_field_map — the cache built into the format itself — rather
# than each call re-scanning Fields linearly.
#
# 104db multi-entity ownership rules (added 2026-07-23, previously scoped
# out — see docs/Changelogs.md pkg031 entry): mirrors the same hard rules
# lib_bejson_Core_bejson_validator.py enforces on load, so a bad write is
# rejected here immediately instead of only surfacing the next time the
# file is loaded/validated.
#   - do_bejson_add_field: on a 104db file, the field definition MUST include
#     a "Record_Type_Parent" naming one of the file's Records_Type entries —
#     rejected outright otherwise, rather than silently adding an
#     unassigned/invalid field the way this used to.
#   - do_bejson_delete_field: refuses to delete the "Record_Type_Parent"
#     field itself on a 104db file (index 0, structurally mandatory for the
#     whole file, not owned by any single entity).
#   - do_bejson_create_record / do_bejson_set_value: on a 104db file, a
#     Record_Type_Parent value (column 0) must be one of Records_Type —
#     rejected outright if not, matching the validator's own hard error.
#     Setting a value on a field owned by a DIFFERENT entity type than the
#     row declares isn't structurally invalid (the validator doesn't block
#     it either), so it's a warning, not a rejection.

def _bejson_104db_valid_field_def(doc: dict, field_def: dict) -> Optional[str]:
    """Returns an error string if field_def is invalid for a 104db file,
    else None. Not called at all for 104/104a."""
    rtp = field_def.get("Record_Type_Parent")
    if not rtp:
        return (
            "field definition for a 104db file must include "
            "\"Record_Type_Parent\": \"<one of the file's Records_Type entries>\" "
            f"(Records_Type here: {doc.get('Records_Type')})."
        )
    if rtp not in doc.get("Records_Type", []):
        return f"Record_Type_Parent '{rtp}' is not one of this file's Records_Type: {doc.get('Records_Type')}."
    return None


def _bejson_104db_valid_row_type_parent(doc: dict, value) -> Optional[str]:
    """Returns an error string if value isn't a valid Record_Type_Parent for
    a 104db file's column 0, else None. Not called at all for 104/104a."""
    if value not in doc.get("Records_Type", []):
        return f"Record_Type_Parent '{value}' is not one of this file's Records_Type: {doc.get('Records_Type')}."
    return None


def _bejson_104db_cross_entity_warning(doc: dict, row_type_parent, field_idx: int) -> str:
    """Returns a warning string (possibly empty) if field_idx is owned by a
    different entity type than row_type_parent declares. Not called at all
    for 104/104a."""
    fields = doc.get("Fields", [])
    if field_idx <= 0 or field_idx >= len(fields):
        return ""
    field_owner = fields[field_idx].get("Record_Type_Parent")
    if field_owner and field_owner != row_type_parent:
        return (
            f"\n[WARNING] Field '{fields[field_idx].get('name')}' belongs to "
            f"Record_Type_Parent '{field_owner}', but this row is declared "
            f"'{row_type_parent}' — structurally valid, but semantically "
            f"cross-entity. Confirm this is intentional."
        )
    return ""


def _bejson_resolve(path: str, cwd: str) -> Path:
    return Path(cwd).joinpath(path).resolve()

def do_bejson_fields(path: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    fields = doc.get("Fields", [])
    lines = [f"  {i}: {f.get('name')} ({f.get('type')})" for i, f in enumerate(fields)]
    return (
        f"{path} — {doc.get('Format_Version', '?')}, "
        f"{len(doc.get('Values', []))} record(s)\n" + "\n".join(lines) +
        "\n(Reminder: Fields order matches each Values row's order exactly — "
        "field index N above corresponds to Values[row][N] for every row.)"
    )

_BEJSON_COLUMNS_MAX_ROWS = 200  # hard cap per call, even for rows="" (all)

def do_bejson_columns(path: str, columns: str, cwd: str, rows: str = "") -> str:
    """Return ONLY the requested columns for the requested rows, resolved
    by field name via the field map -- never surfacing unrequested columns
    to the agent's context. This is the piece bejson_fields (schema-only)
    and read_file (everything-or-nothing raw dump) don't cover: selective
    DATA access. The file still has to be fully parsed into memory to read
    anything at all (no streaming BEJSON parser exists) -- what this
    controls is how much comes back into the context window, not how much
    gets read off disk.
    """
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."

    requested_cols = [c.strip() for c in columns.split(",") if c.strip()]
    if not requested_cols:
        return "[ERROR] bejson_columns needs a non-empty columns=\"name,other_name\" attribute."

    fmap = bejson_core_get_field_map(doc)
    unknown = [c for c in requested_cols if c not in fmap]
    if unknown:
        return f"[ERROR] Unknown column(s): {unknown}. Known fields: {list(fmap)}"

    all_rows = doc.get("Values", [])
    total_rows = len(all_rows)
    if total_rows == 0:
        return f"{path} — 0 record(s), nothing to project."

    if not rows:
        start, end = 0, total_rows - 1
    elif "-" in rows:
        try:
            start_s, end_s = rows.split("-", 1)
            start, end = int(start_s), int(end_s)
        except ValueError:
            return f"[ERROR] Invalid rows range '{rows}'. Use 'N', 'N-M', or omit for all rows."
    else:
        try:
            start = end = int(rows)
        except ValueError:
            return f"[ERROR] rows must be an integer or 'N-M' range, got '{rows}'."

    if start < 0 or end >= total_rows or start > end:
        return f"[ERROR] rows range {start}-{end} out of bounds (0-{total_rows - 1})."

    truncated = False
    if end - start + 1 > _BEJSON_COLUMNS_MAX_ROWS:
        end = start + _BEJSON_COLUMNS_MAX_ROWS - 1
        truncated = True

    col_indices = [fmap[c] for c in requested_cols]
    lines = [f"{path} — {len(requested_cols)} column(s) x {end - start + 1} row(s) (of {total_rows} total):"]
    for r_idx in range(start, end + 1):
        row = all_rows[r_idx]
        projected = {c: (row[idx] if idx < len(row) else None) for c, idx in zip(requested_cols, col_indices)}
        lines.append(f"  [{r_idx}] {projected}")

    if truncated:
        lines.append(f"(truncated at {_BEJSON_COLUMNS_MAX_ROWS} rows -- request a narrower rows=\"N-M\" range for the rest.)")

    return "\n".join(lines)

def do_bejson_add_field(path: str, field_json: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        field_def = json.loads(field_json)
    except json.JSONDecodeError as e:
        return f"[ERROR] field definition must be JSON like {{\"name\":\"x\",\"type\":\"string\"}}: {e}"
    if not isinstance(field_def, dict) or "name" not in field_def or "type" not in field_def:
        return "[ERROR] field definition needs at least \"name\" and \"type\"."

    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    fmap = bejson_core_get_field_map(doc)
    if field_def["name"] in fmap:
        return f"[ERROR] Field '{field_def['name']}' already exists at index {fmap[field_def['name']]}."

    if doc.get("Format_Version") == "104db":
        err = _bejson_104db_valid_field_def(doc, field_def)
        if err:
            return f"[ERROR] {err}"

    record_backup(str(fpath), json.dumps(doc), "bejson_add_field")
    doc["Fields"].append(field_def)
    for row in doc.get("Values", []):
        row.append(None)
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"
    return f"[SUCCESS] Added field '{field_def['name']}' to {path} (now {len(doc['Fields'])} fields, {len(doc.get('Values', []))} rows null-padded)."

def do_bejson_delete_field(path: str, field_name: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    fmap = bejson_core_get_field_map(doc)
    field_name = field_name.strip()
    if field_name not in fmap:
        return f"[ERROR] Field '{field_name}' not found. Known fields: {list(fmap)}"
    idx = fmap[field_name]

    if doc.get("Format_Version") == "104db" and idx == 0:
        return (
            "[ERROR] Cannot delete 'Record_Type_Parent' (index 0) from a 104db "
            "file — it's structurally mandatory for the whole file, not owned "
            "by any single entity type."
        )

    record_backup(str(fpath), json.dumps(doc), "bejson_delete_field")
    del doc["Fields"][idx]
    for row in doc.get("Values", []):
        if len(row) > idx:
            del row[idx]
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"
    return f"[SUCCESS] Deleted field '{field_name}' from {path} (was index {idx})."

def do_bejson_create_record(path: str, values_json: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        values = json.loads(values_json)
    except json.JSONDecodeError as e:
        return f"[ERROR] record values must be a JSON array like [\"a\", 1, true]: {e}"
    if not isinstance(values, list):
        return "[ERROR] record values must be a JSON array."

    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    expected = len(doc.get("Fields", []))
    if len(values) != expected:
        return f"[ERROR] Expected {expected} value(s) matching Fields, got {len(values)}."

    warning = ""
    if doc.get("Format_Version") == "104db":
        err = _bejson_104db_valid_row_type_parent(doc, values[0] if values else None)
        if err:
            return f"[ERROR] {err}"
        for i, val in enumerate(values):
            if val is not None:
                warning += _bejson_104db_cross_entity_warning(doc, values[0], i)

    record_backup(str(fpath), json.dumps(doc), "bejson_create_record")
    doc["Values"].append(values)
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"
    return f"[SUCCESS] Added record at row {len(doc['Values']) - 1} in {path} ({len(doc['Values'])} rows total).{warning}"

def do_bejson_delete_record(path: str, row: str, cwd: str) -> str:
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        row_idx = int(row)
    except ValueError:
        return f"[ERROR] row must be an integer, got '{row}'."

    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    rows = doc.get("Values", [])
    if row_idx < 0 or row_idx >= len(rows):
        return f"[ERROR] row {row_idx} out of range (0-{len(rows) - 1})."

    record_backup(str(fpath), json.dumps(doc), "bejson_delete_record")
    del rows[row_idx]
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"
    return f"[SUCCESS] Deleted row {row_idx} from {path} ({len(rows)} rows remain)."

def do_bejson_set_value(
    path: str, row: str, value: str, cwd: str,
    field: Optional[str] = None, col: Optional[str] = None,
) -> str:
    if not field and col is None:
        return "[ERROR] set_value needs either field=\"name\" or col=\"index\"."
    fpath = _bejson_resolve(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        row_idx = int(row)
    except ValueError:
        return f"[ERROR] row must be an integer, got '{row}'."

    doc = bejson_core_load_file(str(fpath))
    if not isinstance(doc, dict):
        return f"[ERROR] Could not load {path} as BEJSON."
    rows = doc.get("Values", [])
    if row_idx < 0 or row_idx >= len(rows):
        return f"[ERROR] row {row_idx} out of range (0-{len(rows) - 1})."

    if field:
        fmap = bejson_core_get_field_map(doc)
        if field not in fmap:
            return f"[ERROR] Field '{field}' not found. Known fields: {list(fmap)}"
        col_idx = fmap[field]
    else:
        try:
            col_idx = int(col)
        except ValueError:
            return f"[ERROR] col must be an integer, got '{col}'."
    if col_idx < 0 or col_idx >= len(doc.get("Fields", [])):
        return f"[ERROR] column {col_idx} out of range."

    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value  # plain string that isn't valid JSON on its own

    warning = ""
    if doc.get("Format_Version") == "104db":
        if col_idx == 0:
            err = _bejson_104db_valid_row_type_parent(doc, parsed_value)
            if err:
                return f"[ERROR] {err}"
        elif parsed_value is not None:
            row_type_parent = rows[row_idx][0] if rows[row_idx] else None
            warning = _bejson_104db_cross_entity_warning(doc, row_type_parent, col_idx)

    record_backup(str(fpath), json.dumps(doc), "bejson_set_value")
    rows[row_idx][col_idx] = parsed_value
    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"
    field_label = field or f"col {col_idx}"
    return f"[SUCCESS] Set {path} row {row_idx}, {field_label} = {parsed_value!r}.{warning}"


# ── Action XML Tag Parsing & Processing (REST mode) ──────────────────────────

def parse_actions(text: str) -> list[dict]:
    actions = []
    for match in ACTION_PATTERN.finditer(text):
        tag = match.group(1) or match.group(4)
        attrs_raw = match.group(2) or match.group(5) or ""
        content = (match.group(3) or "").strip()
        # BUGFIX 2026-07-23: the model occasionally second-guesses its own
        # tag syntax and HTML-entity-escapes angle brackets inside exec
        # content (e.g. writes &lt;&lt;&lt; instead of <<<), producing a
        # literal "&lt;&lt;&lt;" string that then fails as a bash syntax
        # error rather than working as a here-string redirect. Confirmed
        # against logs/session_2026-07-24_10-27-41.md, 10:28:49 -- unescape
        # here so every action type (exec, write_file, etc.) gets the
        # content the model meant, not what it accidentally over-escaped.
        content = html.unescape(content)

        attrs = {}
        for attr_match in re.finditer(r'([a-zA-Z_]+)="([^"]*)"', attrs_raw):
            attrs[attr_match.group(1)] = html.unescape(attr_match.group(2))

        actions.append({"tag": tag, "attrs": attrs, "content": content})
    return actions

async def run_action_queue(
    actions: list[dict],
    ctx: dict,
) -> list[ExecResult]:
    """Execute queue of actions. Halts on first failure."""
    results = []
    cwd = ctx["_cwd"]
    config = ctx["config"]

    for act in actions[:config.get("max_actions_per_turn", 10)]:
        tag = act["tag"]
        attrs = act["attrs"]
        content = act["content"]

        exec_res = ExecResult(action_type=tag, source="", output="")

        # Safety gate confirmation
        if config.get("confirmation_gate") and tag in ("exec", "delete_file"):
            print(f"\n{C.RED_B}[CONFIRMATION NEEDED]{C.RESET} Action: {tag}")
            print(f"Content: {content or attrs}")
            ans = input("Proceed? [Y/n]: ").strip().lower()
            if ans not in ("", "y", "yes"):
                exec_res.exit_code = -2
                exec_res.output = "Aborted by user confirmation gate."
                results.append(exec_res)
                break

        # Pre-action Hook Execution
        hooks_cfg_path = config.get("hooks_config_path", "config/hooks.bejson")
        hook_ok, hook_msg = await run_action_hook(tag, "pre", cwd, hooks_cfg_path, ctx.get("_shell_env"))
        if not hook_ok:
            exec_res.exit_code = -1
            exec_res.output = hook_msg
            results.append(exec_res)
            break

        if tag == "exec":
            exec_res.source = content
            if config.get("dryrun_mode"):
                exec_res.output = f"[DRYRUN] Would exec: {content}"
            else:
                code, out, new_cwd, new_env = await do_exec(
                    content, cwd,
                    timeout=config.get("exec_timeout_seconds", 60),
                    live_feed=config.get("live_feed_output", False),
                    shell_env=ctx.get("_shell_env"),
                )
                exec_res.exit_code = code
                exec_res.output = out
                if new_cwd != cwd:
                    cleanup_stale_checklists(new_cwd)  # "as we navigate" -- only on an actual cwd change
                ctx["_cwd"] = new_cwd
                cwd = new_cwd
                if new_env is not None:
                    ctx["_shell_env"] = new_env

        elif tag == "read_file":
            exec_res.source = content
            exec_res.output = do_read_file(content, cwd)

        elif tag == "write_file":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_write_file(path, content, cwd)

        elif tag == "edit_file":
            path = attrs.get("path", "")
            exec_res.source = path
            old_m = re.search(r"<old>(.*?)</old>", content, re.DOTALL)
            new_m = re.search(r"<new>(.*?)</new>", content, re.DOTALL)
            if old_m and new_m:
                exec_res.output = do_edit_file(path, old_m.group(1), new_m.group(1), cwd)
            else:
                exec_res.exit_code = -1
                exec_res.output = "[ERROR] Invalid edit_file XML shape. Needs <old> and <new> blocks."

        elif tag == "list_dir":
            exec_res.source = content
            exec_res.output = do_list_dir(content, cwd)

        elif tag == "tree_view":
            exec_res.source = content
            d = int(attrs.get("depth", 3))
            exec_res.output = do_tree_view(content, cwd, depth=d)

        elif tag == "make_dir":
            exec_res.source = content
            exec_res.output = do_make_dir(content, cwd)

        elif tag == "delete_file":
            exec_res.source = content
            exec_res.output = do_delete_file(content, cwd)

        elif tag == "copy_file":
            src = attrs.get("src", "")
            dst = attrs.get("dst", "")
            exec_res.source = f"{src} -> {dst}"
            exec_res.output = do_copy_file(src, dst, cwd)

        elif tag == "diff_file":
            exec_res.source = content
            exec_res.output = do_diff_file(content, cwd)

        elif tag == "restore_file":
            exec_res.source = content
            exec_res.output = do_restore_file(content)

        elif tag == "http_get":
            exec_res.source = content
            exec_res.output = do_http_get(content)

        elif tag == "find_files":
            exec_res.source = content
            exec_res.output = do_find_files(content, cwd=cwd)

        elif tag == "search_text":
            exec_res.source = content
            exec_res.output = do_search_text(content, cwd=cwd)

        elif tag == "fuzzy_find":
            exec_res.source = content
            exec_res.output = do_fuzzy_find(content, cwd)

        elif tag == "env_get":
            exec_res.source = content
            exec_res.output = do_env_get(content)

        elif tag == "speak":
            exec_res.source = content
            speak_ok, speak_msg = do_speak(content)
            exec_res.output = speak_msg
            exec_res.exit_code = 0 if speak_ok else 1

        elif tag == "checkpoint":
            exec_res.source = content
            exec_res.output = do_checkpoint(content, ctx["_backups_dir"])

        elif tag == "checklist_create":
            title = attrs.get("title", "")
            exec_res.source = title
            exec_res.output = do_checklist_create(title, content, cwd)

        elif tag == "checklist_check":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_checklist_check(path, attrs.get("task_id", ""), cwd)

        elif tag == "checklist_add":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_checklist_add(path, content, cwd)

        elif tag == "checklist_view":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_checklist_view(path, cwd)

        elif tag == "html_report":
            title = attrs.get("title", "")
            exec_res.source = title
            exec_res.output = do_html_report_create(title, content, cwd)

        elif tag == "html_report_append":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_html_report_append(path, content, cwd)

        elif tag == "project_log":
            version_label = attrs.get("version", "")
            exec_res.source = version_label
            exec_res.output = do_project_log(version_label, content, cwd)

        elif tag == "bejson_fields":
            exec_res.source = content
            exec_res.output = do_bejson_fields(content, cwd)

        elif tag == "bejson_add_field":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_add_field(path, content, cwd)

        elif tag == "bejson_delete_field":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_delete_field(path, content, cwd)

        elif tag == "bejson_create_record":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_create_record(path, content, cwd)

        elif tag == "bejson_delete_record":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_delete_record(path, attrs.get("row", ""), cwd)

        elif tag == "bejson_set_value":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_set_value(
                path, attrs.get("row", ""), content, cwd,
                field=attrs.get("field"), col=attrs.get("col"),
            )

        elif tag == "bejson_columns":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_columns(
                path, attrs.get("columns", ""), cwd, rows=attrs.get("rows", ""),
            )

        elif tag == "request_continue":
            exec_res.source = content
            exec_res.output = "[SUCCESS] Continue request registered."
            ctx["_continue_requested"] = True

        elif tag == "exec_bg":
            exec_res.source = content
            task_id = _GLOBAL_TASK_MANAGER.spawn_task(content, cwd, shell_env=ctx.get("_shell_env"))
            exec_res.output = f"[SUCCESS] Background task spawned with ID: {task_id}"

        elif tag == "task_status":
            exec_res.source = content
            exec_res.output = _GLOBAL_TASK_MANAGER.get_status(content.strip())

        elif tag == "task_kill":
            exec_res.source = content
            exec_res.output = _GLOBAL_TASK_MANAGER.kill_task(content.strip())

        elif tag == "task_list":
            exec_res.source = "list"
            exec_res.output = _GLOBAL_TASK_MANAGER.list_tasks()

        elif tag == "job_task_done":
            task_id = attrs.get("id", "")
            exec_res.source = task_id
            job_path = ctx.get("_active_job_path")
            jobs_dir = ctx.get("_jobs_dir")
            if not job_path or not jobs_dir:
                exec_res.exit_code = -1
                exec_res.output = "[ERROR] No active job -- the user must explicitly start a job first."
            else:
                ok, msg = jobs.mark_task_completed(jobs_dir, Path(job_path).name, task_id)
                exec_res.exit_code = 0 if ok else -1
                exec_res.output = msg
                if ok and "moved to jobs/complete" in msg:
                    ctx["_active_job_path"] = None
                    ctx["_active_job_doc"] = None

        ctx["stats"].execs += 1
        results.append(exec_res)

        # Post-action Hook Execution (only run if action succeeded)
        if exec_res.exit_code == 0:
            post_ok, post_msg = await run_action_hook(tag, "post", cwd, hooks_cfg_path, ctx.get("_shell_env"))
            if post_msg:
                exec_res.output = (exec_res.output + "\n" + post_msg).strip()
            if not post_ok:
                exec_res.exit_code = -1
                break

        # Halt queue on error
        if exec_res.exit_code != 0:
            break

    return results

def assemble_results_payload(results: list[ExecResult]) -> str:
    """Build response XML payload with exec results for REST turn."""
    parts = []
    for r in results:
        parts.append(
            f"<{r.action_type}_result>\n"
            f"source: {r.source}\n"
            f"exit_code: {r.exit_code}\n"
            f"{r.output}\n"
            f"</{r.action_type}_result>"
        )
    return "\n\n".join(parts)

# ── Rollback Checkpoint Helper ────────────────────────────────────────────────

def rollback_checkpoint(label: str, backups_dir: Path) -> tuple[bool, str]:
    cp_path = backups_dir / "checkpoints.bejson"
    if not cp_path.exists():
        return False, "No checkpoints saved."
    try:
        doc = bejson_core_load_file(str(cp_path))
        if not isinstance(doc, dict):
            return False, f"Checkpoint file unreadable: {cp_path}"
        fmap = bejson_core_get_field_map(doc)
        label_idx = fmap.get("label", 0)
        bids_idx = fmap.get("backup_ids", 1)
        rows = doc.get("Values", [])
        target = next((r for r in rows if r[label_idx] == label), None)
        if not target:
            return False, f"Checkpoint '{label}' not found."

        bids = target[bids_idx]
        success_count = 0
        errors = []
        for bid in reversed(bids):
            ok, msg = restore_backup(bid, skip_snapshot=True)
            if ok:
                success_count += 1
            else:
                errors.append(msg)
        
        if errors:
            return False, f"Rollback partially succeeded. Restored {success_count}/{len(bids)}. Errors: {'; '.join(errors)}"
        return True, f"Rollback succeeded. Restored {success_count} files."
    except Exception as e:
        return False, str(e)


# ── System Prompt Builder ─────────────────────────────────────────────────────

def build_system_prompt(cwd: str, bubble: str = "", active_job: str = "") -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        cwd=cwd,
        bubble=bubble or "(none)",
        active_job_section=f"\n{active_job}\n" if active_job else "",
    )

# NOTE: The local _atomic_write(path, data) json.dump helper that used to live
# here was removed 2026-07-16 — its only caller (checklist_update) now goes
# through bejson_core_atomic_write for validation-aware atomic writes. See
# Docs/Changelogs.md.
