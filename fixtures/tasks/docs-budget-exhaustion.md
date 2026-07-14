# Fixture: repeated docs failures trip the `L3` budget (`fixtures/sample-project`)

Step 6 Tier-2 verification input (docs/implementation/step-06-documenter-docs-reviewer.md).
Exercises loop-budget exhaustion on `L3` (default `loop_limits.l3: 3`, `lib/loop_budget.py`,
reused unchanged from Step 5): a docs changeset the documentation reviewer keeps bouncing, so the
orchestrator escalates instead of looping forever.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request (`intstack_peek`). Manually script the
documenter to reintroduce a variant of `docs-aspirational.md`'s seeded error on every visit (e.g.
each rework "fixes" the flagged sentence but immediately restates the same removes-the-top-element
claim in different words) so the documentation reviewer returns `request_changes` three times
running, without ever converging.

## Why this exercises the `L3` loop budget specifically

- Each individual bounce is a legitimate, well-formed `request_changes` verdict (as in
  `docs-aspirational.md`) — the interesting behavior isn't the reviewer's judgement on any one
  visit, it's the orchestrator's bookkeeping across repeated visits to the same edge.
- `lib.loop_budget.record_bounce`'s `budget_class_for_edge` maps `L3` → `loop_limits.l3` (default
  `3`) independently of `L1`'s counter (default `3`) or the `escalations` class `L2`/`L4`/`L5`
  share — this fixture should show the `L3` counter incrementing on its own without touching any
  other edge's count.

## Expected agent behavior (for manual dogfooding)

- Documentation reviewer (1st, 2nd, 3rd visits): each finds the restated aspirational claim;
  verdict `request_changes` each time.
- Orchestrator: on the 1st bounce, `record_bounce('<state_dir>', 'L3', <loop_limits>)` returns
  `count: 1, exceeded: false`; 2nd bounce `count: 2, exceeded: false`; 3rd bounce `count: 3,
  exceeded: true` against the default `loop_limits.l3: 3` (a limit of 3 permits exactly 3 bounces;
  the 3rd is the one that trips it, matching `L1`'s documented semantics in
  `docs-aspirational.md`/`review-impl-bug.md`).
- Orchestrator: on `exceeded: true`, stops routing `L3` and escalates to the human with both
  sides' most recent arguments (the documenter's latest doc commit and the documentation
  reviewer's latest `docs_review_report`), per design doc §15 — the human picks a direction (raise
  the limit and retry, hand-edit the docs directly, or abort) rather than the pipeline bouncing a
  4th time unattended.
