"""Saga rollback: a failure partway through must compensate every
completed step, in reverse order."""

from app.graph import resume_workflow, run_workflow
from app.saga import SagaResult, SagaStep, run_saga
from app.store import get_store


def test_saga_compensates_in_reverse_on_failure():
    events: list[str] = []

    def ok_step(name):
        def action():
            events.append(f"do:{name}")
            return {"step": name}

        def compensate(_result):
            events.append(f"undo:{name}")
            return {"undone": name}

        return SagaStep(name, action, compensate)

    def failing_step():
        def action():
            events.append("do:fail")
            raise RuntimeError("boom")

        def compensate(_result):
            events.append("undo:fail")
            return {}

        return SagaStep("fail", action, compensate)

    result: SagaResult = run_saga(
        [ok_step("one"), ok_step("two"), failing_step(), ok_step("three")]
    )
    assert result.ok is False
    assert result.failed_step == "fail"
    assert result.completed == ["one", "two"]
    assert result.compensated == ["two", "one"]  # reverse order
    assert "three" not in result.completed
    assert events == ["do:one", "do:two", "do:fail", "undo:two", "undo:one"]


def test_saga_all_steps_ok_no_compensation():
    calls: list[str] = []
    steps = [
        SagaStep(
            f"s{i}",
            lambda i=i: calls.append(f"do:{i}") or {"i": i},
            lambda _r, i=i: calls.append(f"undo:{i}"),
        )
        for i in range(3)
    ]
    result = run_saga(steps)
    assert result.ok is True
    assert result.completed == ["s0", "s1", "s2"]
    assert result.compensated == []
    assert calls == ["do:0", "do:1", "do:2"]


def test_graph_payment_failure_rolls_back(seeded, checkpointer):
    """A payment whose notify step fails must reverse the reservation
    and the ledger entry (graph-level, via simulate_failure)."""
    run_workflow(
        "Approve payment for invoice INV-1003",
        thread_id="saga-1",
        checkpointer=checkpointer,
        record=False,
        simulate_failure=True,
    )
    state = resume_workflow("saga-1", True, checkpointer=checkpointer, record=False)
    assert state["status"] == "failed"
    assert state["saga_log"] and any(
        "COMPENSATED: post_ledger_entry" in line for line in state["saga_log"]
    )
    assert any("COMPENSATED: reserve_payment" in line for line in state["saga_log"])
    reservations = get_store().list("reservations")
    assert len(reservations) == 1
    assert reservations[0][1]["status"] == "reversed"
    ledger = get_store().list("ledger")
    assert len(ledger) == 1
    assert ledger[0][1]["status"] == "reversed"
