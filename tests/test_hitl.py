"""HITL enforcement: a financial action must never execute without a
human approval, and a rejection must leave no side effects behind."""

from app.graph import resume_workflow, run_workflow
from app.store import get_store


def test_payment_pauses_for_approval(seeded, checkpointer):
    state = run_workflow(
        "Approve payment for invoice INV-1003",
        thread_id="hitl-1",
        checkpointer=checkpointer,
        record=False,
    )
    assert state["status"] == "awaiting_approval"
    assert state["needs_approval"] is True
    assert state["financial_action"]["invoice_id"] == "INV-1003"
    assert state["financial_action"]["amount"] == 62000
    # Nothing was executed while waiting: no reservation, no ledger entry.
    assert get_store().list("reservations") == []
    assert get_store().list("ledger") == []


def test_approve_executes_saga(seeded, checkpointer):
    run_workflow(
        "Approve payment for invoice INV-1003",
        thread_id="hitl-2",
        checkpointer=checkpointer,
        record=False,
    )
    state = resume_workflow("hitl-2", True, checkpointer=checkpointer, record=False)
    assert state["status"] == "completed"
    assert state["approval"] is True
    assert any("STEP OK: reserve_payment" in line for line in state["saga_log"])
    assert any("STEP OK: post_ledger_entry" in line for line in state["saga_log"])
    reservations = get_store().list("reservations")
    assert len(reservations) == 1
    assert reservations[0][1]["status"] == "reserved"
    ledger = get_store().list("ledger")
    assert len(ledger) == 1
    assert ledger[0][1]["status"] == "posted"


def test_reject_leaves_no_side_effects(seeded, checkpointer):
    run_workflow(
        "Pay invoice INV-1004 to Acme Office Supplies",
        thread_id="hitl-3",
        checkpointer=checkpointer,
        record=False,
    )
    state = resume_workflow("hitl-3", False, checkpointer=checkpointer, record=False)
    assert state["status"] == "rejected"
    assert state["approval"] is False
    assert get_store().list("reservations") == []
    assert get_store().list("ledger") == []


def test_validation_only_never_needs_approval(seeded, checkpointer):
    state = run_workflow(
        "Validate invoice INV-1001",
        thread_id="hitl-4",
        checkpointer=checkpointer,
        record=False,
    )
    assert state["status"] == "completed"
    assert state["needs_approval"] is False
    assert state["financial_action"] is None
