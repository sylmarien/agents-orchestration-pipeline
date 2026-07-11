# agents-orchestration-pipeline

A semi-autonomous multi-agent pipeline that takes a development task from raw request to merged
pull request: an orchestrator supervises per-task pipelines of first-class agents (refiner,
designer, implementer, code reviewer, documenter, documentation reviewer, submitter, PR shepherd),
each in its own git worktree, with configurable human gating and a decision journal.

The design document lives at [docs/agent-pipeline-design.md](docs/agent-pipeline-design.md).

The staged implementation plan (build order, per-step verification, and technical design for each
step) lives at [docs/implementation/](docs/implementation/README.md). Implementation is underway;
[Step 1](docs/implementation/step-01-scaffold-and-config.md) (plugin scaffold and the
configuration model) is complete — see `config/`, `lib/resolve_config.py`, and `tests/`.
[Step 2](docs/implementation/step-02-orchestrator-core.md) (orchestrator core: routing, state,
worktrees) is also complete — see `agents/orchestrator.md`, `config/transition_table.yaml`,
`lib/{graph_validate,worktree,state}.py`, `commands/`, `skills/`, and `fixtures/`. Real pipeline
agents (refiner onward) don't exist yet; the orchestrator drives a **stub-agent harness**
(`fixtures/stub_agent.md` + `fixtures/stub-outcomes/`) in their place until Steps 3–8 replace
them one at a time.
