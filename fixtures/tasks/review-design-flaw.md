# Fixture: code reviewer escalates a design flaw (`fixtures/sample-project`)

Step 5 Tier-2 verification input (docs/implementation/step-05-code-reviewer.md). Exercises `L2`
(code_reviewer → designer, `escalate_design`) and `GE1` auto-activation: a diff that faithfully
implements `design_doc` — checks green, traceability chain intact — but where the flaw is in the
design itself, not in how the implementer executed it.

## Raw request

Reuse `fixtures/tasks/impl-add-peek.md`'s raw request (`intstack_peek`), but manually author
`design_doc` with a seeded off-by-one: instead of "read `items[count - 1]` without modifying
`count`" (the correct top-of-stack index, matching how `intstack_push`/`intstack_pop` already
index — `intstack_push` writes the new value at `items[count]` and *then* increments `count`, so
the top element always lives at `items[count - 1]`), the design specifies "read `items[count]`."
Have the designer's test case and the implementer's diff both faithfully follow this design: the
test asserts `intstack_peek` returns whatever happens to sit at `items[count]` (uninitialized or
stale data from a prior pop, depending on the stack's history), and the implementer, coding exactly
to the design, makes that test pass.

## Why this is a design flaw, not an implementation bug

The diff matches `design_doc` exactly, checks are green, and the traceability chain is intact —
there is nothing here for `request_changes`/`L1` to fix: the implementer did precisely what it was
told, correctly. The defect is that `design_doc` itself specifies the wrong index, one that
returns garbage instead of the top-of-stack value `refined_spec`'s acceptance criterion actually
asks for ("look at the top ... without removing it") — a reviewer must compare the design's chosen
index against `intstack_push`/`intstack_pop`'s own established indexing convention (both already
in the diff, both correct) to notice the mismatch.

## Expected agent behavior (for manual dogfooding)

- Code reviewer: diff matches `design_doc` exactly, checks are green, the traceability chain
  holds — but comparing the design's `items[count]` against how `intstack_push`/`intstack_pop`
  already index the same array (`items[count - 1]` is the top), the reviewer determines the
  design's chosen index is wrong and no implementation-level fix (the diff already matches the
  design faithfully) resolves it. Verdict `escalate_design`; `review_report` names the mismatched
  index and cites the existing `push`/`pop` convention as evidence.
- Orchestrator: routes `L2` (→ designer). Because `G2` was already approved for this pipeline,
  `GE1` auto-activates regardless of the run's gate preset (design doc §6 "Overrides" approval-
  invalidation rule) — the human sees the escalation even under `full_auto`.
- Designer (respawned): corrects `design_doc`'s index to `items[count - 1]` and its test case's
  expected value, returns `outcome: design_ready`; the pipeline re-runs downstream from there and
  the implementer's corrected diff converges on the next pass.
