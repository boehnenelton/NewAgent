# NewAgent Codebase Audit — Efficiency, Standardization, Hardening, Refinement

**Author:** Claude (Sonnet), for Elton Boehnen
**Date:** 2026-09-13
**Scope:** Core engine and entry points (agent.py, cliagent.py, webagent.py,
JobMaker.py), the shared `lib/` family (config, actions, engine_rest, jobs,
context_bubble, tui, errors, Core bejson/mfdb primitives), and the new
sub-agent family (`lib_bejson_newagent_subagent_*.py`, `subagent_admin.py`)
added this session.
**Out of scope:** `tools/` and `lib_extensions/` — these are separately
forked-in subprojects (NA-CMS, NA-Chunker, NA-WebExtract, NA-MD2HTML,
Gemini Terminal Agent, huggingface/provocative extensions) each large
enough to warrant its own audit pass rather than a shallow pass folded
into this one. Flagged here as a gap, not silently skipped.
**Method:** Targeted reading of the highest-risk surfaces (concurrency,
persistence, retry logic, context assembly) plus systematic grep sweeps
for known anti-pattern signatures (bare `except`, unchecked write return
values, positional row indexing, module-level mutable state, fixed-delay
retry loops). This is not a line-by-line review of ~30,000 lines of code
— it is a risk-prioritized pass. Findings are cited with exact file/line
references so each one is independently verifiable, not asserted from
memory.

---

## Executive Summary

The codebase is in genuinely good shape for its size — the config layer's
Field Map Cache discipline, the REST engine's error-classification-by-HTTP-
status design, and the action-tag execution model are all well-reasoned
and consistently documented with FIX-comment provenance trails, which is
rare and valuable. The problems found are not "this code is bad" — they
are "this code was built by many separate passes (including my own two
passes this session) that each solved a local problem correctly without
noticing a better, already-existing solution sitting one file away."

The single most important finding is **Section 1**: a well-built,
PID-liveness-based file lock primitive (`ResilientPIDLock` in
`lib_bejson_Core_bejson_core.py`) already exists and is already proven in
production use by `mfdb_core.py`, but neither my own `config_lib` fix
(pkg104-104, this session) nor my own new `subagent_common.py`
(pkg112-113, this session) used it — both independently reinvented a
strictly weaker locking scheme (`os.O_CREAT|os.O_EXCL` plus a
time-based, not liveness-based, stale-lock heuristic). This is a
standardization failure I introduced myself, and it's the clearest example
in the whole audit of the actual root cause behind most of what follows:
**there is no single place a contributor (human or AI) checks before
building a new primitive**, so the same problem gets re-solved at
different quality levels in different files.

Ten concrete, actionable findings follow, ordered by severity. Findings 1,
2, and 3 are data-integrity risks (silent corruption or lost writes under
real conditions, not theoretical). Findings 4-6 are efficiency and
robustness gaps in hot paths. Findings 7 is a self-critique of the
sub-agent family delivered this session — an audit that only ever finds
fault with pre-existing code is not a credible audit. Findings 8-10 are
process/standardization gaps that make future findings-like-these more
likely to recur.

---

## Deep Analysis

### 1. Locking is reinvented per-file instead of standardized on `ResilientPIDLock` (SEVERITY: HIGH)

`lib_bejson_Core_bejson_core.py` (lines 33-82) already contains this:

```
class ResilientPIDLock:
    def acquire(self) -> bool:
        # mkdir(exist_ok=False) -- atomic claim, same guarantee as O_EXCL
        # os.kill(pid, 0) -- checks if the LOCK HOLDER PROCESS is actually
        #                    still alive, not just "has it been N seconds"
    def __enter__(self) / __exit__(self):
        # real context manager: `with ResilientPIDLock(path) as lock: ...`
```

This is used correctly today by `lib_bejson_Core_mfdb_core.py` (manifest
locking) and `tools/NA-Chunker/CLI_Chunker.py`. It is a genuinely better
design than what I built twice this session:

