# Idea: Dynamic Priority-Based Context Budget Reallocation
**Status:** HYPOTHETICAL / COMPLEX — explicitly deferred, not planned, not implemented.
**Date:** 2026-08-05

## What this actually is

This maps directly onto a system that already exists:
`lib_bejson_newagent_context_bubble.py`'s pkg015 pipeline already does the
"context window is a file, wiped and rebuilt each turn, budgeted in
percentages" part exactly as described. The categories already exist as
`constant_config.bejson` rows: `pct_persistent_policy`, `pct_active_tasks`,
`pct_env_file`, `pct_keyword_triggers`, `pct_knowledge_pool`,
`pct_cwd_context`, all sized against `max_context_tokens`.

What doesn't exist yet, and is the actual idea here: those percentages are
**fixed**. A category gets its slice whether it uses all of it or none of
it. The idea is to make the allocation **dynamic** — unused budget from an
under-filled category flows to categories that need more, ranked by
priority, instead of sitting unused or hard-capping a category that could've
used it.

## The idea, translated out of the physics metaphor

- Every category keeps its configured percentage as a **ceiling**, not a
  fixed amount. If a category only fills, say, 3% of its own 10% ceiling,
  the other 7% becomes available to redistribute.
- Redistribution follows **priority order**, not equal split: the
  highest-priority category that's actually hungry (wants more than its
  ceiling) gets first claim on the freed budget; if it's satisfied, the
  next-priority hungry category gets what's left; and so on.
- If nothing is hungry, freed budget just... doesn't get spent. No category
  is forced to pad itself to hit a target size.
- The "gravity / water in a pool" framing is really just: priority order
  determines the flow direction, and each pool only takes what it can hold
  before overflow moves to the next.

## Why this is genuinely complex (not just "add a formula")

- **Needs an explicit priority ranking**, not just percentages. Right now
  the six pct_* categories are peers with no declared precedence between
  them. This idea requires deciding — and Elton deciding, not a guessed
  default — which category outranks which when both are hungry at once.
- **"Hungry" needs a real definition per category.** Persistent policy and
  cwd context are closer to fixed-size (they either fit or they're
  truncated); keyword triggers and knowledge pool are naturally
  variable-size. A reallocation pass needs to know which categories can
  even meaningfully ask for more.
- **Interacts with the existing Observer (Part 4) compression step.**
  `run_observer_compression()` already exists to shrink an over-budget
  bubble; a reallocation layer changes what "over budget" even means per
  category, so the two would need to be designed together, not bolted on
  separately.
- **Ordering/determinism matters for debugging.** The current fixed-percent
  system is easy to reason about: category X is capped at Y tokens, full
  stop. A flowing/overflow model needs to stay just as inspectable, or
  every future "why did the bubble drop my knowledge pool row" question
  becomes much harder to answer.

## What this would touch, if built

- `constant_config.bejson`: would need a new priority-ordering field
  alongside the existing pct_* rows.
- `assemble_bubble()` in `lib_bejson_newagent_context_bubble.py`: the
  per-category token-budget math currently treats each pct_* value as a
  hard slice; this would replace that with the priority-ordered
  fill-then-overflow pass described above.
- Logging (`context_logs.bejson` / `logger.update_last_bubble()`): would
  want to record what got reallocated where, or the flowing behavior
  becomes invisible/undebuggable exactly when it matters most.

No code written, no priority ordering guessed. Logged here per Elton's
instruction so the idea isn't lost, to be designed properly (starting with
"what's the actual priority order between these six categories") when
there's time to do it right rather than as a quick add-on.
