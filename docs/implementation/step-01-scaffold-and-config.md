# Step 1 — Plugin scaffold & configuration model

| | |
|---|---|
| **Depends on** | — |
| **Implements** | [§9 Configuration model](../agent-pipeline-design.md#9-configuration-model), [§14 Packaging (skeleton)](../agent-pipeline-design.md#14-packaging) |
| **Status** | Planned |

## Goal

Stand up an installable-but-inert plugin and the **configuration foundation every later step reads
from**: the JSON schema for `pipeline.yaml`, the built-in defaults (config layer 1), and the
deterministic 3-layer resolver with fail-fast validation. Nothing runs a pipeline yet; this step
makes "install the plugin and resolve a config" work and be tested.

## Scope

**In:** plugin manifest; directory skeleton; `config/config_schema.json`; `config/built_in_defaults.yaml`;
`lib/resolve_config.py`; unit tests + config fixtures.
**Out:** agents, routing, worktrees, any pipeline execution (Steps 2+).

## Deliverables (tree delta)

```
.claude-plugin/plugin.json
config/config_schema.json
config/built_in_defaults.yaml
lib/resolve_config.py
fixtures/configs/{project-worked-example.yaml, prompt-delta-worked-example.json, expected-resolved-worked-example.json, ...}
tests/test_resolve_config.py
tests/test_schema.py
```

## Technical design

### `plugin.json`
Minimal valid manifest — `name: agent-pipeline`, version (tracks the plugin version, not the design
doc), description, and declared component directories (`agents/`, `commands/`, `skills/`, `hooks/`).
At this step the component dirs are empty or absent; the manifest is filled in as later steps add
components. It also records the **config_schema version** so a `pipeline.yaml` can state which schema
it targets ([§14 versioning](../agent-pipeline-design.md#14-packaging)).

### `config_schema.json`
JSON Schema (draft 2020-12) covering **every knob in the registry** ([§9 knob registry](../agent-pipeline-design.md#knob-registry)):
`topology`, `worktree.*`, `gates.preset`/`gates.add`/`gates.remove`, `escalation_policy`,
`autonomy.<agent>`, `loop_limits.*`, `implementer.*`, `checks.*`, `submitter.single_commit`,
`pr_shepherd.enabled`, `documenter.skip_allowed`, `decision_journal.in_pr_body`, `budget.*`,
`model.*`, `ticketing.*`. Enumerated knobs (e.g. `gates.preset ∈ {full_auto, checkpoint,
pre_submit_only, paranoid}`) constrain their values. **`topology` is enumerated to `{option_a}`
only** — the design lists `option_b`/`option_c` as future alternatives, but this implementation
covers Option A exclusively (see [README §7](README.md#7-out-of-scope-for-this-plan)); the other
two values are rejected rather than accepted-but-ignored, so misconfiguration fails fast instead of
silently running Option A under a different label.
`additionalProperties: false` at each level so **unknown keys are rejected** — the design's fail-fast
rule. Conditional requirements encoded with `if/then` (e.g. `ticketing.system: jira` requires
`ticketing.jira.url` and `ticketing.jira.project`).

### `built_in_defaults.yaml`
Config **layer 1**: one value per knob, exactly the "Default" column of the knob registry
(`topology: option_a`, `gates.preset: checkpoint`, `implementer.inner_loop.max_iterations: 10`,
`budget.tokens: null`, `model.default: inherit`, `ticketing.system: none`, …). This file is the
single source for defaults so they can evolve with the plugin without stale copies in projects.

### `resolve_config.py`
Pure function `resolve(defaults, project_yaml, prompt_delta) -> (resolved, provenance)` implementing
[§9 merge semantics](../agent-pipeline-design.md#9-configuration-model):

- **Deep-merge maps** key-by-key; later layers touch only keys they set.
- **Scalars/lists replace wholesale** — no list concatenation — with the single exception that
  `gates.add`/`gates.remove` are applied as explicit deltas against the preset's gate set.
- **Provenance**: for each resolved key, record its winning layer (defaults/project/prompt) — this
  is what the run manifest and the resolved-config echo need in Step 2.
- **Validation** against `config_schema.json` happens **before** merge for each layer; an unknown or
  ill-typed key raises immediately (fail fast, no silent typo).
- The prompt layer arrives as an already-typed delta (a JSON object). Parsing *natural language*
  directives into that delta is the orchestrator's job (Step 2); this function's contract is typed
  in → resolved out, so it is deterministically testable.

The resolver is a library the orchestrator calls (or replicates by reasoning); keeping it as tested
code means config precedence is never left to LLM recall.

## Verification

**Tier 1 — unit tests (`tests/`):**
- Golden-file tests: each `fixtures/configs/*` triple (project yaml + prompt delta → expected
  resolved + expected provenance) resolves exactly, including the §9 worked example
  (`gates.preset: full_auto` from prompt over `checkpoint`; `implementer.inner_loop.max_iterations:
  20` from prompt; `checks` from project; everything else from defaults).
- `gates.add`/`gates.remove` delta semantics vs. wholesale list replacement for other lists.
- Precedence matrix: for a knob set in all three layers, prompt wins; project over defaults; etc.
- **Fail-fast:** unknown key, wrong enum value, wrong type, and `ticketing.system: jira` without
  `url`/`project` each raise with a clear message.
- Schema self-check: every knob in the registry has a schema entry and a default (a test iterates
  the registry list and asserts coverage — guards against drift when knobs are added).

**Tier 2 — plugin loads:** installing the plugin in Claude Code surfaces no manifest errors and the
(empty) `/pipeline:` namespace is registered. No pipeline behavior expected yet.

## Definition of done

- [ ] `plugin.json` valid; plugin installs without error.
- [ ] Schema covers every knob; `additionalProperties:false` enforced; conditional requirements encoded.
- [ ] Defaults file has exactly one entry per knob, matching the registry.
- [ ] Resolver passes all golden-file, precedence, delta, and fail-fast tests.
- [ ] Design §9 worked example reproduced by a test.
