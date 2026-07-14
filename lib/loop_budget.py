"""Loop-budget accounting (design doc §5 "Loop budgets"; implementation plan Step 5 "Code
reviewer + rework loops & loop budgets").

`lib.state` already persists the raw per-edge bounce counters (`increment_loop_counter`,
`read_loop_counters`, Step 2) -- this module adds the piece Step 5 actually needs on top: which
`loop_limits.*` knob governs a given backward edge, and whether a given bounce has exhausted it.
The orchestrator's routing loop (`agents/orchestrator.md` "The routing loop", step 4) calls
`record_bounce` exactly once per backward-edge traversal, in place of calling
`lib.state.increment_loop_counter` directly, so the exceeded-or-not comparison lives in one
tested place instead of being re-derived in agent prose.

    budget_class_for_edge(edge_id) -> str                     # e.g. "L1" -> "l1"
    record_bounce(state_dir, edge_id, loop_limits) -> dict     # increment + compare to limit
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.state import increment_loop_counter

# Backward-edge id -> the `loop_limits.*` knob it draws its bounce budget from (design doc §5
# "Loop budgets" table; config/config_schema.json's `loop_limits` properties). L6 is the
# Option B/C-only edge and is deliberately absent -- this build has no Option B/C
# (CLAUDE.md; docs/implementation/README.md §7).
EDGE_BUDGET_CLASS: dict[str, str] = {
    "L1": "l1",
    "L2": "escalations",
    "L3": "l3",
    "L4": "escalations",
    "L5": "escalations",
    "L7": "post_pr",
    "L8": "post_pr",
    "L9": "post_pr",
    "L10": "post_pr",
}


class LoopBudgetError(Exception):
    """Raised for an edge id with no known budget class, or a `loop_limits` dict missing the
    entry that class needs."""


def budget_class_for_edge(edge_id: str) -> str:
    """The `loop_limits.*` key governing `edge_id`'s bounce budget. Raises for any id that is
    not a backward (rework/escalation/post-PR) edge -- forward (`T*`) edges have no bounce
    budget at all."""
    try:
        return EDGE_BUDGET_CLASS[edge_id]
    except KeyError:
        raise LoopBudgetError(f"edge {edge_id!r} has no known loop-budget class") from None


def record_bounce(state_dir: str | Path, edge_id: str, loop_limits: dict[str, int]) -> dict[str, Any]:
    """Increment `edge_id`'s bounce counter (persisting it and appending the `loop_increment`
    history record, via `lib.state.increment_loop_counter`) and report whether this bounce has
    exhausted its budget class's limit.

    Returns `{"edge_id", "budget_class", "count", "limit", "exceeded"}`. `exceeded` is true from
    the bounce that *reaches* the limit onward (a limit of 3 permits exactly 3 bounces; the 3rd
    is the one that trips it -- design doc §5's Tier-2 example: "a diff that keeps failing review
    3x trips the L1 budget"). The orchestrator escalates to the human instead of continuing to
    route the bounce whenever `exceeded` is true.
    """
    budget_class = budget_class_for_edge(edge_id)
    if budget_class not in loop_limits:
        raise LoopBudgetError(f"loop_limits has no {budget_class!r} entry for edge {edge_id!r}")
    limit = loop_limits[budget_class]
    count = increment_loop_counter(state_dir, edge_id)
    return {
        "edge_id": edge_id,
        "budget_class": budget_class,
        "count": count,
        "limit": limit,
        "exceeded": count >= limit,
    }


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m lib.loop_budget <record-bounce> '<json-kwargs>'", file=sys.stderr)
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "record-bounce":
            print(json.dumps(record_bounce(**kwargs)))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (LoopBudgetError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