- **`lib_bejson_newagent_config.py`'s `get_or_create_web_auth_token()`**
  (added pkg104, hardened pkg104-extended) uses a hand-rolled lock file
  plus `time.time() - lock_path.stat().st_mtime > lock_stale_after` to
  decide a lock is abandoned. This is a *guess by elapsed time*. A
  legitimately slow (not dead) holder past `lock_stale_after` (30s) gets
  its lock stolen out from under it. `ResilientPIDLock`'s `os.kill(pid, 0)`
  check asks the actual question that matters — "is the holder process
  still alive" — and never steals a live process's lock regardless of how
  long it's taking.

- **`lib_bejson_newagent_subagent_common.py`'s `with_file_lock()`** (new
  this session) has the *same* class of weakness, plus an additional
  structural one `ResilientPIDLock` avoids by design: because my lock only
  wraps the *mutate* step, the file's *existence* has to be established
  separately first (the `os.O_CREAT|os.O_EXCL` "claim" step), which is why
  a torn-read retry loop was needed at all (see the file's own changelog —
  this took real debugging effort to get right). If the create-or-load-
  mutate-write sequence were instead wrapped in a single
  `with ResilientPIDLock(path):` block from the start, there would be no
  window where any reader could observe a partially-written file, because
  the file would never be touched outside the lock in the first place —
  the torn-read problem would not exist to solve.

**Impact:** Two production-facing config/session files currently rely on
a weaker, self-built guarantee than a proven one already sitting in the
same import tree. The risk is bounded today (both were stress-tested to
0 failures across 200+ threads this session) but the *design* is fragile
in a way `ResilientPIDLock` isn't, and the next contributor who needs a
lock has no signal that `ResilientPIDLock` is the house standard — nothing
points to it.

**Recommendation:** Retrofit both `get_or_create_web_auth_token()` and
`with_file_lock()` to use `ResilientPIDLock` internally instead of their
own claim/lock-file logic. This is a net simplification, not just a
hardening — it deletes the stale-reclaim clock-math and the torn-read
retry loop entirely, replacing both with one `with` block per operation.

---

### 2. Discarded write-failure return values, concentrated in `mfdb_core.py` (SEVERITY: HIGH)

`bejson_core_atomic_write()` returns `bool` specifically so callers can
detect a failed persist. Grep across the audited surface:

| File | Calls | Return value checked/propagated |
|---|---|---|
| `lib_bejson_Core_mfdb_core.py` | 16 | **2** |
| `lib_bejson_newagent_context_bubble.py` | 7 | 4 |
| `lib_bejson_newagent_session.py` | 6 | 3 |
| `lib_bejson_newagent_config.py` | 6 | 3 (pre-existing; my own additions this session are checked) |
| everywhere else audited | 30 | 28 |

(Methodology note: this table counts `if not X(...)` / `if X(...)` /
`= X(...)` textually. `return bejson_core_atomic_write(...)` — a
legitimate way to propagate the result to *that function's own caller* —
reads as "unchecked" by this grep but isn't a defect; I manually verified
each flagged line below is a genuine bare, discarded call, not a
`return`.)

`mfdb_core.py` is the standout and the one worth fixing first — it is the
**database layer**, where a silently-failed write is a silent data-loss
bug, not a cosmetic one:

```
lib/lib_bejson_Core_mfdb_core.py:527:    bejson_core_atomic_write(entity_path, doc)
lib/lib_bejson_Core_mfdb_core.py:559:    bejson_core_atomic_write(entity_path, doc)
lib/lib_bejson_Core_mfdb_core.py:891:    bejson_core_atomic_write(resolved, entity_doc)
lib/lib_bejson_Core_mfdb_core.py:974:    bejson_core_atomic_write(manifest_path, manifest_doc)
```

Each is a bare statement — the boolean result is computed and thrown
away. If disk is full, permissions are wrong, or the target path becomes
briefly unwritable (all real conditions on Android/Termux storage,
not hypothetical), the caller proceeds as though the write succeeded:
manifest and entity-file state can silently diverge from what's actually
on disk, and the *next* read will look normal until the divergence causes
a downstream lookup miss with no error trail pointing back to the actual
failed write.

