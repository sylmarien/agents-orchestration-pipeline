"""Resource budgets + model selection (design doc §10 "Resource budgets", §11 "Model selection";
implementation plan Step 9). Two cross-cutting concerns bundled in one module because the design
doc bundles them in one step: both are resolved through the same three config layers and both
enrich the run manifest.

**Budget accounting.** Unit is tokens (input + output per the API usage object), accumulated per
pipeline; the manifest additionally records the full input/output/cache_creation/cache_read split
per agent/stage so a cache-heavy run's raw totals don't overstate cost. The orchestrator calls
`record_usage` after every spawn (using whatever usage object that spawn's result carries) and
`check_budget` to decide whether to journal a warning (`warn_ratio`, no pause) or fire GB1
(exhaustion -- pause at the next safe point). `budget.tokens: null` (the built-in default) means
unlimited, so a zero-config run never stalls.

**Model selection.** `resolve_model` implements the five-step precedence order (design doc §11):
prompt `model.<agent>` > prompt `model.default` > project `model.<agent>` > project `model.default`
> inherit (the model active at spawn). It takes the *raw* project/prompt layers rather than the
already-merged resolved config, because a plain per-key merge would conflate "project set this
agent specifically" with "prompt set a blanket default" -- the two must stay distinguishable for
the precedence order above to come out right (a prompt-wide override beats a project-specific one).

    record_usage(state_dir, node, usage) -> dict          # accumulate one spawn's usage into budget.json
    read_usage(state_dir) -> dict                          # raw per-node breakdown
    totals(state_dir) -> dict                              # summed across every node
    aggregate_totals(state_dirs) -> dict                   # summed across multiple pipelines (multi-pipeline view)
    check_budget(state_dir, budget_tokens, warn_ratio) -> dict   # ratio / warn / exceeded
    resolve_model(agent, project_model=None, prompt_model=None, spawn_model="inherit") -> str
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BUDGET_ARTIFACT_NAME = "budget.json"

_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Known model identifiers this build validates a resolved `model.*` knob against, so an
# unresolvable name fails fast at spawn (design doc §11) instead of silently falling through to a
# spawn-time host error with no context. This list is a snapshot, not a registry the plugin
# maintains long-term -- update it as new models ship. "inherit" is not itself a model id; it is
# handled directly by `resolve_model` (case 5) and never reaches this set.
KNOWN_MODELS = {
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "sonnet",
    "opus",
    "haiku",
    "fable",
}


class BudgetError(Exception):
    """Raised for an unresolvable model name, or malformed budget bookkeeping input."""


# --------------------------------------------------------------------------------------
# Usage accounting
# --------------------------------------------------------------------------------------


def _budget_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / BUDGET_ARTIFACT_NAME


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def read_usage(state_dir: str | Path) -> dict[str, dict[str, int]]:
    """Per-node cumulative usage breakdown (`{node: {input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens}}`), accumulated across every visit --
    a node revisited via a rework loop keeps accumulating into the same entry, since a node id and
    an agent are the same thing in this build's single linear topology (design doc §10:
    "per agent and per stage")."""
    return _read_json(_budget_path(state_dir), default={}) or {}


def record_usage(state_dir: str | Path, node: str, usage: dict[str, Any]) -> dict[str, int]:
    """Accumulate one spawn's usage object into `node`'s running total and persist it. `usage` may
    carry any subset of the four usage fields (missing ones are treated as 0); unrecognized keys
    are ignored so this stays forward-compatible with whatever a given runtime's usage object
    happens to include. Returns the node's new cumulative totals."""
    by_node = read_usage(state_dir)
    current = by_node.get(node, {field: 0 for field in _USAGE_FIELDS})
    for field in _USAGE_FIELDS:
        current[field] = current.get(field, 0) + int(usage.get(field, 0) or 0)
    by_node[node] = current
    _write_json(_budget_path(state_dir), by_node)
    return current


