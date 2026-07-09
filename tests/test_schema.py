import json
from pathlib import Path

import pytest

from lib.resolve_config import ConfigError, load_defaults, load_schema, resolve

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"

AGENTS = [
    "refiner",
    "designer",
    "implementer",
    "code_reviewer",
    "documenter",
    "documentation_reviewer",
    "submitter",
    "pr_shepherd",
]

# Every dotted knob path from the design doc §9 knob registry table, `<agent>` rows expanded
# to one path per agent and `.*` rows expanded to their concrete sub-knobs.
REGISTRY_KNOBS = (
    ["topology", "worktree.root", "worktree.name_template", "gates.preset", "gates.add", "gates.remove", "escalation_policy"]
    + [f"autonomy.{agent}" for agent in AGENTS]
    + ["loop_limits.l1", "loop_limits.l3", "loop_limits.escalations", "loop_limits.post_pr"]
    + ["implementer.inner_loop.max_iterations", "implementer.tdd"]
    + ["checks.build", "checks.test", "checks.static"]
    + ["submitter.single_commit", "pr_shepherd.enabled", "documenter.skip_allowed", "decision_journal.in_pr_body"]
    + ["budget.tokens", "budget.usd", "budget.warn_ratio"]
    + ["model.default"]
    + [f"model.{agent}" for agent in AGENTS]
    + [
        "ticketing.system",
        "ticketing.jira.url",
        "ticketing.jira.project",
        "ticketing.status_mapping",
        "ticketing.post_report",
        "ticketing.sync_spec",
        "ticketing.create_if_missing",
    ]
)

# Knobs whose registry "Default" is derived from a sibling knob rather than a literal value:
# model.<agent> defaults to model.default; checks.* default to repo auto-detection. Both are
# intentionally absent (or null) in built_in_defaults.yaml -- see the comment at its top.
DERIVED_DEFAULT_PATHS = {f"model.{agent}" for agent in AGENTS} | {"checks.build", "checks.test", "checks.static"}


def _schema_has_path(schema: dict, path: str) -> bool:
    node = schema
    for part in path.split("."):
        props = node.get("properties", {})
        if part not in props:
            return False
        node = props[part]
    return True


def _defaults_has_path(defaults: dict, path: str) -> bool:
    node = defaults
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@pytest.fixture
def schema() -> dict:
    return load_schema()


@pytest.fixture
def defaults() -> dict:
    return load_defaults()


@pytest.mark.parametrize("path", REGISTRY_KNOBS)
def test_every_registry_knob_has_a_schema_entry(schema, path):
    assert _schema_has_path(schema, path), f"{path} has no entry in config_schema.json"


@pytest.mark.parametrize("path", [p for p in REGISTRY_KNOBS if p not in DERIVED_DEFAULT_PATHS])
def test_every_non_derived_knob_has_a_default(defaults, path):
    assert _defaults_has_path(defaults, path), f"{path} has no built-in default"


def test_derived_default_knobs_are_absent_or_null_in_defaults(defaults):
    assert "refiner" not in defaults.get("model", {})
    assert defaults["checks"]["build"] is None
    assert defaults["checks"]["test"] is None
    assert defaults["checks"]["static"] is None


@pytest.mark.parametrize(
    "container_path",
    ["", "worktree", "gates", "autonomy", "loop_limits", "implementer", "checks", "budget", "model", "ticketing", "ticketing.jira"],
)
def test_additional_properties_false_enforced(schema, container_path):
    node = schema
    if container_path:
        for part in container_path.split("."):
            node = node["properties"][part]
    assert node["additionalProperties"] is False, f"{container_path or '<root>'} must reject unknown keys"


def test_topology_is_restricted_to_option_a(defaults, schema):
    # option_b/option_c are out of scope for this implementation (README §7) -- the schema must
    # reject them rather than silently accepting-but-ignoring an unsupported topology.
    assert schema["properties"]["topology"]["enum"] == ["option_a"]
    assert defaults["topology"] == "option_a"
    with pytest.raises(ConfigError):
        resolve(defaults, {"topology": "option_b"}, {}, schema=schema)
    with pytest.raises(ConfigError):
        resolve(defaults, {}, {"topology": "option_c"}, schema=schema)


def test_enumerated_knobs_are_constrained(schema):
    assert set(schema["properties"]["gates"]["properties"]["preset"]["enum"]) == {
        "full_auto",
        "checkpoint",
        "pre_submit_only",
        "paranoid",
    }


def test_ticketing_jira_conditional_requirement_is_encoded(schema):
    conditionals = schema["properties"]["ticketing"]["allOf"]
    assert any("if" in c and "then" in c for c in conditionals)


# --- Tier 2: plugin manifest is well-formed and installable -----------------------------------


def test_plugin_manifest_is_valid_json():
    with open(PLUGIN_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["name"] == "agent-pipeline"
    assert isinstance(manifest.get("version"), str) and manifest["version"]
    assert isinstance(manifest.get("description"), str) and manifest["description"]


def test_config_schema_is_valid_json_document():
    with open(REPO_ROOT / "config" / "config_schema.json", encoding="utf-8") as f:
        schema = json.load(f)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
