import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.journal import (
    JournalError,
    acknowledge_entry,
    append_entry,
    merge_journals,
    pending_entries,
    read_journal,
    resolve_override,
    validate_entry,
)
from lib.state import init_state_dir

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    return repo_dir


@pytest.fixture
def state_dir(repo) -> Path:
    return init_state_dir(repo, "task1")


def _options():
    return [
        {"option": "use library X", "consequence": "faster, adds a dependency"},
        {"option": "hand-roll it", "consequence": "no new dependency, more code to maintain"},
    ]


# --- Schema validation -------------------------------------------------------------------


def _valid_entry(**overrides):
    entry = {
        "id": "task1-D001",
        "pipeline": "task1",
        "agent": "designer",
        "timestamp": "2026-07-12T10:00:00+00:00",
        "stage_artifact": "design_doc",
        "question": "which serializer to use?",
        "options_considered": _options(),
        "chosen": "use library X",
        "rationale": "already a transitive dependency",
        "reversal_cost": "low",
        "status": "pending_review",
        "override_action": None,
    }
    entry.update(overrides)
    return entry


def test_valid_entry_passes():
    validate_entry(_valid_entry())  # must not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"agent": "not_an_agent"},
        {"timestamp": "not-a-timestamp"},
        {"options_considered": [{"option": "only one"}]},
        {"options_considered": "not-a-list"},
        {"reversal_cost": "extreme"},
        {"status": "in_progress"},
        {"question": ""},
        {"status": "overridden", "override_action": None},
    ],
)
def test_invalid_entry_rejected(overrides):
    with pytest.raises(JournalError):
        validate_entry(_valid_entry(**overrides))


# --- append / read -----------------------------------------------------------------------


def test_append_entry_auto_fills_id_and_timestamp(state_dir):
    entry = append_entry(
        state_dir,
        pipeline="task1",
        agent="refiner",
        stage_artifact="refined_spec",
        question="does 'users' mean all tenants or just the current one?",
        options_considered=_options(),
        chosen="use library X",
        rationale="matches existing usage",
        reversal_cost="low",
    )
    assert entry["id"] == "task1-R001"
    assert entry["status"] == "pending_review"
    assert entry["timestamp"]


def test_append_entry_ids_increment_per_pipeline_across_agents(state_dir):
    first = append_entry(
        state_dir,
        pipeline="task1",
        agent="refiner",
        stage_artifact="refined_spec",
        question="q1",
        options_considered=_options(),
        chosen="a",
        rationale="r",
        reversal_cost="low",
    )
    second = append_entry(
        state_dir,
        pipeline="task1",
        agent="designer",
        stage_artifact="design_doc",
        question="q2",
        options_considered=_options(),
        chosen="a",
        rationale="r",
        reversal_cost="medium",
    )
    assert first["id"] == "task1-R001"
    assert second["id"] == "task1-D002"
    assert [e["id"] for e in read_journal(state_dir)] == ["task1-R001", "task1-D002"]


def test_append_entry_rejects_unknown_agent(state_dir):
    with pytest.raises(JournalError):
        append_entry(
            state_dir,
            pipeline="task1",
            agent="not_an_agent",
            stage_artifact="refined_spec",
            question="q",
            options_considered=_options(),
            chosen="a",
            rationale="r",
            reversal_cost="low",
        )


def test_read_journal_empty_before_any_append(state_dir):
    assert read_journal(state_dir) == []


# --- pending selection --------------------------------------------------------------------


def test_pending_entries_filters_by_status(state_dir):
    append_entry(
        state_dir, pipeline="task1", agent="refiner", stage_artifact="refined_spec", question="q1",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="low",
    )
    acked = append_entry(
        state_dir, pipeline="task1", agent="designer", stage_artifact="design_doc", question="q2",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="low",
    )
    acknowledge_entry(state_dir, acked["id"])

    pending = pending_entries(state_dir)
    assert [e["id"] for e in pending] == ["task1-R001"]


# --- acknowledge -------------------------------------------------------------------------


def test_acknowledge_entry_updates_status(state_dir):
    entry = append_entry(
        state_dir, pipeline="task1", agent="refiner", stage_artifact="refined_spec", question="q",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="low",
    )
    acknowledged = acknowledge_entry(state_dir, entry["id"])
    assert acknowledged["status"] == "acknowledged"
    assert read_journal(state_dir)[0]["status"] == "acknowledged"


def test_acknowledge_missing_entry_raises(state_dir):
    with pytest.raises(JournalError):
        acknowledge_entry(state_dir, "task1-R999")


# --- override -> rollback resolution -------------------------------------------------------


def test_resolve_override_marks_overridden_and_resolves_target(state_dir):
    entry = append_entry(
        state_dir, pipeline="task1", agent="refiner", stage_artifact="refined_spec", question="q",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="medium",
    )
    result = resolve_override(state_dir, entry["id"], "redo the spec's scope section")

    assert result["rollback_to_node"] == "refiner"
    assert result["entry"]["status"] == "overridden"
    assert result["entry"]["override_action"] == "redo the spec's scope section"
    assert read_journal(state_dir)[0]["status"] == "overridden"


def test_resolve_override_requires_action(state_dir):
    entry = append_entry(
        state_dir, pipeline="task1", agent="designer", stage_artifact="design_doc", question="q",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="high",
    )
    with pytest.raises(JournalError):
        resolve_override(state_dir, entry["id"], "")


def test_resolve_override_missing_entry_raises(state_dir):
    with pytest.raises(JournalError):
        resolve_override(state_dir, "task1-R999", "redo it")


# --- merge across pipelines ----------------------------------------------------------------


def test_merge_journals_concatenates_and_orders_by_timestamp(repo):
    state_dir_a = init_state_dir(repo, "task1")
    state_dir_b = init_state_dir(repo, "task2")

    append_entry(
        state_dir_a, pipeline="task1", agent="refiner", stage_artifact="refined_spec", question="q1",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="low",
        timestamp="2026-07-12T09:00:00+00:00",
    )
    append_entry(
        state_dir_b, pipeline="task2", agent="designer", stage_artifact="design_doc", question="q2",
        options_considered=_options(), chosen="a", rationale="r", reversal_cost="low",
        timestamp="2026-07-12T08:00:00+00:00",
    )

    merged = merge_journals([state_dir_a, state_dir_b])
    assert [e["pipeline"] for e in merged] == ["task2", "task1"]


def test_merge_journals_empty_for_no_state_dirs():
    assert merge_journals([]) == []


# --- CLI -----------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.journal", "append", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)
