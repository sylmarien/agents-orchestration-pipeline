import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lib.resolve_config import ConfigError, load_defaults, load_schema, resolve, validate
from skills.init.inspect import diff_against_existing, inspect_repo, parse_schema_version, render_pipeline_yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_PROJECT = _REPO_ROOT / "fixtures" / "sample-project"
_PLUGIN_MANIFEST = _REPO_ROOT / ".claude-plugin" / "plugin.json"


def _run(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def sample_project(tmp_path) -> Path:
    dest = tmp_path / "sample-project"
    shutil.copytree(_SAMPLE_PROJECT, dest)
    return dest


@pytest.fixture
def git_repo(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    _run(["git", "init"], repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], repo_dir)
    _run(["git", "config", "user.name", "Test"], repo_dir)
    (repo_dir / "README.md").write_text("hello\n")
    _run(["git", "add", "README.md"], repo_dir)
    _run(["git", "commit", "-m", "initial"], repo_dir)
    return repo_dir


# --- inspect_repo: checks proposal (reuses lib.checks) ------------------------------------------


def test_inspect_repo_proposes_checks_from_sample_project_makefile(sample_project):
    proposals = inspect_repo(sample_project)
    assert proposals["checks"] == {
        "build": "make build",
        "test": "make test",
        "static": ["make format-check", "make lint"],
    }


def test_inspect_repo_omits_checks_with_no_makefile(tmp_path):
    proposals = inspect_repo(tmp_path)
    assert "checks" not in proposals


# --- inspect_repo: ticketing proposal (reuses lib.ticketing.github) -----------------------------


def test_inspect_repo_proposes_github_issues_for_a_github_remote(git_repo):
    _run(["git", "remote", "add", "origin", "https://github.com/acme/widgets.git"], git_repo)
    proposals = inspect_repo(git_repo)
    assert proposals["ticketing"] == {"system": "github_issues"}


def test_inspect_repo_omits_ticketing_for_a_non_github_remote(git_repo):
    _run(["git", "remote", "add", "origin", "https://gitlab.com/acme/widgets.git"], git_repo)
    proposals = inspect_repo(git_repo)
    assert "ticketing" not in proposals


def test_inspect_repo_omits_ticketing_with_no_remote(git_repo):
    proposals = inspect_repo(git_repo)
    assert "ticketing" not in proposals


# --- render_pipeline_yaml / parse_schema_version round trip -------------------------------------


def test_render_pipeline_yaml_only_writes_customized_keys():
    text = render_pipeline_yaml({"gates": {"preset": "full_auto"}}, {}, "1.0.0")
    data = yaml.safe_load(text)
    assert data == {"gates": {"preset": "full_auto"}}


def test_render_pipeline_yaml_includes_rationale_comment():
    text = render_pipeline_yaml({"gates": {"preset": "full_auto"}}, {"gates": "requested during /pipeline:init"}, "1.0.0")
    assert "# requested during /pipeline:init" in text


def test_render_pipeline_yaml_header_round_trips_through_parse_schema_version():
    text = render_pipeline_yaml({}, {}, "1.0.0")
    assert parse_schema_version(text) == "1.0.0"


def test_parse_schema_version_absent_returns_none():
    assert parse_schema_version("gates:\n  preset: checkpoint\n") is None


def test_rendered_pipeline_yaml_validates_against_schema(sample_project):
    proposals = inspect_repo(sample_project)
    text = render_pipeline_yaml(proposals, {"checks": "detected from this repo's Makefile"}, "1.0.0")
    data = yaml.safe_load(text)
    validate(data, load_schema(), "project_config")


def test_rendered_pipeline_yaml_resolves_cleanly_against_built_in_defaults(sample_project):
    # A generated file must be usable as configuration layer 2 exactly like a hand-written one --
    # the same three-layer resolver the orchestrator calls at spawn (design doc §9).
    proposals = inspect_repo(sample_project)
    text = render_pipeline_yaml(proposals, {"checks": "detected"}, "1.0.0")
    project_config = yaml.safe_load(text)
    resolved, provenance = resolve(load_defaults(), project_config, {}, schema=load_schema())
    assert resolved["checks"]["build"] == "make build"
    assert provenance["checks.build"] == "project"


def test_render_pipeline_yaml_empty_customization_is_header_only():
    text = render_pipeline_yaml({}, {}, "1.0.0")
    assert yaml.safe_load(text) is None or yaml.safe_load(text) == {}
    assert "schema_version: 1.0.0" in text


# --- diff_against_existing -----------------------------------------------------------------------


def test_diff_reports_added_keys():
    diff = diff_against_existing({}, {"gates": {"preset": "full_auto"}})
    assert diff == {"added": {"gates": {"preset": "full_auto"}}, "removed": {}, "changed": {}}


def test_diff_reports_removed_keys():
    diff = diff_against_existing({"gates": {"preset": "full_auto"}}, {})
    assert diff == {"added": {}, "removed": {"gates": {"preset": "full_auto"}}, "changed": {}}


def test_diff_reports_changed_keys():
    diff = diff_against_existing({"gates": {"preset": "full_auto"}}, {"gates": {"preset": "paranoid"}})
    assert diff == {
        "added": {},
        "removed": {},
        "changed": {"gates": {"from": {"preset": "full_auto"}, "to": {"preset": "paranoid"}}},
    }


def test_diff_is_empty_for_identical_config():
    same = {"gates": {"preset": "checkpoint"}}
    assert diff_against_existing(same, dict(same)) == {"added": {}, "removed": {}, "changed": {}}


# --- Idempotent re-run / schema migration ---------------------------------------------------------


def test_rerun_on_older_schema_version_stamps_current_version_forward(tmp_path):
    old_text = render_pipeline_yaml({"gates": {"preset": "full_auto"}}, {}, "0.9.0")
    pipeline_yaml = tmp_path / "pipeline.yaml"
    pipeline_yaml.write_text(old_text, encoding="utf-8")

    assert parse_schema_version(pipeline_yaml.read_text(encoding="utf-8")) == "0.9.0"

    # A re-run re-renders with the plugin's *current* schema version regardless of what the file
    # previously carried -- this is the whole of "migration" while there is only one schema shape.
    manifest = json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    new_text = render_pipeline_yaml({"gates": {"preset": "full_auto"}}, {}, manifest["configSchemaVersion"])
    pipeline_yaml.write_text(new_text, encoding="utf-8")

    assert parse_schema_version(pipeline_yaml.read_text(encoding="utf-8")) == manifest["configSchemaVersion"]
    assert yaml.safe_load(new_text) == yaml.safe_load(old_text)


# --- CLI -------------------------------------------------------------------------------------


def test_cli_prints_inspection_json(sample_project):
    result = subprocess.run(
        [sys.executable, "-m", "skills.init.inspect", str(sample_project)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["checks"]["build"] == "make build"


# --- Structural completeness: every shipped component is present and well-formed ----------------

_SKILL_COMMAND_PAIRS = ["run", "status", "decisions", "init"]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter block"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)


def test_every_skill_has_a_matching_command_wrapper():
    for name in _SKILL_COMMAND_PAIRS:
        assert (_REPO_ROOT / "skills" / name / "SKILL.md").is_file(), f"missing skills/{name}/SKILL.md"
        assert (_REPO_ROOT / "commands" / f"{name}.md").is_file(), f"missing commands/{name}.md"


def test_every_agent_file_has_valid_frontmatter():
    agents_dir = _REPO_ROOT / "agents"
    agent_files = sorted(agents_dir.glob("*.md"))
    assert len(agent_files) == 9  # orchestrator + 8 spokes (design doc §14 "Agents (9)")
    for path in agent_files:
        fm = _frontmatter(path)
        assert fm.get("name") == path.stem
        assert fm.get("description")
        assert fm.get("tools")


def test_every_skill_file_has_valid_frontmatter():
    for name in _SKILL_COMMAND_PAIRS:
        fm = _frontmatter(_REPO_ROOT / "skills" / name / "SKILL.md")
        assert fm.get("name") == name
        assert fm.get("description")


def test_hooks_json_references_existing_scripts():
    hooks = json.loads((_REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for events in hooks["hooks"].values():
        for matcher_entry in events:
            for hook in matcher_entry["hooks"]:
                for arg in hook.get("args", []):
                    script = arg.replace("${CLAUDE_PLUGIN_ROOT}/", "")
                    if script.endswith(".py"):
                        assert (_REPO_ROOT / script).is_file(), f"hooks.json references missing {script}"


def test_reference_design_doc_is_bundled_and_matches_source():
    bundled = _REPO_ROOT / "reference" / "agent-pipeline-design.md"
    source = _REPO_ROOT / "docs" / "agent-pipeline-design.md"
    assert bundled.is_file()
    assert bundled.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_plugin_manifest_declares_a_config_schema_version_for_init_to_target():
    manifest = json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(manifest.get("configSchemaVersion"), str) and manifest["configSchemaVersion"]
    assert manifest["version"] == "1.0.0"


# --- Facultative: init proposes nothing that isn't schema-valid on its own -----------------------


def test_init_never_proposes_an_invalid_config(sample_project):
    proposals = inspect_repo(sample_project)
    validate(proposals, load_schema(), "project_config")
    with pytest.raises(ConfigError):
        validate({"not_a_real_knob": True}, load_schema(), "project_config")
