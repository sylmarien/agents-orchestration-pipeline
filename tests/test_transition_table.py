import copy

import pytest

from lib.graph_validate import (
    _PACKAGE_DIR,
    FORBIDDEN_OPTION_BC_EDGE_IDS,
    GraphValidationError,
    load_table,
    validate,
)


@pytest.fixture
def table() -> dict:
    return load_table()


def test_built_in_table_validates(table):
    validate(table)  # must not raise


def test_built_in_table_has_no_option_bc_edges(table):
    edge_ids = {e["id"] for e in table["edges"]}
    assert edge_ids.isdisjoint(FORBIDDEN_OPTION_BC_EDGE_IDS)


@pytest.mark.parametrize("forbidden_id", sorted(FORBIDDEN_OPTION_BC_EDGE_IDS))
def test_option_bc_edge_id_rejected(table, forbidden_id):
    mutated = copy.deepcopy(table)
    mutated["edges"].append(
        {"id": forbidden_id, "from": "designer", "to": "documenter", "trigger": "design_ready", "gate": "G2"}
    )
    with pytest.raises(GraphValidationError, match="Option B/C-only"):
        validate(mutated)


def test_dangling_edge_endpoint_rejected(table):
    mutated = copy.deepcopy(table)
    mutated["edges"].append({"id": "TX", "from": "refiner", "to": "nonexistent_node", "trigger": "spec_ready", "gate": None})
    with pytest.raises(GraphValidationError, match="not declared in `nodes`"):
        validate(mutated)


def test_undeclared_trigger_rejected(table):
    mutated = copy.deepcopy(table)
    for edge in mutated["edges"]:
        if edge["id"] == "T1":
            edge["trigger"] = "not_a_real_outcome"
    with pytest.raises(GraphValidationError, match="not a declared outcome"):
        validate(mutated)


def test_unresolved_gate_rejected(table):
    mutated = copy.deepcopy(table)
    for edge in mutated["edges"]:
        if edge["id"] == "T1":
            edge["gate"] = "G99"
    with pytest.raises(GraphValidationError, match="does not resolve"):
        validate(mutated)


def test_unclosed_artifact_dependency_rejected(table):
    mutated = copy.deepcopy(table)
    for node in mutated["nodes"]:
        if node["id"] == "designer":
            node["consumes"].append("nonexistent_artifact")
    with pytest.raises(GraphValidationError, match="neither an intake artifact nor produced"):
        validate(mutated)


def test_no_terminal_rejected(table):
    mutated = copy.deepcopy(table)
    mutated["edges"] = [e for e in mutated["edges"] if e["id"] != "T8"]
    with pytest.raises(GraphValidationError, match="not reachable"):
        validate(mutated)


def test_multiple_entry_candidates_rejected(table):
    mutated = copy.deepcopy(table)
    mutated["edges"] = [e for e in mutated["edges"] if e["id"] != "T1"]
    with pytest.raises(GraphValidationError, match="expected exactly one entry node"):
        validate(mutated)


def test_terminal_with_outgoing_edge_rejected(table):
    mutated = copy.deepcopy(table)
    for node in mutated["nodes"]:
        if node["id"] == "pr_shepherd":
            node["outcomes"].append("bogus_from_terminal")
    mutated["edges"].append({"id": "TX", "from": "done", "to": "refiner", "trigger": "spec_ready", "gate": None})
    with pytest.raises(GraphValidationError, match="has outgoing edges"):
        validate(mutated)


def test_terminal_with_backward_outgoing_edge_rejected(table):
    # A backward (L-prefixed, non-forward) edge out of the terminal node must be caught too --
    # the outgoing-edge check must not look only at forward edges.
    mutated = copy.deepcopy(table)
    for node in mutated["nodes"]:
        if node["id"] == "pr_shepherd":
            node["outcomes"].append("bogus_from_terminal")
    mutated["edges"].append({"id": "L99", "from": "done", "to": "refiner", "trigger": "spec_ready", "gate": None})
    with pytest.raises(GraphValidationError, match="has outgoing edges"):
        validate(mutated)


def test_duplicate_node_id_rejected(table):
    mutated = copy.deepcopy(table)
    mutated["nodes"].append({"id": "refiner", "agent": "x", "consumes": [], "produces": [], "outcomes": []})
    with pytest.raises(GraphValidationError, match="duplicate node id"):
        validate(mutated)


def test_duplicate_edge_id_rejected(table):
    mutated = copy.deepcopy(table)
    mutated["edges"].append({"id": "L1", "from": "designer", "to": "refiner", "trigger": "spec_gap", "gate": "GE2"})
    with pytest.raises(GraphValidationError, match="duplicate edge id"):
        validate(mutated)


# --- Fixture/table consistency: the stub-outcome scenarios must be valid walks through the
# built-in graph. This is a deterministic, code-only consistency check of hand-authored YAML
# fixtures against the transition table -- not a routing engine (design doc Q9: v1 routing is
# LLM-interpreted; this only validates that the *fixtures* are internally consistent so the
# stub-agent harness can drive a real orchestrator through them predictably).


FIXTURES_DIR = _PACKAGE_DIR / "fixtures" / "stub-outcomes"


def _load_scenario(name: str) -> dict:
    import yaml

    with open(FIXTURES_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _simulate(table: dict, scenario: dict) -> list[str]:
    """Walk the scenario's scripted (node, outcome) visits through the table's edges, in the
    order each node is first reached, following each outcome to its matching outgoing edge.
    Returns the list of edge ids traversed. Raises AssertionError on any inconsistency."""
    edges_by_source: dict[str, list[dict]] = {}
    for edge in table["edges"]:
        edges_by_source.setdefault(edge["from"], []).append(edge)

    visit_counts: dict[str, int] = {}
    node = table["entry_node"]
    trace: list[str] = []
    terminal = table["terminal_node"]
    guard = 0
    while node != terminal:
        guard += 1
        assert guard < 100, "simulation did not reach the terminal node -- possible infinite loop"

        visits = scenario["nodes"].get(node)
        assert visits, f"scenario has no scripted outcomes for node {node!r}"
        idx = visit_counts.get(node, 0)
        assert idx < len(visits), f"scenario ran out of scripted outcomes for node {node!r} (visit {idx + 1})"
        visit_counts[node] = idx + 1
        outcome = visits[idx]["outcome"]

        candidates = [e for e in edges_by_source.get(node, []) if e["trigger"] == outcome]
        assert len(candidates) == 1, f"node {node!r} outcome {outcome!r} does not match exactly one outgoing edge"
        edge = candidates[0]
        trace.append(edge["id"])
        node = edge["to"]
    return trace


@pytest.mark.parametrize(
    "scenario_name,expected_edges",
    [
        ("happy-path", ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]),
        ("review-bounce", ["T1", "T2", "T3", "L1", "T3", "T4", "T5", "T6", "T7", "T8"]),
        ("escalation", ["T1", "T2", "L5", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]),
    ],
)
def test_stub_scenario_is_a_valid_walk(table, scenario_name, expected_edges):
    scenario = _load_scenario(scenario_name)
    assert _simulate(table, scenario) == expected_edges
