"""Eval harness: run the golden set through the graph and measure.

Metrics are computed from real runs — nothing here is hardcoded.
The autonomous-resolution rate is the share of golden cases that finish
without a human approval step. Run with:  python -m app.eval
"""

import json
import time
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from .graph import run_workflow
from .seed import seed_all

BASE_DIR = Path(__file__).resolve().parent.parent
GOLDEN_PATH = BASE_DIR / "data" / "golden_set.json"
RESULTS_PATH = BASE_DIR / "data" / "eval_results.json"


def load_golden() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text())


def outcome_of(state: dict) -> str:
    if state.get("status") == "awaiting_approval" or state.get("needs_approval"):
        return "needs_approval"
    return "autonomous"


def run_eval(limit: int | None = None, verbose: bool = True) -> dict:
    seed_all()
    cases = load_golden()
    if limit:
        cases = cases[:limit]
    checkpointer = MemorySaver()
    rows: list[dict] = []
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        state = run_workflow(
            case["request"],
            thread_id=f"eval-{case['id']}",
            checkpointer=checkpointer,
            record=False,
        )
        outcome = outcome_of(state)
        rows.append(
            {
                "id": case["id"],
                "request": case["request"],
                "expected_intent": case["expected_intent"],
                "predicted_intent": state.get("intent"),
                "expected_agent": case["expected_agent"],
                "predicted_agent": state.get("agent"),
                "expected_outcome": case["expected_outcome"],
                "outcome": outcome,
                "status": state.get("status"),
                "intent_ok": state.get("intent") == case["expected_intent"],
                "agent_ok": state.get("agent") == case["expected_agent"],
                "outcome_ok": outcome == case["expected_outcome"],
                "latency_ms": state.get("latency_ms", 0),
                "tokens": state.get("tokens", 0),
            }
        )
        if verbose:
            mark = "OK " if rows[-1]["outcome_ok"] and rows[-1]["intent_ok"] else "MISS"
            print(
                f"[{mark}] {case['id']} {state.get('intent')} -> "
                f"{state.get('agent')} ({outcome}) "
                f"{round(time.perf_counter() - case_started, 2)}s"
            )
    total = len(rows)
    intent_ok = sum(r["intent_ok"] for r in rows)
    agent_ok = sum(r["agent_ok"] for r in rows)
    outcome_ok = sum(r["outcome_ok"] for r in rows)
    autonomous = sum(1 for r in rows if r["outcome"] == "autonomous")
    total_tokens = sum(r["tokens"] for r in rows)
    avg_latency = round(sum(r["latency_ms"] for r in rows) / max(total, 1), 1)
    summary = {
        "cases": total,
        "routing_accuracy": round(intent_ok / total, 4) if total else 0,
        "agent_accuracy": round(agent_ok / total, 4) if total else 0,
        "outcome_accuracy": round(outcome_ok / total, 4) if total else 0,
        "autonomous_resolution_rate": round(autonomous / total, 4) if total else 0,
        "autonomous_cases": autonomous,
        "needs_approval_cases": total - autonomous,
        "avg_latency_ms": avg_latency,
        "total_tokens": total_tokens,
        "total_seconds": round(time.perf_counter() - started, 1),
        "rows": rows,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2))
    if verbose:
        print()
        print(f"Cases: {total}")
        print(f"Routing accuracy: {summary['routing_accuracy']:.1%}")
        print(f"Agent accuracy: {summary['agent_accuracy']:.1%}")
        print(f"Outcome accuracy: {summary['outcome_accuracy']:.1%}")
        print(
            f"Autonomous resolution rate: {summary['autonomous_resolution_rate']:.1%} "
            f"({autonomous}/{total})"
        )
        print(f"Avg latency: {avg_latency} ms | Total tokens: {total_tokens}")
        print(f"Results written to {RESULTS_PATH}")
    return summary


def markdown_table(summary: dict) -> str:
    lines = [
        "| Metric | Value |",
        "|---|---|",
        f"| Golden cases | {summary['cases']} |",
        f"| Routing accuracy | {summary['routing_accuracy']:.1%} |",
        f"| Agent accuracy | {summary['agent_accuracy']:.1%} |",
        f"| Outcome accuracy | {summary['outcome_accuracy']:.1%} |",
        (
            f"| Autonomous resolution rate | {summary['autonomous_resolution_rate']:.1%} "
            f"({summary['autonomous_cases']}/{summary['cases']}) |"
        ),
        f"| Cases needing human approval | {summary['needs_approval_cases']} |",
        f"| Avg latency per case | {summary['avg_latency_ms']} ms |",
        f"| Total tokens (mock provider) | {summary['total_tokens']} |",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    summary = run_eval()
    print()
    print(markdown_table(summary))
