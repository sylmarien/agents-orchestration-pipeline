import json
import re
from pathlib import Path

import pytest

from lib.resolve_config import ConfigError, load_defaults, load_schema, resolve

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
_KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

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


# --- Tier 2: plugin marketplace manifest is well-formed and installable -----------------------


@pytest.fixture
def marketplace() -> dict:
    with open(MARKETPLACE_MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def test_marketplace_manifest_is_valid_json(marketplace):
    assert isinstance(marketplace.get("name"), str) and marketplace["name"]
    assert isinstance(marketplace.get("owner"), dict) and marketplace["owner"].get("name")
    assert isinstance(marketplace.get("plugins"), list) and marketplace["plugins"]


def test_marketplace_name_is_kebab_case(marketplace):
    # Reserved-name checks and the claude.ai marketplace sync both require kebab-case
    # (docs: "Plugin name is not kebab-case" warning applies to plugin names; the same
    # convention is followed here for the marketplace name itself).
    assert _KEBAB_CASE_RE.match(marketplace["name"]), f"{marketplace['name']!r} is not kebab-case"


# Marketplace names Anthropic reserves for official use -- a third-party marketplace must never
# collide with one of these (docs/en/plugin-marketplaces "Reserved names").
_RESERVED_MARKETPLACE_NAMES = {
    "claude-code-marketplace",
    "claude-code-plugins",
    "claude-plugins-official",
    "claude-plugins-community",
    "claude-community",
    "anthropic-marketplace",
    "anthropic-plugins",
    "agent-skills",
    "anthropic-agent-skills",
    "knowledge-work-plugins",
    "life-sciences",
    "claude-for-legal",
    "claude-for-financial-services",
    "financial-services-plugins",
    "first-party-plugins",
    "healthcare",
}


def test_marketplace_name_is_not_reserved(marketplace):
    assert marketplace["name"] not in _RESERVED_MARKETPLACE_NAMES


def test_marketplace_lists_the_agent_pipeline_plugin_at_repo_root(marketplace):
    entries = {p["name"]: p for p in marketplace["plugins"]}
    assert "agent-pipeline" in entries
    entry = entries["agent-pipeline"]
    # A relative-path source resolves against the marketplace root (the directory containing
    # `.claude-plugin/`), which for this repo is the repo root itself -- the same root that
    # already carries `.claude-plugin/plugin.json` (this file's own directory).
    assert entry["source"] == "./"
    assert (REPO_ROOT / ".claude-plugin" / "plugin.json").is_file()


def test_marketplace_plugin_names_are_unique(marketplace):
    names = [p["name"] for p in marketplace["plugins"]]
    assert len(names) == len(set(names))


def test_marketplace_entry_does_not_shadow_plugin_json_version(marketplace):
    # Claude Code always prefers plugin.json's `version` over the marketplace entry's, silently --
    # setting both risks a stale marketplace value masking real releases (docs/en/plugin-
    # marketplaces "Version resolution"). Since plugin.json already pins a version, the
    # marketplace entry must leave `version` unset so plugin.json stays the single source of truth.
    entries = {p["name"]: p for p in marketplace["plugins"]}
    with open(PLUGIN_MANIFEST, encoding="utf-8") as f:
        plugin_manifest = json.load(f)
    if plugin_manifest.get("version"):
        assert "version" not in entries["agent-pipeline"]
