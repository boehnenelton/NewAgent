"""
Library:        lib_bejson_newagent_actions.py
Family:         NewAgent
Description:    Model action execution tools, XML tag parser, action queue dispatcher, and TaskManager.
Version:        2.9.0
Date:           2026-10-16
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  b5fde8ef-fe2b-429a-9c17-ab7935b55656

CHANGELOG:
- 2.9.0 (2026-10-16): Added actions_signature() and is_announcement_only() for the agent loop's
  auto-continue guard (pkg128). No change to parse_actions()/run_action_queue() behaviour.
- 2.8.0 (2026-10-16): Added fallback parser in parse_actions() for OpenRouter models
  (e.g. nvidia/nemotron-3-super-120b-a12b:free) whose post-training forces native
  tool-call tokens (<|tool_call_start|>[tag(...)]<|tool_call_end|>, <tool_call>...</tool_call>,
  or line-level [tag(...)]) instead of raw XML tags. Supports both quoted Pythonic
  positional/keyword arguments and unquoted shell/text payloads.
- 2.7.0 (2026-10-14): Fixed undefined C (confirmation gate) and list_backups (diff_file); exec keeps stdout with no trailing newline and applies the output cap after cwd/env parsing; http_get restricted to http/https; fd probed once per process.
- 2.6.0 (2026-10-14): Added _resolve_user_path() (~ expansion for all file action tags) and exec output cap (_cap_exec_text, output_cap param).
- 2.5.0 (2026-10-01): CRITICAL field bug, caught from Elton's own uploaded
  session logs (session_2026-09-30_19-06-34.*) after a `search_text
  bookwriter` call returned 1,954,412 bytes. do_search_text() shelled out
  to ripgrep with NO output cap and NO exclusions at all -- the match
  recursed into logs/ (archived session transcripts, themselves full of
  nested escaped JSON from prior sessions), exploding a single common
  word into ~2MB that got fed straight into the next turn's context AND
  persisted into the session's own logs, which is why the uploaded log
  files were themselves ~2MB after only 2 turns. Added -g exclusions for
  logs/, backups/, .git/, __pycache__/, node_modules/, plus a 64KB output
  cap (new _cap_subprocess_output(), matching the cap do_http_get and
  do_read_file already had -- do_search_text/do_find_files/do_fuzzy_find
  were the only three subprocess-backed actions missing one). Found and
  fixed a SECOND bug verifying the first: the -g exclusion globs didn't
  actually work -- ripgrep anchors a relative glob ("logs/**") to the
  search-root ARGUMENT's own relative structure, and the code passed an
  absolute resolved path with no cwd= set, so the glob never anchored to
  anything. Confirmed directly: `rg -g '!logs/**' pat /abs/path` still
  matches inside /abs/path/logs/, while running with cwd=/abs/path and
  searching "." correctly excludes it. Fixed by setting cwd= to the
  search root (or its parent, when path names a single file) and
  searching a relative target. do_find_files and do_fuzzy_find also
  capped for consistency (same missing-cap class of bug, lower blast
  radius). (Note: this file's own header Version/changelog had drifted
  behind the live VERSION constant, which was already at 2.4.0 with no
  corresponding changelog entry here -- realigned going forward; did not
  guess at or backfill what that untracked 2.3.1->2.4.0 change was.)
  Verified: real ripgrep installed and run (not mocked) against a
  reproduction of the field scenario (huge file under logs/ + a real
  source-file match) -- logs/ correctly excluded, real match returned,
  cap applies to oversized legitimate matches too; py_compile clean.
- 2.3.1 (2026-08-20): tools/init/Cli_Init.py renamed to CLI_Init.py, per
  Elton's tools/ naming pass -- updated the context_set tag's example
  reference in the system-prompt text to match. No functional change.
- 2.3.0 (2026-08-17): INIT -- Issue 4/5 of Elton's request. Added
  context_set action tag / do_context_set() -- thin wrapper around
  lib_bejson_newagent_context_bubble.upsert_cwd_context_section(). Whenever
  Elton hands the model a project's purpose or ground rules, it calls
  <context_set section="Purpose">...</context_set> right then instead of
  composing bejson_create_record/bejson_set_value itself (which risks
  duplicating a row if it doesn't already know whether one exists) or
  shell-invoking tools/NA-Init/CLI_Init.py via exec (quoting risk on
  multi-sentence content). ACTION_PATTERN regex, system-prompt tag docs,
  and the dispatcher all updated. Context/Persistent_Policy.md (always
  injected) updated with the instruction to actually use it. Verified:
  idempotent re-run replaces in place rather than duplicating, empty
  section rejected, regex/parse_actions round-trip confirmed.
- 2.2.0 (2026-08-16): CLI_Schema_Distribution (Elton's Option 3). Added
  bejson_create action tag / do_bejson_create() -- creates a brand-new
  BEJSON 104/104a/104db file from a Fields spec, enforcing the canonical
  type vocabulary (string/integer/number/boolean/array/object, lowercase;
  104a additionally forbids array/object; 104db additionally requires a
  Record_Type_Parent first field + per-field Record_Type_Parent) BEFORE
  ever writing to disk, with an error naming the exact problem. Closes the
  gap Elton flagged (task lists occasionally shipping a "Number" type
  string instead of "number") at its source: every other bejson_* tag
  requires the file to already exist, so a brand-new file previously had
  to go through write_file with the whole Fields array hand-typed from
  memory -- the one place nothing checked the type vocabulary before it
  hit disk. ACTION_PATTERN regex, system-prompt tag docs, and the
  run_action_queue dispatcher all updated; knowledge_pool.bejson's
  bejson_core_8 entry (always-active BEJSON tool reference) updated to
  list bejson_create first and say to prefer it over write_file for new
  BEJSON files. Verified with 6 targeted tests including the literal
  reported bug string, plus a regex/parse_actions check.
- 2.1.0 (2026-08-08): Added the Job Creation System's job_task_done
  action tag (self-closing, dispatched via lib_bejson_newagent_jobs), and an
  active_job param on build_system_prompt() that injects the running job's
  goal + incomplete tasks (via jobs.build_job_context_block) into the system
  prompt only when a job has actually been started (empty otherwise, so
  nothing changes for sessions with no active job).
"""

