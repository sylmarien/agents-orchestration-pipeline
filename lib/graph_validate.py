"""Well-formedness checks for config/transition_table.yaml (design doc §5 / §13 validation
rules, applied to the built-in Option A graph).

    validate(table) -> None   # raises GraphValidationError listing every violation

Checks (subset of the §13 custom-graph validation rules, already applicable to the built-in
graph):
  - every edge references declared nodes;
  - every edge's trigger is a declared outcome of its source node;
  - every edge's gate id (if any) resolves against the table's `gates` mapping;
  - the artifact dependency graph is closed: every node's `consumes` is either an intake
    artifact or produced by some node upstream of it on the forward spine;
  - there is exactly one entry node (no incoming forward edges) and it matches `entry_node`;
  - `terminal_node` is reachable from `entry_node` via forward edges and has no outgoing edges.

Plus one build-specific guard: the Option B/C-only edges (T2b, T3b, T4c, L6) may never appear in
this file, dormant or otherwise (CLAUDE.md; docs/implementation/README.md §7).

Run this at plugin build time and at pipeline spawn -- a malformed graph must fail fast rather
than misroute a live pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TABLE_PATH = _PACKAGE_DIR / "config" / "transition_table.yaml"

# Edge ids that belong exclusively to Option B/C in the design doc's §5 transition table. This
# build implements Option A only; these ids must never appear, dormant or otherwise.
FORBIDDEN_OPTION_BC_EDGE_IDS = {"T2b", "T3b", "T4c", "L6"}

# An edge id starting with this prefix is a forward (spine) edge; anything else (L-prefixed) is
# a rework/escalation/post-PR loop edge, excluded from the forward topological order used by the
# entry/terminal and artifact-closure checks.
_FORWARD_EDGE_PREFIX = "T"


class GraphValidationError(Exception):
    """Raised when a transition table fails one or more well-formedness checks."""


def load_table(path: str | Path = DEFAULT_TABLE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        table = yaml.safe_load(f)
    if not isinstance(table, dict):
        raise GraphValidationError(f"{path}: expected a YAML mapping at the top level, got {type(table).__name__}")
    return table


def _check_forbidden_edges(edges: list[dict], errors: list[str]) -> None:
    for edge in edges:
        if edge.get("id") in FORBIDDEN_OPTION_BC_EDGE_IDS:
            errors.append(
                f"edge {edge.get('id')!r}: Option B/C-only edge id is not permitted in this "
                "build (Option A only -- CLAUDE.md)"
            )


def _check_edge_endpoints(node_ids: set[str], edges: list[dict], errors: list[str]) -> None:
    for edge in edges:
        eid = edge.get("id", "<unknown>")
        for end in ("from", "to"):
            if edge.get(end) not in node_ids:
                errors.append(f"edge {eid!r}: {end} node {edge.get(end)!r} is not declared in `nodes`")


def _check_triggers(nodes_by_id: dict[str, dict], edges: list[dict], errors: list[str]) -> None:
    for edge in edges:
        eid = edge.get("id", "<unknown>")
        source = nodes_by_id.get(edge.get("from"))
        if source is None:
            continue  # already reported by _check_edge_endpoints
        outcomes = source.get("outcomes") or []
        if edge.get("trigger") not in outcomes:
            errors.append(
                f"edge {eid!r}: trigger {edge.get('trigger')!r} is not a declared outcome of "
                f"node {edge.get('from')!r} (declared outcomes: {outcomes})"
            )


def _check_gate_ids(gates: dict, edges: list[dict], errors: list[str]) -> None:
    for edge in edges:
        gate = edge.get("gate")
        if gate is not None and gate not in gates:
            errors.append(f"edge {edge.get('id', '<unknown>')!r}: gate {gate!r} does not resolve in `gates`")


def _check_unique_ids(nodes: list[dict], edges: list[dict], errors: list[str]) -> None:
    for label, items in (("node", nodes), ("edge", edges)):
        seen: set[str] = set()
        for item in items:
            item_id = item.get("id")
            if item_id in seen:
                errors.append(f"duplicate {label} id {item_id!r}: ids must be unique")
            seen.add(item_id)


def _forward_edges(edges: list[dict]) -> list[dict]:
    return [e for e in edges if str(e.get("id", "")).startswith(_FORWARD_EDGE_PREFIX)]


def _forward_adjacency(node_ids: set[str], forward_edges: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """incoming/outgoing adjacency over the forward-edge subgraph, shared by the topological-
    order, entry/terminal, and artifact-closure checks so the graph is only walked once."""
    incoming: dict[str, set[str]] = {n: set() for n in node_ids}
    outgoing: dict[str, set[str]] = {n: set() for n in node_ids}
    for edge in forward_edges:
        src, dst = edge.get("from"), edge.get("to")
        if src in node_ids and dst in node_ids:
            incoming[dst].add(src)
            outgoing[src].add(dst)
    return incoming, outgoing


def _topological_order(
    node_ids: set[str], incoming: dict[str, set[str]], outgoing: dict[str, set[str]], errors: list[str]
) -> list[str]:
    """Kahn's algorithm over the forward-edge subgraph. Appends an error and returns [] on a cycle."""
    remaining = {n: set(v) for n, v in incoming.items()}
    ready = sorted(n for n in node_ids if not remaining[n])
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(outgoing[n]):
            remaining[m].discard(n)
            if not remaining[m] and m not in order and m not in ready:
                ready.append(m)

    if len(order) != len(node_ids):
        errors.append("forward edges contain a cycle: cannot compute a topological order for the closure/entry checks")
        return []
    return order


