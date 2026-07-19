---
name: init
description: >-
  Generate or update this project's .agents/pipeline.yaml (configuration layer 2): inspect the
  repo for evidence-backed proposals, walk the knob registry interactively, and write only the
  keys that differ from the built-in defaults. Facultative -- the pipeline runs correctly from
  built-in defaults alone, with no pipeline.yaml at all.
---

# `init` skill

Invoked as `/pipeline:init`. Unlike `run`/`status`/`decisions`, this skill never spawns the
orchestrator and never touches a worktree or a pipeline's state directory (design doc §14 "Init
skill": **facultative** — "the pipeline must run correctly without it... the skill only
materializes configuration layer 2"). Handle everything below directly in the current session.

## What this skill does

1. **Determine the repo root** (the git repo `/pipeline:init` was invoked in) and the path
   `.agents/pipeline.yaml` within it.
2. **Load any existing file** (this is what makes a re-run idempotent, design doc §14
   "Idempotent re-runs"):
   ```
   python3 -c "
   import json
   from pathlib import Path
   from lib.resolve_config import load_yaml
   from skills.init.inspect import parse_schema_version
   path = Path('.agents/pipeline.yaml')
   existing = load_yaml(path) if path.exists() else {}
   existing_version = parse_schema_version(path.read_text(encoding='utf-8')) if path.exists() else None
   print(json.dumps({'existing': existing, 'existing_version': existing_version}))
   "
   ```
   A first-ever run has `existing: {}`, `existing_version: null` — treat that as "nothing to
   diff against," not an error. `existing_version` older than the current plugin's
   `configSchemaVersion` (`.claude-plugin/plugin.json`) is what step 4's migration case handles;
   there is only ever been one schema version so far, so in practice this is a no-op today —
   `render_pipeline_yaml` (step 6) always stamps the *current* version regardless of what the
   file previously carried, so a plain re-run migrates it forward for free.
3. **Inspect the repo** for evidence-backed proposals (build/test/static commands from a
   Makefile, `ticketing.system: github_issues` when `origin` is GitHub-hosted):
   ```
   python3 -c "from skills.init.inspect import inspect_repo; import json; print(json.dumps(inspect_repo('<repo_root>')))"
   ```
   Only knobs with concrete repo evidence come back here (design doc: "for this repo it would
   propose bazel build/test, clang-format, clang-tidy... propose ticketing.github_issues when
   the repo has a GitHub remote"). Everything else stays unproposed and is walked at its
   built-in default in the next step.
4. **Walk the full knob registry** (`config/config_schema.json`; every row of
   `docs/agent-pipeline-design.md`'s §9 knob registry table), showing each knob's built-in
   default (`config/built_in_defaults.yaml`) and step 3's proposal where one exists. Ask via
   `AskUserQuestion` only about the ones worth customizing per project — the design doc's own
   worked list: gate preset, check commands, loop budgets, commit policy
   (`submitter.single_commit`), token budget, per-agent models, and ticketing (system, plus for
   `jira`: url/project/status mapping). Batch these into as few round-trips as practical — one
   consolidated set of questions, the same "ask freely but don't nag" shape the refiner uses for
   `ask_freely` (`agents/refiner.md`) — rather than one prompt per knob.
   - **Offer "accept all proposed/default values" as the first choice**, so a user who just
     wants step 3's evidence-backed proposals (or nothing at all) can finish in one step (design
     doc §14 "accept all-defaults in one step").
   - **On a re-run** (`existing` from step 2 is non-empty), don't start the conversation from
     scratch — diff the new proposal against what's already on disk and ask only about what
     actually changed:
     ```
     python3 -c "from skills.init.inspect import diff_against_existing; import json; print(json.dumps(diff_against_existing(<existing>, <proposed-and-answered dict>)))"
     ```
     Present `added`/`changed`/`removed` as the diff to confirm; anything absent from the diff
     stays exactly as it was in the existing file.
5. **Assemble the customized-keys dict**: step 3's proposals the user accepted, plus anything
   they set by hand in step 4. A knob the user left at (or explicitly confirmed) its built-in
   default is never included — design doc §14 "omit keys left at default so defaults can evolve
   without stale copies in projects."
6. **Validate before writing** — fail fast on anything that slipped through malformed:
   ```
   python3 -c "
   from lib.resolve_config import load_schema, validate
   validate(<customized dict>, load_schema(), 'project_config')
   "
   ```
   A `ConfigError` here means step 4/5 produced something invalid; report it and let the user
   correct that specific answer rather than writing a broken file.
7. **Render and write** `.agents/pipeline.yaml`, one rationale string per customized top-level
   key (why it's non-default — "detected from this repo's Makefile" for an inspection-sourced
   proposal, or a short paraphrase of what the user asked for in step 4):
   ```
   python3 -c "
   import json
   from pathlib import Path
   from skills.init.inspect import render_pipeline_yaml
   manifest = json.loads(Path('<plugin_root>/.claude-plugin/plugin.json').read_text(encoding='utf-8'))
   text = render_pipeline_yaml(<customized dict>, <rationale dict, one entry per customized top-level key>, manifest['configSchemaVersion'])
   out = Path('.agents/pipeline.yaml')
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(text, encoding='utf-8')
   print(text)
   "
   ```
8. **Report** the written path and a summary of what's customized (and, on a re-run, what
   changed per step 4's diff) back to the user. This is the *only* effect of this skill — no
   worktree is created, no state directory is written, and no pipeline run starts just because
   `/pipeline:init` was invoked. A subsequent `/pipeline:run` picks the file up as configuration
   layer 2, same as if it had been hand-written.

## What this skill does not do

- It never resolves per-run overrides — that is the prompt layer, handled entirely by
  `/pipeline:run` (design doc §14 "Out of scope").
- It never installs or configures the plugin itself.
- It never spawns the orchestrator, creates a worktree, or writes anything under a pipeline's
  state directory.
- It never blocks a run: the orchestrator only *suggests* `/pipeline:init` when it finds no
  `.agents/pipeline.yaml` in a repo it's spawned in (`agents/orchestrator.md`, "Startup" step 3),
  and proceeds from built-in defaults either way when the user declines or ignores the
  suggestion.
