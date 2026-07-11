"""Pipeline state directory: per-node scratch state and the append-only pipeline-state history
(design doc §4 "Pipeline state and persistence").

The state directory is separate from the throwaway git worktree and is *not* auto-deleted when
the worktree is cleaned up -- it is the durable home for everything that must survive a stage
restart, a paused gate, or a gap of days between sessions:

    <state_dir>/
        manifest.json          # run manifest snapshot (resolved config + provenance + versions)
        history.jsonl           # append-only pipeline-state history (one JSON record per line)
        loop_budgets.json       # edge id -> bounce count, for loop-budget enforcement
        node-state/<node>.json  # each node's own within-stage scratch progress
        artifacts/<name>        # working artifacts (design_doc, notes, evidence, reports, ...)

The history file is the crash-recovery substrate for the pure-agent router (routing position
lives in a file, not only in the orchestrator's context window) and the control-flow audit
trail. It is append-only and ordered: `latest_position` replays it to find where a pipeline was
last routed to, which is what a restart resumes from.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_HISTORY_EVENTS = {
    "transition",
    "gate_open",
    "gate_resolved",
    "escalation",
    "loop_increment",
    "restart",
}


class StateError(Exception):
    """Raised for state-directory misuse (bad event type, missing directory, etc.)."""


def default_state_root(repo_root: str | Path) -> Path:
    """Default base directory for all pipelines' state directories: a sibling of the repo root,
    mirroring `worktree.root`'s default `../.agents-worktrees` so state, like worktrees, never
    lives inside the git-tracked source tree."""
    return Path(repo_root).resolve().parent / ".agents-state"


def state_dir_path(repo_root: str | Path, pipeline_id: str, state_root: str | Path | None = None) -> Path:
    root = Path(state_root).resolve() if state_root is not None else default_state_root(repo_root)
    return root / pipeline_id


def init_state_dir(repo_root: str | Path, pipeline_id: str, state_root: str | Path | None = None) -> Path:
    """Create the state directory (and its subdirectories) if it does not already exist.
    Idempotent -- safe to call again on resume."""
    state_dir = state_dir_path(repo_root, pipeline_id, state_root)
    (state_dir / "node-state").mkdir(parents=True, exist_ok=True)
    (state_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    history_path = state_dir / "history.jsonl"
    if not history_path.exists():
        history_path.touch()
    return state_dir


def _write_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _read_json(path: Path, default: dict | None = None) -> dict | None:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------------------
# Run manifest (snapshot, not append-only)
# --------------------------------------------------------------------------------------


def write_manifest(state_dir: str | Path, manifest: dict) -> None:
    _write_json(Path(state_dir) / "manifest.json", manifest)


def read_manifest(state_dir: str | Path) -> dict | None:
    return _read_json(Path(state_dir) / "manifest.json")


# --------------------------------------------------------------------------------------
# Pipeline-state history (append-only)
# --------------------------------------------------------------------------------------


def append_history(state_dir: str | Path, event: str, **fields: Any) -> dict:
    """Append one record to history.jsonl and return it. `fields` may include any of `from`,
    `to`, `edge`, `gate`, `detail` per the record shape in design doc §4; unset fields are
    omitted rather than written as null."""
    if event not in ALLOWED_HISTORY_EVENTS:
        raise StateError(f"unknown history event {event!r}; expected one of {sorted(ALLOWED_HISTORY_EVENTS)}")

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **{k: v for k, v in fields.items() if v is not None},
    }
    history_path = Path(state_dir) / "history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def read_history(state_dir: str | Path) -> list[dict]:
    history_path = Path(state_dir) / "history.jsonl"
    if not history_path.exists():
        return []
    with open(history_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def latest_position(state_dir: str | Path) -> str | None:
    """The `to` node of the most recent `transition` record, i.e. where a resumed pipeline picks
    back up. None if no transition has been recorded yet (a fresh pipeline starts at the
    transition table's entry_node)."""
    for record in reversed(read_history(state_dir)):
        if record["event"] == "transition":
            return record.get("to")
    return None


# --------------------------------------------------------------------------------------
# Per-node state (within-stage scratch progress)
# --------------------------------------------------------------------------------------


def write_node_state(state_dir: str | Path, node_id: str, data: dict) -> None:
    _write_json(Path(state_dir) / "node-state" / f"{node_id}.json", data)


def read_node_state(state_dir: str | Path, node_id: str) -> dict | None:
    return _read_json(Path(state_dir) / "node-state" / f"{node_id}.json")


# --------------------------------------------------------------------------------------
# Working artifacts (design_doc, implementation_notes, verification_evidence, review reports, ...)
# --------------------------------------------------------------------------------------


def write_artifact(state_dir: str | Path, name: str, content: str) -> Path:
    path = Path(state_dir) / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def read_artifact(state_dir: str | Path, name: str) -> str:
    return (Path(state_dir) / "artifacts" / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# Loop-budget counters
# --------------------------------------------------------------------------------------


def read_loop_counters(state_dir: str | Path) -> dict[str, int]:
    return _read_json(Path(state_dir) / "loop_budgets.json", default={})


def increment_loop_counter(state_dir: str | Path, edge_id: str) -> int:
    """Increment the bounce counter for a backward edge, persist it, and append the
    corresponding `loop_increment` history record. Returns the new count."""
    counters = read_loop_counters(state_dir)
    counters[edge_id] = counters.get(edge_id, 0) + 1
    _write_json(Path(state_dir) / "loop_budgets.json", counters)
    append_history(state_dir, "loop_increment", edge=edge_id, detail=f"count={counters[edge_id]}")
    return counters[edge_id]


def _cli(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: python -m lib.state <init|append-history|read-history|latest-position> '<json-kwargs>'",
            file=sys.stderr,
        )
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "init":
            print(json.dumps({"state_dir": str(init_state_dir(**kwargs))}))
        elif command == "append-history":
            print(json.dumps(append_history(**kwargs)))
        elif command == "read-history":
            print(json.dumps(read_history(**kwargs)))
        elif command == "latest-position":
            print(json.dumps({"node": latest_position(**kwargs)}))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (StateError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
