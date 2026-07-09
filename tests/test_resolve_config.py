import json
from pathlib import Path

import pytest

from lib.resolve_config import ConfigError, load_defaults, load_schema, load_yaml, resolve

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "configs"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def defaults() -> dict:
    return load_defaults()


@pytest.fixture
def schema() -> dict:
    return load_schema()


# Golden-file case labels. These are arbitrary test-case names, unrelated to the design's
# topology options -- this implementation covers Option A only (see CLAUDE.md and
# docs/implementation/README.md §7); no fixture here sets `topology` to anything but option_a.
GOLDEN_CASES = ["worked-example", "defaults-only", "delta-precedence"]


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_golden_file_resolution(defaults, schema, case):
    project = load_yaml(FIXTURES / f"project-{case}.yaml")
    prompt = _load_json(FIXTURES / f"prompt-delta-{case}.json")
    expected_resolved = _load_json(FIXTURES / f"expected-resolved-{case}.json")
    expected_provenance = _load_json(FIXTURES / f"expected-provenance-{case}.json")

    resolved, provenance = resolve(defaults, project, prompt, schema=schema)

    assert resolved == expected_resolved
    assert provenance == expected_provenance


def test_design_section_9_worked_example(defaults, schema):
    # design doc §9: gates.preset=full_auto from prompt over project's checkpoint;
    # implementer.inner_loop.max_iterations=20 from prompt; checks from project;
    # everything else from defaults.
    project = load_yaml(FIXTURES / "project-worked-example.yaml")
    prompt = _load_json(FIXTURES / "prompt-delta-worked-example.json")

    resolved, provenance = resolve(defaults, project, prompt, schema=schema)

    assert resolved["gates"]["preset"] == "full_auto"
    assert provenance["gates.preset"] == "prompt"
    assert resolved["implementer"]["inner_loop"]["max_iterations"] == 20
    assert provenance["implementer.inner_loop.max_iterations"] == "prompt"
    assert provenance["checks.build"] == "project"
    assert provenance["checks.static"] == "project"
    assert provenance["submitter.single_commit"] == "project"
    untouched = set(provenance) - {
        "gates.preset",
        "implementer.inner_loop.max_iterations",
        "checks.build",
        "checks.static",
        "submitter.single_commit",
    }
    assert all(provenance[key] == "defaults" for key in untouched)


def test_no_config_resolves_to_defaults(defaults, schema):
    resolved, provenance = resolve(defaults, {}, {}, schema=schema)
    assert resolved == defaults
    assert all(layer == "defaults" for layer in provenance.values())


def test_gates_add_remove_are_deltas_not_wholesale_replacement(defaults, schema):
    project = {"gates": {"add": ["G3"], "remove": ["G7"]}}
    prompt = {"gates": {"add": ["G6"]}}
    resolved, provenance = resolve(defaults, project, prompt, schema=schema)

    assert resolved["gates"]["add"] == ["G3", "G6"]
    assert resolved["gates"]["remove"] == ["G7"]
    assert provenance["gates.add"] == "project+prompt"
    assert provenance["gates.remove"] == "project"


def test_gates_add_duplicate_across_layers_is_not_repeated(defaults, schema):
    project = {"gates": {"add": ["G3"]}}
    prompt = {"gates": {"add": ["G3", "G6"]}}
    resolved, _ = resolve(defaults, project, prompt, schema=schema)
    assert resolved["gates"]["add"] == ["G3", "G6"]


def test_ordinary_lists_replace_wholesale(defaults, schema):
    project = {"checks": {"static": ["clang-format", "clang-tidy"]}}
    prompt = {"checks": {"static": ["ruff"]}}
    resolved, provenance = resolve(defaults, project, prompt, schema=schema)
    assert resolved["checks"]["static"] == ["ruff"]
    assert provenance["checks.static"] == "prompt"


def test_precedence_matrix_prompt_over_project_over_defaults(defaults, schema):
    # budget.warn_ratio set at all three layers: prompt should win.
    project = {"budget": {"warn_ratio": 0.6}}
    prompt = {"budget": {"warn_ratio": 0.5}}
    resolved, provenance = resolve(defaults, project, prompt, schema=schema)
    assert resolved["budget"]["warn_ratio"] == 0.5
    assert provenance["budget.warn_ratio"] == "prompt"

    # project only (no prompt override): project should win over defaults.
    resolved2, provenance2 = resolve(defaults, project, {}, schema=schema)
    assert resolved2["budget"]["warn_ratio"] == 0.6
    assert provenance2["budget.warn_ratio"] == "project"

    # neither layer sets it: defaults win.
    resolved3, provenance3 = resolve(defaults, {}, {}, schema=schema)
    assert resolved3["budget"]["warn_ratio"] == 0.8
    assert provenance3["budget.warn_ratio"] == "defaults"


def test_deep_merge_touches_only_the_keys_it_sets(defaults, schema):
    project = {"autonomy": {"designer": "lean_decide"}}
    resolved, provenance = resolve(defaults, project, {}, schema=schema)
    assert resolved["autonomy"]["designer"] == "lean_decide"
    assert resolved["autonomy"]["refiner"] == "ask_freely"
    assert resolved["autonomy"]["implementer"] == "lean_decide"
    assert provenance["autonomy.designer"] == "project"
    assert provenance["autonomy.refiner"] == "defaults"


# --- Fail-fast validation -------------------------------------------------------------


def test_unknown_key_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="unknown key"):
        resolve(defaults, {"nonexistent_knob": True}, {}, schema=schema)


def test_unknown_nested_key_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="unknown key"):
        resolve(defaults, {"gates": {"bogus": 1}}, {}, schema=schema)


def test_wrong_enum_value_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="is not one of"):
        resolve(defaults, {"gates": {"preset": "yolo"}}, {}, schema=schema)


def test_wrong_type_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="expected type"):
        resolve(defaults, {"submitter": {"single_commit": "true"}}, {}, schema=schema)


def test_prompt_layer_unknown_key_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="unknown key"):
        resolve(defaults, {}, {"not_a_real_knob": 1}, schema=schema)


def test_ticketing_jira_without_url_or_project_rejected(defaults, schema):
    with pytest.raises(ConfigError, match="missing required key"):
        resolve(defaults, {"ticketing": {"system": "jira"}}, {}, schema=schema)


def test_ticketing_jira_with_only_url_rejected(defaults, schema):
    with pytest.raises(ConfigError):
        resolve(
            defaults,
            {"ticketing": {"system": "jira", "jira": {"url": "https://jira.example.com"}}},
            {},
            schema=schema,
        )


def test_ticketing_jira_fully_configured_is_accepted(defaults, schema):
    resolved, provenance = resolve(
        defaults,
        {
            "ticketing": {
                "system": "jira",
                "jira": {"url": "https://jira.example.com", "project": "PROJ"},
            }
        },
        {},
        schema=schema,
    )
    assert resolved["ticketing"]["system"] == "jira"
    assert resolved["ticketing"]["jira"] == {"url": "https://jira.example.com", "project": "PROJ"}
    assert provenance["ticketing.jira.url"] == "project"


def test_ticketing_github_issues_does_not_require_jira_block(defaults, schema):
    resolved, _ = resolve(defaults, {"ticketing": {"system": "github_issues"}}, {}, schema=schema)
    assert resolved["ticketing"]["system"] == "github_issues"


def test_defaults_file_itself_is_schema_valid(defaults, schema):
    # If the shipped defaults ever drift out of sync with the schema, this must fail loudly.
    resolve(defaults, {}, {}, schema=schema)