**Impact:** This is the exact failure mode `ResilientPIDLock`'s own
liveness discipline and the config-lib fixes this session were built to
prevent for *concurrency* races — but a discarded return value defeats it
regardless of how good the locking underneath is. A lock guarantees only
one writer at a time; it does not guarantee that writer's write actually
landed.

**Recommendation:** Every `bejson_core_atomic_write()` call site should
either check-and-raise, check-and-return-False-to-its-own-caller, or have
an explicit one-line comment stating why it's intentionally
fire-and-forget (rare, and none of the four `mfdb_core.py` sites above
look like that case). This is a mechanical, low-risk fix — no logic
changes, just adding `if not bejson_core_atomic_write(...): raise/log/
return False` at four call sites plus whichever of the other ~25 unchecked
sites turn out, on inspection, to be genuine (not `return`-based) misses.

---

### 3. Field-map fallback landmine in `lib_bejson_newagent_session.py` (SEVERITY: MEDIUM-HIGH)

The house rule (policy §6.2) is explicit: *"Positional lookups, hardcoded
indices, and fixed field offsets are strictly prohibited."* The session
logger mostly follows this — it builds a field map (`fmap =
bejson_core_get_field_map(db_doc)`) and looks up columns by name. But
every single lookup carries a hardcoded numeric fallback:

```python
sess_row[fmap.get("model_used", 3)] = model_used
sess_row[fmap.get("total_input_tokens", 4)] = ...
turn_row[fmap.get("turn_id", 7)] = turn_id
turn_row[fmap.get("session_fk", 8)] = self.session_guid
# ... 15 more of these across the Session/Turn/Action row builders
```

If `"model_used"` is ever missing from the field map (a genuinely stale
schema, a corrupted `Fields` array, a future rename that misses this
file), `fmap.get(...)` doesn't fail loud — it silently returns `3` and
writes `model_used`'s value into whatever column index 3 *used* to mean.
This is worse than no field map at all: a pure positional-index version
would at least be honest about what it does, whereas this version *looks*
schema-safe while actually degrading to the exact behavior the Field Map
Cache system exists to prevent, and does so silently.

**Impact:** A future schema change to `_104DB_FIELDS` that isn't
perfectly mirrored in this file's fallback numbers produces column
corruption with no exception, no log line, nothing — it would surface
only as "the session log looks wrong" days or weeks later, with no error
to trace back to this file.

**Recommendation:** Replace `fmap.get(name, N)` with `fmap[name]` (raise
`KeyError` loud, which is the correct failure mode for a genuinely
missing/renamed field) or, if a soft-fail is truly wanted, `fmap.get(name)`
with an explicit `if idx is None: logger.error(...); continue` — never a
silent numeric guess.

---

### 4. `context_bubble.assemble_bubble()` re-reads and re-parses static data on every single turn (SEVERITY: MEDIUM, efficiency)

`assemble_bubble()` (line 903) is called once per model turn (every
message in every session, across agent.py/cliagent.py/webagent.py). Its
body calls, unconditionally, every time:

```
load_constants(config_dir)             # constants.bejson
_read_policy(p["policy"], ...)         # PERSISTENT_POLICY.md or similar
scan_triggers(user_msg, p["triggers"], ...)   # triggers.bejson (4.9 KB)
build_knowledge_section(p["knowledge"], ...)  # knowledge_pool.bejson (28 KB)
```

None of these files change mid-session in the overwhelmingly common case
— policy, triggers, and the knowledge pool are edited by the user between
sessions, not by the agent mid-turn (and if the agent *does* edit one of
them mid-session via a `bejson_*` action tag, that's a rare, detectable
event, not the steady-state case). Every turn currently pays the full
disk-read + JSON-parse + BEJSON-validate cost for ~35KB+ of substantially
static data, on top of whatever the turn's own actual work is.

**Impact:** On Android/Termux storage (the project's actual deployment
target per policy §4.3/§8.7), disk I/O latency is not free, and this cost
scales with conversation length for zero benefit in the common case. It's
not currently a *correctness* bug, but it is real, measurable, avoidable
per-turn latency that compounds over a long session.

