# Fixture: documenter documents a user-visible change, docs reviewer approves (`fixtures/sample-project`)

Step 6 Tier-2 verification input (docs/implementation/step-06-documenter-docs-reviewer.md). The
baseline case: run the full R→D→I→CR→DOC→DR loop over an unmodified `impl-add-peek` request (same
one `fixtures/tasks/review-clean.md` uses) and confirm the documenter documents the new function
and the documentation reviewer approves on the first pass, routing G6 to the (stub) submitter.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request verbatim (`intstack_peek`) against a fresh
copy of `fixtures/sample-project`. Do not seed any bug, design flaw, aspirational doc claim, or
internal-only change — this fixture exercises the documenter's and documentation reviewer's
straightforward *approve* path.

## Why this exercises the documenter and documentation reviewer

- `intstack_peek` is a new public function (`include/intstack.h`, mirroring `intstack_pop`'s
  shape) — squarely a user-visible/interface change per design doc §2 Documenter: the sample
  project's `README.md` (which already documents `intstack_push`/`intstack_pop`) needs a matching
  entry for `intstack_peek`, including its empty-stack failure behavior.
- Nothing here is internal-only, so `documenter.skip_allowed` never comes into play; this is the
  path most runs take.
- The documentation reviewer must verify the documenter's prose against the actual diff (does the
  documented empty-stack behavior match what `intstack_peek` really returns?) and against
  `refined_spec`'s acceptance criteria (both the happy-path and empty-stack criteria need to be
  covered by the docs), not just accept the documenter's own account.

## Expected agent behavior (for manual dogfooding)

- Documenter: reads `diff` (`git diff <base_commit>..<pre_docs_commit>`), `design_doc`,
  `refined_spec`, `implementation_notes`; adds an `intstack_peek` entry to
  `fixtures/sample-project/README.md` alongside the existing `push`/`pop` entries, describing both
  the happy path and the empty-stack failure mode; commits it; writes `pr_summary.md` summarizing
  what/why/how-verified; ends with `outcome: docs_ready`.
- Orchestrator: captures `pre_docs_commit` before this, the documenter's first spawn in this
  pipeline; routes T5 (→ documentation reviewer) under gate G5.
- Documentation reviewer: reads `docs_changeset` (`git diff <pre_docs_commit>..HEAD`) against
  `diff` and `refined_spec`; the new README entry matches `intstack_peek`'s actual behavior and
  covers both acceptance criteria; no findings; verdict `approve`; ends with `outcome: approve`.
- Orchestrator: routes T6 (→ stub submitter) under gate G6; no `L3` loop-budget counter is ever
  incremented for this pipeline.
