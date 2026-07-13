"""Decision journal: schema validation, storage, pending-entry selection, cross-pipeline merge,
and override -> rollback resolution (design doc §8 "Decision journal").

Every pipeline agent that decides something autonomously instead of escalating it appends one
entry here (design doc §7 "Autonomy gradient" + §8 "Escalation rule"). The journal is itself a
shared artifact (`decision_journal`, YAML) and one of the transition table's `intake_artifacts`
(`config/transition_table.yaml`) -- available (empty) before the first node runs, and readable by
every later node without ever being "produced" by a single one in the producer/consumer sense.

Storage: one file per pipeline, `<state_dir>/artifacts/decision_journal.yaml`, a YAML list of
entries matching the journal entry schema below. Reuses `lib.state`'s artifact read/write so the
file lives in the same place as every other working artifact.

    validate_entry(entry) -> None                              # raises JournalError
    append_entry(state_dir, ...) -> dict                        # id/timestamp auto-filled
    read_journal(state_dir) -> list[dict]
    pending_entries(state_dir) -> list[dict]                    # status == pending_review
    acknowledge_entry(state_dir, entry_id) -> dict
    resolve_override(state_dir, entry_id, override_action) -> dict   # -> {"entry", "rollback_to_node"}
    merge_journals(state_dirs) -> list[dict]                    # across a multi-pipeline run

Autonomy-gradient escalation threshold (design doc §7 levels / §8 escalation rule):

    evaluate_escalation(level, reversal_cost, num_plausible_answers, escalation_policy) -> dict
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from lib.state import read_artifact, write_artifact

JOURNAL_ARTIFACT_NAME = "decision_journal.yaml"

AGENTS = {
    "refiner",
    "designer",
    "implementer",
    "code_reviewer",
    "documenter",
    "documentation_reviewer",
    "submitter",
    "pr_shepherd",
}

# Short id prefix per agent, used to auto-generate human-scannable entry ids (design doc §8
# example: `task1-D003` -- pipeline id, agent prefix, 1-based sequence number zero-padded to 3).
_AGENT_ID_PREFIX = {
    "refiner": "R",
    "designer": "D",
    "implementer": "I",
    "code_reviewer": "CR",
    "documenter": "DOC",
    "documentation_reviewer": "DR",
    "submitter": "S",
    "pr_shepherd": "PRS",
}

REVERSAL_COSTS = {"low", "medium", "high"}
_REVERSAL_COST_ORDER = {"low": 0, "medium": 1, "high": 2}

STATUSES = {"pending_review", "acknowledged", "overridden"}

AUTONOMY_LEVELS = {"ask_freely", "lean_ask", "lean_decide", "decide", "full"}

# The generic ad-hoc-escalation mechanism only applies to the two stages the design doc gives an
# explicit reversal-cost threshold for (§7 "Stage assignment"): refiner (ask_freely) escalates on
# medium+ ambiguity, designer (lean_ask) on high. Deeper stages' escalation paths are the named
# transition-table edges (design_infeasible, escalate_design, ...), not this generic threshold --
# `None` here means "this mechanism never escalates for this level".
ESCALATION_THRESHOLD = {
    "ask_freely": "medium",
    "lean_ask": "high",
    "lean_decide": None,
    "decide": None,
    "full": None,
}

ESCALATION_POLICIES = {"gradient", "never"}


class JournalError(Exception):
    """Raised for a malformed journal entry or an unresolvable lookup (missing entry id, ...)."""


def journal_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "artifacts" / JOURNAL_ARTIFACT_NAME


def validate_entry(entry: dict) -> None:
    """Raise JournalError listing every violation of the journal entry schema (design doc §8)."""
    errors: list[str] = []

    def _require_str(field: str) -> None:
        if not isinstance(entry.get(field), str) or not entry.get(field):
            errors.append(f"{field!r} must be a non-empty string")

    _require_str("id")
    _require_str("pipeline")
    _require_str("stage_artifact")
    _require_str("question")
    _require_str("chosen")
    _require_str("rationale")

    if entry.get("agent") not in AGENTS:
        errors.append(f"agent {entry.get('agent')!r} is not one of {sorted(AGENTS)}")

    timestamp = entry.get("timestamp")
    if not isinstance(timestamp, str):
        errors.append("'timestamp' must be an ISO-8601 string")
    else:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"'timestamp' {timestamp!r} is not a valid ISO-8601 timestamp")

    options = entry.get("options_considered")
    if not isinstance(options, list) or len(options) < 2:
        errors.append("'options_considered' must list at least two options (the chosen one and a runner-up)")
    else:
        for i, option in enumerate(options):
            if not isinstance(option, dict) or not option.get("option") or not option.get("consequence"):
                errors.append(f"options_considered[{i}] must be an object with non-empty 'option' and 'consequence'")

    if entry.get("reversal_cost") not in REVERSAL_COSTS:
        errors.append(f"reversal_cost {entry.get('reversal_cost')!r} is not one of {sorted(REVERSAL_COSTS)}")

    if entry.get("status") not in STATUSES:
        errors.append(f"status {entry.get('status')!r} is not one of {sorted(STATUSES)}")

    override_action = entry.get("override_action")
    if override_action is not None and not isinstance(override_action, str):
        errors.append("'override_action' must be a string or null")
    if entry.get("status") == "overridden" and not override_action:
        errors.append("status 'overridden' requires a non-empty 'override_action'")

    if errors:
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        raise JournalError(f"invalid journal entry:\n{bullet_list}")


def read_journal(state_dir: str | Path) -> list[dict]:
    path = journal_path(state_dir)
    if not path.exists():
        return []
    return yaml.safe_load(read_artifact(state_dir, JOURNAL_ARTIFACT_NAME)) or []


def _write_journal(state_dir: str | Path, entries: list[dict]) -> None:
    write_artifact(state_dir, JOURNAL_ARTIFACT_NAME, yaml.safe_dump(entries, sort_keys=False))


def _next_id(state_dir: str | Path, pipeline: str, agent: str) -> str:
    sequence = len(read_journal(state_dir)) + 1
    return f"{pipeline}-{_AGENT_ID_PREFIX[agent]}{sequence:03d}"


def append_entry(
    state_dir: str | Path,
    *,
    pipeline: str,
    agent: str,
    stage_artifact: str,
    question: str,
    options_considered: list[dict],
    chosen: str,
    rationale: str,
    reversal_cost: str,
    status: str = "pending_review",
    override_action: str | None = None,
    entry_id: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """Validate and append one journal entry; return the stored entry. `id`/`timestamp` are
    auto-filled when omitted, matching the schema example (design doc §8: `task1-D003`)."""
    if agent not in AGENTS:
        raise JournalError(f"agent {agent!r} is not one of {sorted(AGENTS)}")

    entry = {
        "id": entry_id or _next_id(state_dir, pipeline, agent),
        "pipeline": pipeline,
        "agent": agent,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "stage_artifact": stage_artifact,
        "question": question,
        "options_considered": options_considered,
        "chosen": chosen,
        "rationale": rationale,
        "reversal_cost": reversal_cost,
        "status": status,
        "override_action": override_action,
    }
    validate_entry(entry)

    entries = read_journal(state_dir)
    entries.append(entry)
    _write_journal(state_dir, entries)
    return entry


def pending_entries(state_dir: str | Path) -> list[dict]:
    return [e for e in read_journal(state_dir) if e["status"] == "pending_review"]


def _find_entry(entries: list[dict], entry_id: str) -> dict:
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    raise JournalError(f"no journal entry with id {entry_id!r}")


def acknowledge_entry(state_dir: str | Path, entry_id: str) -> dict:
    """Mark a pending entry `acknowledged` (the human has seen it and accepts it as-is)."""
    entries = read_journal(state_dir)
    entry = _find_entry(entries, entry_id)
    entry["status"] = "acknowledged"
    _write_journal(state_dir, entries)
    return entry


def resolve_override(state_dir: str | Path, entry_id: str, override_action: str) -> dict:
    """Mark an entry `overridden` with the redo description, and resolve the rollback target --
    the stage that made the decision, i.e. the node the orchestrator must re-enter (design doc
    §8: "the orchestrator then rolls the pipeline back to the stage that made it"). Returns
    `{"entry": <updated entry>, "rollback_to_node": <agent/node id>}`; does not itself touch
    pipeline state or history -- performing the rollback is the orchestrator's job (P7)."""
    if not override_action:
        raise JournalError("override_action must be a non-empty string")
    entries = read_journal(state_dir)
    entry = _find_entry(entries, entry_id)
    entry["status"] = "overridden"
    entry["override_action"] = override_action
    _write_journal(state_dir, entries)
    return {"entry": entry, "rollback_to_node": entry["agent"]}


