"""FastAPI app: dashboard + REST API + MCP endpoint.

Dashboard at / (static files under app/static).
MCP tools at /mcp (FastMCP streamable HTTP).
REST API under /api.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .graph import resume_workflow, run_workflow
from .llm import get_llm
from .mcp_server import mcp
from .seed import seed_all
from .store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_all()
    yield


app = FastAPI(title=config.APP_TITLE, version=config.APP_VERSION, lifespan=lifespan)


class RunRequest(BaseModel):
    request: str
    simulate_failure: bool = False


def _public_run(run: dict) -> dict:
    return {
        "id": run.get("id"),
        "request": run.get("request"),
        "intent": run.get("intent"),
        "agent": run.get("agent"),
        "status": run.get("status"),
        "result": run.get("result"),
        "citations": run.get("citations", []),
        "steps": run.get("steps", []),
        "tool_calls": run.get("tool_calls", []),
        "trace": run.get("trace", []),
        "financial_action": run.get("financial_action"),
        "approval": run.get("approval"),
        "saga_log": run.get("saga_log", []),
        "error": run.get("error"),
        "tokens": run.get("tokens", 0),
        "latency_ms": run.get("latency_ms", 0),
        "cost_usd": run.get("cost_usd", 0),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    store = get_store()
    return {
        "status": "ok",
        "app": config.APP_TITLE,
        "version": config.APP_VERSION,
        "llm_provider": get_llm().name,
        "store": "postgres" if config.DATABASE_URL else "json",
        "runs_recorded": len(store.list("runs")),
        "approvals_pending": len(
            [r for _, r in store.list("runs") if r.get("status") == "awaiting_approval"]
        ),
    }


@app.post("/api/runs")
def create_run(payload: RunRequest):
    if not payload.request.strip():
        raise HTTPException(status_code=400, detail="request must not be empty")
    state = run_workflow(
        payload.request.strip(), simulate_failure=payload.simulate_failure
    )
    return _public_run(
        {
            **state,
            "id": state["request_id"],
            "finished_at": state.get("finished_at"),
        }
    )


@app.get("/api/runs")
def list_runs(limit: int = 50):
    store = get_store()
    runs = [v for _, v in store.list("runs")]
    runs.sort(key=lambda r: r.get("finished_at", ""), reverse=True)
    return [_public_run(r) for r in runs[:limit]]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = get_store().get("runs", run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _public_run(run)


@app.get("/api/approvals")
def list_approvals():
    store = get_store()
    pending = [
        r for _, r in store.list("runs") if r.get("status") == "awaiting_approval"
    ]
    pending.sort(key=lambda r: r.get("finished_at", ""), reverse=True)
    return [_public_run(r) for r in pending]


@app.post("/api/approvals/{run_id}/approve")
def approve(run_id: str):
    run = get_store().get("runs", run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.get("status") != "awaiting_approval":
        raise HTTPException(status_code=400, detail="run is not awaiting approval")
    state = resume_workflow(run_id, True)
    return _public_run({**state, "id": run_id})


@app.post("/api/approvals/{run_id}/reject")
def reject(run_id: str):
    run = get_store().get("runs", run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.get("status") != "awaiting_approval":
        raise HTTPException(status_code=400, detail="run is not awaiting approval")
    state = resume_workflow(run_id, False)
    return _public_run({**state, "id": run_id})


@app.get("/api/metrics")
def metrics():
    store = get_store()
    runs = [v for _, v in store.list("runs")]
    completed = [r for r in runs if r.get("status") == "completed"]
    awaiting = [r for r in runs if r.get("status") == "awaiting_approval"]
    autonomous = len(completed)  # completed without an approval step
    total = len(runs)
    return {
        "total_runs": total,
        "completed": len(completed),
        "awaiting_approval": len(awaiting),
        "rejected": len([r for r in runs if r.get("status") == "rejected"]),
        "failed": len([r for r in runs if r.get("status") == "failed"]),
        "autonomous_rate": round(autonomous / total, 4) if total else 0,
        "avg_latency_ms": round(sum(r.get("latency_ms", 0) for r in runs) / total, 1)
        if total
        else 0,
        "total_tokens": sum(r.get("tokens", 0) for r in runs),
        "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in runs), 6),
        "llm_provider": get_llm().name,
    }


@app.get("/api/eval")
def latest_eval():
    path = BASE_DIR / "data" / "eval_results.json"
    if not path.exists():
        return {"error": "No eval results yet. Run: python -m app.eval"}
    return json.loads(path.read_text())


@app.get("/api/seed")
def seed_info():
    return seed_all()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/mcp", mcp.http_app(path="/"), name="mcp")