import ast
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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Callable
from lib_bejson_newagent_tui import ExecResult
from lib_bejson_newagent_backup import record_backup, restore_backup, get_live_backup_ids
from lib_bejson_Core_bejson_core import (
    bejson_core_create_104a,
    bejson_core_create_104,
    bejson_core_create_104db,
    bejson_core_atomic_write,
    bejson_core_load_file,
    bejson_core_get_field_map,
)
from lib_bejson_Core_bejson_validator import validate_bejson, VALID_VERSIONS
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_jobs as jobs

_CHECKPOINT_FIELDS = [
    {"name": "label", "type": "string"},
    {"name": "backup_ids", "type": "array"},
    {"name": "created_at", "type": "string"},
]

VERSION = "2.9.0"
_SYSTEM_PROMPT_TEMPLATE = """You are a highly capable terminal agent running on Termux/Android.
You have access to files, shell execution, search tools, and memory.

CWD: {cwd}

CRITICAL RULES:
1. Always test your code edits by executing relevant test suites immediately.
2. Maintain separate single-concern files to keep bloat down.
3. Credit Elton Boehnen (boehnenelton2024@gmail.com) in all files you modify or output.
4. In REST mode, emit your actions inside XML tags. You can chain up to 10 actions per turn.
   Do NOT use <|tool_call_start|>, <tool_call>, or [tag(...)] function-call syntax; emit raw XML tags directly.
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
     <bejson_create path="..." version="104a" records_type="MyRecord">[{{"name":"id","type":"string"}},{{"name":"count","type":"integer"}}]</bejson_create>
     <bejson_create path="..." version="104db" record_types="TypeA,TypeB">[{{"name":"Record_Type_Parent","type":"string"}}, ...]</bejson_create>
       (creates a NEW BEJSON file with a schema you specify -- rejects an
        invalid field type (must be exactly string/integer/number/boolean/
        array/object, lowercase; 104a forbids array/object) before ever
        writing anything, with an error naming the exact problem, instead
        of silently producing a file with a wrong type string. File must
        not already exist -- use bejson_add_field etc. to modify one that
        does. Prefer this over write_file for any brand-new BEJSON file.)
     <bejson_fields>path/to/file.bejson</bejson_fields>
     <context_set section="Purpose">This project is a Flask media toolkit for Android.</context_set>
       (upserts a section into THIS directory's context.bejson -- auto-
        injected into every future turn here with no keyword needed. Call
        this whenever the user hands you a project's purpose, main rules,
        or other standing context worth surviving beyond this
        conversation. Setting the same section again replaces it, so this
        is also how you correct it later.)
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
    r"bejson_delete_record|bejson_set_value|bejson_columns|bejson_create|context_set|"
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
        act_idx = fmap["action_type"]
        evt_idx = fmap["event"]
        cmd_idx = fmap["command"]
        ena_idx = fmap["enabled"]

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


_CWD_MARKER = "__NEWAGENT_CWD_MARKER__"
_ENV_MARKER = "__NEWAGENT_ENV_MARKER__"


def is_command_denylisted(command: str, denylist: Optional[list[str]]) -> Optional[str]:
    """Returns the matched denylist entry if `command` should be blocked,
    else None. Checks whether any denylisted token appears ANYWHERE in the
    command string, not just at the start.

    FIX (2026-08-25, audit F-03): the previous check --
    `cmd.strip().startswith(blocked)` -- only ever caught a denylisted
    command as the very first thing typed. Every one of these trivially
    passed it: `echo hello && rm -rf /`, `bash -c "rm -rf /"`,
    `cd / && rm -rf .` -- each starts with something else (`echo`, `bash`,
    `cd`), so the blocked payload riding along after `&&`/`;`/inside a
    `bash -c` string was never inspected at all.

    This is a substring-anywhere check instead, which closes that
    specific bypass class. It is NOT a claim that arbitrary shell input
    can be made fully safe by any denylist -- shell composition (command
    substitution, quoting, encoding, aliases) can obscure a payload in
    ways no static string match will catch. Real safety here comes from
    F-02's fix (this endpoint requiring authentication and defaulting to
    loopback-only instead of being reachable from any device on the
    network) -- this check is a second layer, not the primary defense.
    """
    if not denylist or not command:
        return None
    normalized = command.strip()
    for blocked in denylist:
        if blocked and blocked in normalized:
            return blocked
    return None


async def do_exec(
    command: str,
    cwd: str,
    timeout: int = 60,
    live_feed: bool = False,
    shell_env: Optional[dict] = None,
    denylist: Optional[list[str]] = None,
    output_cap: Optional[int] = None,
) -> tuple[int, str, str, Optional[dict]]:
    """Execute shell command asynchronously with optional streaming, CWD
    tracking, and a Global Environment Dictionary (audit Part 1/II — chosen
    over a full PTY session as the lighter option).

    denylist (2026-08-25, audit F-02/F-03): checked here, in the one
    execution primitive both call paths share (agent.py's tool-call path
    via engine_interactions.py's _execute_tool, AND webagent.py's
    /api/exec HTTP route, which used to call this function directly with
    no denylist check at all). See is_command_denylisted()'s docstring
    for exactly what changed and what this check does and does not
    guarantee.

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
    blocked_on = is_command_denylisted(command, denylist)
    if blocked_on:
        return 1, f"[BLOCKED] Command matches denylist: {blocked_on}", cwd, None

    cmd_to_run = (
        f"cd {shlex.quote(cwd)} && {command} && "
        f"printf '\\n%s\\n' '{_CWD_MARKER}' && pwd && "
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
        # 2026-10-13 audit P1-9: exec was the one uncapped output path. Cap it
        # like the search actions (exec_output_cap_bytes; 0 disables). The cap
        # is applied AFTER the cwd/env tail is parsed off (below) -- capping
        # first could cut the markers off and lose cwd/env tracking.

        # Parse CWD + persisted env from stdout: expected tail shape is
        # ...command output... \n <cwd> \n __NEWAGENT_ENV_MARKER__ \n <env dump>
        new_cwd = cwd
        new_env: Optional[dict] = None
        sentinel = "\n" + _CWD_MARKER + "\n"
        sentinel_idx = full_out.rfind(sentinel) if exit_code == 0 else -1
        if sentinel_idx >= 0:
            # Exact split: the command's own stdout is everything before the
            # sentinel, byte-for-byte -- including output with no trailing
            # newline (previously swallowed: `printf hi` returned '').
            body = full_out[:sentinel_idx]
            tail_lines = full_out[sentinel_idx + len(sentinel):].splitlines()
            if tail_lines and os.path.isdir(tail_lines[0].strip()):
                new_cwd = tail_lines[0].strip()
            parsed_env: dict = {}
            seen_marker = False
            for line in tail_lines[1:]:
                if not seen_marker:
                    seen_marker = line.strip() == _ENV_MARKER
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k:
                        parsed_env[k] = v
            if parsed_env:
                new_env = parsed_env
            full_out = body + ("\n" if body and not body.endswith("\n") else "")
            stdout_lines = []
        else:
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

        full_out = _cap_exec_text(full_out, output_cap)
        full_err = _cap_exec_text(full_err, output_cap)
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
    id_idx = fmap["task_id"]
    status_idx = fmap["status"]
    ts_idx = fmap["completed_ts"]

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
    id_idx = fmap["task_id"]
    desc_idx = fmap["description"]
    status_idx = fmap["status"]

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

def _resolve_user_path(path: str, cwd: str) -> Path:
    """Resolve a file-tag path against cwd with the same ~ semantics the shell
    uses (2026-10-13 audit P1-6: read_file '~/.gemini/GEMINI.md' reported 'File
    not found' while `exec cat` on the same path worked). Absolute and ~ paths
    ignore cwd; relative paths join to it."""
    return Path(cwd).joinpath(os.path.expanduser(str(path))).resolve()


def _config_int(value) -> Optional[int]:
    """config.json stores some numerics as strings; None => caller default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cap_exec_text(text: str, cap: Optional[int]) -> str:
    """Truncate exec output to cap bytes (default SUBPROCESS_OUTPUT_CAP_BYTES;
    cap <= 0 disables). Appends a notice so the model knows to narrow."""
    limit = SUBPROCESS_OUTPUT_CAP_BYTES if cap is None else cap
    if limit <= 0:
        return text
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + (
        f"\n... [truncated ({limit // 1024} KB exec cap hit) -- pipe through head/tail/grep, "
        "or redirect to a file and read a slice]")


def do_read_file(path: str, cwd: str) -> str:
    fpath = _resolve_user_path(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        return fpath.read_text("utf-8", errors="replace")[:100000]
    except Exception as e:
        return f"[ERROR] Failed to read: {e}"

def do_write_file(path: str, content: str, cwd: str) -> str:
    fpath = _resolve_user_path(path, cwd)
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
    fpath = _resolve_user_path(path, cwd)
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
    dpath = _resolve_user_path(path, cwd)
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
    dpath = _resolve_user_path(path, cwd)
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
    dpath = _resolve_user_path(path, cwd)
    try:
        dpath.mkdir(parents=True, exist_ok=True)
        return f"[SUCCESS] Created directory: {path}"
    except Exception as e:
        return f"[ERROR] Failed to create: {e}"

def do_delete_file(path: str, cwd: str) -> str:
    fpath = _resolve_user_path(path, cwd)
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
    src_path = _resolve_user_path(src, cwd)
    dst_path = _resolve_user_path(dst, cwd)
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
    fpath = _resolve_user_path(path, cwd)
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        from lib_bejson_newagent_backup import list_backups
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
    scheme = urllib.parse.urlparse(str(url).strip()).scheme.lower()
    if scheme not in ("http", "https"):
        return f"[ERROR] http_get only supports http:// and https:// URLs (got scheme '{scheme or 'none'}')."
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

_FD_AVAILABLE: Optional[bool] = None


def _fd_available() -> bool:
    """Probe for `fd` once per process (was a subprocess spawn on every
    find_files call). shutil.which is enough -- no `fd --version` run."""
    global _FD_AVAILABLE
    if _FD_AVAILABLE is None:
        _FD_AVAILABLE = shutil.which("fd") is not None
    return _FD_AVAILABLE


def do_find_files(pattern: str, base: str = ".", cwd: str = ".") -> str:
    bpath = _resolve_user_path(base, cwd)
    proc = "fd" if _fd_available() else "find"

    try:
        if proc == "fd":
            cmd = ["fd", "-H", pattern, str(bpath)]
        else:
            cmd = ["find", str(bpath), "-name", f"*{pattern}*"]
        
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return _cap_subprocess_output(res.stdout.strip()) if res.stdout else "No matches found."
    except Exception as e:
        return f"[ERROR] Find failed: {e}"

SUBPROCESS_OUTPUT_CAP_BYTES = 65536  # 64KB -- matches do_http_get's existing cap

def _cap_subprocess_output(text: str) -> str:
    """Shared with do_search_text/do_find_files/do_fuzzy_find (Remediation
    pkg, found live-broken in the field: a `search_text bookwriter` call
    returned 1,954,412 bytes -- matched into old archived session log
    dumps under logs/, which themselves contain nested escaped JSON from
    PRIOR sessions, so a single common word recursively exploded into
    ~2MB. That got force-fed into the very next turn's context (8015
    input tokens for a 2-turn 'hi' session) and persisted into the new
    session's own logs, which is why the uploaded logs were themselves
    ~2MB after only 2 turns. Every other subprocess-backed action already
    caps its output (do_http_get: 64KB; do_read_file: 100KB) -- these
    three were the only ones that didn't."""
    data = text.encode("utf-8", errors="replace")
    if len(data) <= SUBPROCESS_OUTPUT_CAP_BYTES:
        return text
    truncated = data[:SUBPROCESS_OUTPUT_CAP_BYTES].decode("utf-8", errors="ignore")
    return truncated + "\n... [truncated (64 KB cap hit) -- narrow the pattern/path for more targeted results]"

def do_search_text(pattern: str, path: str = ".", cwd: str = ".") -> str:
    spath = _resolve_user_path(path, cwd)
    # FIX (Remediation pkg): path may name a single file (narrow the
    # search) or a directory (the common case) -- cwd= below needs a
    # directory either way, and the search target needs to be relative
    # to it for the exclusion globs to anchor correctly (see comment below).
    if spath.is_file():
        search_root, target = spath.parent, spath.name
    else:
        search_root, target = spath, "."
    try:
        cmd = [
            "rg", "-n",
            # FIX (Remediation pkg): logs/ and backups/ hold archived
            # session transcripts (themselves containing nested escaped
            # JSON from prior sessions) and checkpoint snapshots -- never
            # what a code/content search is actually looking for, and the
            # single biggest source of runaway matches. .git/__pycache__/
            # node_modules excluded as the usual non-source noise.
            "-g", "!logs/**", "-g", "!backups/**", "-g", "!.git/**",
            "-g", "!__pycache__/**", "-g", "!node_modules/**",
            pattern, target,
        ]
        # FIX (Remediation pkg, found testing the above): ripgrep anchors
        # a relative -g glob ("logs/**") to the SEARCH-ROOT ARGUMENT's own
        # relative structure, not the pattern's literal text. Passing an
        # absolute path argument (the original code, always -- spath is
        # always .resolve()d) broke that anchoring entirely -- confirmed
        # directly: `rg -g '!logs/**' pattern /abs/path` still matched
        # inside /abs/path/logs/, while `cd /abs/path && rg -g '!logs/**'
        # pattern .` correctly excluded it. So the exclusion globs above
        # were silently non-functional for every real call (which always
        # resolves to an absolute path) -- exactly the gap that let the
        # 1,954,412-byte `search_text bookwriter` result through logs/ in
        # the field. Now runs with cwd=search_root and a relative target
        # so the globs actually anchor where they're meant to.
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(search_root))
        return _cap_subprocess_output(res.stdout.strip()) if res.stdout else "No matches found."
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
        return _cap_subprocess_output(out.strip()) if out else "No matches found."
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
            label_idx = fmap["label"]
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
    return _resolve_user_path(path, cwd)

