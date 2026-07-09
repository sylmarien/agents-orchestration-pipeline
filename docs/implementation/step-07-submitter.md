# Step 7 — Submitter + permissions & sandboxing

| | |
|---|---|
| **Depends on** | [Step 6](step-06-documenter-docs-reviewer.md) |
| **Implements** | [§2 Submitter](../agent-pipeline-design.md#submitter), [§6 G7](../agent-pipeline-design.md#6-human-gating), [§16 Permissions & sandboxing](../agent-pipeline-design.md#16-permissions-and-sandboxing), [§4 durable artifacts](../agent-pipeline-design.md#3-shared-artifacts-the-hand-off-contracts) |
| **Status** | Planned |

## Goal

Replace the final stub: the submitter squashes the branch to **exactly one commit**, re-verifies,
pushes the branch, and opens the PR — and this is where the **sandbox** becomes enforced, because the
submitter is the only agent permitted to push/create-PR/force-push. After this step the whole linear
spine R→…→S runs for real, ending at a live PR (G7). Only the post-PR shepherd (Step 8) remains.

## Scope

**In:** `agents/submitter.md`; single-commit squash + rebase + re-verify; branch push and
host-agnostic PR creation; PR body assembly (summary + evidence + decision journal); G7; the
`sandbox_guard.py` hook enforcing [§16](../agent-pipeline-design.md#16-permissions-and-sandboxing).
**Out:** post-PR watching and the amend/force-push on rework (Step 8, though the sandbox allowance for
submitter force-push is established here).

## Deliverables (tree delta)

```
agents/submitter.md
hooks/hooks.json              # register sandbox_guard on PreToolUse (Bash/git, network)
hooks/sandbox_guard.py        # push/force-push/egress/write-confinement enforcement
tests/test_sandbox_guard.py
```

## Technical design

### Submitter (`submitter.md`)
[§2 Submitter](../agent-pipeline-design.md#submitter), autonomy `full` (mechanical; surprises are
pipeline errors, not negotiations):
- **Single commit:** squash the branch's entire working history (implementer + documenter commits)
  into one commit whose message consolidates the change, **rebased onto the latest default branch**;
  then **re-verify build/tests/checks on the squashed result** before pushing (`submitter.single_commit:
  true`).
- **Push + PR:** push the pipeline branch and open the PR. **How** a PR is opened is **host-specific
  and delegated to the project's own instructions** — the pipeline hard-codes no hosting provider.
  Use the repo's PR template if present.
- **PR body:** summary (from the documenter's material) + verification evidence + the **full decision
  journal** (`decision_journal.in_pr_body: true`), so reviewers see what was decided autonomously.
- Report the PR URL to the orchestrator. Ends `done` (→G7).

**Durable vs. ephemeral at the boundary** ([§3 durability](../agent-pipeline-design.md#3-shared-artifacts-the-hand-off-contracts)):
the `diff` + `docs_changeset` become the single commit; the `decision_journal` rides in the PR body;
the ephemeral state-dir artifacts (design_doc, notes, evidence, reports) are **never** added to the
commit — being outside the worktree they cannot be.

### Sandbox hook (`sandbox_guard.py` + `hooks.json`)
[§16](../agent-pipeline-design.md#16-permissions-and-sandboxing), trusted-environment scope — guards
against accidental damage and runaway autonomy, not a malicious insider. Registered as a
`PreToolUse` hook on Bash/git and network tool calls:
- **No agent pushes to the default branch** (e.g. `main`) under any circumstance.
- **Only the submitter** may push the pipeline branch, create the PR, and **force-push** (the
  squash + later L7–L10 re-pushes). Every other agent attempting a push/PR/force-push is blocked.
- **Filesystem confinement:** writes restricted to the agent's assigned worktree + its slice of the
  state directory.
- **Network egress:** outbound fetches restricted to an **allow-list**; anything else requires human
  approval, never performed autonomously.
The hook identifies the calling agent from the run context so the submitter allowance is scoped to
the submitter alone. These guarantees apply to bundled and (future) bring-your-own agents alike.

### G7 gate
`pr_created` on T7 — **notification-only by default** (fires after the fact); the pr_shepherd starts
watching here (Step 8). Active in every preset as a notify.

## Verification

**Tier 1 — unit tests (`test_sandbox_guard.py`):**
- A `git push origin main` from any agent is blocked.
- A branch push / PR create / `push --force` is allowed for the submitter identity and blocked for
  refiner/implementer/etc.
- A write outside the worktree + state dir is blocked; inside is allowed.
- An egress to a non-allow-listed domain is blocked (routes to human approval); an allow-listed one
  passes.

**Tier 2 — end-to-end (full real spine against `fixtures/sample-project`):**
- Full run to G7: the PR exists and contains **exactly one commit**, rebased on the default branch,
  whose squared result **re-passes** build/tests/checks; the PR body carries summary + evidence +
  full journal; the repo's PR template (if present) is used.
- **Single-commit invariant:** assert `git rev-list --count base..head == 1`.
- **Sandbox in situ:** confirm no non-submitter agent pushed anything during the run (state history +
  hook log); the default branch was never pushed to.
- **Re-verify catches drift:** seed a rebase that breaks the build; the submitter's post-squash
  re-verify fails and it does **not** push a red PR (escalates instead).

## Definition of done

- [ ] PR created with exactly one commit, rebased on default branch, re-verified green.
- [ ] PR body includes summary, verification evidence, and the full decision journal.
- [ ] PR creation delegated to project instructions (no hard-coded host); PR template honored.
- [ ] Sandbox hook enforces §16: no default-branch push; only submitter pushes/creates/force-pushes;
      writes confined; egress allow-listed.
- [ ] G7 notifies; orchestrator receives the PR URL.
