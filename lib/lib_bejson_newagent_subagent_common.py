"""
Library:        lib_bejson_newagent_subagent_common.py
Family:         NewAgent (subagent family)
Description:    Shared plumbing for the sub-agent library family
                (lib_bejson_newagent_subagent_profiles/sessions/signals/runtime):
                path resolution under a caller-supplied subagents_dir, a
                race-safe locked read-modify-write helper for BEJSON 104
                files with multiple potential concurrent writers, and
                field-map row<->dict conversion. Every other file in this
                family routes its disk I/O through with_file_lock() here
                instead of each reimplementing its own locking (the same
                code-duplication the Cognitive_Core audit flagged between
                lib_bejson_agentic_core.py and lib_mfdb_agent_core.py).

                Inspired by Cognitive_Core's lib_bejson_agentic_core.py
                (AgentSession/AgentSignal durable-state pattern) but the
                locking here is new: Cognitive_Core's session/signal
                writes were plain load -> mutate -> bejson_core_atomic_write
                with no coordination at all between callers. Sub-agents are
                explicitly meant to run concurrently (multiple dispatched
                sessions, the main agent polling signals while a sub-agent
                writes them), so an uncoordinated read-modify-write on a
                shared sessions.bejson/signals.bejson would lose updates
                under real concurrency -- the exact class of bug found and
                fixed the hard way in lib_bejson_newagent_config.py 1.14.0
                (see that file's changelog): a naive "if not exists: create"
                branch, and a plain load-then-atomic_write elsewhere, both
                let a slower writer silently revert a faster writer's
                already-saved data. with_file_lock() below is that fix
                generalized into a single reusable primitive instead of
                three copies of the same lock code.
Version:        1.1.0
Date:           2026-09-18
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  b8b339e4-7532-4aba-86eb-2ff23ef7ff7d

CHANGELOG:
- 1.1.0 (2026-09-18): Remediation pass, audit finding #1 (HIGH -- locking
  reinvented per-file). with_file_lock()'s own update-lock (Step 2) was a
  hand-rolled os.open(O_CREAT|O_EXCL) + wall-clock-age stale-lock reclaim,
  independently reinvented instead of using the proven ResilientPIDLock
  (PID-liveness check via os.kill(pid, 0)) already used correctly
  elsewhere in the codebase (e.g. mfdb_core.py). Real bug this closes: a
  legitimately slow holder (large write on a loaded phone) taking longer
  than the stale-after window had its lock stolen by another still-alive
  process -- a genuine concurrent-write race. A second, more serious bug
  found while retrofitting: if the old acquisition loop's deadline passed
  without acquiring, it fell straight through into the critical section
  completely UNPROTECTED instead of raising -- silent total lock failure,
  not just a weak one. ResilientPIDLock now guards Step 2 and raises
  OSError on a genuine timeout instead. lock_stale_after parameter
  removed (unused by ResilientPIDLock's liveness-based reclaim; no
  caller in the codebase passed it explicitly). Verified: 10 threads x 20
  concurrent with_file_lock() writers against one file -> exactly 200
  rows landed, zero errors, no leftover .lock.lockdir; py_compile clean.
- 1.0.0 (2026-09-12): Initial version. New library, not a port of anything
  in Cognitive_Core -- extracted up front so profiles/sessions/signals/
  runtime never duplicate lock or path-resolution logic between them.
"""

import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_atomic_write,
    bejson_core_get_field_map,
    ResilientPIDLock,
)

VERSION = "1.1.0"

LOCK_TIMEOUT_SECONDS = 10.0
READ_RETRY_ATTEMPTS = 20  # ~1s worst case at 0.05s/attempt -- see with_file_lock's docstring
READ_RETRY_DELAY_SECONDS = 0.05


# --- Path resolution (never hardcoded -- every caller passes its own
#     subagents_dir, same convention as jobs.py's ensure_job_dirs(jobs_dir)
#     and config_lib's init_config(config_path)) --------------------------

def profiles_dir(subagents_dir: Path) -> Path:
    return subagents_dir / "profiles"


def sessions_path(subagents_dir: Path) -> Path:
    return subagents_dir / "sessions.bejson"


def signals_path(subagents_dir: Path) -> Path:
    return subagents_dir / "signals.bejson"


def ensure_subagent_dirs(subagents_dir: Path) -> None:
    """Create subagents/ and subagents/profiles/ if missing. Call once at
    agent bootstrap, same role as jobs.ensure_job_dirs()."""
    subagents_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir(subagents_dir).mkdir(parents=True, exist_ok=True)


# --- Field-map row/dict conversion (Field Map Cache is mandatory --
#     positional literals like Cognitive_Core's `[session_id, agent_name,
#     initial_step, ...]` are never used anywhere in this family) --------

def row_to_dict(doc: dict, row: list) -> dict:
    field_map = bejson_core_get_field_map(doc)
    return {name: row[idx] for name, idx in field_map.items() if idx < len(row)}


def dict_to_row(doc: dict, record: dict, defaults: Optional[dict] = None) -> list:
    """Builds a row in the doc's actual current Fields order from a
    {field_name: value} dict -- never assume the schema's declared order
    matches Fields order after a migration/reorder. Missing keys fall back
    to `defaults` (by name) and then to None (BEJSON's explicit-null rule
    -- never omitted, never "")."""
    field_map = bejson_core_get_field_map(doc)
    defaults = defaults or {}
    row = [None] * len(field_map)
    for name, idx in field_map.items():
        if name in record:
            row[idx] = record[name]
        elif name in defaults:
            row[idx] = defaults[name]
    return row


