# Fixture: code reviewer approves a clean diff (`fixtures/sample-project`)

Step 5 Tier-2 verification input (docs/implementation/step-05-code-reviewer.md). The baseline
case: run the full R→D→I→CR loop over an unmodified `impl-add-peek` request and confirm the
reviewer approves on the first pass, with no rework loop triggered.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request verbatim (`intstack_peek`) against a fresh
copy of `fixtures/sample-project`. Do not seed any bug, design flaw, or traceability gap — this
fixture exists to exercise the reviewer's *approve* path, not its adversarial one.

## Why this exercises the code reviewer

- The implementer converges genuinely green (design doc §2 Implementer: "never hand off red
  work"), with a complete criterion→test-case→implemented-test chain (both acceptance criteria
  covered, both tests present and passing).
- There is nothing here for the reviewer to object to: correctness, edge cases, and style are all
  in order, the diff matches the design, and the traceability chain is unbroken.

## Expected agent behavior (for manual dogfooding)

- Code reviewer: reads the diff (`git diff <base_commit>..HEAD`), `design_doc`, `refined_spec`,
  `implementation_notes`, and `verification_evidence`; finds at most advisory-level findings (if
  any); writes `review_report` with `Verdict: approve`; ends with `outcome: approve`.
- Orchestrator: routes T4 (→ documenter) under gate G4; no `L1`/`L2` loop-budget counter is ever
  incremented for this pipeline.
