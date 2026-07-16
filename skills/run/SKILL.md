---
name: run
description: >-
  Start the agent-pipeline orchestrator on one or more tasks. Accepts prompt-layer config
  overrides in prose (e.g. "fix the login redirect, no gating until PR") and, for this build's
  walking skeleton, an optional stub scenario to drive nodes that don't have a real agent yet.
---

# `run` skill

Invoked as `/pipeline:run <task description>`. This is what turns a user's request into one or
more running pipelines.

## What this skill does

1. **If the current session is not already running as the `orchestrator` agent**, spawn one via
   the `Task` tool (`subagent_type: orchestrator`) and hand it everything below; relay its
   output back to the user. If the current session *is* the orchestrator, do the following
   directly — there is no need to spawn a copy of yourself.
2. **Parse the arguments** into:
   - the task description(s) — split into independent tasks per design doc P4 if the request
     bundles unrelated work (the orchestrator's judgement call, not a mechanical split here);
   - a **prompt-layer config delta** — look for phrases that name a knob from
     `config/config_schema.json` (gate preset requests like "no gating until PR" →
     `gates.preset: full_auto`, "let me sign off on the design but nothing else" →
     `{preset: full_auto, add: [G2]}`, per design doc §6 Overrides table; check command
     overrides; budget/model overrides; etc.) — anything not named in prose stays unset, so it
     resolves from the project config or built-in defaults;
   - an optional stub scenario reference (`--stub <scenario>`, e.g. `--stub review-bounce`) — every
     node has a real agent as of Step 8, so this exists purely to drive the routing/gating/state/
     worktree machinery deterministically against `fixtures/stub-outcomes/<scenario>.yaml` for
     testing, per `agents/orchestrator.md`'s "Spawning a node" section, not to fill a gap in the
     roster. This flag does not exist in the shipped (post-Step-11) plugin and must never be
     presented to the user as a real feature.
3. **Hand off to the orchestrator's startup sequence** (`agents/orchestrator.md` §"Startup:
   resolving config, worktree, and state") with the parsed task(s) and prompt delta.

## What this skill does not do

- It does not resolve config, create worktrees, or route transitions itself — all of that is the
  orchestrator agent's job (`agents/orchestrator.md`). This skill is only the argument-parsing
  and dispatch layer between the `/pipeline:run` command and the orchestrator.
- It does not validate the prompt delta against the config schema — that happens inside the
  orchestrator's config-resolution step, which fails fast on anything invalid.
