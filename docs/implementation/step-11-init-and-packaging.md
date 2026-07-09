# Step 11 — Init skill & packaging finalization

| | |
|---|---|
| **Depends on** | [Step 1](step-01-scaffold-and-config.md) (schema/defaults) + every knob-owning step |
| **Implements** | [§14 Packaging](../agent-pipeline-design.md#14-packaging), [§14 Init skill](../agent-pipeline-design.md#init-skill), [§9 transparency](../agent-pipeline-design.md#9-configuration-model), [Q5](../agent-pipeline-design.md#q5--default-gate-preset-when-neither-project-config-nor-prompt-sets-one) |
| **Status** | Planned |

## Goal

Close the plugin out as a shippable, versioned unit: the facultative **`init` skill** that generates
a project `pipeline.yaml`, final manifest completeness, versioning/migration, the bundled reference
doc, and the end-to-end transparency guarantees (resolved-config echo, manifest at first contact,
policy notes in the PR body). Comes last because `init` walks the **full knob registry**, which is
only complete once every knob-owning step exists.

## Scope

**In:** `agents`/`skills`/`commands` fully registered in `plugin.json`; `init` skill + `/pipeline:init`;
bundled `reference/agent-pipeline-design.md`; schema-versioned `pipeline.yaml` with migration;
run-manifest transparency wiring; packaging non-goals enforced.
**Out:** the custom-graph / Mermaid-authoring surface ([§13](../agent-pipeline-design.md#13-custom-agent-graphs-future-direction), future).

## Deliverables (tree delta)

```
commands/init.md
skills/init/SKILL.md
skills/init/inspect.py        # repo inspection → proposed knob values
reference/agent-pipeline-design.md   # bundled copy of the design
.claude-plugin/plugin.json    # (finalize) all 9 agents, 4 skills/commands, hooks, resources
tests/test_init.py
```

## Technical design

### Init skill (`init`)
[§14 init skill](../agent-pipeline-design.md#init-skill) — **facultative**: the pipeline must run
correctly without it (it only materializes config **layer 2**). Invocation `/pipeline:init`, or
auto-**suggested** by the orchestrator when it finds no `pipeline.yaml` (suggestion only, never a
blocker).
- **Inspect** the repo (`inspect.py`) to propose sensible values — build system, test runner,
  formatters/linters, CI config (the design's example repo → bazel build/test, clang-format,
  clang-tidy); propose `ticketing.github_issues` when the repo has a GitHub remote.
- **Walk the knob registry** interactively, showing each knob's built-in default and asking only
  about the ones worth customizing per project (gate preset — the [Q5](../agent-pipeline-design.md#q5--default-gate-preset-when-neither-project-config-nor-prompt-sets-one)
  default is `checkpoint`, but init asks so most repos pin their own answer — check commands, loop
  budgets, commit policy, token budget, per-agent models, ticketing incl. jira url/project/mapping);
  **accept all-defaults in one step**.
- **Validate** against `config_schema.json` before writing.
- **Write** `.agents/pipeline.yaml` at the repo root, each customized key commented with its
  rationale; **omit keys left at default** so defaults can evolve without stale copies.
- **Idempotent re-runs**: load the existing file, propose a diff, migrate the schema version forward.

### Packaging & versioning
[§14 plugin](../agent-pipeline-design.md#plugin): finalize `plugin.json` to declare all 9 agents, the
4 skills + command wrappers, the hooks, and the **resources** (config_schema, built_in_defaults, and
the bundled design doc as reference). **Versioned as one unit**; the run manifest records the plugin
version so a run is reproducible. The config_schema carries its own version; `pipeline.yaml` states
which schema version it targets; the init skill migrates old files forward.
**Non-goals enforced:** no pipeline components live loose in the project repo — the only project-side
artifact is the facultative `pipeline.yaml`.

### Transparency wiring (finalization)
[§9 transparency](../agent-pipeline-design.md#9-configuration-model): the fully resolved config (each
key's winning layer) is written to the run manifest at spawn and journaled; prompt-layer overrides are
read back in the spawn confirmation; the manifest is shown at first human contact and in the final
report; the PR body notes any non-default policy that shaped the change (e.g. `escalation_policy=never`).
Most of these are wired in earlier steps; this step audits that all four surfaces are present and
consistent end-to-end.

## Verification

**Tier 1 — unit tests (`test_init.py`):**
- `inspect.py` proposes the expected build/test/lint commands for `fixtures/sample-project` and
  proposes `github_issues` when a GitHub remote is present.
- Generated `pipeline.yaml` validates against the schema; only customized keys are written (defaults
  omitted) and each carries a rationale comment.
- Idempotent re-run on an existing file proposes a diff and migrates an older schema version forward.
- `plugin.json` declares every shipped component; a test enumerates `agents/`, `skills/`, `commands/`,
  `hooks/` and asserts each is registered.

**Tier 2 — end-to-end:**
- **Zero-config run** (no `pipeline.yaml`, bare prompt) still works and uses `checkpoint` (Q5) —
  proving init is facultative.
- **`/pipeline:init` → run:** init writes a config; a subsequent run picks up layer 2; the
  resolved-config echo, first-contact manifest, and PR-body policy note all reflect it.
- **Suggestion, not blocker:** in a repo with no `pipeline.yaml`, the orchestrator suggests init but
  proceeds when declined.
- **Fresh install smoke test:** installing only the plugin (no project artifacts) yields a working
  pipeline from built-in defaults alone.

## Definition of done

- [ ] `init` inspects, walks the full registry, validates, and writes a minimal commented `pipeline.yaml`;
      idempotent + schema-migrating; facultative (zero-config run works, defaulting to checkpoint).
- [ ] `plugin.json` declares all agents/skills/commands/hooks/resources; versioned as one unit; design
      doc bundled as reference.
- [ ] Schema versioning + `pipeline.yaml` schema-version + forward migration in place.
- [ ] All four §9 transparency surfaces present and consistent; no loose components in the project repo.
