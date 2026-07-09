# Step 6 — Documenter + documentation reviewer

| | |
|---|---|
| **Depends on** | [Step 5](step-05-code-reviewer.md) |
| **Implements** | [§2 Documenter](../agent-pipeline-design.md#documenter), [§2 Documentation reviewer](../agent-pipeline-design.md#documentation-reviewer), [§6 G5/G6](../agent-pipeline-design.md#6-human-gating), [§5 L3](../agent-pipeline-design.md#loop-budgets), [Q4 two definitions](../agent-pipeline-design.md#q4--are-the-two-reviewers-distinct-agent-instances-or-one-reviewer-role-instantiated-twice) |
| **Status** | Planned |

## Goal

Replace the last two content stubs with the documenter and the (separately-tuned) documentation
reviewer, completing the real spine up to the submitter. Reuses the Step 5 loop-budget machinery for
the L3 docs-rework loop. Only the submitter (S) remains a stub after this step.

## Scope

**In:** `agents/documenter.md`, `agents/documentation_reviewer.md`; `docs_changeset` and
`docs_review_report` artifacts; gates G5/G6; L3 loop; documenter skip-with-justification; PR-facing
summary material (consumed by the submitter in Step 7).
**Out:** the actual PR (Step 7). Option-B parallel docs / L6 recheck edge stay dormant data.

## Deliverables (tree delta)

```
agents/documenter.md
agents/documentation_reviewer.md
fixtures/tasks/docs-*         # changes with / without a user-visible surface
```

## Technical design

### Documenter (`documenter.md`)
[§2 Documenter](../agent-pipeline-design.md#documenter), autonomy `decide`:
- Update README / CLAUDE.md / config docs / in-code comments where behavior, interfaces, or
  workflows changed; document new configuration knobs and their defaults.
- Write the **PR-facing summary material** (what / why / how-verified) that the submitter reuses in
  Step 7.
- **Skip-with-justification** when a change genuinely needs no docs (`documenter.skip_allowed:
  true`), journaled so the human can veto the skip.
- Docs commits are **working history** — squashed into the PR's single commit by the submitter.
Produces `docs_changeset` (git commits in the worktree) + the summary material to the state dir.
Ends `done` (→G5).

### Documentation reviewer (`documentation_reviewer.md`)
[§2 Documentation reviewer](../agent-pipeline-design.md#documentation-reviewer), autonomy `decide`, a
**separate agent definition** from the code reviewer ([Q4](../agent-pipeline-design.md#q4--are-the-two-reviewers-distinct-agent-instances-or-one-reviewer-role-instantiated-twice) —
prompt tuned to prose, not code):
- Verify docs statements against the **actual code** (no aspirational docs).
- Check completeness against the spec's user-visible surface and terminology consistency with
  existing project docs.
Produces `docs_review_report` with **verdict ∈ {approve, request_changes}**. `request_changes` →
**L3** back to the documenter (reusing `lib/loop_budget.py`, default max 3).

### Gates
- **G5** (`docs_done`) on T5 — present the `docs_changeset`.
- **G6** (`pre_submit`) on T6 (docs_reviewer→submitter) — present the `docs_review_report` and the
  **full bundle**. This is the single gate of the `pre_submit_only` preset; off under `checkpoint`.

## Verification

**Tier 1 — unit tests:** none new (loop budgets already covered in Step 5; assert L3 uses the same
counter mechanism).

**Tier 2 — end-to-end (real R…DR, stubbed S):**
- **User-visible change:** documenter updates the right docs and writes summary material; docs
  reviewer approves; routes G6 → (stub) submitter. Assert every user-visible/interface change from
  the spec is documented.
- **Aspirational-docs catch:** seed a docs changeset that overstates behavior; docs reviewer returns
  `request_changes` → L3 → documenter corrects → approve. History shows one L3 loop.
- **Justified skip:** a purely-internal change with no user surface → documenter skips with a
  journaled justification; the skip is surfaced for human veto and, unvetoed, the run proceeds.
- **L3 budget:** repeated docs failures trip the L3 budget → escalation.

## Definition of done

- [ ] Every user-visible/interface change documented, or the omission journaled with a reason.
- [ ] Docs reviewer is a distinct definition; verifies docs against code; issues an explicit verdict.
- [ ] L3 loop + budget work via the shared machinery.
- [ ] G5 and G6 present the right bundles; `pre_submit_only` pauses only at G6.
- [ ] Summary material produced for the submitter.
