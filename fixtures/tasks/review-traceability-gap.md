# Fixture: code reviewer catches a traceability-chain gap (`fixtures/sample-project`)

Step 5 Tier-2 verification input (docs/implementation/step-05-code-reviewer.md). Exercises the
traceability-chain audit itself, independent of any functional bug: one acceptance criterion has
no implemented test, so the criterion→test-case→implemented-test chain is broken even though
every check that *does* run is green.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request (`intstack_peek`), which has two acceptance
criteria in `refined_spec` (happy-path peek; peek on an empty stack) and two designed test cases
in `design_doc`, one per criterion. After the implementer converges, manually delete the
empty-stack test from the diff (and its entry from `verification_evidence`'s criterion-to-test
map) while leaving the happy-path test and the `intstack_peek` implementation itself untouched and
correct — `resolved_checks` still comes back all-green, because the remaining tests all pass; only
the empty-stack criterion is now silently untested.

## Why this exercises the traceability audit specifically

Every check the reviewer could re-run (`lib.checks.run_all`) reports green — there is no failing
build, test, or static check to point at. The gap is only visible by **walking the three
documents together**: `refined_spec` still lists the empty-stack acceptance criterion,
`design_doc` still lists its test case, but `verification_evidence`'s criterion-to-test map has no
corresponding implemented test — the chain's last link is missing. A reviewer that only re-runs
checks (rather than auditing the chain per design doc §2 Code reviewer's "DRAFT REQ") would
approve this diff.

## Expected agent behavior (for manual dogfooding)

- Code reviewer: `lib.checks.run_all` (if re-run) comes back all-green; auditing the three
  documents together, the reviewer finds the empty-stack criterion has a designed test case but no
  matching entry in `verification_evidence`'s map and no such test present in the diff. Classifies
  this a **blocking** finding (design doc §2: "a broken link is a blocking finding") — never
  advisory, regardless of how green the checks are. Because the design's test case is
  correct and only the implementation is missing it, this is an implementation gap the implementer
  can close: verdict `request_changes`.
- Orchestrator: routes `L1` (→ implementer, ungated).
- Implementer (respawned): reads `review_report`, adds the missing empty-stack test (still
  passing, since `intstack_peek`'s own logic was never touched), updates
  `verification_evidence`'s map, hands back `outcome: code_complete`.
- Code reviewer (second visit): the chain is now unbroken; verdict `approve`.
