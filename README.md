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
`lib/{graph_validate,worktree,state}.py`, `commands/`, `skills/`, and `fixtures/`.
[Step 3](docs/implementation/step-03-refiner-designer.md) (refiner + designer, gates G1/G2, the
decision journal, and the autonomy gradient) is also complete — see `agents/{refiner,designer}.md`,
`lib/journal.py`, `commands/decisions.md`, `skills/decisions/`, and `fixtures/tasks/`.
[Step 4](docs/implementation/step-04-implementer.md) (implementer + inner green loop) is also
complete — see `agents/implementer.md`, `lib/checks.py`, and `fixtures/sample-project/`.
[Step 5](docs/implementation/step-05-code-reviewer.md) (code reviewer + rework loops & loop
budgets) is also complete — see `agents/code_reviewer.md` and `lib/loop_budget.py`.
[Step 6](docs/implementation/step-06-documenter-docs-reviewer.md) (documenter + documentation
reviewer, gates G5/G6, the L3 docs-rework loop) is also complete — see `agents/documenter.md` and
`agents/documentation_reviewer.md`.
[Step 7](docs/implementation/step-07-submitter.md) (submitter + permissions/sandboxing) is also
complete — see `agents/submitter.md` and `hooks/sandbox_guard.py`. The real linear spine now runs
end-to-end from the refiner through a live PR (G7).
[Step 8](docs/implementation/step-08-pr-shepherd.md) (PR shepherd) is also complete — see
`agents/pr_shepherd.md` and `fixtures/pr-events/`. Every node now has a real agent; the
**stub-agent harness** (`fixtures/stub_agent.md` + `fixtures/stub-outcomes/`) remains only for
deterministic routing tests, per `agents/orchestrator.md`'s "Spawning a node".
[Step 9](docs/implementation/step-09-budgets-and-models.md) (resource budgets + model selection) is
also complete — see `lib/budget.py`, `hooks/budget_meter.py`, and `agents/orchestrator.md`'s
"Resource budgets and model selection".
[Step 10](docs/implementation/step-10-ticketing.md) (ticketing integration: `none`/`github_issues`/
`jira`) is also complete — see `lib/ticketing/`, `tests/test_ticketing.py`, and the "Ticketing"
sections of `agents/orchestrator.md`, `agents/submitter.md`, and `agents/pr_shepherd.md`.

## Installing

This repository is both the plugin and its own [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
(`.claude-plugin/marketplace.json`). From within Claude Code:

```
/plugin marketplace add sylmarien/agents-orchestration-pipeline
/plugin install agent-pipeline@agent-pipeline-marketplace
```

Then invoke it with `/pipeline:run <task description>` (see `commands/run.md`).
