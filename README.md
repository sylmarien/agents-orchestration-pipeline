# agents-orchestration-pipeline

A semi-autonomous multi-agent pipeline that takes a development task from raw request to merged
pull request: an orchestrator supervises per-task pipelines of first-class agents (refiner,
designer, implementer, code reviewer, documenter, documentation reviewer, submitter, PR shepherd),
each in its own git worktree, with configurable human gating and a decision journal.

The design document lives at [docs/agent-pipeline-design.md](docs/agent-pipeline-design.md).
No implementation exists yet.
