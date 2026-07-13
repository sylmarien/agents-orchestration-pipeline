# Fixture: design-time spec gap

Step 3 Tier-2 verification input (docs/implementation/step-03-refiner-designer.md). A raw task
whose spec can look complete to the refiner but hides a gap only the design phase surfaces —
exercising `L4`/`GE2` (designer → refiner, `spec_gap`).

## Raw request

> Enforce the configured token budget (`budget.tokens`) by rejecting a pipeline run outright, at
> spawn time, if it would exceed the budget.

## Why this triggers a design-time gap

A plausible `refined_spec` reads cleanly on its own ("if `budget.tokens` is set and the estimated
run cost exceeds it, refuse to start the pipeline and report why") — nothing about it looks
untestable or ambiguous to the refiner. The gap only appears once the designer tries to turn it
into an actual design: **there is no estimator anywhere in this build that predicts a pipeline's
token cost before it runs** (`lib/budget.py` doesn't exist until Step 9, and even there the design
doc's resource-budgets model is *metering as you go*, not *pre-run estimation* — see design doc
§10). The spec asked for a capability ("estimated run cost") that nothing upstream defined how to
produce.

## Expected agent behavior (for manual dogfooding)

- Refiner accepts the spec as internally consistent (it has no way to know an estimator doesn't
  exist without doing design-level exploration) and reaches G1.
- Designer, while identifying files/modules to touch, discovers there is no pre-run cost
  estimation mechanism to build on and no acceptance criterion in the spec defining what
  "estimated run cost" should even mean (e.g. a fixed per-agent token allowance? a historical
  average? user-supplied?) — a genuine spec gap, not a design choice the designer should just
  pick for itself. Designer emits `spec_gap` (`L4`) with that detail instead of guessing.
- Because G1 was already approved, `GE2` auto-activates regardless of gate preset when the
  rollback reaches the refiner (design doc §6 "Overrides" approval-invalidation rule).
