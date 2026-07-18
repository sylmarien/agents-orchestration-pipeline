import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.ticketing import (
    TicketingError,
    parse_reference,
    render_link,
    resolve_mode,
    should_prompt_for_creation,
    status_for,
)
from lib.ticketing.github import is_github_remote
from lib.ticketing.github import parse_reference as github_parse_reference
from lib.ticketing.github import render_link as github_render_link
from lib.ticketing.jira import parse_reference as jira_parse_reference
from lib.ticketing.jira import render_link as jira_render_link

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_STATUS_MAPPING = {"start": "In Progress", "pr": "In Review", "merged": "Done"}


# --- Mode resolution / spawn-time validation ----------------------------------------------------


def test_resolve_mode_none_has_no_side_effects():
    result = resolve_mode({"system": "none"})
    assert result == {"mode": "none", "degraded": False, "reason": None}


def test_resolve_mode_jira_missing_url_and_project_raises():
    with pytest.raises(TicketingError):
        resolve_mode({"system": "jira", "jira": {"url": None, "project": None}})


def test_resolve_mode_jira_missing_project_only_raises():
    with pytest.raises(TicketingError):
        resolve_mode({"system": "jira", "jira": {"url": "https://jira.example.com", "project": None}})


def test_resolve_mode_jira_fully_configured_is_accepted():
    result = resolve_mode({"system": "jira", "jira": {"url": "https://jira.example.com", "project": "PROJ"}})
    assert result == {"mode": "jira", "degraded": False, "reason": None}


def test_resolve_mode_github_issues_on_github_remote_is_accepted():
    result = resolve_mode({"system": "github_issues"}, remote_url="git@github.com:acme/widgets.git")
    assert result == {"mode": "github_issues", "degraded": False, "reason": None}


def test_resolve_mode_github_issues_on_non_github_remote_degrades_without_raising():
    result = resolve_mode({"system": "github_issues"}, remote_url="https://gitlab.com/acme/widgets.git")
    assert result["mode"] == "none"
    assert result["degraded"] is True
    assert result["reason"]


def test_resolve_mode_github_issues_with_no_remote_at_all_degrades():
    result = resolve_mode({"system": "github_issues"}, remote_url=None)
    assert result == {
        "mode": "none",
        "degraded": True,
        "reason": (
            "ticketing.system is github_issues but the repository's origin remote (None) "
            "is not a GitHub URL; degrading to none for this run"
        ),
    }


def test_resolve_mode_unknown_system_raises():
    with pytest.raises(TicketingError):
        resolve_mode({"system": "trello"})


# --- Status mapping ------------------------------------------------------------------------------


def test_status_for_resolves_defaults():
    assert status_for("start", _DEFAULT_STATUS_MAPPING) == "In Progress"
    assert status_for("pr", _DEFAULT_STATUS_MAPPING) == "In Review"
    assert status_for("merged", _DEFAULT_STATUS_MAPPING) == "Done"


def test_status_for_honors_project_overrides():
    overridden = {"start": "Backlog", "pr": "Code Review", "merged": "Shipped"}
    assert status_for("pr", overridden) == "Code Review"


def test_status_for_unknown_stage_raises():
    with pytest.raises(TicketingError):
        status_for("closed", _DEFAULT_STATUS_MAPPING)


def test_status_for_missing_mapping_key_raises():
    with pytest.raises(TicketingError):
        status_for("merged", {"start": "In Progress", "pr": "In Review"})


# --- create_if_missing: prompt/never, no "always" ------------------------------------------------


def test_create_if_missing_prompt_always_prompts():
    assert should_prompt_for_creation("prompt") is True


def test_create_if_missing_never_never_creates():
    assert should_prompt_for_creation("never") is False


def test_create_if_missing_invalid_value_raises():
    with pytest.raises(TicketingError):
        should_prompt_for_creation("always")


# --- Intake: reference parsing --------------------------------------------------------------------


def test_github_parse_reference_bare_hash():
    assert github_parse_reference("fix the bug in #42 please") == {"system": "github_issues", "id": "42"}


def test_github_parse_reference_issue_url():
    result = github_parse_reference("see https://github.com/acme/widgets/issues/7 for details")
    assert result == {"system": "github_issues", "id": "7", "owner": "acme", "repo": "widgets"}


def test_github_parse_reference_none_when_absent():
    assert github_parse_reference("just fix the login bug") is None


def test_jira_parse_reference_bare_key():
    assert jira_parse_reference("work on PROJ-123 next") == {"system": "jira", "id": "PROJ-123", "project": "PROJ"}


def test_jira_parse_reference_browse_url():
    result = jira_parse_reference("https://acme.atlassian.net/browse/PROJ-123")
    assert result == {"system": "jira", "id": "PROJ-123", "project": "PROJ"}


def test_jira_parse_reference_none_when_absent():
    assert jira_parse_reference("just fix the login bug") is None


def test_jira_parse_reference_filters_out_other_projects():
    assert jira_parse_reference("see OTHER-9 for context", project="PROJ") is None
    assert jira_parse_reference("see PROJ-9 for context", project="PROJ") == {
        "system": "jira",
        "id": "PROJ-9",
        "project": "PROJ",
    }


def test_dispatch_parse_reference_routes_by_system():
    assert parse_reference("fix #42", "github_issues") == {"system": "github_issues", "id": "42"}
    assert parse_reference("fix PROJ-42", "jira", project="PROJ") == {"system": "jira", "id": "PROJ-42", "project": "PROJ"}


def test_dispatch_parse_reference_none_system_always_none():
    assert parse_reference("fix #42", "none") is None


# --- is_github_remote ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remote_url",
    ["https://github.com/acme/widgets.git", "git@github.com:acme/widgets.git", "https://github.com/acme/widgets"],
)
def test_is_github_remote_recognizes_github_hosts(remote_url):
    assert is_github_remote(remote_url) is True


@pytest.mark.parametrize("remote_url", ["https://gitlab.com/acme/widgets.git", "git@bitbucket.org:acme/widgets.git", "", None])
def test_is_github_remote_rejects_non_github_hosts(remote_url):
    assert is_github_remote(remote_url) is False


# --- Link rendering ---------------------------------------------------------------------------------


def test_github_render_link_closing():
    assert github_render_link("42", closes=True) == "Fixes #42"


def test_github_render_link_non_closing():
    assert github_render_link("42", closes=False) == "Refs #42"


def test_jira_render_link_is_the_bare_key_regardless_of_closes():
    assert jira_render_link("PROJ-123", closes=True) == "PROJ-123"
    assert jira_render_link("PROJ-123", closes=False) == "PROJ-123"


def test_dispatch_render_link_routes_by_system():
    assert render_link("github_issues", "42", closes=True) == "Fixes #42"
    assert render_link("jira", "PROJ-123") == "PROJ-123"


def test_dispatch_render_link_unknown_system_raises():
    with pytest.raises(TicketingError):
        render_link("trello", "42")


# --- CLI ---------------------------------------------------------------------------------------------


def test_cli_resolve_mode_round_trips_through_json():
    result = subprocess.run(
        [sys.executable, "-m", "lib.ticketing", "resolve-mode", json.dumps({"ticketing_config": {"system": "none"}})],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"mode": "none", "degraded": False, "reason": None}


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.ticketing", "status-for", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)


def test_cli_jira_missing_config_reports_structured_error():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.ticketing",
            "resolve-mode",
            json.dumps({"ticketing_config": {"system": "jira", "jira": {"url": None, "project": None}}}),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "error" in json.loads(result.stdout)
