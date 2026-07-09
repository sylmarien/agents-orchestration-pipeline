# Step 10 — Ticketing integration

| | |
|---|---|
| **Depends on** | [Step 3](step-03-refiner-designer.md) (refiner/spec-sync), [Step 7](step-07-submitter.md) (linking), [Step 8](step-08-pr-shepherd.md) (status on merge/close) |
| **Implements** | [§12 Ticketing integration](../agent-pipeline-design.md#12-ticketing-integration), [Q6](../agent-pipeline-design.md#q6--can-the-ticket-system-drive-intake-or-only-enrich-it), [Q7](../agent-pipeline-design.md#q7--how-are-jira-credentials-supplied) |
| **Status** | Planned |

## Goal

Add optional ticket-system integration as a **configuration knob** (`ticketing.system`, default
`none`) over the already-working pipeline: intake, spec sync-back, PR/commit linking, status
transitions, and end-of-run reporting — for GitHub issues and Jira. No agent behavior changes when
ticketing is off (the default), so this step is purely additive.

## Scope

**In:** ticketing capability wired into the orchestrator, refiner, submitter, and pr_shepherd for
modes `none` / `github_issues` / `jira`; spawn-time validation + graceful degradation; status
mapping; reporting. **Reference-only intake** ([Q6](../agent-pipeline-design.md#q6--can-the-ticket-system-drive-intake-or-only-enrich-it)).
**Out:** label-driven pull-based intake (explicitly future, out of scope); bundling a Jira-auth
skill (not a v1 commitment — [Q7](../agent-pipeline-design.md#q7--how-are-jira-credentials-supplied)).

## Deliverables (tree delta)

```
lib/ticketing/__init__.py     # common contract
lib/ticketing/github.py       # github_issues mode
lib/ticketing/jira.py         # jira mode (auth delegated, never handled here)
tests/test_ticketing.py
```

## Technical design

### Modes & validation
[§12 modes](../agent-pipeline-design.md#modes):
- **`none`** (default): tasks come from the prompt only; no ticket side effects.
- **`github_issues`**: uses the repo the pipeline runs in; **graceful degradation** — if the project
  isn't actually on GitHub while this mode is set, ignore the setting and behave as `none` with a
  journaled spawn warning, **never a spawn failure**.
- **`jira`**: requires `ticketing.jira.url` + `ticketing.jira.project`; **missing config fails fast at
  spawn** (jira is always an explicit choice). Credentials are **never** in `pipeline.yaml` — auth is
  delegated to an existing Jira MCP connector or skill; the pipeline never handles the credential.
  Connectivity validated at spawn (fail fast).

### Common contract (`lib/ticketing/`)
One interface implemented per mode, covering [§12 capabilities](../agent-pipeline-design.md#capabilities-common-contract-implemented-per-mode):
- **Intake** (orchestrator/refiner): a task referencing a ticket (`#42`, `PROJ-123`, or a URL) →
  fetch title, description, comments, links → hand to the refiner as part of the request. The ticket
  is an **input document, not a conversation channel** — refiner questions still go to the user.
- **Spec sync** (`ticketing.sync_spec`, default true): on refiner completion, write the refined spec
  back (github_issues: issue body / pinned comment; jira: description / comment). If ticketing is
  active but no ticket was referenced, the orchestrator **creates one from the spec — but always
  prompts the user first** regardless of preset (`ticketing.create_if_missing`, values `prompt`/`never`,
  default `prompt`; there is deliberately no "always"); confirmation + outcome journaled.
- **Linking** (submitter): link PR ↔ ticket (github_issues: `Fixes #42`; jira: ticket key in
  title/body) and include the ticket ref in the squashed commit message and branch name.
- **Status sync**: orchestrator → in-progress at spawn; submitter/shepherd → in-review at PR open;
  shepherd → resolved on merge (github: auto-close via `Fixes`; jira: workflow transition) and
  reverted on close-unmerged. Jira workflow names vary, so `ticketing.status_mapping` is a knob with
  defaults (start: In Progress, pr: In Review, merged: Done).
- **Reporting** (`ticketing.post_report`, default true when a system is active): post the final
  summary (outcome, PR link, journal highlights) as a ticket comment at run end.

## Verification

**Tier 1 — unit tests (`test_ticketing.py`):**
- `jira` mode missing url/project raises at spawn; `github_issues` on a non-GitHub repo degrades to
  `none` with a journaled warning (no failure).
- Status mapping resolves defaults and honors overrides.
- `create_if_missing: prompt` always prompts; `never` never creates; neither creates without user
  confirmation.
- Intake parses `#42` / `PROJ-123` / URL references correctly.

**Tier 2 — end-to-end:**
- **github_issues, referenced ticket:** run a task referencing a repo issue → spec synced to the
  issue; ticket → In Progress at spawn, In Review at PR, closed via `Fixes` on merge; final report
  posted as a comment; PR + commit + branch carry the reference.
- **github_issues, no ticket:** the orchestrator prompts before creating; on "yes" it creates and
  syncs; on "no" it proceeds ticketless — both journaled.
- **jira (mocked connector):** the same lifecycle via the delegated connector; the pipeline never
  touches a credential; a missing connector fails fast at spawn.
- **`none` (default):** a full run has zero ticket side effects (regression guard that ticketing is
  additive).

## Definition of done

- [ ] Three modes behave per §12; jira fails fast, github_issues degrades gracefully.
- [ ] Intake enriches (reference-only); spec sync-back; ticket creation always user-confirmed.
- [ ] PR/commit/branch linking; full status lifecycle incl. revert on close-unmerged; end-of-run report.
- [ ] Credentials never in config; jira auth delegated; connectivity validated at spawn.
- [ ] `ticketing.system: none` leaves all agent behavior unchanged.
