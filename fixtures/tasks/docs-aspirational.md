# Fixture: docs reviewer catches an aspirational doc claim (`fixtures/sample-project`)

Step 6 Tier-2 verification input (docs/implementation/step-06-documenter-docs-reviewer.md).
Exercises `L3` (documentation_reviewer → documenter, `request_changes`): a docs changeset that
reads plausibly but overstates what the code actually does, so the documentation reviewer must
catch it by comparing prose against the diff, not by trusting the documenter's account.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request (`intstack_peek`), then, after the code
reviewer approves (as in `fixtures/tasks/review-clean.md`), manually seed this aspirational claim
into the documenter's README entry before the documentation reviewer sees it:

> Document `intstack_peek` as also *removing* the top element after reading it (i.e. describe it
> as behaving like `intstack_pop` that happens to also return the value) — the opposite of what
> the design doc and the diff actually specify (peek must leave `count`/the stack unchanged).
> Leave the actual `intstack_peek` implementation and its tests untouched and correct; only the
> prose is wrong.

## Why this exercises the documentation reviewer

- The doc reads fluently and isn't self-contradictory — a reviewer that only skims for internal
  consistency approves it. The documentation reviewer must read `docs_changeset` against the
  actual `diff` (design doc §2 Documentation reviewer: "no aspirational docs") to notice the
  described behavior contradicts what `intstack_peek` really does (it does not mutate `count`).
- This is squarely a documenter defect, not a code defect: `diff` is exactly what the code reviewer
  already approved in `review-clean.md`'s run; only the new prose is wrong.

## Expected agent behavior (for manual dogfooding)

- Documentation reviewer: reads `docs_changeset` against `diff`; finds the README's "removes the
  top element" claim contradicts `intstack_peek`'s actual (unchanged) effect on `count`; itemizes
  it in `docs_review_report`, quoting the doc's claim and the diff's actual behavior; verdict
  `request_changes`; ends with `outcome: request_changes`.
- Orchestrator: routes `L3` (→ documenter, ungated); increments the `L3` loop-budget counter to 1
  (`lib.loop_budget.record_bounce`, `budget_class: l3`, `exceeded: false` against the default limit
  of 3).
- Documenter (respawned): reads `docs_review_report`, corrects the README entry to describe
  `intstack_peek` as non-mutating, re-commits, hands back `outcome: docs_ready`.
- Documentation reviewer (second visit): the claim now matches the diff; verdict `approve`.
