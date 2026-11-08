"""Checkpoint recovery: a killed run resumes from its last checkpoint
without duplicating a side effect."""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.graph import build_graph, resume_workflow, run_workflow
from app.store import get_store


def test_checkpoint_resume_after_kill(seeded, tmp_path):
    """Run to the HITL pause, throw the graph away (simulated crash),
    rebuild it on the same SQLite file, resume, and verify the payment
    was applied exactly once."""
    db_path = str(tmp_path / "checkpoints.db")

    # First "process": run to the approval pause, then die.
    conn1 = sqlite3.connect(db_path, check_same_thread=False)
    graph1 = build_graph(SqliteSaver(conn1))
    from app.graph import _now_iso

    initial = {
        "request_id": "ckpt-1",
        "request": "Approve payment for invoice INV-1003",
        "intent": "",
        "agent": "",
        "steps": [],
        "tool_calls": [],
        "result": "",
        "citations": [],
        "needs_approval": False,
        "financial_action": None,
        "approval": None,
        "status": "running",
        "side_effects": [],
        "saga_log": [],
        "error": None,
        "tokens": 0,
        "latency_ms": 0,
        "cost_usd": 0,
        "trace": [],
        "started_at": _now_iso(),
        "simulate_failure": False,
    }
    out1 = graph1.invoke(initial, {"configurable": {"thread_id": "ckpt-1"}})
    assert out1["status"] == "awaiting_approval"
    conn1.close()  # simulated crash: process dies here

    # Second "process": a brand-new graph object on the same checkpoint file.
    conn2 = sqlite3.connect(db_path, check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    state = resume_workflow("ckpt-1", True, checkpointer=saver2, record=False)
    assert state["status"] == "completed"
    ledger = get_store().list("ledger")
    assert len(ledger) == 1, "ledger entry must exist exactly once"
    assert ledger[0][1]["status"] == "posted"


def test_completed_run_state_is_persisted(seeded, checkpointer):
    """After approval, the finished state is readable from the checkpointer."""
    from app.graph import build_graph

    run_workflow(
        "Approve payment for invoice INV-1003",
        thread_id="ckpt-3",
        checkpointer=checkpointer,
        record=False,
    )
    resume_workflow("ckpt-3", True, checkpointer=checkpointer, record=False)
    graph = build_graph(checkpointer)
    snapshot = graph.get_state({"configurable": {"thread_id": "ckpt-3"}})
    assert snapshot.values["status"] == "completed"
    assert snapshot.values["approval"] is True
    assert snapshot.values["financial_action"]["invoice_id"] == "INV-1003"
