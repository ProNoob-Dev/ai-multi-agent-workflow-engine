"""Router classification tests: every golden request must route correctly."""

from app.agents import classify_intent
from app.eval import load_golden


def test_router_matches_golden_set():
    for case in load_golden():
        assert classify_intent(case["request"]) == case["expected_intent"], case["id"]


def test_router_unknown_request_defaults_to_lookup():
    assert classify_intent("tell me something interesting") == "lookup"
    assert classify_intent("") == "lookup"


def test_router_payment_beats_report_keywords():
    # "payments" (plural) must not trigger the payment rule; the report wins.
    assert classify_intent("Summarise this month's approved payments") == "report"
    assert classify_intent("Pay invoice INV-1004") == "invoice"


def test_router_payment_terms_is_a_lookup():
    assert classify_intent("Find vendor Acme Office Supplies payment terms") == "lookup"
