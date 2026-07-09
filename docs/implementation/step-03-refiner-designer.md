# Step 3 — Refiner + Designer, gates G1/G2, decision journal, autonomy gradient

| | |
|---|---|
| **Depends on** | [Step 2](step-02-orchestrator-core.md) |
| **Implements** | [§2 Refiner](../agent-pipeline-design.md#refiner), [§2 Designer](../agent-pipeline-design.md#designer), [§6 gates G1/G2/GE2](../agent-pipeline-design.md#6-human-gating), [§7 Autonomy gradient](../agent-pipeline-design.md#7-autonomy-gradient), [§8 Decision journal](../agent-pipeline-design.md#8-decision-journal) |
| **Status** | Planned |

## Goal

Replace the first two stubs with real agents and build the two cross-cutting systems they exercise
first: the **decision journal** and the **autonomy gradient**. After this step the pipeline produces
a real `refined_spec` and `design_doc`, pauses at G1/G2 under `checkpoint`, and surfaces journaled
decisions at every prompt. Nodes I→S remain stubs.

## Scope

**In:** `agents/refiner.md`, `agents/designer.md`; decision-journal schema, storage, presentation,
and override→rollback; autonomy-gradient escalation mechanism (`ask_freely`, `lean_ask`); the
`decisions` skill; GE2 auto-activation.
**Out:** implementer onward (stubbed); ticket spec-sync (Step 10).

## Deliverables (tree delta)

```
agents/refiner.md
agents/designer.md
commands/decisions.md
skills/decisions/SKILL.md
lib/journal.py                # journal read/write/merge + override→rollback resolution
tests/{test_journal.py, test_autonomy.py}
fixtures/tasks/*              # sample raw requests with known ambiguities
```

## Technical design

### Decision journal (`lib/journal.py` + orchestrator/agent prompt contract)
Per [§8](../agent-pipeline-design.md#8-decision-journal). Every agent appends YAML entries matching
the [journal entry schema](../agent-pipeline-design.md#journal-entry-schema) (`id`, `pipeline`,
`agent`, `timestamp`, `stage_artifact`, `question`, `options_considered`, `chosen`, `rationale`,
`reversal_cost ∈ {low,medium,high}`, `status ∈ {pending_review,acknowledged,overridden}`,
`override_action`). `journal.py` provides: append; merge across a multi-pipeline run; select pending
entries; and **override resolution** — mapping an overridden entry to the stage that produced it so
the orchestrator can roll the pipeline back there and re-run (reusing the Step 2 rollback machinery).

**Presentation** (orchestrator behavior): pending entries are shown (a) before approval at every
active gate, (b) whenever the user is prompted for *any* reason (they ride along), and (c) in the
final report / PR body. This step wires (a) and (b); (c)'s PR body lands in Step 7.

### `decisions` skill
`/pipeline:decisions` lists journaled decisions for running pipelines and lets the user
acknowledge or **override** one mid-run; an override that requires redoing work triggers the
rollback-to-deciding-stage path in `journal.py` + orchestrator.

### Autonomy gradient (`lib/autonomy` contract + agent prompts)
Per [§7](../agent-pipeline-design.md#7-autonomy-gradient) and the [§8 escalation rule](../agent-pipeline-design.md#8-decision-journal):
an agent escalates only when **both** (1) ≥2 materially different answers are plausible **and** (2)
the reversal cost meets the stage's threshold. Thresholds per level:
- `refiner: ask_freely` — escalate on medium+ ambiguity about user intent; batch questions into one
  consolidated round-trip; still decide+journal the trivial ones.
- `designer: lean_ask` — escalate on high reversal cost; decide medium with journal.

Escalations are ad-hoc questions routed through the orchestrator to the user — a **separate channel**
from gates (a `full_auto` run still permits these escalations unless `escalation_policy: never`,
under which they become journaled decisions flagged high_risk). The gradient is a per-stage
escalation threshold read from config (`autonomy.<agent>`, `escalation_policy`), so it is data the
agent prompt is told to honor, not hard-coded.

### Refiner (`refiner.md`)
[§2 Refiner](../agent-pipeline-design.md#refiner): restate the task; enumerate explicit/implicit
requirements; explore the codebase to ground the spec; define in/out-of-scope and **mechanically
testable acceptance criteria** (each phrased so the designer can turn it into test cases — the first
link of the traceability chain; non-automatable criteria say so and state their manual verification).
Produces `refined_spec` (markdown) to the state directory. Ends `done` (→G1) or escalates.

### Designer (`designer.md`)
[§2 Designer](../agent-pipeline-design.md#designer): choose the approach; document alternatives
rejected (feeds the journal); identify files/modules/interfaces/data-flow and build-config impact;
**translate every acceptance criterion into concrete test cases** (inputs, expected outcomes, level:
unit/integration/e2e — the middle link of the chain). Produces `design_doc` as an **ephemeral
state-directory artifact** ([Q8](../agent-pipeline-design.md#q8--where-does-the-designers-output-design_doc-live-durably)) —
uncommitted, never in the PR. Ends `done` (→G2) or emits `spec_gap` (→L4/GE2 back to refiner).

### GE2 / GE1 auto-activation
The escalation gate **GE2** (on L4, designer→refiner) auto-activates regardless of preset when the
rework would discard work the human already approved at G1 — the approval-invalidation rule
([§6 overrides](../agent-pipeline-design.md#overrides)). Wire GE2 here; GE1 (L2/L5/L9) is wired as
its loops arrive (Steps 5/8). Backward edges are ungated by default otherwise.

## Verification

**Tier 1 — unit tests:**
- `journal.py`: entries validate against the schema; pending selection; merge across pipelines;
  override maps to the correct deciding stage; rollback target resolution.
- Autonomy threshold logic: given (plausible-answers, reversal-cost, level, escalation_policy),
  the decision to escalate-vs-journal matches the §7/§8 truth table, including `escalation_policy:
  never` converting escalations to high_risk-flagged journal entries.

**Tier 2 — end-to-end (real R+D, stubbed rest):**
- On a `fixtures/tasks/*` request with a **low-ambiguity** spec under `checkpoint`: refiner produces
  a testable-criteria spec, pauses at G1; approve; designer produces a design mapping every criterion
  to ≥1 test case, pauses at G2; approve; run proceeds into stubs. Assert the spec's criteria are all
  testable-or-marked and the design covers each criterion.
- **High-ambiguity** request: refiner escalates a batched question set (not a drip) before G1; the
  answer is journaled.
- **Spec gap:** a design-time gap triggers L4; GE2 fires because G1 was already approved; the
  rollback re-enters the refiner.
- **Override:** overriding a refiner decision via `/pipeline:decisions` rolls back to the refiner and
  re-runs; the entry's status becomes `overridden` with `override_action` set.
- **Journal surfacing:** at G2, pending entries from R and D are shown before approval is requested.

## Definition of done

- [ ] Refiner spec has only mechanically-testable (or explicitly-non-automatable) acceptance criteria.
- [ ] Designer maps every criterion to ≥1 test case; design_doc lives in the state dir, uncommitted.
- [ ] Journal entries conform to schema; surfaced at gates and on any prompt; override → rollback works.
- [ ] Autonomy thresholds honored per level; `escalation_policy: never` behaves per §7.
- [ ] GE2 auto-activates on L4 when G1 was approved.