def totals(state_dir: str | Path) -> dict[str, int]:
    """Pipeline-wide totals across every node, full split plus `tokens` (input + output -- the
    budget-counted unit per design doc §10; cache tokens are tracked for transparency but do not
    themselves count against `budget.tokens`)."""
    by_node = read_usage(state_dir)
    summed = {field: sum(node_usage.get(field, 0) for node_usage in by_node.values()) for field in _USAGE_FIELDS}
    summed["tokens"] = summed["input_tokens"] + summed["output_tokens"]
    return summed


def aggregate_totals(state_dirs: list[str | Path]) -> dict[str, int]:
    """Sum `totals()` across multiple pipelines' state directories, for the run-level aggregate a
    multi-pipeline run reports whenever any one pipeline's GB1 fires (design doc §10
    "Multi-pipeline")."""
    aggregate = {field: 0 for field in (*_USAGE_FIELDS, "tokens")}
    for state_dir in state_dirs:
        pipeline_totals = totals(state_dir)
        for field in aggregate:
            aggregate[field] += pipeline_totals[field]
    return aggregate


def check_budget(state_dir: str | Path, budget_tokens: int | None, warn_ratio: float) -> dict[str, Any]:
    """Compare the pipeline's cumulative token spend against its configured budget.

    Returns `{"total_tokens", "budget_tokens", "ratio", "warn", "exceeded"}`. `budget_tokens: None`
    (the built-in default, unlimited) always yields `ratio: None`, `warn: False`, `exceeded:
    False` -- a zero-config run never stalls (design doc §10). `warn` fires at `warn_ratio` (no
    pause, journal only); `exceeded` fires at 100% (pause + GB1)."""
    total_tokens = totals(state_dir)["tokens"]
    if budget_tokens is None:
        return {"total_tokens": total_tokens, "budget_tokens": None, "ratio": None, "warn": False, "exceeded": False}
    ratio = total_tokens / budget_tokens
    return {
        "total_tokens": total_tokens,
        "budget_tokens": budget_tokens,
        "ratio": ratio,
        "warn": ratio >= warn_ratio,
        "exceeded": ratio >= 1.0,
    }


# --------------------------------------------------------------------------------------
# Model selection
# --------------------------------------------------------------------------------------


def resolve_model(
    agent: str,
    project_model: dict[str, str] | None = None,
    prompt_model: dict[str, str] | None = None,
    spawn_model: str = "inherit",
) -> str:
    """Five-step model-resolution order for one agent (design doc §11, first match wins):
    prompt `model.<agent>` -> prompt `model.default` -> project `model.<agent>` -> project
    `model.default` -> inherit (`spawn_model`, the model active at the spawning session).

    `project_model`/`prompt_model` are each layer's own raw `model` dict (e.g. `{"default": "X",
    "documenter": "Y"}`) -- deliberately *not* the already-merged resolved config, since a plain
    per-key merge of the two layers cannot distinguish "the project set this agent" from "the
    prompt set a blanket default," and the precedence order above depends on that distinction
    (a prompt-wide default outranks a project-specific override).

    Raises `BudgetError` for any resolved name that is neither `"inherit"` nor a known model id
    (design doc §11: "unresolvable model names fail fast at spawn")."""
    project_model = project_model or {}
    prompt_model = prompt_model or {}

    for candidate in (prompt_model.get(agent), prompt_model.get("default"), project_model.get(agent), project_model.get("default")):
        if candidate:
            resolved = candidate
            break
    else:
        resolved = "inherit"

    if resolved == "inherit":
        return spawn_model
    if resolved not in KNOWN_MODELS:
        raise BudgetError(f"unknown model {resolved!r} for agent {agent!r}; known models are {sorted(KNOWN_MODELS)}")
    return resolved


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: python -m lib.budget <record-usage|totals|aggregate-totals|check-budget|resolve-model> '<json-kwargs>'",
            file=sys.stderr,
        )
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "record-usage":
            print(json.dumps(record_usage(**kwargs)))
        elif command == "totals":
            print(json.dumps(totals(**kwargs)))
        elif command == "aggregate-totals":
            print(json.dumps(aggregate_totals(**kwargs)))
        elif command == "check-budget":
            print(json.dumps(check_budget(**kwargs)))
        elif command == "resolve-model":
            print(json.dumps({"model": resolve_model(**kwargs)}))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (BudgetError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