# --- Race-safe locked read-modify-write ------------------------------------

def with_file_lock(
    path: Path,
    mutate_fn: Callable[[dict], tuple],
    empty_doc_factory: Callable[[], dict],
    *,
    lock_timeout: float = LOCK_TIMEOUT_SECONDS,
) -> Any:
    """Runs mutate_fn(doc) -> (write_needed, result) under an exclusive file
    lock scoped to `path`. mutate_fn mutates `doc` in place (e.g. appending/
    editing Values) and returns a 2-tuple: write_needed (bool) tells this
    function whether to persist doc back to disk, and result is returned
    as-is to with_file_lock's own caller. A pure read (e.g. list_sessions)
    returns (False, <whatever it read>); a read-modify-write (e.g.
    update_session) returns (True, <the updated record>) -- explicit about
    which happened rather than overloading a single return value to mean
    both "the answer" and "whether to save it".

    Two races this closes, both found and fixed the hard way while
    stress-testing lib_bejson_newagent_config.py 1.14.0's token-generation
    lock (see that file's changelog for the full story):

    1. First creation: a plain `if not path.exists(): atomic_write(defaults)`
       lets two concurrent callers both take that branch and both write --
       whichever's atomic_write() lands last silently discards whatever the
       other wrote in between. Guarded here with an os.O_CREAT|os.O_EXCL
       claim on `path` itself: only one caller can win the claim; the loser
       falls through to the tolerant read below instead of writing at all.

    2. Torn read: a caller whose exists() check lands AFTER another
       process's claim (which creates an empty 0-byte file) but BEFORE that
       process's real atomic_write() has replaced it takes the ordinary
       "load existing file" path with no protection, reads a 0-byte file,
       and treats it as corrupt. Closed by retrying the load briefly
       (READ_RETRY_ATTEMPTS x READ_RETRY_DELAY_SECONDS) on an unparseable
       result before giving up and falling back to empty_doc_factory().

    The actual read-mutate-write critical section, once the base file is
    known to exist and be valid, is guarded by ResilientPIDLock (Remediation
    pkg, audit finding #1 -- this used to be a hand-rolled second lock
    scheme here, independently reinvented and weaker than the proven
    PID-liveness-checked ResilientPIDLock already used correctly elsewhere
    in the codebase, e.g. mfdb_core.py). Two real bugs that fix closes:
    the old scheme reclaimed a lock purely by wall-clock age (older than
    lock_stale_after == abandoned), so a legitimately slow holder (a large
    write on a loaded phone) taking longer than that window had its lock
    stolen by another still-alive process -- a genuine concurrent-write
    race, exactly what ResilientPIDLock's os.kill(pid, 0) liveness check
    exists to prevent. Separately, and more seriously: if the old
    acquisition loop's deadline passed without ever acquiring, it fell
    straight through into the critical section completely UNPROTECTED
    instead of raising -- a silent total lock-acquisition failure, not
    just a weak one. ResilientPIDLock raises OSError on a genuine timeout
    instead of ever running the critical section unlocked.
    """
    lock_path = path.with_name(path.name + ".lock")

    # --- Step 1: guarantee the base file exists and has real content,
    #     racing at most once against other first-time creators.
    if not path.exists():
        try:
            claim_fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(claim_fd)
        except FileExistsError:
            pass  # someone else is creating it -- fall through to the tolerant read below
        else:
            if not bejson_core_atomic_write(str(path), empty_doc_factory()):
                raise IOError(f"[Subagent] Failed to create {path}")

    # --- Step 2: acquire the update lock.
    lock = ResilientPIDLock(str(lock_path), timeout_seconds=int(lock_timeout))
    if not lock.acquire():
        raise OSError(f"[Subagent] Timed out acquiring lock for {path} after {lock_timeout}s")

    try:
        # --- Step 3: torn-read-tolerant load.
        doc = None
        for _ in range(READ_RETRY_ATTEMPTS):
            # A zero-byte file is the known, expected shape of "someone
            # else's exclusive-create claim landed, their real content
            # hasn't yet" (see the docstring above) -- skip straight to
            # the retry sleep instead of calling bejson_core_load_file(),
            # which logs its own ERROR-level line on every failed parse.
            # That log message is accurate but misleading here: this
            # isn't a corrupt file, it's an expected transient state this
            # loop is specifically built to wait out.
            try:
                if path.stat().st_size == 0:
                    time.sleep(READ_RETRY_DELAY_SECONDS)
                    continue
            except FileNotFoundError:
                time.sleep(READ_RETRY_DELAY_SECONDS)
                continue
            doc = bejson_core_load_file(str(path))
            if isinstance(doc, dict) and doc.get("Values") is not None:
                break
            time.sleep(READ_RETRY_DELAY_SECONDS)
        if not isinstance(doc, dict) or doc.get("Values") is None:
            doc = empty_doc_factory()

        write_needed, result = mutate_fn(doc)
        if write_needed:
            if not bejson_core_atomic_write(str(path), doc):
                raise IOError(f"[Subagent] Failed to write {path}")
        return result
    finally:
        lock.release()
