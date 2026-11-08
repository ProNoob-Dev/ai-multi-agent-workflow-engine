"""LangGraph state machine: Router -> Domain Agent -> [HITL gate] -> Execute -> Done.

Human-in-the-loop: any financial action pauses at the hitl_gate node via
LangGraph interrupt(). The run stays checkpointed until a human approves
or rejects it through the API; only then does execute_action run the
compensating saga. Financial actions can never execute without approval
— that is enforced by the graph topology, not by convention.

Checkpointing: PostgresSaver when DATABASE_URL is set (falls back to
SQLite with a warning if unavailable), otherwise a SQLite file
(data/checkpoints.db). A killed run resumes from its last checkpoint.
"""

import sqlite3
import threading
import time
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import config
from .agents import (
    AGENT_FOR_INTENT,
    classify_intent,
    invoice_agent,
    lookup_agent,
    policy_agent,
    report_agent,
)
from .mcp_server import call_tool_sync
from .saga import SagaResult, SagaStep, run_saga
from .store import get_store
from .tracing import cost_usd, emit_langfuse, emit_otel, new_run_id

GRAPH_LOCK = threading.Lock()
_GRAPH = None
_CHECKPOINTER = None


class WorkflowState(TypedDict, total=False):
    request_id: str
    request: str
    intent: str
    agent: str
    steps: list
    tool_calls: list
    result: str
    citations: list
    needs_approval: bool
    financial_action: dict | None
    approval: bool | None
    status: str
    side_effects: list
    saga_log: list
    error: str | None
    tokens: int
    latency_ms: float
    cost_usd: float
    trace: list
    started_at: str
    simulate_failure: bool


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _trace(state: dict, name: str, duration_ms: float, tokens: int = 0) -> dict:
    span = {"name": name, "duration_ms": round(duration_ms, 1), "tokens": tokens}
    return {"trace": state.get("trace", []) + [span]}


def router_node(state: dict) -> dict:
    started = time.perf_counter()
    intent = classify_intent(state["request"])
    duration = (time.perf_counter() - started) * 1000
    out = {
        "intent": intent,
        "agent": AGENT_FOR_INTENT[intent],
        "steps": state.get("steps", []) + [f"Router classified intent: {intent}"],
    }
    out.update(_trace(state, "router", duration))
    emit_otel("router", {"intent": intent})
    return out


def hitl_gate(state: dict) -> dict:
    """Pause for human approval. interrupt() checkpoints the run here;
    it resumes only via Command(resume=...)."""
    action = state.get("financial_action") or {}
    decision = interrupt(
        {
            "type": "financial_action",
            "action": action,
            "message": (
                f"Approval needed: {action.get('type')} of "
                f"{action.get('currency')} {action.get('amount'):,.0f} "
                f"for {action.get('invoice_id')}."
            ),
        }
    )
    approved = bool(decision)
    return {
        "approval": approved,
        "steps": state.get("steps", [])
        + [f"Human decision: {'approved' if approved else 'rejected'}"],
    }