**Recommendation:** Cache `load_constants`/`_read_policy`/trigger-doc/
knowledge-pool-doc results keyed by `(path, mtime)`, invalidating only
when the file's `mtime` actually changes (a two-line `os.stat().st_mtime`
check per file, checked once per turn, is far cheaper than re-parsing
28KB of JSON every turn). `scan_triggers` itself must still run every
turn (it depends on the live `user_msg`), but the *document it scans
against* doesn't need to be re-loaded from disk to do that.

---

### 5. Path-passing convention drift: explicit-parameter vs. module-global-set-once (SEVERITY: LOW-MEDIUM, standardization)

The dominant, and better, convention in this codebase is explicit paths
per call — `config_lib.init_config(config_path)`, `jobs.ensure_job_dirs
(jobs_dir)`, and everything in the new subagent family take their target
path(s) as arguments every time, matching policy §7.3's "never hardcode
paths" in spirit even though these aren't hardcoded, just not
parameterized per-call.

`lib_bejson_newagent_input.py` and `lib_bejson_newagent_backup.py` instead
use a "configure once at import/startup" global:

```python
_snippets_path: Optional[Path] = None
def init_input(snippets_path: Path) -> None:
    global _snippets_path
    _snippets_path = snippets_path
```

This works fine today because each of agent.py/cliagent.py/webagent.py is
its own process with its own one-time `init_input()` call. It becomes a
real problem the moment anything needs two different snippet stores in
one process — which is not hypothetical: a sub-agent session running with
its own `cwd`/profile might reasonably want its own snippets scope
separate from the main agent's, and this module structurally cannot
support that without a rewrite, whereas the explicit-parameter modules
already can.

**Impact:** Low today, but it's exactly the kind of inconsistency that
turns into a multi-file rewrite later instead of a non-issue, specifically
*because* the sub-agent family (which needs per-session isolation) now
exists as a real consumer that could hit this wall.

**Recommendation:** No urgent action. When either module needs its next
real feature touch, migrate it to explicit-parameter style to match the
rest of the codebase, rather than extending the global-state pattern
further.

---

### 6. Network-failure retry uses a fixed delay, not backoff+jitter (SEVERITY: LOW, hardening)

`lib_bejson_newagent_engine_rest.py`'s HTTP-status-based error handling
(429/401/403/5xx) is genuinely well-designed — distinct cooldown
semantics per failure class, with clear comments explaining the reasoning
for each (lines ~820-865). The one gap: the raw network-exception branch
(DNS failure, connection timeout, no connectivity — never reaching the
provider at all) uses a single fixed `NETWORK_ERROR_RETRY_DELAY` sleep
between attempts, not an exponential backoff.

**Impact:** Minor. A fixed delay is fine for a brief blip but wastes
retry budget hammering a real outage at a constant rate instead of
backing off, and offers no jitter if multiple concurrent turns (main
agent + dispatched sub-agents, now a real scenario post this session's
sub-agent work) hit a network failure simultaneously and retry in
lockstep.

**Recommendation:** Exponential backoff with jitter for this branch only
(`delay = base * (2 ** attempt) + random.uniform(0, jitter)`, capped).
Leave the HTTP-status-specific cooldowns exactly as they are — they're
already correctly differentiated and don't need this change.

---

### 7. Self-critique: known weaknesses in the sub-agent family delivered this session (SEVERITY: MEDIUM, disclosure)

An audit that only finds fault in pre-existing code isn't credible. Real
gaps in `lib_bejson_newagent_subagent_*.py` / `subagent_admin.py`:

- **No token/char budgeting on sub-agent history.** `update_session`'s
  `max_history_turns` trims by *turn count*, not by size —
  `context_bubble.py`'s `_budget_chars()` pattern (percentage-of-context
  budgets per section) has no equivalent here. A sub-agent profile with a
  high `max_turns` and a task that produces large tool outputs (e.g. a
  big file read) could accumulate a session history that blows the
  model's context window well before `max_turns` is reached.
