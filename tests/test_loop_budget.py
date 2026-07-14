import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.loop_budget import (
    EDGE_BUDGET_CLASS,
    LoopBudgetError,
    budget_class_for_edge,
    record_bounce,
)
from lib.state import init_state_dir, read_history, read_loop_counters

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOOP_LIMITS = {"l1": 3, "l3": 3, "escalations": 2, "post_pr": 5}


@pytest.fixture
def state_dir(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    return init_state_dir(repo_dir, "task1")


# --- Budget-class mapping ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "edge_id,expected_class",
    [
        ("L1", "l1"),
        ("L2", "escalations"),
        ("L3", "l3"),
        ("L4", "escalations"),
        ("L5", "escalations"),
        ("L7", "post_pr"),
        ("L8", "post_pr"),
        ("L9", "post_pr"),
        ("L10", "post_pr"),
    ],
)
def test_budget_class_for_edge(edge_id, expected_class):
    assert budget_class_for_edge(edge_id) == expected_class


def test_every_mapped_edge_id_covered_exactly_once():
    # Every backward edge in config/transition_table.yaml has exactly one budget class, and no
    # Option B/C-only edge (L6) is ever mapped (CLAUDE.md; docs/implementation/README.md §7).
    assert set(EDGE_BUDGET_CLASS) == {"L1", "L2", "L3", "L4", "L5", "L7", "L8", "L9", "L10"}


@pytest.mark.parametrize("edge_id", ["T1", "L6", "L99", "bogus"])
def test_budget_class_for_unknown_edge_rejected(edge_id):
    with pytest.raises(LoopBudgetError):
        budget_class_for_edge(edge_id)


# --- record_bounce: increments + exhaustion -----------------------------------------------------


def test_l1_exhausts_at_configured_limit(state_dir):
    first = record_bounce(state_dir, "L1", _LOOP_LIMITS)
    second = record_bounce(state_dir, "L1", _LOOP_LIMITS)
    third = record_bounce(state_dir, "L1", _LOOP_LIMITS)

    assert [r["count"] for r in (first, second, third)] == [1, 2, 3]
    assert [r["exceeded"] for r in (first, second, third)] == [False, False, True]
    assert first["budget_class"] == "l1"
    assert first["limit"] == 3


@pytest.mark.parametrize("edge_id", ["L2", "L5"])
def test_l2_l5_exhaust_at_escalations_limit(state_dir, edge_id):
    first = record_bounce(state_dir, edge_id, _LOOP_LIMITS)
    second = record_bounce(state_dir, edge_id, _LOOP_LIMITS)

    assert first["exceeded"] is False
    assert second["exceeded"] is True
    assert second["budget_class"] == "escalations"
    assert second["limit"] == 2


def test_counters_survive_a_state_reload(tmp_path):
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    state_dir = init_state_dir(repo_dir, "task1")
    record_bounce(state_dir, "L1", _LOOP_LIMITS)
    record_bounce(state_dir, "L1", _LOOP_LIMITS)

    # Simulate a crash/restart: re-initializing the same pipeline id must not reset the counter.
    resumed_state_dir = init_state_dir(repo_dir, "task1")
    result = record_bounce(resumed_state_dir, "L1", _LOOP_LIMITS)
    assert result["count"] == 3
    assert result["exceeded"] is True


def test_distinct_edges_count_independently(state_dir):
    record_bounce(state_dir, "L1", _LOOP_LIMITS)
    record_bounce(state_dir, "L1", _LOOP_LIMITS)
    record_bounce(state_dir, "L2", _LOOP_LIMITS)

    assert read_loop_counters(state_dir) == {"L1": 2, "L2": 1}


def test_record_bounce_delegates_to_state_loop_increment_history(state_dir):
    record_bounce(state_dir, "L1", _LOOP_LIMITS)
    records = read_history(state_dir)
    assert len(records) == 1
    assert records[0]["event"] == "loop_increment"
    assert records[0]["edge"] == "L1"


def test_record_bounce_rejects_forward_edge(state_dir):
    with pytest.raises(LoopBudgetError):
        record_bounce(state_dir, "T1", _LOOP_LIMITS)


def test_record_bounce_rejects_loop_limits_missing_the_needed_key(state_dir):
    with pytest.raises(LoopBudgetError):
        record_bounce(state_dir, "L1", {"escalations": 2})


# --- CLI -----------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.loop_budget", "record-bounce", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)
