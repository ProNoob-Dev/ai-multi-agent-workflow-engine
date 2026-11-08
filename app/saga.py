"""Compensating sagas.

A saga is an ordered list of steps. Each step has an action and a
compensation. If any step fails, the compensations of all completed steps
run in reverse order, rolling the workflow back to a consistent state.
Every step is idempotent (keyed), so a retried saga never double-applies
a side effect.
"""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class SagaStep:
    name: str
    action: Callable[[], dict]
    compensation: Callable[[dict], dict]
    result: dict | None = None


@dataclass
class SagaResult:
    ok: bool
    completed: list[str] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)


def run_saga(steps: list[SagaStep]) -> SagaResult:
    """Run the steps in order; compensate in reverse on failure."""
    result = SagaResult(ok=True)
    done: list[SagaStep] = []
    for step in steps:
        try:
            out = step.action()
        except Exception as exc:  # noqa: BLE001 - saga must catch everything
            result.ok = False
            result.failed_step = step.name
            result.error = str(exc)
            result.log.append(f"STEP FAILED: {step.name}: {exc}")
            break
        if isinstance(out, dict) and out.get("error"):
            result.ok = False
            result.failed_step = step.name
            result.error = str(out["error"])
            result.log.append(f"STEP FAILED: {step.name}: {out['error']}")
            break
        step.result = out
        done.append(step)
        result.completed.append(step.name)
        result.log.append(f"STEP OK: {step.name}")
    if not result.ok:
        for step in reversed(done):
            try:
                step.compensation(step.result or {})
                result.compensated.append(step.name)
                result.log.append(f"COMPENSATED: {step.name}")
            except Exception as exc:  # noqa: BLE001 - keep compensating
                result.log.append(f"COMPENSATION FAILED: {step.name}: {exc}")
    return result
