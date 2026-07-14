# Fixture: code reviewer catches an implementation bug the checks missed (`fixtures/sample-project`)

Step 5 Tier-2 verification input (docs/implementation/step-05-code-reviewer.md). Exercises `L1`
(code_reviewer → implementer, `request_changes`): a diff whose build/tests genuinely pass, but
that still has a real correctness bug the reviewer must catch by reading the diff itself, not by
trusting `verification_evidence`.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request (`intstack_peek`), then, after the
implementer converges all-green, manually mutate the committed diff to seed this bug:

> In `intstack_peek`, swap the empty-stack guard's comparison so it reads
> `if (!intstack_is_empty(stack))` (inverted) before writing to `*out`, instead of guarding against
> the empty case. Leave the happy-path test (`push` then `peek`) passing — construct the seeded
> variant so its own **existing** designed test cases still pass with the mutation (e.g. by also
> loosening the empty-stack test's assertion to something the buggy code satisfies), so the bug
> survives the implementer's own inner green loop and lands in `verification_evidence` marked
> all-green.

## Why this exercises the code reviewer

- `resolved_checks` are green and `verification_evidence` claims full coverage — a reviewer that
  only re-runs checks or trusts the implementer's report approves this diff. The reviewer must
  actually read `intstack_peek`'s logic against `design_doc`'s described behavior (peek on an
  empty stack must fail the same way `intstack_pop` does) to notice the guard is inverted.
- This is squarely an **implementation bug**, not a design flaw: `design_doc`'s design is correct
  and testable as written; the diff just doesn't implement it correctly.

## Expected agent behavior (for manual dogfooding)

- Code reviewer: finds the inverted guard; classifies it **blocking** (correctness — empty-stack
  peek can read/report success incorrectly); verdict `request_changes`; `review_report` names the
  exact file/line and explains the expected vs. actual guard condition.
- Orchestrator: routes `L1` (→ implementer, ungated); increments the `L1` loop-budget counter to
  1 (`lib.loop_budget.record_bounce`, `budget_class: l1`, `exceeded: false` against the default
  limit of 3).
- Implementer (respawned): reads `review_report`, fixes the guard, re-greens, hands back
  `outcome: code_complete`.
- Code reviewer (second visit): the guard is now correct; verdict `approve`.
