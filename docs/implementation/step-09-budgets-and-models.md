# Step 9 — Resource budgets + model selection

| | |
|---|---|
| **Depends on** | [Step 2](step-02-orchestrator-core.md) (buildable in parallel; verified once the spine of [Step 8](step-08-pr-shepherd.md) exists) |
| **Implements** | [§10 Resource budgets](../agent-pipeline-design.md#10-resource-budgets), [§11 Model selection](../agent-pipeline-design.md#11-model-selection), [§6 GB1](../agent-pipeline-design.md#6-human-gating) |
| **Status** | Planned |

## Goal

Layer the two cross-cutting resource concerns onto the working pipeline: **per-pipeline token
budgets** (warn, then the always-on GB1 exhaustion gate) and **per-agent model selection** (resolved
through the same three config layers). Both feed the run manifest's transparency guarantees.

## Scope

**In:** `lib/budget.py`; `hooks/budget_meter.py`; GB1 gate; model resolution + per-agent model
binding at spawn; manifest enrichment (spend breakdown, resolved models).
**Out:** currency-precise cost governance beyond `budget.usd` with a supplied pricing table (best-effort).

## Deliverables (tree delta)

```
lib/budget.py                 # usage accumulation, warn-ratio, exhaustion detection
hooks/budget_meter.py         # Claude Code hook: read per-message usage, accumulate, block on exhaustion
hooks/hooks.json              # (extend) register budget_meter on PostToolUse/Stop
tests/test_budget.py
```

## Technical design

### Accounting (`lib/budget.py`)
[§10 accounting](../agent-pipeline-design.md#10-resource-budgets): unit = **tokens** (input + output
per the API usage object), accumulated **per pipeline**; sub-agents count against their pipeline. The
manifest records the full split (input / output / cache_creation / cache_read) **per agent and per
stage** — raw totals overstate cost on cache-heavy runs, so the breakdown is what makes the number
interpretable. Optional secondary `budget.usd` layered on **only** when a pricing table for the
models in use is supplied (tokens are primary because they're pricing-independent).

### Enforcement per runtime
Per the [§10 enforcement table](../agent-pipeline-design.md#10-resource-budgets):
- **Agent SDK / Messages API (normative mechanism):** the orchestrator accumulates each response's
  usage object per agent session and declines to start / interrupts the next stage at the cap.
- **Claude Code:** no built-in cumulative budget, so `budget_meter.py` is a hook that reads per-message
  usage from the session transcript, accumulates it, and **blocks further tool calls / stops the
  session** when exceeded — per-session, so the orchestrator still sums across agents.
- **Task Budgets (model awareness):** optionally pass `output_config.task_budget` so agents pace
  themselves within a turn — complementary, *not* the authority; the orchestrator's metering is
  authoritative.

### Behavior
- **Warning** at `budget.warn_ratio` (default 0.8): journal a warning + surface on the pipeline graph;
  **no pause**.
- **Exhaustion** at 100%: pause at the next safe point (first-class sessions make pausing
  resume-safe) and fire **GB1** (`budget_exhausted`) presenting spend breakdown per agent/stage,
  pipeline position, pending journal entries, and a rough estimate of remaining work. User choices:
  extend (new amount), continue unmetered, or abort (worktree + artifacts preserved).
- **Always active** whenever a budget is configured — **no preset suppresses GB1** (a spend stop is
  not a workflow checkpoint), same rationale as the GE escalation gates.
- **Multi-pipeline:** budgets are per pipeline; when any GB1 fires the orchestrator also reports the
  run-level aggregate.
- **Default `budget.tokens: null`** (unlimited — a zero-config run must not stall on an arbitrary cap).

### Model selection
[§11](../agent-pipeline-design.md#11-model-selection). Resolution order per agent (first match wins):
prompt `model.<agent>` → prompt `model.default` → project `model.<agent>` → project `model.default` →
**inherit** the model active at spawn. Each agent is its own session, so per-agent models never mean
switching mid-session (which would invalidate the model-scoped prompt cache). Rework re-enters a
stage with that stage's configured model; a gate-time model override ("retry the implementer with
model X") is journaled like any decision. Resolved models are recorded in the manifest and shown on
the graph node (drill-down). Unresolvable model names **fail fast** at spawn.

## Verification

**Tier 1 — unit tests (`test_budget.py`):**
- Accumulation sums input+output across mocked usage objects; the split (input/output/cache_*) is
  preserved per agent/stage.
- Warn fires exactly at `warn_ratio`; exhaustion at 100%; `budget.tokens: null` never triggers either.
- Multi-pipeline aggregate is correct.
- Model resolution truth table: each of the five precedence cases picks the expected model; an
  unknown model name raises at spawn.

**Tier 2 — end-to-end:**
- Set a low `budget.tokens` on a real run: the 0.8 warning appears (journaled + on the graph, no
  pause); at 100% **GB1** pauses with the breakdown bundle; "extend" resumes, "abort" preserves
  artifacts. Confirm `full_auto` does **not** suppress GB1.
- **Claude Code hook path:** `budget_meter.py` blocks further tool calls once the per-session cap is
  crossed; the orchestrator sums across the run's agents.
- **Per-agent models:** a run with `model.documenter=<cheap>` and `model.designer=<strong>` records
  those exact models per agent in the manifest and on the nodes; unset agents inherit the spawn model.

## Definition of done

- [ ] Token accounting per pipeline with the full input/output/cache split in the manifest.
- [ ] Warn at 0.8 (no pause); GB1 at 100% with breakdown + choices; always-on regardless of preset.
- [ ] Claude Code hook enforces the per-session cap; orchestrator sums across agents.
- [ ] Model resolution follows the five-step order; per-agent models recorded; unknown model fails fast.
- [ ] `budget.tokens: null` default keeps zero-config runs unmetered.
