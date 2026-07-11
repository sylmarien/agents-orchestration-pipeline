import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.state import (
    StateError,
    append_history,
    default_state_root,
    increment_loop_counter,
    init_state_dir,
    latest_position,
    read_artifact,
    read_history,
    read_loop_counters,
    read_manifest,
    read_node_state,
    state_dir_path,
    write_artifact,
    write_manifest,
    write_node_state,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    return repo_dir


def test_default_state_root_is_sibling_of_repo(repo):
    assert default_state_root(repo) == (repo.parent / ".agents-state").resolve()


def test_init_state_dir_creates_layout(repo):
    state_dir = init_state_dir(repo, "task1")
    assert state_dir == state_dir_path(repo, "task1")
    assert (state_dir / "node-state").is_dir()
    assert (state_dir / "artifacts").is_dir()
    assert (state_dir / "history.jsonl").exists()


def test_init_state_dir_is_idempotent(repo):
    init_state_dir(repo, "task1")
    append_history(state_dir_path(repo, "task1"), "transition", **{"from": "refiner", "to": "designer", "edge": "T1"})
    state_dir = init_state_dir(repo, "task1")  # resume: must not wipe existing history
    assert len(read_history(state_dir)) == 1


def test_custom_state_root_honored(repo, tmp_path):
    custom_root = tmp_path / "custom-state"
    state_dir = init_state_dir(repo, "task1", state_root=custom_root)
    assert state_dir == (custom_root / "task1").resolve()


# --- Manifest ---------------------------------------------------------------------------


def test_manifest_round_trips(repo):
    state_dir = init_state_dir(repo, "task1")
    manifest = {"pipeline_id": "task1", "plugin_version": "0.1.0", "resolved_config": {"topology": "option_a"}}
    write_manifest(state_dir, manifest)
    assert read_manifest(state_dir) == manifest


def test_manifest_missing_returns_none(repo):
    state_dir = init_state_dir(repo, "task1")
    assert read_manifest(state_dir) is None


# --- History: append-only, ordered ------------------------------------------------------


def test_history_is_append_only_and_ordered(repo):
    state_dir = init_state_dir(repo, "task1")
    append_history(state_dir, "transition", **{"from": "refiner", "to": "designer", "edge": "T1", "gate": "G1"})
    append_history(state_dir, "gate_open", gate="G2")
    append_history(state_dir, "gate_resolved", gate="G2", detail="approved")
    append_history(state_dir, "transition", **{"from": "designer", "to": "implementer", "edge": "T2"})

    records = read_history(state_dir)
    assert [r["event"] for r in records] == ["transition", "gate_open", "gate_resolved", "transition"]
    assert records[0]["to"] == "designer"
    assert records[3]["to"] == "implementer"
    # ts strictly non-decreasing (ordered by append time)
    assert [r["ts"] for r in records] == sorted(r["ts"] for r in records)


def test_history_unknown_event_rejected(repo):
    state_dir = init_state_dir(repo, "task1")
    with pytest.raises(StateError):
        append_history(state_dir, "not_a_real_event")


def test_history_omits_unset_fields(repo):
    state_dir = init_state_dir(repo, "task1")
    record = append_history(state_dir, "escalation", detail="design infeasible")
    assert "from" not in record
    assert "to" not in record
    assert "edge" not in record
    assert "gate" not in record
    assert record["detail"] == "design infeasible"


def test_read_history_empty_before_any_append(repo):
    state_dir = init_state_dir(repo, "task1")
    assert read_history(state_dir) == []


# --- Crash/restart resumption -------------------------------------------------------------


def test_latest_position_none_for_fresh_pipeline(repo):
    state_dir = init_state_dir(repo, "task1")
    assert latest_position(state_dir) is None


def test_latest_position_resumes_from_last_transition(repo):
    state_dir = init_state_dir(repo, "task1")
    append_history(state_dir, "transition", **{"from": "refiner", "to": "designer", "edge": "T1"})
    append_history(state_dir, "transition", **{"from": "designer", "to": "implementer", "edge": "T2"})
    append_history(state_dir, "gate_open", gate="G3")  # non-transition record after the last transition

    assert latest_position(state_dir) == "implementer"


def test_simulated_restart_resumes_not_from_scratch(repo):
    """A crash mid-run leaves history + per-node state on disk; re-initializing the same
    pipeline id must resume from the last recorded position, not restart at the entry node."""
    state_dir = init_state_dir(repo, "task1")
    append_history(state_dir, "transition", **{"from": "refiner", "to": "designer", "edge": "T1"})
    write_node_state(state_dir, "designer", {"progress": "drafting alternatives"})

    # Simulate the process dying and a fresh session re-initializing the same pipeline.
    resumed_state_dir = init_state_dir(repo, "task1")

    assert latest_position(resumed_state_dir) == "designer"
    assert read_node_state(resumed_state_dir, "designer") == {"progress": "drafting alternatives"}


# --- Per-node state --------------------------------------------------------------------


def test_node_state_round_trips(repo):
    state_dir = init_state_dir(repo, "task1")
    write_node_state(state_dir, "implementer", {"iteration": 3, "last_failure": "test_foo"})
    assert read_node_state(state_dir, "implementer") == {"iteration": 3, "last_failure": "test_foo"}


def test_node_state_missing_returns_none(repo):
    state_dir = init_state_dir(repo, "task1")
    assert read_node_state(state_dir, "implementer") is None


def test_node_state_overwritten_not_appended(repo):
    state_dir = init_state_dir(repo, "task1")
    write_node_state(state_dir, "implementer", {"iteration": 1})
    write_node_state(state_dir, "implementer", {"iteration": 2})
    assert read_node_state(state_dir, "implementer") == {"iteration": 2}


# --- Artifacts ---------------------------------------------------------------------------


def test_artifact_round_trips(repo):
    state_dir = init_state_dir(repo, "task1")
    write_artifact(state_dir, "design_doc.md", "# Design\n\nstub")
    assert read_artifact(state_dir, "design_doc.md") == "# Design\n\nstub"


# --- Loop-budget counters ----------------------------------------------------------------


def test_loop_counter_increments_and_persists(repo):
    state_dir = init_state_dir(repo, "task1")
    assert increment_loop_counter(state_dir, "L1") == 1
    assert increment_loop_counter(state_dir, "L1") == 2
    assert increment_loop_counter(state_dir, "L2") == 1
    assert read_loop_counters(state_dir) == {"L1": 2, "L2": 1}


def test_loop_counter_appends_history_record(repo):
    state_dir = init_state_dir(repo, "task1")
    increment_loop_counter(state_dir, "L1")
    records = read_history(state_dir)
    assert len(records) == 1
    assert records[0]["event"] == "loop_increment"
    assert records[0]["edge"] == "L1"


# --- CLI -------------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.state", "init", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)
