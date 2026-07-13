# Fixture: design infeasible at implementation time (`fixtures/sample-project`)

Step 4 Tier-2 verification input (docs/implementation/step-04-implementer.md). A raw request whose
design can look executable on paper but turns out to rest on a capability that does not exist in
`fixtures/sample-project` — exercising `L5`/`GE1` (implementer → designer, `design_infeasible`).

## Raw request

> Make `IntStack` (`fixtures/sample-project`) grow past `INTSTACK_CAPACITY` automatically instead
> of rejecting the push, by reusing the project's existing dynamic-array-resize helper.

## Why this triggers an implementation-time infeasibility

A plausible design reads cleanly on its own ("on overflow, call the project's existing resize
helper to grow `items` and retry the push") — nothing about it looks obviously wrong to the
designer working from the spec and the file list alone. The gap only surfaces once the
implementer actually goes looking for that helper: **`fixtures/sample-project` has no
dynamic-array-resize helper anywhere** — `IntStack.items` is a fixed-size array member (design doc
§2 Implementer: "journal any deviation forced by reality and, if the deviation invalidates the
design, hand back to the designer"). Growing it would require changing `IntStack`'s storage from
an inline array to a heap-allocated buffer — a different data structure, not a bug fix within the
approved design — so this is a design invalidation, not an implementation detail to route around
silently.

## Expected agent behavior (for manual dogfooding)

- Refiner and designer both proceed without escalating (the request looks internally consistent
  and buildable from the spec alone; the missing helper is not discoverable without the
  implementer's own code-level exploration).
- Implementer, while implementing the design, discovers there is no resize helper to reuse and
  that satisfying the design as written requires restructuring `IntStack`'s storage — outside
  what "implement exactly the design" licenses it to decide on its own. It writes its reasoning to
  `node-state/implementer.json` (`{"status": "design_infeasible", "detail": "..."}`), journals the
  finding, and ends its turn with `outcome: design_infeasible` **without** committing any
  half-finished change to the worktree.
- Because `G2` was already approved, `GE1` auto-activates regardless of gate preset when the
  rollback reaches the designer (design doc §6 "Overrides" approval-invalidation rule).