- **`_ScopedModelRegistry` is a fragile duck-typed stand-in.** It exposes
  exactly the one attribute (`active`) `RestPrompter.prompt()` reads
  *today*. If `RestPrompter` ever grows a second read off `model_reg`
  (a new capability flag, a per-model timeout override, anything), the
  scoped stand-in silently has no such attribute and fails with an
  `AttributeError` deep inside a sub-agent turn instead of a clear
  "profile model_override needs an update" error at the call site.
- **No automatic pruning of `sessions.bejson`/`signals.bejson`.**
  Completed/errored sessions and consumed signals accumulate forever
  unless a caller explicitly calls `delete_session`/deletes consumed
  signal rows — there's no equivalent of a jobs-style cleanup sweep. For
  a lightly-used feature this is fine; if sub-agent dispatch becomes
  routine, both files grow unbounded.
- **Zero testing against a real API call.** Every test this session used
  a mocked `RestPrompter.prompt` (necessarily, since no live keys were
  available in this environment) — the actual network path, real model
  response parsing, and real key-rotation-under-sub-agent-load are
  unverified.

**Recommendation:** Track these as known-limitations (they already are, in
each file's own docstring/changelog), and treat "add token-aware history
trimming" as the first follow-up if sub-agent usage moves past
experimental — everything else here is acceptable technical debt for a
`subagents_enabled: false`-by-default feature, but the context-budget gap
is the one that will actually bite in real use before the others do.

---

### 8. No regression test suite (SEVERITY: MEDIUM, process)

There is no `tests/` directory anywhere in the audited scope. Every
verification this session (the config-lock stress test, the sub-agent
turn-loop tests, the malformed-JSON-doesn't-crash check) was written
ad hoc, run once, and discarded — meaning the *next* change to
`lib_bejson_newagent_config.py` or the subagent family has no automated
way to catch a regression of a bug that was already found and fixed once
this session (the token-generation race took two attempts and real
instrumentation to actually close; nothing stops a future edit from
reopening it silently).

**Impact:** Compounding risk — every audit like this one has to
re-discover known-good behavior from scratch instead of running a suite
and trusting green.

**Recommendation:** Promote the concurrency stress tests and the
subagent-turn-loop tests written this session into a permanent
`tests/test_config_locking.py` and `tests/test_subagent_runtime.py`
(or wherever the project's convention would put them — `dev/` per
policy §1.1's directory architecture is the closest existing fit if a
dedicated `tests/` folder isn't wanted). Even a handful of promoted tests
from this session would have caught the log-noise regression and the
file-creation race on the first try instead of needing live debugging.

---

### 9. Schema evolution handles additions, not renames (SEVERITY: LOW, refinement)

`config_lib.init_config()`'s backfill logic (the `changed = schema_stale`
path) correctly adds a newly-declared default field to an existing file
that predates it — this is exactly how `subagents_enabled` landed
correctly in pkg112's config.json backfill test this session. It has no
mechanism for a field *rename*: if `"exec_denylist"` were renamed to
`"exec_deny_patterns"` in a future version, every existing config.json
would silently keep the old field under its old name forever (backfill
only adds what's missing; it never migrates what's present under a
different name).

**Impact:** Low today — no renames have happened yet — but worth naming
explicitly since it's the kind of gap that's cheap to design for now and
expensive to retrofit once real user data depends on the old name.

**Recommendation:** If a rename is ever needed, ship it as an explicit
one-time migration step (read old name if present, write new name, drop
old), not as an extension of the additive-backfill path, which isn't
built for it.

---

### 10. Positional indexing against an in-memory literal (SEVERITY: LOW, minor)

`lib_bejson_newagent_engine_rest.py:1169`:
```python
known_profiles = {row[1]: row[6] for row in DEFAULT_MODEL_CATALOG}
```
`DEFAULT_MODEL_CATALOG` is a Python literal, not a loaded BEJSON file —
the schema-drift risk the no-positional-indexing rule exists to prevent
doesn't really apply to a constant defined three lines above its own use.
Flagged only because it's the one place in the audited scope that reads
as a literal violation of policy §6.2's wording even though the spirit
of the rule isn't at risk here.

**Recommendation:** Cosmetic only — convert to named tuples or a list of
dicts if this file is touched for other reasons; not worth a dedicated
change on its own.

---

## Actionable Suggestions (Summary)

1. **Retrofit `config_lib.get_or_create_web_auth_token()` and
   `subagent_common.with_file_lock()` to use `ResilientPIDLock`** instead
   of their own O_EXCL+timestamp locking. *Impact: removes an entire class
   of stale-lock/torn-read edge cases by construction; net code deletion,
   not addition.*
2. **Audit and fix the 4 bare `bejson_core_atomic_write()` calls in
   `mfdb_core.py`** (lines 527, 559, 891, 974) to check-and-handle the
   return value. *Impact: closes a real silent-data-loss path in the
   database layer.*
3. **Replace `fmap.get(name, N)` numeric fallbacks in
   `lib_bejson_newagent_session.py`** with loud failure on a missing
   field. *Impact: restores the actual guarantee the Field Map Cache
   system is supposed to provide for this file.*
4. **Cache `context_bubble.py`'s policy/triggers/knowledge-pool reads**
   keyed by mtime instead of re-reading every turn. *Impact: removes
   avoidable per-turn disk I/O and JSON-parse cost that compounds over
   long sessions.*
5. **Migrate `lib_bejson_newagent_input.py`/`backup.py` off module-global
   path state** to explicit-parameter style when next touched. *Impact:
   removes a structural blocker to per-session isolation the sub-agent
   family will eventually want.*
6. **Add exponential backoff+jitter to the raw-network-exception retry
   branch** in `engine_rest.py`. *Impact: better behavior under real
   outages and concurrent-turn contention; the HTTP-status-specific
   cooldowns are already fine as-is.*
7. **Add token/char-budgeted history trimming to the sub-agent
   runtime**, not just turn-count trimming. *Impact: prevents a
   long-running sub-agent from silently blowing its context window.*
8. **Promote this session's ad hoc stress tests into a permanent test
   suite** (`tests/` or `dev/`). *Impact: regressions of already-fixed
   bugs get caught automatically instead of requiring live re-debugging.*
9. **Design any future config field rename as an explicit migration
   step**, not an extension of the additive-backfill path. *Impact:
   avoids silent old-field-name persistence once real user data exists.*
10. **Cosmetic**: convert `engine_rest.py`'s `DEFAULT_MODEL_CATALOG`
    positional access to named access next time that file is touched.
    *Impact: negligible; full policy-letter compliance.*

---

## Implementation Roadmap

**Phase 1 — Data integrity (do first, low risk, high value):**
- Item 2 (mfdb_core.py unchecked writes) — mechanical, four call sites,
  no design change.
- Item 3 (session.py fallback landmine) — mechanical, ~17 call sites,
  no design change.

**Phase 2 — Concurrency consolidation:**
- Item 1 (ResilientPIDLock retrofit) — touches two files
  (`lib_bejson_newagent_config.py`, `lib_bejson_newagent_subagent_common.py`),
  each independently stress-testable the same way this session's fixes
  were (30+ concurrent threads, assert zero lost writes). Re-run both
  existing stress tests after the retrofit to confirm no regression
  before shipping.

**Phase 3 — Efficiency:**
- Item 4 (context_bubble caching) — the highest-value efficiency win
  found; benchmark before/after with a multi-turn session to quantify
  the actual latency reduction before calling it done.
- Item 6 (backoff+jitter) — small, isolated change to one retry branch.

**Phase 4 — Process/standardization (ongoing, not a single delivery):**
- Item 8 (test suite) — start with the two suites this session already
  proved out; grow incrementally rather than attempting full coverage in
  one pass.
- Items 5, 9, 10 — apply opportunistically the next time each affected
  file is touched for an unrelated reason, per policy §7.1's "surgical
  scope" principle rather than as standalone busywork deliveries.

**Not recommended as a phase:** a full audit of `tools/` and
`lib_extensions/`. Each is large enough (NA-CMS/NA-Chunker/NA-WebExtract/
NA-MD2HTML alone are multiple full applications) to warrant its own
dedicated audit request rather than being folded into this one at the
depth this report already went to for the core engine.