def merge_journals(state_dirs: list[str | Path]) -> list[dict]:
    """Concatenate every named pipeline's journal (each entry already carries its own `pipeline`
    field) into one timestamp-ordered list, for presenting decisions across a multi-pipeline run
    (design doc P4 split) or across all currently-running pipelines (`/pipeline:decisions`)."""
    merged: list[dict] = []
    for state_dir in state_dirs:
        merged.extend(read_journal(state_dir))
    return sorted(merged, key=lambda e: e["timestamp"])


def evaluate_escalation(
    level: str,
    reversal_cost: str,
    num_plausible_answers: int,
    escalation_policy: str = "gradient",
) -> dict[str, Any]:
    """Autonomy-gradient escalation decision (design doc §7 levels + §8 escalation rule).

    An agent escalates only when BOTH (1) at least two materially different answers are
    plausible, and (2) the reversal cost meets the stage's threshold (§7). `escalation_policy:
    never` (design doc §7 "Interaction with gating") suppresses every would-be escalation,
    converting it into a journal entry flagged `high_risk` for the G7 report instead.

    Returns `{"escalate": bool, "status": "pending_review", "high_risk": bool}` -- `status` is
    always `pending_review` here because either path (decide-and-journal, or escalate-then-
    journal-the-answer) starts life as a fresh entry awaiting human review at the next gate.
    """
    if level not in AUTONOMY_LEVELS:
        raise JournalError(f"level {level!r} is not one of {sorted(AUTONOMY_LEVELS)}")
    if reversal_cost not in REVERSAL_COSTS:
        raise JournalError(f"reversal_cost {reversal_cost!r} is not one of {sorted(REVERSAL_COSTS)}")
    if escalation_policy not in ESCALATION_POLICIES:
        raise JournalError(f"escalation_policy {escalation_policy!r} is not one of {sorted(ESCALATION_POLICIES)}")

    threshold = ESCALATION_THRESHOLD[level]
    would_escalate = (
        num_plausible_answers >= 2
        and threshold is not None
        and _REVERSAL_COST_ORDER[reversal_cost] >= _REVERSAL_COST_ORDER[threshold]
    )

    if escalation_policy == "never":
        return {"escalate": False, "status": "pending_review", "high_risk": would_escalate}
    return {"escalate": would_escalate, "status": "pending_review", "high_risk": False}


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: python -m lib.journal "
            "<append|read|pending|acknowledge|override|merge|evaluate-escalation> '<json-kwargs>'",
            file=sys.stderr,
        )
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "append":
            print(json.dumps(append_entry(**kwargs)))
        elif command == "read":
            print(json.dumps(read_journal(**kwargs)))
        elif command == "pending":
            print(json.dumps(pending_entries(**kwargs)))
        elif command == "acknowledge":
            print(json.dumps(acknowledge_entry(**kwargs)))
        elif command == "override":
            print(json.dumps(resolve_override(**kwargs)))
        elif command == "merge":
            print(json.dumps(merge_journals(**kwargs)))
        elif command == "evaluate-escalation":
            print(json.dumps(evaluate_escalation(**kwargs)))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (JournalError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