# CLI_Schema_Distribution (Elton's request, 2026-08): the model was
# occasionally hand-typing invalid Field type strings (e.g. "Number"
# instead of "number") when authoring a brand-new BEJSON file via
# write_file -- the only path that existed for that until now, since every
# other bejson_* action below operates on a file that must already exist.
# validate_bejson() doesn't actually reject an unrecognized type string (its
# type-check chain just silently skips value-checking a column whose type
# it doesn't recognize), so a "Type": "Number" file could slip through
# looking clean. This closes that gap at the source: do_bejson_create()
# enforces the canonical type vocabulary itself, up front, before ever
# writing to disk, with an error that names the exact allowed values --
# not just a general BEJSON validation failure the model has to
# reverse-engineer. This is Option 3 from Elton's proposal: a tool that
# deploys an already-valid schema so the model works from there, instead
# of freehand-authoring the whole Fields array (and its type strings) from
# memory every time.
_BEJSON_VALID_FIELD_TYPES = {"string", "integer", "number", "boolean", "array", "object"}

def do_bejson_create(
    path: str, version: str, fields_json: str, cwd: str,
    records_type: str = "", record_types: str = "",
) -> str:
    fpath = _bejson_resolve(path, cwd)
    if fpath.exists():
        return f"[ERROR] {path} already exists -- bejson_create is for NEW files only. Use bejson_add_field/bejson_create_record/bejson_set_value to modify an existing one."

    version = (version or "").strip()
    if version not in VALID_VERSIONS:
        return f"[ERROR] version=\"{version}\" is not valid. Must be one of: {sorted(VALID_VERSIONS)}."

    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError as e:
        return f"[ERROR] fields must be a JSON array like [{{\"name\":\"x\",\"type\":\"string\"}}]: {e}"
    if not isinstance(fields, list) or not fields:
        return "[ERROR] fields must be a non-empty JSON array of {\"name\":..., \"type\":...} objects."

    bad_type_errors = []
    seen_names = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict) or "name" not in f or "type" not in f:
            bad_type_errors.append(f"field {i}: needs at least \"name\" and \"type\" keys, got {f!r}.")
            continue
        fname, ftype = f["name"], f["type"]
        if fname in seen_names:
            bad_type_errors.append(f"field {i} ('{fname}'): duplicate field name.")
        seen_names.add(fname)
        if ftype not in _BEJSON_VALID_FIELD_TYPES:
            bad_type_errors.append(
                f"field {i} ('{fname}'): type=\"{ftype}\" is not a valid BEJSON type. "
                f"Must be exactly one of: {sorted(_BEJSON_VALID_FIELD_TYPES)} (lowercase)."
            )
        elif version == "104a" and ftype in ("array", "object"):
            bad_type_errors.append(
                f"field {i} ('{fname}'): type=\"{ftype}\" is forbidden in 104a -- "
                f"104a only allows scalar types (string/integer/number/boolean). "
                f"Use 104db (multi-entity) or 104 if this field genuinely needs {ftype}."
            )
    if bad_type_errors:
        return "[ERROR] Invalid field definition(s):\n  " + "\n  ".join(bad_type_errors)

    if version == "104db":
        rt_list = [t.strip() for t in record_types.split(",") if t.strip()]
        if len(rt_list) < 2:
            return "[ERROR] 104db needs record_types=\"TypeA,TypeB\" (2+ comma-separated entity names)."
        if fields[0].get("name") != "Record_Type_Parent":
            return "[ERROR] 104db's first field must be named exactly \"Record_Type_Parent\" (see do_bejson_add_field's 104db notes for why)."
        for i, f in enumerate(fields):
            if f["name"] != "Record_Type_Parent" and "Record_Type_Parent" not in f:
                return (
                    f"[ERROR] field {i} ('{f['name']}') needs its own "
                    f"\"Record_Type_Parent\": \"<one of {rt_list}>\" key -- every field in a "
                    f"104db file must declare which entity type owns it."
                )
            rtp = f.get("Record_Type_Parent")
            if rtp is not None and rtp not in rt_list:
                return f"[ERROR] field {i} ('{f['name']}')'s Record_Type_Parent '{rtp}' is not in record_types {rt_list}."
        doc = bejson_core_create_104db(rt_list, fields, [])
    else:
        rt = (records_type or "").strip()
        if not rt:
            return f"[ERROR] {version} needs records_type=\"YourRecordName\"."
        builder = bejson_core_create_104a if version == "104a" else bejson_core_create_104
        doc = builder(rt, fields, [])

    # Defense in depth: run the real Core validator too, even though the
    # checks above are stricter than it is (see module comment above).
    result = validate_bejson(doc, is_file=False)
    if not result.valid:
        return "[ERROR] Passed local checks but failed validate_bejson (this shouldn't normally happen -- report it): " + "; ".join(result.errors)

    if not bejson_core_atomic_write(str(fpath), doc):
        return f"[ERROR] Atomic write failed for {path}"

    field_list = ", ".join(f"{f['name']} ({f['type']})" for f in fields)
    return (
        f"[SUCCESS] Created {path} -- BEJSON {version}, "
        f"Records_Type={doc['Records_Type']}, {len(fields)} field(s): {field_list}. "
        f"0 rows -- use bejson_create_record to add data."
    )

