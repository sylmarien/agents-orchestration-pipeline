# Step 2 — Orchestrator core: routing, state, worktrees

| | |
|---|---|
| **Depends on** | [Step 1](step-01-scaffold-and-config.md) |
| **Implements** | [§4 Orchestration & execution model](../agent-pipeline-design.md#4-orchestration-and-execution-model), [§4 Worktree placement](../agent-pipeline-design.md#worktree-placement-and-isolation), [§4 Pipeline state & persistence](../agent-pipeline-design.md#pipeline-state-and-persistence), [§5 transition table](../agent-pipeline-design.md#transition-table-normative-diagrams-above-are-views-of-this-table), [§6 gating mechanism](../agent-pipeline-design.md#6-human-gating), [§15 failure handling](../agent-pipeline-design.md#15-failure-handling-orchestrator-level) |
| **Status** | Planned |

## Goal

Build the **walking skeleton**: the orchestrator agent that resolves config, creates a state
directory and worktree, and drives the linear spine end-to-end by interpreting the transition table
as data — pausing at active gates and recording every move to the pipeline-state history. Real
pipeline agents don't exist yet, so this step also delivers the **stub-agent harness** that stands in
for every node, making the whole control plane testable before any real agent is written.

## Scope

**In:** `agents/orchestrator.md`; `config/transition_table.yaml`; `lib/worktree.py`, `lib/state.py`,
`lib/graph_validate.py`; the `run` and `status` skills + `/pipeline:run`, `/pipeline:status`
commands; stub-agent harness; run manifest (skeleton). Gate **mechanism** (pause/resume, present
bundle) and the `checkpoint`/`full_auto`/`pre_submit_only`/`paranoid` presets.
**Out:** real refiner…pr_shepherd (Steps 3–8); budgets (Step 9); ticketing (Step 10).

## Deliverables (tree delta)

```
agents/orchestrator.md
config/transition_table.yaml
lib/{worktree.py, state.py, graph_validate.py}
commands/{run.md, status.md}
skills/run/SKILL.md
skills/status/SKILL.md
fixtures/stub-outcomes/{happy-path.yaml, review-bounce.yaml, escalation.yaml, ...}
tests/{test_transition_table.py, test_worktree.py, test_state.py}
```

## Technical design

### Transition table as data (`transition_table.yaml`)
A machine-readable encoding of [§5's normative tables](../agent-pipeline-design.md#transition-table-normative-diagrams-above-are-views-of-this-table):
`nodes` (id, agent impl, autonomy, consumes/produces artifact types, declarable outcomes) and
`edges` (id, from, to, trigger, gate, options-tag). All forward (T1–T8), backward (L1–L6), and
post-PR (L7–L10) edges are present; each edge is tagged with the topologies it belongs to
(`[A,B,C]`, `A`, `B`, `C`). The active graph = edges whose tag includes the run's `topology` (default
`option_a`). **Option B/C edges ship here as dormant data** so switching topology stays a knob flip,
never a code change ([§5 implementation note](../agent-pipeline-design.md#5-pipeline-topology)).

The orchestrator reads this file into context and routes over it (pure-agent, [Q9](../agent-pipeline-design.md#q9--how-is-the-transition-graph-executed-llm-interpreted-routing-or-a-deterministic-engine)).
The table is the orchestrator's data alone (P7): stub and real agents never see it.

### `graph_validate.py`
Deterministic well-formedness checks over the table (subset of the [§13 validation rules](../agent-pipeline-design.md#13-custom-agent-graphs-future-direction),
applicable already to the built-in graph): every edge references declared nodes; every trigger is a
declared outcome of its source node; artifact dependencies are closed (each `consumes` is produced
upstream or supplied at intake); exactly one entry node and a reachable terminal; every gate id
resolves. Run at plugin build time and at spawn — a malformed graph fails fast.

### `state.py` — state directory & pipeline-state history
Per [§4 state & persistence](../agent-pipeline-design.md#pipeline-state-and-persistence):

- Creates the **state directory** (separate from the worktree) per pipeline.
- **Per-node state files** — scratch a stage writes its within-stage progress to, so a crashed or
  resumed stage restarts where it left off.
- **Pipeline-state history file** — append-style record of transitions, gate events, positions,
  loop-budget counters, and (future) join state. This is *both* the crash-recovery substrate for the
  pure-agent router (routing position lives in a file, not only in the LLM context) *and* the
  control-flow audit trail. Working artifacts (refined_spec-when-ticketing-off, design_doc, notes,
  evidence, reports) also live in this directory so they survive worktree cleanup.
- Append-only writer with a defined record shape (`ts`, `event` ∈ {transition, gate_open,
  gate_resolved, escalation, loop_increment, restart}, `from`, `to`, `edge`, `gate`, `detail`).

### `worktree.py` — worktree lifecycle
Per [§4 worktree placement](../agent-pipeline-design.md#worktree-placement-and-isolation):
`name_template` resolution (`{pipeline_id}[-{agent_id}]/{repo_name}`, with the `-{agent_id}` segment
collapsing when a single agent is active), `worktree.root` relative-to-repo-root vs. absolute
handling, `git worktree add` on a fresh branch, and **auto-clean on completion** (terminal at G8 or
user stop) while the state directory persists. The `{repo_name}` leaf is preserved so out-of-tree
relative build paths (`../build`) never collide across parallel worktrees.

### Orchestrator agent (`orchestrator.md`)
The user's sole interlocutor. Its prompt encodes the [§2 orchestrator responsibilities](../agent-pipeline-design.md#orchestrator):
accept a task, resolve config via the three layers (calling `resolve_config.py`; parsing the prompt
into a typed delta), echo resolved overrides back, write the **run manifest** (resolved config +
provenance + plugin/schema versions — enriched with models/spend in Step 9), create worktree +
state dir, then loop: spawn the node's agent → read its typed outcome → match against the table's
trigger → if the chosen edge's gate is active under the preset, pause and present (artifact + pending
journal + proposed next step) and await approve/revise/override/abort → else pass-through (logged) →
advance → append to state history. Handles [§15 failures](../agent-pipeline-design.md#15-failure-handling-orchestrator-level):
restart a stage from its input artifacts, roll back, or abort preserving artifacts.

### Stub-agent harness
A generic stub agent bound to any node id: it reads its scripted outcome from a
`fixtures/stub-outcomes/*` file, writes a placeholder artifact of the node's `produces` type, and
returns that typed outcome. This lets the orchestrator be driven through the happy path, a
review-bounce loop, an escalation, and every gate **deterministically**, with no real agent built.
The harness is a verification asset, not shipped in the plugin package.

### `run` / `status` skills
`run` spawns the orchestrator on one or more tasks with prompt-layer overrides
(`/pipeline:run "fix X, no gating until PR"`). `status` reads the pipeline-state history + manifest
to show each pipeline's current node, pending gates, and (from Step 3) pending journal entries.

## Verification

**Tier 1 — unit tests:**
- `graph_validate.py`: the built-in table passes; hand-mutated bad tables (dangling edge, undeclared
  trigger, unclosed artifact dep, no terminal) each fail with the right error.
- `worktree.py`: name-template resolution for single vs. multi-agent, relative vs. absolute root,
  and `{repo_name}` leaf preservation; add creates a branch; clean removes the worktree but not the
  state dir.
- `state.py`: history is append-only and ordered; per-node state round-trips; a simulated restart
  resumes from the last record.

**Tier 2 — scripted end-to-end with stubs:**
- **Happy path:** `full_auto` preset drives R→D→I→CR→DOC→DR→S→(G7) with all-`done` stubs; assert the
  state history shows exactly that node sequence, G7 as notification-only, worktree created then
  auto-cleaned, state dir persisted.
- **Gating:** `checkpoint` preset pauses at G1 and G2 and nowhere else; approving resumes; the
  passed-through gates are logged with their bundle. `paranoid` pauses at every forward transition.
- **Loops:** a `review-bounce` stog script (CR emits `request_changes`) routes CR→I→CR via L1 and
  the history records the loop_increment.
- **Crash/restart:** killing a node mid-run and re-spawning resumes from its per-node state, not from
  scratch.
- **Config echo/manifest:** resolved overrides are read back to the user and written to the manifest
  with correct provenance.

## Definition of done

- [ ] Table validates; Option A active, Option B/C present but dormant.
- [ ] Orchestrator drives the full linear spine with stubs and records a correct, append-only history.
- [ ] All four gate presets behave per §6; passed-through gates logged.
- [ ] Worktree created and auto-cleaned; state directory persists; artifacts land in the state dir.
- [ ] Stub harness can script happy path, a gate, a loop, and an escalation.
- [ ] Crash-restart resumes from per-node state (§15).
