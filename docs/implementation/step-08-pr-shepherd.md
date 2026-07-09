# Step 8 — PR shepherd

| | |
|---|---|
| **Depends on** | [Step 7](step-07-submitter.md) |
| **Implements** | [§2 PR shepherd](../agent-pipeline-design.md#pr-shepherd), [§5 post-PR edges L7–L10](../agent-pipeline-design.md#loop-budgets), [§6 G8](../agent-pipeline-design.md#6-human-gating), [Q2](../agent-pipeline-design.md#q2--does-the-submitter-also-babysit-the-pr-or-does-the-pipeline-end-at-pr-creation) |
| **Status** | Planned |

## Goal

Add the ninth agent, which babysits the PR after G7 until it is merged or closed — watching CI,
review comments, reviews, and mergeability, and routing actionable findings back into the pipeline
via the orchestrator (L7–L10). This closes the full lifecycle: the pipeline now goes from raw request
all the way to a merged PR. G8 is terminal.

## Scope

**In:** `agents/pr_shepherd.md`; PR-activity subscription/triage; `rework_request` and
`pr_status_report` artifacts; post-PR re-attribution edges L7–L10 with their shared rework budget;
the submitter's amend + force-push on rework; G8; `pr_shepherd.enabled` knob behavior.
**Out:** ticketing status transitions on merge/close (Step 10 adds those atop this).

## Deliverables (tree delta)

```
agents/pr_shepherd.md
fixtures/pr-events/*          # scripted CI-failure / review-comment / mergeability events
```

## Technical design

### PR shepherd (`pr_shepherd.md`)
[§2 PR shepherd](../agent-pipeline-design.md#pr-shepherd), autonomy `decide` (triages autonomously;
routing goes through the orchestrator):
- **Subscribe** to PR activity — CI runs, comments, reviews, mergeability — and **triage every
  event**: actionable / informational / duplicate. Triage decisions are journaled; duplicates skipped
  silently. (In this runtime, subscription is the `subscribe_pr_activity` mechanism; events arrive as
  activity messages — the shepherd does not poll with sleeps.)
- For each actionable finding, emit a `rework_request` (yaml: finding, source event, proposed owner,
  severity) and flag it to the orchestrator, which **re-attributes**:
  - **L7** → implementer (CI failures, code findings)
  - **L8** → documenter (docs findings)
  - **L9** → designer (structural objections; **GE1** auto-activates)
  - **L10** → submitter (rebases / conflicts / re-push)
- Reworked changes **re-enter the normal review path** (code reviewer / docs reviewer) before the
  submitter **amends the PR's single commit and force-pushes** (the §16 submitter-only force-push).
- Answer reviewer questions the existing artifacts (spec, design, journal) already answer, **without
  touching code**; stay frugal — comment only when genuinely needed.
- **Escalate to the human** when a comment demands out-of-scope work, contradicts a gate-approved
  artifact, or the same finding survives the rework budget.
- Produce `pr_status_report` (CI state, open threads, mergeability, terminal state). Report terminal
  state (merged / closed) to the orchestrator, closing the pipeline.

### Post-PR loop budget
[§5 loop budgets](../agent-pipeline-design.md#loop-budgets): L7–L10 share a **max rework rounds =
5** budget (`loop_limits` post-PR); exhaustion **or a repeat finding** escalates to the human. Uses
the same `lib/loop_budget.py` counters, persisted in the state history.

### Untrusted-input note
PR comments / review text / CI logs are external content. Per the design's trusted-environment scope
([§16](../agent-pipeline-design.md#16-permissions-and-sandboxing)) hardening against adversarial
inputs is a v1 non-goal, but the shepherd's prompt still treats comment bodies as data to triage, not
instructions to obey, and escalates anything that would redirect the task.

### G8 gate & the enabled knob
**G8** (`pr_terminal`) — notification-only, PR merged or closed, pipeline over; triggers worktree
auto-clean while the state directory persists. When `pr_shepherd.enabled: false` the pipeline **ends
at G7** exactly as before this step (the shepherd is skipped) — verify both modes.

## Verification

**Tier 2 — end-to-end (full spine + shepherd), driving `fixtures/pr-events/*`:**
- **CI failure:** a failing-CI event → shepherd emits an L7 `rework_request` → implementer fixes →
  re-review → submitter amends the single commit and force-pushes; the PR still has exactly one
  commit afterward.
- **Docs finding on the PR:** → L8 documenter path.
- **Structural objection:** → L9 designer, GE1 fires.
- **Rebase/conflict:** → L10 submitter re-push.
- **Answerable question:** shepherd replies from existing artifacts without a code change (and stays
  silent on duplicates/informational events).
- **Out-of-scope / contradicting comment:** shepherd escalates to the human rather than acting.
- **Budget:** the same finding surviving 5 rounds (or a detected repeat) escalates.
- **Terminal:** a merged event → G8, orchestrator closes the pipeline, worktree auto-cleaned, state
  dir persists.
- **Disabled:** with `pr_shepherd.enabled: false`, the pipeline terminates at G7 and no shepherd runs.

## Definition of done

- [ ] Shepherd subscribes and triages every event (actionable/informational/duplicate), journaling triage.
- [ ] L7–L10 re-attribute correctly; reworked changes re-enter review before submitter amend+force-push;
      PR stays single-commit.
- [ ] Frugal, artifact-grounded replies; escalation on out-of-scope/contradiction/budget-exhaustion.
- [ ] Post-PR rework budget (5) enforced; repeat finding escalates.
- [ ] G8 terminal → worktree auto-cleaned, state dir persists; `pr_shepherd.enabled:false` ends at G7.
