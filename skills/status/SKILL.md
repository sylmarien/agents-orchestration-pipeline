---
name: status
description: >-
  Show running agent-pipeline pipelines: current node, pending gates, and (from Step 3) pending
  decision-journal entries, read from each pipeline's state directory.
---

# `status` skill

Invoked as `/pipeline:status [pipeline_id]`. Read-only — never advances a pipeline, never
resolves a gate, never touches a worktree.

## What this skill does

1. Determine the state root: `python3 -c "from lib.state import default_state_root; print(default_state_root('<repo_root>'))"`
   (or the project's configured state root, if this build later exposes one as a knob — Step 2
   does not add such a knob; see `lib/state.py`'s module docstring for the default layout).
2. For each pipeline directory under the state root (or just the one named by `pipeline_id`, if
   given):
   - `python3 -c "from lib.state import read_manifest; import json; print(json.dumps(read_manifest('<state_dir>')))"`
     for the resolved config and provenance this run was spawned with.
   - `python3 -m lib.state latest-position '{"state_dir": "<state_dir>"}'` for the current node
     (`null` means the pipeline has not started routing yet, or has already reached the terminal
     node — check the history's last record to tell those apart).
   - `python3 -m lib.state read-history '{"state_dir": "<state_dir>"}'` — scan for the most
     recent `gate_open` record with no matching later `gate_resolved` record on the same gate: an
     unresolved one is a pending gate blocking this pipeline right now.
3. Present, per pipeline: `pipeline_id`, current node, whether it's paused on a gate (and which),
   and the resolved gate preset. Pending decision-journal entries are not yet produced by
   anything in this build (the journal lands in Step 3) — omit that section until then rather
   than fabricating it.

## What this skill does not do

- It never spawns an agent, resolves a gate, or mutates any state-directory file — it only
  reads. Resolving a paused gate happens through the orchestrator's own gate-prompt flow
  (`agents/orchestrator.md`), not through this skill.