def do_context_set(section: str, content: str, cwd: str) -> str:
    """
    Elton's INIT request: "anytime he's given important project
    instructions like the purpose of a project or our main rules, inject
    those into the directory structure of the project in an init." Thin
    wrapper around lib_bejson_newagent_context_bubble.upsert_cwd_context_section
    -- one reliable call instead of the model composing bejson_create_record
    (must-not-duplicate-if-exists) + bejson_set_value (must-know-it-already-
    exists) itself, and no shell-quoting risk the way invoking the
    standalone tools/NA-Init/CLI_Init.py CLI via <exec> would have for
    multi-sentence content. Same underlying file/schema either way --
    context.bejson, auto-injected into every turn's context with no
    keyword trigger and no cooldown.
    """
    if not section.strip():
        return "[ERROR] section cannot be empty."
    ok, msg = bubble.upsert_cwd_context_section(cwd, section.strip(), content)
    return ("[SUCCESS] " if ok else "[ERROR] ") + msg

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

_VALID_ACTION_TAGS = frozenset({
    "exec", "read_file", "write_file", "edit_file", "list_dir", "tree_view",
    "make_dir", "delete_file", "copy_file", "diff_file", "restore_file",
    "http_get", "find_files", "search_text", "fuzzy_find", "env_get",
    "speak", "checkpoint", "checklist_create", "checklist_check",
    "checklist_add", "checklist_view", "html_report", "html_report_append",
    "project_log", "request_continue", "bejson_fields", "bejson_add_field",
    "bejson_delete_field", "bejson_create_record", "bejson_delete_record",
    "bejson_set_value", "bejson_columns", "bejson_create", "context_set",
    "exec_bg", "task_status", "task_kill", "task_list", "job_task_done",
})

