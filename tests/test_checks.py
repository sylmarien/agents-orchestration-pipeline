import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lib.checks import detect_checks, resolve_checks, run_all, run_check

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_PROJECT = _REPO_ROOT / "fixtures" / "sample-project"


@pytest.fixture
def sample_project(tmp_path) -> Path:
    """A disposable copy of fixtures/sample-project, so a test that seeds a failure or runs
    `make build` never mutates the committed fixture."""
    dest = tmp_path / "sample-project"
    shutil.copytree(_SAMPLE_PROJECT, dest)
    return dest


# --- Detection ---------------------------------------------------------------------------------


def test_detect_checks_sample_project(sample_project):
    detected = detect_checks(sample_project)
    assert detected == {
        "build": "make build",
        "test": "make test",
        "static": ["make format-check", "make lint"],
    }


def test_detect_checks_no_makefile(tmp_path):
    assert detect_checks(tmp_path) == {"build": None, "test": None, "static": None}


def test_detect_checks_ignores_undeclared_targets(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\techo building\n")
    assert detect_checks(tmp_path) == {"build": "make build", "test": None, "static": None}


# --- resolve_checks: config overrides detection key-by-key ----------------------------------


def test_resolve_checks_with_no_config_uses_detection(sample_project):
    resolved = resolve_checks(sample_project)
    assert resolved == {
        "build": "make build",
        "test": "make test",
        "static": ["make format-check", "make lint"],
    }


def test_resolve_checks_project_override_wins_per_key(sample_project):
    resolved = resolve_checks(sample_project, configured={"build": "make -B build", "test": None, "static": None})
    assert resolved["build"] == "make -B build"
    assert resolved["test"] == "make test"
    assert resolved["static"] == ["make format-check", "make lint"]


def test_resolve_checks_missing_config_keys_fall_back_to_detection(sample_project):
    resolved = resolve_checks(sample_project, configured={})
    assert resolved == resolve_checks(sample_project)


# --- run_check / run_all on a green tree ------------------------------------------------------


def test_run_check_reports_pass(sample_project):
    result = run_check(sample_project, "echo", "true")
    assert result == {
        "name": "echo",
        "command": "true",
        "passed": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "failing_items": [],
    }


def test_run_check_reports_fail(sample_project):
    result = run_check(sample_project, "echo", "false")
    assert result["passed"] is False
    assert result["returncode"] != 0


def test_run_all_green_tree_reports_all_pass(sample_project):
    resolved = resolve_checks(sample_project)
    results = run_all(sample_project, resolved)

    assert results["all_green"] is True
    assert results["build"]["passed"] is True
    assert results["test"]["passed"] is True
    assert all(r["passed"] for r in results["static"])
    assert results["test"]["failing_items"] == []


def test_run_all_runs_every_check_even_after_a_failure(sample_project):
    # A broken production source file fails both `build` and `test` (the test binary compiles
    # the same source) -- confirm run_all still executes and reports every configured check
    # (`test` and every `static` command) rather than short-circuiting after `build` goes red.
    intstack_c = sample_project / "src" / "intstack.c"
    text = intstack_c.read_text()
    seeded = text.replace("stack->count += 1;", "stack->count += ;")
    assert seeded != text
    intstack_c.write_text(seeded)

    resolved = resolve_checks(sample_project)
    results = run_all(sample_project, resolved)

    assert results["build"]["passed"] is False
    assert results["test"] is not None
    assert results["test"]["passed"] is False
    assert len(results["static"]) == 2
    assert results["all_green"] is False


# --- Seeded failures are parsed into specific failing items -----------------------------------


def test_seeded_failing_test_is_parsed_as_specific_item(sample_project):
    test_file = sample_project / "tests" / "test_intstack.c"
    text = test_file.read_text()
    # Flip the expected LIFO value so the first assertion in test_push_and_pop fails, while every
    # other check in the binary still passes.
    seeded = text.replace(
        'CHECK("test_push_and_pop_lifo_order", intstack_pop(&stack, &value) == 0 && value == 2,',
        'CHECK("test_push_and_pop_lifo_order", intstack_pop(&stack, &value) == 0 && value == 999,',
    )
    assert seeded != text
    test_file.write_text(seeded)

    resolved = resolve_checks(sample_project)
    results = run_all(sample_project, resolved)

    assert results["build"]["passed"] is True
    assert results["test"]["passed"] is False
    assert results["test"]["failing_items"] == [
        {"test": "test_push_and_pop_lifo_order", "message": "expected pop to return the most recently pushed value"}
    ]
    # Every other check in the same binary still reports its own pass.
    assert results["all_green"] is False


def test_seeded_build_error_is_parsed_with_file_and_line(sample_project):
    intstack_c = sample_project / "src" / "intstack.c"
    text = intstack_c.read_text()
    seeded = text.replace("stack->count += 1;", "stack->count += ;")
    assert seeded != text
    intstack_c.write_text(seeded)

    result = run_check(sample_project, "build", "make build")

    assert result["passed"] is False
    assert result["failing_items"], "expected at least one parsed compiler diagnostic"
    item = result["failing_items"][0]
    assert item["file"].endswith("intstack.c")
    assert isinstance(item["line"], int)
    assert item["message"]


def test_seeded_format_violation_is_parsed_as_specific_item(sample_project):
    intstack_h = sample_project / "include" / "intstack.h"
    text = intstack_h.read_text()
    seeded = text.replace(
        "void intstack_init(IntStack *stack);",
        "void   intstack_init(IntStack   *stack);",
    )
    assert seeded != text
    intstack_h.write_text(seeded)

    result = run_check(sample_project, "static[0]", "make format-check")

    assert result["passed"] is False
    assert result["failing_items"]
    assert any(item["file"].endswith("intstack.h") for item in result["failing_items"])


# --- CLI -----------------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.checks", "detect", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in result.stdout


def test_cli_run_all_round_trips_through_json(sample_project):
    import json

    resolved = resolve_checks(sample_project)
    result = subprocess.run(
        [sys.executable, "-m", "lib.checks", "run-all", json.dumps({"repo_root": str(sample_project), "resolved": resolved})],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["all_green"] is True
