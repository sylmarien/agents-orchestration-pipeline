import json
import subprocess
import sys
from pathlib import Path

import pytest

from hooks.budget_meter import evaluate as hook_evaluate
from hooks.budget_meter import parse_transcript_usage
from lib.budget import BudgetError, aggregate_totals, check_budget, record_usage, resolve_model, totals
from lib.state import init_state_dir

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def state_dir(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    return init_state_dir(repo_dir, "task1")


# --- Usage accounting --------------------------------------------------------------------------


def test_record_usage_accumulates_across_calls(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 100, "output_tokens": 50})
    result = record_usage(state_dir, "implementer", {"input_tokens": 20, "output_tokens": 10})

    assert result == {
        "input_tokens": 120,
        "output_tokens": 60,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_record_usage_preserves_the_full_split_per_node(state_dir):
    record_usage(
        state_dir,
        "implementer",
        {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 200},
    )
    record_usage(state_dir, "code_reviewer", {"input_tokens": 10, "output_tokens": 5})

    result = totals(state_dir)
    assert result == {
        "input_tokens": 110,
        "output_tokens": 55,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 200,
        "tokens": 165,  # input + output only, per design doc §10's "unit: tokens"
    }


def test_record_usage_ignores_missing_fields_as_zero(state_dir):
    result = record_usage(state_dir, "refiner", {"input_tokens": 10})
    assert result["output_tokens"] == 0
    assert result["cache_creation_input_tokens"] == 0


def test_usage_survives_a_state_reload(tmp_path):
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    state_dir = init_state_dir(repo_dir, "task1")
    record_usage(state_dir, "implementer", {"input_tokens": 100, "output_tokens": 50})

    resumed = init_state_dir(repo_dir, "task1")
    result = record_usage(resumed, "implementer", {"input_tokens": 5, "output_tokens": 5})
    assert result["input_tokens"] == 105


def test_multi_pipeline_aggregate_sums_across_state_dirs(tmp_path):
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    state_dir_a = init_state_dir(repo_dir, "task1")
    state_dir_b = init_state_dir(repo_dir, "task2")
    record_usage(state_dir_a, "implementer", {"input_tokens": 100, "output_tokens": 50})
    record_usage(state_dir_b, "implementer", {"input_tokens": 10, "output_tokens": 5})

    result = aggregate_totals([state_dir_a, state_dir_b])
    assert result["tokens"] == 165
    assert result["input_tokens"] == 110


# --- Warn / exhaustion ---------------------------------------------------------------------------


def test_budget_tokens_null_never_warns_or_exceeds(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 10_000_000, "output_tokens": 10_000_000})
    result = check_budget(state_dir, None, 0.8)
    assert result == {"total_tokens": 20_000_000, "budget_tokens": None, "ratio": None, "warn": False, "exceeded": False}


def test_warn_fires_exactly_at_warn_ratio(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 800, "output_tokens": 0})
    result = check_budget(state_dir, 1000, 0.8)
    assert result["ratio"] == pytest.approx(0.8)
    assert result["warn"] is True
    assert result["exceeded"] is False


def test_no_warn_just_below_warn_ratio(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 799, "output_tokens": 0})
    result = check_budget(state_dir, 1000, 0.8)
    assert result["warn"] is False


def test_exhaustion_fires_at_100_percent(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 1000, "output_tokens": 0})
    result = check_budget(state_dir, 1000, 0.8)
    assert result["warn"] is True
    assert result["exceeded"] is True


def test_exhaustion_fires_past_100_percent(state_dir):
    record_usage(state_dir, "implementer", {"input_tokens": 2000, "output_tokens": 0})
    result = check_budget(state_dir, 1000, 0.8)
    assert result["exceeded"] is True


# --- Model resolution: five-step precedence table -----------------------------------------------


def test_model_resolution_prompt_agent_wins_over_everything():
    result = resolve_model(
        "documenter",
        project_model={"default": "opus", "documenter": "haiku"},
        prompt_model={"default": "sonnet", "documenter": "fable"},
        spawn_model="opus",
    )
    assert result == "fable"


def test_model_resolution_prompt_default_wins_over_project_agent():
    # Design doc §11: a prompt-wide override outranks a project-specific per-agent one.
    result = resolve_model(
        "documenter",
        project_model={"documenter": "haiku"},
        prompt_model={"default": "sonnet"},
        spawn_model="opus",
    )
    assert result == "sonnet"


def test_model_resolution_falls_back_to_project_agent():
    result = resolve_model("documenter", project_model={"documenter": "haiku"}, prompt_model=None, spawn_model="opus")
    assert result == "haiku"


def test_model_resolution_falls_back_to_project_default():
    result = resolve_model("documenter", project_model={"default": "opus"}, prompt_model=None, spawn_model="sonnet")
    assert result == "opus"


def test_model_resolution_falls_back_to_inherit():
    result = resolve_model("documenter", project_model=None, prompt_model=None, spawn_model="sonnet")
    assert result == "sonnet"


def test_model_resolution_unknown_model_name_raises():
    with pytest.raises(BudgetError):
        resolve_model("documenter", project_model={"default": "gpt-99"}, spawn_model="sonnet")


# --- Claude Code hook: per-session enforcement -------------------------------------------------


def _write_transcript(path: Path, usages: list[dict[str, int]]) -> None:
    lines = [json.dumps({"type": "assistant", "message": {"usage": usage}}) for usage in usages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_transcript_usage_sums_assistant_turns(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, [{"input_tokens": 100, "output_tokens": 20}, {"input_tokens": 50, "output_tokens": 10}])

    result = parse_transcript_usage(transcript)
    assert result == {"input_tokens": 150, "output_tokens": 30}


def test_parse_transcript_usage_missing_file_is_zero(tmp_path):
    result = parse_transcript_usage(tmp_path / "does-not-exist.jsonl")
    assert result == {"input_tokens": 0, "output_tokens": 0}


def test_parse_transcript_usage_skips_malformed_lines(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('not json\n{"type": "assistant", "message": {"usage": {"input_tokens": 5, "output_tokens": 5}}}\n')
    result = parse_transcript_usage(transcript)
    assert result == {"input_tokens": 5, "output_tokens": 5}


def test_hook_allows_when_no_budget_configured(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, [{"input_tokens": 1_000_000, "output_tokens": 1_000_000}])
    result = hook_evaluate({"cwd": str(tmp_path), "transcript_path": str(transcript)})
    assert result["permissionDecision"] == "allow"


def test_hook_denies_once_session_usage_reaches_configured_budget(tmp_path):
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "pipeline.yaml").write_text("budget:\n  tokens: 100\n")
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, [{"input_tokens": 80, "output_tokens": 20}])

    result = hook_evaluate({"cwd": str(tmp_path), "transcript_path": str(transcript)})
    assert result["permissionDecision"] == "deny"
    assert "budget" in result["permissionDecisionReason"]


def test_hook_allows_below_configured_budget(tmp_path):
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "pipeline.yaml").write_text("budget:\n  tokens: 1000\n")
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, [{"input_tokens": 80, "output_tokens": 20}])

    result = hook_evaluate({"cwd": str(tmp_path), "transcript_path": str(transcript)})
    assert result["permissionDecision"] == "allow"


# --- CLI ------------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.budget", "totals", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)
