"""Check auto-detection and execution (design doc §9 knob registry `checks.build/test/static`;
§2 Implementer "inner loop"): detect a repo's build/test/static-check commands when the project
config leaves them null, run them in the worktree, and parse pass/fail plus failing-item detail
so the implementer's inner loop can react to *what* failed, not just *that* something failed.

    detect_checks(repo_root) -> dict                    # {"build":.., "test":.., "static": [...] | None}
    resolve_checks(repo_root, configured=None) -> dict  # configured (checks.* knob) overrides detection
    run_check(repo_root, name, command) -> dict          # one command -> pass/fail + parsed detail
    run_all(repo_root, resolved) -> dict                 # build + test + every static command, + all_green

Detection targets a `Makefile` with `build`/`test`/`format-check`/`lint` targets -- this plugin's
lightweight stand-in for the design doc's own example toolchain (`bazel build/test`,
`clang-format`, `clang-tidy`), matching `fixtures/sample-project`'s own Makefile. A repo with no
Makefile (or one missing a given target) detects null for that key; a project must then set
`checks.*` explicitly in `.agents/pipeline.yaml` for that check to run at all.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)")

# Compiler/linter diagnostics (gcc, clang, clang-format --dry-run, clang-tidy):
# "path/to/file.c:12:5: error: message" or "...:12: warning: message [check-name]".
_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<level>error|warning)\s*:\s*(?P<message>.+)$",
    re.MULTILINE,
)

# This plugin's own tiny test-runner output format (see fixtures/sample-project/tests):
# "[FAIL] test_name: message" / "[PASS] test_name".
_TEST_RESULT_RE = re.compile(
    r"^\[(?P<status>PASS|FAIL)\]\s+(?P<name>\S+)(?::\s*(?P<message>.*))?$",
    re.MULTILINE,
)


class ChecksError(Exception):
    """Raised for malformed check configuration."""


def _makefile_targets(makefile_path: Path) -> set[str]:
    targets: set[str] = set()
    for line in makefile_path.read_text(encoding="utf-8").splitlines():
        if not line or line[0] in "\t#" or line.startswith("."):
            continue
        match = _TARGET_RE.match(line)
        if match:
            targets.add(match.group(1))
    return targets


def detect_checks(repo_root: str | Path) -> dict[str, Any]:
    """Auto-detect build/test/static commands from repo markers. Currently recognizes a
    `Makefile` with conventional target names; a target the Makefile doesn't define detects as
    null rather than guessing a command that would just fail."""
    makefile = Path(repo_root) / "Makefile"
    if not makefile.exists():
        return {"build": None, "test": None, "static": None}

    targets = _makefile_targets(makefile)
    static = [f"make {t}" for t in ("format-check", "lint") if t in targets]
    return {
        "build": "make build" if "build" in targets else None,
        "test": "make test" if "test" in targets else None,
        "static": static or None,
    }


def resolve_checks(repo_root: str | Path, configured: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project config (`checks.build`/`test`/`static`, already resolved by `lib.resolve_config`)
    overrides auto-detection key-by-key; a key left null (or absent) in `configured` falls back
    to `detect_checks`."""
    configured = configured or {}
    detected = detect_checks(repo_root)
    return {key: configured.get(key) if configured.get(key) is not None else detected[key] for key in ("build", "test", "static")}


def _parse_failing_items(output: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"file": m["file"], "line": int(m["line"]), "message": m["message"].strip()} for m in _DIAGNOSTIC_RE.finditer(output)
    ]
    items.extend(
        {"test": m["name"], "message": (m["message"] or "").strip()}
        for m in _TEST_RESULT_RE.finditer(output)
        if m["status"] == "FAIL"
    )
    return items


def run_check(repo_root: str | Path, name: str, command: str) -> dict[str, Any]:
    """Run one check command in `repo_root` (the pipeline's worktree) and return its structured
    result: pass/fail, raw output, and any parsed failing items -- diagnostic locations or failed
    test names -- so the inner loop and `verification_evidence` can report *what* is still red."""
    result = subprocess.run(shlex.split(command), cwd=str(repo_root), capture_output=True, text=True)
    return {
        "name": name,
        "command": command,
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "failing_items": _parse_failing_items(result.stdout + result.stderr),
    }


def run_all(repo_root: str | Path, resolved: dict[str, Any]) -> dict[str, Any]:
    """Run build, then test, then every static-check command in `resolved` (as returned by
    `resolve_checks`) against `repo_root`. Every configured check runs regardless of an earlier
    failure -- the inner loop wants the full picture of what's still red, not just the first
    failure -- rolled up into a single `all_green` verdict (design doc §2 Implementer: "exit only
    when all green")."""
    results: dict[str, Any] = {}
    all_green = True

    for key in ("build", "test"):
        command = resolved.get(key)
        if command:
            check = run_check(repo_root, key, command)
            results[key] = check
            all_green = all_green and check["passed"]
        else:
            results[key] = None

    static_commands = resolved.get("static") or []
    static_results = [run_check(repo_root, f"static[{i}]", cmd) for i, cmd in enumerate(static_commands)]
    results["static"] = static_results
    all_green = all_green and all(r["passed"] for r in static_results)

    results["all_green"] = all_green
    return results


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m lib.checks <detect|resolve|run-check|run-all> '<json-kwargs>'", file=sys.stderr)
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "detect":
            print(json.dumps(detect_checks(**kwargs)))
        elif command == "resolve":
            print(json.dumps(resolve_checks(**kwargs)))
        elif command == "run-check":
            print(json.dumps(run_check(**kwargs)))
        elif command == "run-all":
            print(json.dumps(run_all(**kwargs)))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (ChecksError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