def execute_action(state: dict) -> dict:
    """Run the financial action as a compensating saga."""
    started = time.perf_counter()
    action = state.get("financial_action") or {}
    request_id = state["request_id"]
    invoice_id = action.get("invoice_id")
    amount = float(action.get("amount") or 0)
    simulate_failure = state.get("simulate_failure", False)

    def _reserve():
        return call_tool_sync(
            "reserve_payment",
            {
                "invoice_id": invoice_id,
                "amount": amount,
                "idempotency_key": f"{request_id}:reserve",
            },
        )

    def _unreserve(result):
        if result.get("id"):
            call_tool_sync("reverse_payment", {"reservation_id": result["id"]})

    def _post_ledger():
        return call_tool_sync(
            "post_ledger_entry",
            {
                "entry": {
                    "type": "payment",
                    "invoice_id": invoice_id,
                    "amount": amount,
                    "currency": action.get("currency", "INR"),
                    "description": f"Payment for {invoice_id}",
                },
                "idempotency_key": f"{request_id}:ledger",
            },
        )

    def _unpost(result):
        if result.get("id"):
            call_tool_sync("reverse_ledger_entry", {"entry_id": result["id"]})

    def _notify():
        if simulate_failure:
            raise RuntimeError("simulated notification failure")
        store = get_store()
        store.put(
            "notifications",
            f"{request_id}:notify",
            {
                "id": f"{request_id}:notify",
                "invoice_id": invoice_id,
                "amount": amount,
                "message": f"Payment of {amount:,.0f} for {invoice_id} released.",
            },
        )
        return {"notified": True}

    def _unnotify(_result):
        store = get_store()
        store.delete("notifications", f"{request_id}:notify")
        return {"undone": True}

    saga: SagaResult = run_saga(
        [
            SagaStep("reserve_payment", _reserve, _unreserve),
            SagaStep("post_ledger_entry", _post_ledger, _unpost),
            SagaStep("notify_finance", _notify, _unnotify),
        ]
    )
    duration = (time.perf_counter() - started) * 1000
    out: dict = {
        "saga_log": saga.log,
        "side_effects": state.get("side_effects", [])
        + [f"{request_id}:reserve", f"{request_id}:ledger"],
        "steps": state.get("steps", []) + [f"Saga: {'; '.join(saga.log)}"],
    }
    out.update(_trace(state, "execute_action", duration))
    if saga.ok:
        out["status"] = "completed"
        out["result"] = (
            (state.get("result") or "")
            + f"\n\nPayment released: {action.get('currency')} {amount:,.0f} "
            f"for {invoice_id} (approved by a human, saga completed)."
        )
    else:
        out["status"] = "failed"
        out["error"] = saga.error
        out["result"] = (state.get("result") or "") + (
            f"\n\nPayment FAILED at step '{saga.failed_step}': {saga.error}. "
            f"Compensations ran for: {', '.join(saga.compensated) or 'none'}."
        )
    emit_otel("execute_action", {"ok": saga.ok})
    return out


def finalize_node(state: dict) -> dict:
    started = time.perf_counter()
    status = state.get("status", "running")
    if state.get("approval") is False:
        status = "rejected"
    elif status in ("running", "awaiting_approval"):
        status = "completed"
    latency = (time.perf_counter() - started) * 1000
    tokens = state.get("tokens", 0)
    out = {
        "status": status,
        "latency_ms": round(
            (
                datetime.now(UTC) - datetime.fromisoformat(state["started_at"])
            ).total_seconds()
            * 1000,
            1,
        ),
        "cost_usd": cost_usd(tokens),
    }
    out.update(_trace(state, "finalize", latency))
    return out


def _route_from_router(state: dict) -> str:
    return state.get("intent", "lookup")


def _after_agent(state: dict) -> str:
    return "hitl_gate" if state.get("needs_approval") else "finalize"


def _after_gate(state: dict) -> str:
    return "execute_action" if state.get("approval") else "finalize"


def _wrap_agent(fn):
    """Wrap a domain agent so token counts accumulated on the state dict
    (which LangGraph does not persist from in-place mutation) are returned
    as a proper state update."""

    def wrapped(state: dict) -> dict:
        out = fn(state)
        out["tokens"] = state.get("tokens", 0)
        return out

    wrapped.__name__ = fn.__name__
    return wrapped


