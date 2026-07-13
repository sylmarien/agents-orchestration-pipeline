# Fixture: implementer happy path (`fixtures/sample-project`)

Step 4 Tier-2 verification input (docs/implementation/step-04-implementer.md). Run against
`fixtures/sample-project` as `repo_root`: a raw request with a straightforward, unambiguous
implementation so the refiner and designer both converge cleanly, and the interesting behavior to
observe is the **implementer's** inner green loop, not upstream ambiguity.

## Raw request

> Add a way to look at the top of the `IntStack` (`fixtures/sample-project`) without removing it.
> Calling it on an empty stack must not crash or read out-of-bounds memory — it should report
> failure the same way `intstack_pop` does on an empty stack.

## Why this exercises the implementer

- The spec/design are both single-reading: one new function (`intstack_peek`, mirroring
  `intstack_pop`'s `int stack, int *out) -> 0/-1` shape), one new acceptance criterion, one new
  designed test case. Refiner and designer should each converge without escalating — the fixture
  isolates the implementer's own machinery.
- The sample project ships green (build + test + format-check + lint all pass as committed) with
  `intstack_peek` deliberately absent, so the implementer starts from a genuinely green baseline
  and must keep it green through the addition.
- Implementing test-first is natural here: the design's test cases (peek returns the top value
  without changing `count`/`is_empty`; peek on an empty stack returns the sentinel failure and
  leaves the stack untouched) can be written as failing tests against the not-yet-existing
  `intstack_peek` before it's implemented — i.e. before the production code even compiles, which
  the implementer's TDD-first requirement must handle by writing the failing test, watching the
  *build* fail (not just the test), then implementing the function.
- A seeded loop-convergence check per the step 4 doc ("a task needing several iterations converges
  within budget"): implement `intstack_peek` first without the empty-stack guard, observe the new
  empty-stack test fail, fix, reconverge — a small but real multiple-iteration case. Artificially
  capping `implementer.inner_loop.max_iterations` to `1` for this same task should instead force
  the exhaustion escalation (`escalation: inner_loop_exhausted`) rather than a hand-off of red
  work.

## Expected agent behavior (for manual dogfooding)

- Refiner: one acceptance criterion for the happy-path peek, one for the empty-stack case; both
  mechanically testable; no escalation.
- Designer: two test cases mapped 1:1 to the two criteria (unit level); no `spec_gap`.
- Implementer: writes both tests failing first, implements `intstack_peek` in
  `include/intstack.h` + `src/intstack.c`, reaches all-green (build + test + format-check + lint),
  records `verification_evidence` with the criterion→test map, and ends with
  `outcome: code_complete`.
