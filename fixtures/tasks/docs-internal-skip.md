# Fixture: documenter skips a purely internal change, journaled for human veto (`fixtures/sample-project`)

Step 6 Tier-2 verification input (docs/implementation/step-06-documenter-docs-reviewer.md).
Exercises the documenter's skip-with-justification path (`documenter.skip_allowed: true`, the
built-in default) and the documentation reviewer's independent check that the skip was actually
warranted.

## Raw request

> Refactor `fixtures/sample-project/src/intstack.c` so `intstack_push` and `intstack_pop` share
> their bounds-check logic in one static helper, with no change to any public function's signature,
> behavior, or the `README.md`-documented interface. Build, tests, and lint must remain exactly
> green throughout — this is a pure internal deduplication.

## Why this exercises the documenter and documentation reviewer

- There is no new function, no changed signature, no new config knob, and no behavior change a
  user or downstream caller would ever observe — squarely the "genuinely needs no docs" case
  design doc §2 Documenter's skip clause describes, distinct from `docs-aspirational.md` and
  `docs-user-visible.md` where real user-visible surface exists.
- The documentation reviewer must not simply accept an empty `docs_changeset` — it independently
  re-derives, from `diff` and `refined_spec`, that the change truly has no user-visible/interface
  surface before approving (this fixture's `diff` should make that easy to confirm: same public
  signatures, same `README.md`-documented behavior, only a private static helper introduced).
- The skip is journaled `pending_review`, not silently dropped — it rides along with G5's bundle so
  a human running under `checkpoint` or `paranoid` sees and can veto it.

## Expected agent behavior (for manual dogfooding)

- Documenter: surveys `diff` against `design_doc`/`refined_spec`; finds no user-visible or
  interface surface; makes no doc commits; journals the skip
  (`agent='documenter'`, `stage_artifact='docs_changeset'`, `reversal_cost='low'`,
  `status='pending_review'`) with a rationale naming the specific absence (no new/changed public
  signature, no new knob, no behavior change); writes `pr_summary.md` noting the skip explicitly;
  ends with `outcome: docs_ready`.
- Orchestrator: routes T5 (→ documentation reviewer) under gate G5, presenting the pending journal
  entry alongside the (empty) `docs_changeset` per the gate bundle (design doc §6).
- Documentation reviewer: sees an empty `docs_changeset`; reads the journal entry; independently
  confirms against `diff` that no public signature, behavior, or knob changed; agrees the skip was
  justified; verdict `approve`; ends with `outcome: approve`.
- Orchestrator: routes T6 (→ stub submitter) under gate G6. Under `checkpoint` (the shipped
  default), G5/G6 are both off, so the skip is logged as passed-through; under `paranoid` or with
  G5 explicitly added, the human sees the pending skip entry and may override it (per
  `skills/decisions/SKILL.md`) before the run proceeds — verify both presets manually.
