"""Observability: in-process run traces + optional OTel / Langfuse hooks.

Every run is recorded in the store (collection "runs") with its spans,
latency, token use and estimated cost. OpenTelemetry and Langfuse are
optional emitters — they activate only when their SDKs and keys are
present; the in-process trace is always the source of truth.
"""

import time
import uuid

from . import config


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def cost_usd(tokens: int) -> float:
    """Estimated cost (mock rate). Labelled as an estimate everywhere."""
    return round(tokens * config.MOCK_COST_PER_TOKEN_USD, 6)


class Span:
    def __init__(self, name: str):
        self.name = name
        self.started = time.perf_counter()
        self.ended: float | None = None

    def finish(self) -> dict:
        self.ended = time.perf_counter()
        return {
            "name": self.name,
            "duration_ms": round((self.ended - self.started) * 1000, 1),
        }


def emit_otel(span_name: str, attributes: dict) -> None:
    """Best-effort OpenTelemetry span. No-op when OTel is off/absent."""
    if not config.OTEL_ENABLED:
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("multi-agent-workflow-engine")
        with tracer.start_as_current_span(span_name) as span:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))
    except Exception:  # noqa: BLE001, S110 - OTel is optional; never break a run
        pass


def emit_langfuse(run: dict) -> None:
    """Best-effort Langfuse trace. No-op when keys/SDK are absent."""
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return
    try:
        from langfuse import Langfuse

        lf = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
        )
        lf.trace(
            name="workflow-run",
            input={"request": run.get("request")},
            output={"result": (run.get("result") or "")[:500]},
            metadata={
                "intent": run.get("intent"),
                "agent": run.get("agent"),
                "status": run.get("status"),
                "tokens": run.get("tokens"),
                "latency_ms": run.get("latency_ms"),
            },
        )
        lf.flush()
    except Exception:  # noqa: BLE001, S110 - Langfuse is optional; never break a run
        pass
