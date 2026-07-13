---
name: decisions
description: >-
  List journaled decisions across running pipelines (or one named pipeline) and let the user
  acknowledge or override one. An override that requires redoing work hands off to the
  orchestrator, which rolls the affected pipeline back to the deciding stage and re-runs it.
---

# `decisions` skill

Invoked as `/pipeline:decisions [pipeline_id] [--ack <entry_id> | --override <entry_id> "<redo
reason>"]`.

## Listing (no `--ack`/`--override`, the default)

1. Determine the state root: `python3 -c "from lib.state import default_state_root; print(default_state_root('<repo_root>'))"`.
2. Collect the state directory for every pipeline under that root (or just `pipeline_id`, if
   given).
3. Merge and present their journals, most recent first:
   ```
   python3 -c "
   from lib.journal import merge_journals
   import json
   print(json.dumps(merge_journals(['<state_dir_1>', '<state_dir_2>', ...])))
   "
   ```
   Show every entry's `id`, `pipeline`, `agent`, `question`, `chosen`, `rationale`,
   `reversal_cost`, and `status` — pending entries first (design doc §8: these are what the user
   most likely came here to review), then acknowledged/overridden as history. This listing is
   read-only: it never mutates a journal or touches a worktree.

## Acknowledging (`--ack <entry_id>`)

A pure journal write — no pipeline state changes, no rollback, so this skill handles it directly
without involving the orchestrator:
```
python3 -c "from lib.journal import acknowledge_entry; import json; print(json.dumps(acknowledge_entry('<state_dir>', '<entry_id>')))"
```
`entry_id` embeds no pipeline reference on its own, so resolve which pipeline's state directory
owns it first (its `pipeline` field, found via the listing step above) before calling this.

## Overriding (`--override <entry_id> "<redo reason>"`)

Overriding a past decision may invalidate work already done downstream of the deciding stage —
that requires an actual rollback (re-entering the pipeline at that stage), which only the
orchestrator can do (design doc §4 P7: it alone spawns agents, owns worktrees, and writes
pipeline-state history). This skill therefore:

1. **If the current session is not already running as the `orchestrator` agent**, spawn one via
   the `Task` tool (`subagent_type: orchestrator`) for the pipeline that owns `entry_id`. If the
   current session *is* the orchestrator, do the following directly.
2. Resolve the entry and its rollback target:
   ```
   python3 -c "from lib.journal import resolve_override; import json; print(json.dumps(resolve_override('<state_dir>', '<entry_id>', '<redo reason>')))"
   ```
   This marks the entry `overridden` with the given redo reason and returns
   `rollback_to_node` — the stage that made the original decision.
3. Hand off to the orchestrator's own override-rollback handling
   (`agents/orchestrator.md` "Handling an override outside a gate"): append the audit trail,
   re-enter the pipeline at `rollback_to_node`, and let it re-run forward from there. Downstream
   artifacts from the discarded work are simply overwritten as the pipeline retraces its steps —
   nothing needs to be deleted up front.
4. Report the outcome (what is being redone, and from where) back to the user; the orchestrator
   continues the routing loop from there, riding along with any other pending journal entries the
   next time the user is prompted (design doc §8 "Presentation").

## What this skill does not do

- It never resolves a gate directly, even though overriding can look similar — a gate pause is
  handled through the orchestrator's own gate-prompt flow, not through this skill.
- It never fabricates a rollback for an entry that isn't actually `overridden` — `--ack` alone
  never triggers step 3.