def _check_entry_and_terminal(
    table: dict,
    node_ids: set[str],
    edges: list[dict],
    incoming: dict[str, set[str]],
    outgoing: dict[str, set[str]],
    errors: list[str],
) -> None:
    entry = table.get("entry_node")
    terminal = table.get("terminal_node")

    if entry not in node_ids:
        errors.append(f"entry_node {entry!r} is not a declared node")
    if terminal not in node_ids:
        errors.append(f"terminal_node {terminal!r} is not a declared node")
    if entry not in node_ids or terminal not in node_ids:
        return

    candidates = sorted(n for n in node_ids if not incoming[n])
    if len(candidates) != 1:
        errors.append(
            f"expected exactly one entry node (no incoming forward edges), found {candidates}"
        )
    elif candidates[0] != entry:
        errors.append(f"entry_node is {entry!r}, but the node with no incoming forward edges is {candidates[0]!r}")

    # Reachability from entry via forward edges.
    reached: set[str] = set()
    frontier = [entry]
    while frontier:
        n = frontier.pop()
        if n in reached:
            continue
        reached.add(n)
        frontier.extend(outgoing.get(n, ()))
    if terminal not in reached:
        errors.append(f"terminal_node {terminal!r} is not reachable from entry_node {entry!r} via forward edges")

    # Outgoing-edge check covers *all* edges (forward and backward/rework/post-PR alike) -- a
    # terminal node must have no way out of the graph at all, not merely no forward exit.
    all_sources = {e.get("from") for e in edges}
    if terminal in all_sources:
        errors.append(f"terminal_node {terminal!r} has outgoing edges; a terminal node must have none")


def _check_artifact_closure(
    table: dict, nodes_by_id: dict[str, dict], order: list[str], errors: list[str]
) -> None:
    if not order:
        return  # cycle already reported by _topological_order

    available: set[str] = set(table.get("intake_artifacts") or [])
    for node_id in order:
        node = nodes_by_id[node_id]
        consumes = set(node.get("consumes") or [])
        missing = consumes - available
        if missing:
            errors.append(
                f"node {node_id!r}: consumes {sorted(missing)} which is neither an intake "
                "artifact nor produced by any upstream node"
            )
        available |= set(node.get("produces") or [])


def validate(table: dict) -> None:
    """Validate a transition table dict; raise GraphValidationError with all violations found."""
    errors: list[str] = []

    nodes: list[dict] = table.get("nodes") or []
    edges: list[dict] = table.get("edges") or []
    gates: dict = table.get("gates") or {}
    node_ids = {n["id"] for n in nodes if "id" in n}
    nodes_by_id = {n["id"]: n for n in nodes if "id" in n}

    _check_unique_ids(nodes, edges, errors)
    _check_forbidden_edges(edges, errors)
    _check_edge_endpoints(node_ids, edges, errors)
    _check_triggers(nodes_by_id, edges, errors)
    _check_gate_ids(gates, edges, errors)

    forward_edges = _forward_edges(edges)
    incoming, outgoing = _forward_adjacency(node_ids, forward_edges)
    _check_entry_and_terminal(table, node_ids, edges, incoming, outgoing, errors)
    order = _topological_order(node_ids, incoming, outgoing, errors)
    _check_artifact_closure(table, nodes_by_id, order, errors)

    if errors:
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        raise GraphValidationError(f"invalid transition table:\n{bullet_list}")


def validate_file(path: str | Path = DEFAULT_TABLE_PATH) -> dict:
    """Load and validate the table at `path`; return it on success."""
    table = load_table(path)
    validate(table)
    return table


def _cli(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_TABLE_PATH
    try:
        validate_file(path)
    except (GraphValidationError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{path}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
