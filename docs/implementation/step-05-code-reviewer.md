# Step 5 — Code reviewer + rework loops & loop budgets

| | |
|---|---|
| **Depends on** | [Step 4](step-04-implementer.md) |
| **Implements** | [§2 Code reviewer](../agent-pipeline-design.md#code-reviewer), [§5 loops L1/L2/L5 + loop budgets](../agent-pipeline-design.md#loop-budgets), [§6 G4/GE1](../agent-pipeline-design.md#6-human-gating) |
| **Status** | Planned |

## Goal

Replace the code-reviewer stub with the real adversarial reviewer, and make the pipeline's **rework
machinery** real: the L1 (→implementer) and L2 (→designer) bounce edges, the L5 escalation, per-edge
**loop budgets** with escalation on exhaustion, and gate G4. After this step, R→D→I→CR is a fully
real, self-correcting loop; DOC→S remain stubs.

## Scope

**In:** `agents/code_reviewer.md`; `review_report` artifact + verdict contract; loop-budget counters
and exhaustion escalation; G4 gate; GE1 auto-activation on L2/L5.
**Out:** docs review (Step 6 reuses this loop machinery); post-PR loops L7–L10 (Step 8).

## Deliverables (tree delta)

```
agents/code_reviewer.md
lib/loop_budget.py            # per-edge bounce counters + exhaustion → escalation
tests/test_loop_budget.py
fixtures/tasks/review-*       # diffs with seeded bugs / design flaws / traceability gaps
```

## Technical design

### Code reviewer (`code_reviewer.md`)
[§2 Code reviewer](../agent-pipeline-design.md#code-reviewer), autonomy `decide` (never asks the user
directly — disagreement is expressed through the graph):
- Check correctness, edge cases, style, and that the **diff matches the design** (not just "looks
  good").
- Verify acceptance criteria against `verification_evidence`; **re-run checks** when evidence is
  missing or stale (via `lib/checks.py`).
- **Audit the traceability chain** — every automatable criterion maps to a designed test case and an
  implemented, passing test; a broken link is a **blocking** finding.
- Classify findings blocking vs. advisory; advisory-only ⇒ approve.
- Distinguish implementation bugs (→L1 implementer) from design flaws (→L2 designer); **never patches
  code itself**.
Produces `review_report` (markdown) with an explicit **verdict ∈ {approve, request_changes,
escalate_design}** and itemized findings. Verdict is the typed outcome the orchestrator routes on.

### Loop budgets (`lib/loop_budget.py`)
[§5 loop budgets](../agent-pipeline-design.md#loop-budgets): per-edge bounce counters persisted in the
pipeline-state history. Defaults `loop_limits.*`: L1 max 3, L2/L5 max escalations 2. On each bounce
the orchestrator increments the counter and logs `loop_increment`; on exhaustion it **escalates to
the human** with both sides' arguments to pick direction or abort ([§15](../agent-pipeline-design.md#15-failure-handling-orchestrator-level)) —
preventing infinite review ping-pong. Counters are data in the state file, not LLM memory, so the
bound is reliable despite pure-agent routing.

### Routing & gates
- **G4** (`code_review_signoff`) on T4 (code_reviewer→documenter) — present the `review_report`.
  Active on the default linear spine and Option C; **absent in Option B** (approval feeds the join
  gated by G6). Table-driven, so this difference is data.
- **L1** (request_changes → implementer): ungated by default; re-enters the implementer with the
  report; the implementer re-greens its inner loop and returns to CR.
- **L2/L5** (design flaw / design infeasible → designer): **GE1** auto-activates (rework of a
  G2-approved design may invalidate that approval).

## Verification

**Tier 1 — unit tests:**
- `loop_budget.py`: counters increment per edge; L1 exhausts at 3 and raises the escalation; L2/L5
  exhaust at 2; counters survive a state reload; distinct edges count independently.

**Tier 2 — end-to-end (real R+D+I+CR, stubbed DOC→S):**
- **Clean diff:** reviewer approves with only advisory findings; routes G4 → (stub) documenter.
- **Seeded implementation bug:** reviewer returns `request_changes` with a blocking finding → L1 →
  implementer fixes and re-greens → CR approves. State history shows one L1 loop_increment.
- **Seeded design flaw:** `escalate_design` → L2 → GE1 fires → designer rework → re-run downstream.
- **Traceability gap:** a criterion with no implemented test is caught as a blocking finding.
- **Stale/missing evidence:** reviewer re-runs checks rather than trusting the report.
- **Budget exhaustion:** a diff that keeps failing review 3× trips the L1 budget → escalation to the
  human with both arguments.

## Definition of done

- [ ] Reviewer issues an explicit verdict with itemized blocking/advisory findings.
- [ ] Diff-vs-design and full traceability-chain audit performed; broken link ⇒ blocking.
- [ ] L1/L2/L5 route correctly; reviewer never edits code.
- [ ] Loop budgets enforced from state-file counters; exhaustion escalates with both sides' arguments.
- [ ] GE1 auto-activates on L2/L5; G4 present on the linear spine, dormant for Option B.