def build_graph(checkpointer=None):
    graph = StateGraph(WorkflowState)
    graph.add_node("router", router_node)
    graph.add_node("invoice_agent", _wrap_agent(invoice_agent))
    graph.add_node("report_agent", _wrap_agent(report_agent))
    graph.add_node("lookup_agent", _wrap_agent(lookup_agent))
    graph.add_node("policy_agent", _wrap_agent(policy_agent))
    graph.add_node("hitl_gate", hitl_gate)
    graph.add_node("execute_action", execute_action)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _route_from_router,
        {
            "invoice": "invoice_agent",
            "report": "report_agent",
            "lookup": "lookup_agent",
            "policy": "policy_agent",
        },
    )
    for agent_node in ("invoice_agent", "report_agent", "lookup_agent", "policy_agent"):
        graph.add_conditional_edges(
            agent_node, _after_agent, {"hitl_gate": "hitl_gate", "finalize": "finalize"}
        )
    graph.add_conditional_edges(
        "hitl_gate",
        _after_gate,
        {"execute_action": "execute_action", "finalize": "finalize"},
    )
    graph.add_edge("execute_action", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def get_checkpointer():
    """PostgresSaver when DATABASE_URL is set, else SQLite file, else memory."""
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    if config.DATABASE_URL:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            saver = PostgresSaver.from_conn_string(config.DATABASE_URL)
            saver.setup()
            _CHECKPOINTER = saver
            return _CHECKPOINTER
        except Exception as exc:  # noqa: BLE001 - Postgres is optional; fall back to SQLite
            print(f"[graph] PostgresSaver unavailable ({exc}); using SQLite.")
    try:
        conn = sqlite3.connect(config.CHECKPOINT_PATH, check_same_thread=False)
        _CHECKPOINTER = SqliteSaver(conn)
    except Exception:  # noqa: BLE001 - SQLite is optional; fall back to memory
        _CHECKPOINTER = MemorySaver()
    return _CHECKPOINTER


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph(get_checkpointer())
    return _GRAPH


def _record_run(state: dict) -> None:
    run = {
        "id": state["request_id"],
        "request": state.get("request"),
        "intent": state.get("intent"),
        "agent": state.get("agent"),
        "status": state.get("status"),
        "result": state.get("result"),
        "citations": state.get("citations", []),
        "steps": state.get("steps", []),
        "tool_calls": state.get("tool_calls", []),
        "trace": state.get("trace", []),
        "financial_action": state.get("financial_action"),
        "approval": state.get("approval"),
        "saga_log": state.get("saga_log", []),
        "error": state.get("error"),
        "tokens": state.get("tokens", 0),
        "latency_ms": state.get("latency_ms", 0),
        "cost_usd": state.get("cost_usd", 0),
        "started_at": state.get("started_at"),
        "finished_at": _now_iso(),
    }
    get_store().put("runs", run["id"], run)
    emit_langfuse(run)


def run_workflow(
    request: str,
    thread_id: str | None = None,
    checkpointer=None,
    record: bool = True,
    simulate_failure: bool = False,
) -> dict:
    """Run one workflow end to end. Returns the final state (which may
    carry __interrupt__ when it paused for human approval)."""
    request_id = thread_id or new_run_id()
    initial: WorkflowState = {
        "request_id": request_id,
        "request": request,
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
        "simulate_failure": simulate_failure,
    }
    graph = build_graph(checkpointer) if checkpointer is not None else get_graph()
    config_dict = {"configurable": {"thread_id": request_id}}
    with GRAPH_LOCK:
        result = graph.invoke(initial, config_dict)
    state = {k: v for k, v in result.items() if not k.startswith("__")}
    state["request_id"] = request_id
    if record:
        _record_run(state)
    return state


def resume_workflow(
    thread_id: str, approved: bool, checkpointer=None, record: bool = True
) -> dict:
    """Resume an interrupted run with a human decision."""
    graph = build_graph(checkpointer) if checkpointer is not None else get_graph()
    config_dict = {"configurable": {"thread_id": thread_id}}
    with GRAPH_LOCK:
        result = graph.invoke(Command(resume=approved), config_dict)
    state = {k: v for k, v in result.items() if not k.startswith("__")}
    state["request_id"] = thread_id
    if record:
        _record_run(state)
    return state
