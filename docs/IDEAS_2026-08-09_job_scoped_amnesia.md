# Idea: Job-Scoped Amnesia/Rebirth for Focused Subagent/Job Execution
**Status:** HYPOTHETICAL — idea only, not planned, not implemented.
**Date:** 2026-08-09
**Related:** lib_bejson_newagent_jobs.py (Job Creation System, pkg063-066),
lib_bejson_newagent_context_bubble.py's Amnesia/Rebirth (pkg067)

## The idea, as described

Before starting a job, run `/amnesia` to compress and wipe the agent's
general session memory. Then `/jobstart <job>` feeds in *only* that job's
context (goal + tasks) -- a genuinely clean slate, no unrelated session
history to wade through, full focus on the task. On job completion,
`/rebirth` restores the general session context so the agent picks back up
where it left off before the job.

## The wrinkle: rebirth restores *pre-job*, not *post-job*

As built today, `/rebirth` retrieves whatever recap `/amnesia` saved at the
moment it ran -- i.e. it restores the agent to *before* the job, not
*after*. If the job produced useful work or decisions, a naive rebirth
would hand the agent a memory as if the job never happened, discarding
whatever the job's own execution history contained.

A real implementation needs three states, not two:

1. **Pre-job recap** -- compressed general session context (what
   `save_amnesia_recap` already does today, unchanged).
2. **Job execution** -- clean slate + job context only (already works:
   `/jobstart` injects goal/tasks without touching history; running
   `/amnesia` with `auto_amnesia_memory_retrieval` off first gets the
   "clean slate" half of this for free).
3. **Post-job merge** -- pre-job recap + a compressed summary of what the
   job itself did, combined into whatever `/rebirth` ultimately feeds back
   in. This piece doesn't exist yet. Today's `/rebirth` has no idea a job
   ran in between and can't fold its output back in.

## Where this would actually hook in

`lib_bejson_newagent_jobs.py::mark_task_completed()` already knows the
exact moment a job finishes -- that's where it currently just moves the
job file to `jobs/complete/`. That's the natural hook point for a
"job-scoped amnesia" wrapper: on the job's last task completing, compress
*the job's own history* (reusing `run_full_session_compression` on
whatever accumulated during job execution), merge that with the saved
pre-job recap (probably just concatenation with a section header, or a
second compression pass over both combined), and write *that* merged
result to wherever `/rebirth` reads from -- rather than the stale pre-job
snapshot alone.

## Open questions for whenever this gets picked up

- Should the merge be automatic the instant the job completes, or should
  `/rebirth` itself trigger the merge lazily (compress job history only
  at retrieval time, not at completion time)?
- Does this want its own command (e.g. `/jobamnesia <job>` that chains
  amnesia + jobstart in one step), or stay as manual `/amnesia` then
  `/jobstart` for now?
- Multiple jobs run back-to-back before a rebirth -- does each one's
  output get merged in independently, or does starting job #2 without a
  rebirth in between just discard job #1's contribution?