_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>|<tool_call>(.*?)</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

_BRACKET_CALL_SPLIT_PATTERN = re.compile(
    r"\[\s*(" + "|".join(sorted(_VALID_ACTION_TAGS, key=len, reverse=True)) + r")\b\s*(?:\((.*?)\))?\s*\](?=\s*(?:\[\s*(?:" + "|".join(sorted(_VALID_ACTION_TAGS, key=len, reverse=True)) + r")\b|\Z))",
    re.DOTALL | re.IGNORECASE,
)

_LINE_BRACKET_CALL_PATTERN = re.compile(
    r"^\s*\[\s*(" + "|".join(sorted(_VALID_ACTION_TAGS, key=len, reverse=True)) + r")\b\s*(?:\((.*?)\))?\s*\]\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _map_tool_call_to_action(
    tag: str,
    pos_args: list,
    kw_args: dict,
    raw_arg: Optional[str] = None,
) -> Optional[dict]:
    """Translate a parsed (tag, pos_args, kw_args, raw_arg) call from an
    OpenRouter / native tool-call block into NewAgent's canonical
    {'tag': tag, 'attrs': attrs, 'content': content} dict."""
    tag = (tag or "").strip().lower()
    if tag not in _VALID_ACTION_TAGS:
        return None

    def _first_str(*values, default: str = "") -> str:
        for v in values:
            if v is not None and v != "":
                return str(v)
        return default

    attrs: dict[str, str] = {}
    content = ""

    if tag in ("exec", "exec_bg"):
        content = _first_str(
            kw_args.get("command"), kw_args.get("cmd"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag in ("read_file", "list_dir", "make_dir", "delete_file", "diff_file", "bejson_fields"):
        content = _first_str(
            kw_args.get("path"), kw_args.get("file"), kw_args.get("dir"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "restore_file":
        content = _first_str(
            kw_args.get("backup_id"), kw_args.get("id"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "http_get":
        content = _first_str(
            kw_args.get("url"), pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag in ("find_files", "search_text"):
        content = _first_str(
            kw_args.get("pattern"), kw_args.get("query"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "fuzzy_find":
        content = _first_str(
            kw_args.get("query"), kw_args.get("pattern"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "env_get":
        content = _first_str(
            kw_args.get("var_name"), kw_args.get("name"), kw_args.get("var"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "speak":
        content = _first_str(
            kw_args.get("text"), kw_args.get("message"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "checkpoint":
        content = _first_str(
            kw_args.get("label"), pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "request_continue":
        content = _first_str(
            kw_args.get("reason"), pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag in ("task_status", "task_kill"):
        content = _first_str(
            kw_args.get("task_id"), kw_args.get("id"),
            pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "task_list":
        content = ""
    elif tag == "write_file":
        attrs["path"] = _first_str(
            kw_args.get("path"), kw_args.get("file"),
            pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("content"), kw_args.get("text"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "edit_file":
        attrs["path"] = _first_str(
            kw_args.get("path"), kw_args.get("file"),
            pos_args[0] if pos_args else None,
        )
        raw_body = _first_str(kw_args.get("content"), raw_arg)
        if "<old>" in raw_body and "<new>" in raw_body:
            content = raw_body
        else:
            old_val = _first_str(
                kw_args.get("old"), kw_args.get("old_text"),
                pos_args[1] if len(pos_args) > 1 else None,
            )
            new_val = _first_str(
                kw_args.get("new"), kw_args.get("new_text"),
                pos_args[2] if len(pos_args) > 2 else None,
            )
            content = f"<old>{old_val}</old><new>{new_val}</new>"
    elif tag == "tree_view":
        content = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None, raw_arg, default=".",
        )
        depth_val = kw_args.get("depth", pos_args[1] if len(pos_args) > 1 else None)
        if depth_val is not None:
            attrs["depth"] = str(depth_val)
    elif tag == "copy_file":
        attrs["src"] = _first_str(
            kw_args.get("src"), pos_args[0] if pos_args else None,
        )
        attrs["dst"] = _first_str(
            kw_args.get("dst"), pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "checklist_create":
        attrs["title"] = _first_str(
            kw_args.get("title"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("tasks"), kw_args.get("tasks_text"), kw_args.get("content"),
            pos_args[1] if len(pos_args) > 1 else None, raw_arg,
        )
    elif tag == "checklist_check":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        attrs["task_id"] = _first_str(
            kw_args.get("task_id"), kw_args.get("id"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "checklist_add":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("description"), kw_args.get("task"), kw_args.get("content"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "checklist_view":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None, raw_arg,
        )
    elif tag == "html_report":
        attrs["title"] = _first_str(
            kw_args.get("title"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("content"), kw_args.get("body"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "html_report_append":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("content"), kw_args.get("body"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "project_log":
        attrs["version"] = _first_str(
            kw_args.get("version"), kw_args.get("version_label"),
            pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("notes"), kw_args.get("content"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "context_set":
        attrs["section"] = _first_str(
            kw_args.get("section"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("content"), kw_args.get("text"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "bejson_create":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        attrs["version"] = _first_str(
            kw_args.get("version"), pos_args[1] if len(pos_args) > 1 else None,
        )
        if kw_args.get("records_type"):
            attrs["records_type"] = str(kw_args["records_type"])
        if kw_args.get("record_types"):
            attrs["record_types"] = str(kw_args["record_types"])
        fval = kw_args.get("fields") or kw_args.get("fields_json") or kw_args.get("content") or (pos_args[2] if len(pos_args) > 2 else "")
        content = json.dumps(fval) if isinstance(fval, (list, dict)) else str(fval)
    elif tag == "bejson_add_field":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        fval = kw_args.get("field") or kw_args.get("field_json") or kw_args.get("content") or (pos_args[1] if len(pos_args) > 1 else "")
        content = json.dumps(fval) if isinstance(fval, (list, dict)) else str(fval)
    elif tag == "bejson_delete_field":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        content = _first_str(
            kw_args.get("field_name"), kw_args.get("field"), kw_args.get("content"),
            pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "bejson_create_record":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        vval = kw_args.get("values") or kw_args.get("values_json") or kw_args.get("record") or kw_args.get("content") or (pos_args[1] if len(pos_args) > 1 else "")
        content = json.dumps(vval) if isinstance(vval, (list, dict)) else str(vval)
    elif tag == "bejson_delete_record":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        attrs["row"] = _first_str(
            kw_args.get("row"), pos_args[1] if len(pos_args) > 1 else None,
        )
    elif tag == "bejson_set_value":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        attrs["row"] = _first_str(
            kw_args.get("row"), pos_args[1] if len(pos_args) > 1 else None,
        )
        if kw_args.get("field") is not None:
            attrs["field"] = str(kw_args["field"])
        if kw_args.get("col") is not None:
            attrs["col"] = str(kw_args["col"])
        val = kw_args.get("value") if "value" in kw_args else (kw_args.get("content") if "content" in kw_args else (pos_args[2] if len(pos_args) > 2 else ""))
        content = json.dumps(val) if isinstance(val, (list, dict, bool, int, float)) else str(val)
    elif tag == "bejson_columns":
        attrs["path"] = _first_str(
            kw_args.get("path"), pos_args[0] if pos_args else None,
        )
        attrs["columns"] = _first_str(
            kw_args.get("columns"), pos_args[1] if len(pos_args) > 1 else None,
        )
        rows_val = kw_args.get("rows", pos_args[2] if len(pos_args) > 2 else None)
        if rows_val is not None:
            attrs["rows"] = str(rows_val)
    elif tag == "job_task_done":
        attrs["id"] = _first_str(
            kw_args.get("id"), kw_args.get("task_id"),
            pos_args[0] if pos_args else None, raw_arg,
        )

    return {"tag": tag, "attrs": attrs, "content": html.unescape(content.strip())}


def _parse_bracket_invocation(tag: str, inner: Optional[str]) -> Optional[dict]:
    """Parse a single [tag(inner)] invocation where inner may be either valid
    Python literal arguments (e.g. command='ls -la' or 'ls -la') or raw
    unquoted shell/text (e.g. mkdir -p /path && echo "done")."""
    if inner is None:
        return _map_tool_call_to_action(tag, [], {}, "")
    inner_stripped = inner.strip()
    if not inner_stripped:
        return _map_tool_call_to_action(tag, [], {}, "")

    try:
        tree = ast.parse(f"_call({inner_stripped})", mode="eval")
        if isinstance(tree.body, ast.Call):
            pos_args = [ast.literal_eval(a) for a in tree.body.args]
            kw_args = {
                kw.arg: ast.literal_eval(kw.value)
                for kw in tree.body.keywords
                if kw.arg is not None
            }
            return _map_tool_call_to_action(tag, pos_args, kw_args, inner_stripped)
    except Exception:
        pass

    return _map_tool_call_to_action(tag, [], {}, inner_stripped)


def _parse_tool_call_block(block_text: str) -> list[dict]:
    """Parse the body of a <|tool_call_start|>...<|tool_call_end|> or
    <tool_call>...</tool_call> block into a list of action dicts."""
    body = (block_text or "").strip()
    if not body:
        return []

    # 1. Try JSON tool call(s): {"name": "exec", "arguments": {...}} or [...]
    try:
        parsed_json = json.loads(body)
        items = parsed_json if isinstance(parsed_json, list) else [parsed_json]
        json_actions = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = fn.get("name") or fn.get("tool") or fn.get("tag")
            args = fn.get("arguments") if "arguments" in fn else fn.get("parameters", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    act = _map_tool_call_to_action(str(name or ""), [], {}, args)
                    if act:
                        json_actions.append(act)
                    continue
            if isinstance(args, dict):
                act = _map_tool_call_to_action(str(name or ""), [], args)
            elif isinstance(args, list):
                act = _map_tool_call_to_action(str(name or ""), args, {})
            else:
                act = _map_tool_call_to_action(str(name or ""), [], {}, str(args or ""))
            if act:
                json_actions.append(act)
        if json_actions:
            return json_actions
    except Exception:
        pass

    # 2. Try bracketed [tag(...)] call(s) (Nemotron 3 format)
    bracket_actions = []
    for m in _BRACKET_CALL_SPLIT_PATTERN.finditer(body):
        act = _parse_bracket_invocation(m.group(1), m.group(2))
        if act:
            bracket_actions.append(act)
    if bracket_actions:
        return bracket_actions

    return []


def actions_signature(parsed_actions: list[dict]) -> tuple:
    """Order-preserving, hashable fingerprint of one model turn's action batch.

    Used by the agent loop to detect a model re-emitting the identical batch
    turn after turn (pkg128: nemotron-3-super looped ``echo "Task completed"``
    six times). Whitespace-normalised so cosmetic differences don't hide it.
    """
    sig = []
    for act in parsed_actions or []:
        attrs = act.get("attrs") or {}
        sig.append((
            str(act.get("tag", "")),
            tuple(sorted((str(k), str(v)) for k, v in attrs.items())),
            " ".join(str(act.get("content", "")).split()),
        ))
    return tuple(sig)


_ANNOUNCE_ONLY_SHELL_META = re.compile(r"[;&|<>`$\\]|\n")


def is_announcement_only(parsed_actions: list[dict]) -> bool:
    """True when every action is a bare ``<exec>echo ...</exec>`` with no shell
    operators -- i.e. the model is using exec as a speech channel ("All done!")
    rather than doing work. Feeding that result back guarantees another turn in
    which the model repeats itself, so the agent loop hands control back to the
    user instead of auto-continuing.
    """
    if not parsed_actions:
        return False
    for act in parsed_actions:
        if act.get("tag") != "exec":
            return False
        cmd = str(act.get("content", "")).strip()
        if not re.match(r"^echo(\s|$)", cmd):
            return False
        if _ANNOUNCE_ONLY_SHELL_META.search(cmd.replace('\\"', "").replace("\\'", "")[4:]) and not re.fullmatch(r'echo\s+("[^"`$]*"|\'[^\']*\')\s*', cmd):
            return False
    return True


def parse_actions(text: str) -> list[dict]:
    if not text or not isinstance(text, str):
        return []

    events: list[tuple[int, dict]] = []
    xml_spans: list[tuple[int, int]] = []

    for match in ACTION_PATTERN.finditer(text):
        xml_spans.append(match.span())
        tag = (match.group(1) or match.group(4)).lower()
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

        events.append((match.start(), {"tag": tag, "attrs": attrs, "content": content}))

    # Fallback 1: <|tool_call_start|>...<|tool_call_end|> or <tool_call>...</tool_call>
    # blocks that did not already contain a standard XML tag match.
    for tc_match in _TOOL_CALL_BLOCK_PATTERN.finditer(text):
        tc_start, tc_end = tc_match.span()
        if any(xs >= tc_start and xe <= tc_end for xs, xe in xml_spans):
            continue
        inner_block = tc_match.group(1) if tc_match.group(1) is not None else tc_match.group(2)
        for act in _parse_tool_call_block(inner_block):
            events.append((tc_start, act))

    if events:
        events.sort(key=lambda item: item[0])
        return [act for _, act in events]

    # Fallback 2: bare [tag(...)] on its own line (when a provider strips
    # <|tool_call_start|> / <|tool_call_end|> special tokens before returning).
    fallback_actions = []
    for line_match in _LINE_BRACKET_CALL_PATTERN.finditer(text):
        act = _parse_bracket_invocation(line_match.group(1), line_match.group(2))
        if act:
            fallback_actions.append(act)
    return fallback_actions

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
            from lib_bejson_newagent_tui import C  # lazy: avoids an import cycle at module load
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
                    # FIX (2026-09-11, audit V106-09): run_action_queue is the
                    # single call path both agent.py's REST <exec> tag and
                    # cliagent.py's --execute reach do_exec() through -- it
                    # never passed exec_denylist here, so config's denylist
                    # was silently a no-op for every caller except
                    # webagent.py's separate /api/exec route, which calls
                    # do_exec() directly and did pass it. Wiring it in here
                    # closes the gap at the one shared primitive.
                    denylist=config.get("exec_denylist"),
                    output_cap=_config_int(config.get("exec_output_cap_bytes")),
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

        elif tag == "bejson_create":
            path = attrs.get("path", "")
            exec_res.source = path
            exec_res.output = do_bejson_create(
                path, attrs.get("version", ""), content, cwd,
                records_type=attrs.get("records_type", ""),
                record_types=attrs.get("record_types", ""),
            )

        elif tag == "context_set":
            exec_res.source = attrs.get("section", "")
            exec_res.output = do_context_set(attrs.get("section", ""), content, cwd)

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
        label_idx = fmap["label"]
        bids_idx = fmap["backup_ids"]
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
