"""Autonomy-gradient escalation threshold (design doc §7 "Autonomy gradient" + §8 "Decision
journal" escalation rule), implemented as `lib.journal.evaluate_escalation`. Kept in its own test
module (per docs/implementation/step-03-refiner-designer.md's tree delta) even though the
function lives in `lib/journal.py`, since it is conceptually the autonomy-gradient's truth table
rather than journal storage."""

import pytest

from lib.journal import JournalError, evaluate_escalation


@pytest.mark.parametrize(
    "level,reversal_cost,num_answers,expected",
    [
        # ask_freely (refiner): escalate on medium+ ambiguity, but only with >=2 plausible answers.
        ("ask_freely", "low", 2, False),
        ("ask_freely", "medium", 2, True),
        ("ask_freely", "high", 2, True),
        ("ask_freely", "high", 1, False),  # only one plausible answer -> decide, never escalate
        # lean_ask (designer): escalate only on high reversal cost; decide+journal medium.
        ("lean_ask", "medium", 2, False),
        ("lean_ask", "high", 2, True),
        ("lean_ask", "high", 1, False),
        # Deeper stages (implementer onward) have no generic ad-hoc escalation edge through this
        # mechanism -- their escalation paths are named transition-table edges instead (§7).
        ("lean_decide", "high", 2, False),
        ("decide", "high", 2, False),
        ("full", "high", 2, False),
    ],
)
def test_evaluate_escalation_matches_truth_table(level, reversal_cost, num_answers, expected):
    result = evaluate_escalation(level, reversal_cost, num_answers)
    assert result["escalate"] is expected
    assert result["high_risk"] is False
    assert result["status"] == "pending_review"


def test_evaluate_escalation_never_policy_suppresses_and_flags_high_risk():
    """escalation_policy: never converts a would-be escalation into a high_risk-flagged journal
    entry instead of asking the user (design doc §7 "Interaction with gating")."""
    result = evaluate_escalation("ask_freely", "high", 2, escalation_policy="never")
    assert result["escalate"] is False
    assert result["high_risk"] is True


def test_evaluate_escalation_never_policy_no_high_risk_when_not_escalation_worthy():
    result = evaluate_escalation("ask_freely", "low", 2, escalation_policy="never")
    assert result["escalate"] is False
    assert result["high_risk"] is False


def test_evaluate_escalation_never_policy_no_high_risk_with_one_plausible_answer():
    result = evaluate_escalation("lean_ask", "high", 1, escalation_policy="never")
    assert result["escalate"] is False
    assert result["high_risk"] is False


def test_evaluate_escalation_rejects_unknown_level():
    with pytest.raises(JournalError):
        evaluate_escalation("omniscient", "high", 2)


def test_evaluate_escalation_rejects_unknown_reversal_cost():
    with pytest.raises(JournalError):
        evaluate_escalation("ask_freely", "catastrophic", 2)


def test_evaluate_escalation_rejects_unknown_escalation_policy():
    with pytest.raises(JournalError):
        evaluate_escalation("ask_freely", "high", 2, escalation_policy="sometimes")
