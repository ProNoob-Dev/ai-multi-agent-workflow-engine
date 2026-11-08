"""Eval harness tests: metrics are computed from real runs."""

from app.eval import load_golden, run_eval


def test_eval_runs_and_reports(seeded):
    summary = run_eval(limit=5, verbose=False)
    assert summary["cases"] == 5
    assert 0 <= summary["routing_accuracy"] <= 1
    assert 0 <= summary["autonomous_resolution_rate"] <= 1
    assert summary["total_tokens"] > 0
    assert len(summary["rows"]) == 5


def test_eval_full_golden_set_is_perfect_on_routing(seeded):
    summary = run_eval(verbose=False)
    assert summary["cases"] == len(load_golden()) == 20
    assert summary["routing_accuracy"] == 1.0
    assert summary["agent_accuracy"] == 1.0
    assert summary["outcome_accuracy"] == 1.0
    # 17 autonomous / 3 need approval, by construction of the golden set.
    assert summary["autonomous_cases"] == 17
    assert summary["needs_approval_cases"] == 3
