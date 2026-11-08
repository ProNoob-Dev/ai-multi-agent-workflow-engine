"""API tests: health, run creation, approval flow, metrics, eval."""

from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def test_health(seeded):
    with _client() as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "mock"


def test_create_lookup_run(seeded):
    with _client() as client:
        resp = client.post(
            "/api/runs", json={"request": "What is the status of invoice INV-1001?"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["agent"] == "DataLookupAgent"
    assert "INV-1001" in body["result"]
    assert body["id"]


def test_create_run_empty_request_rejected(seeded):
    with _client() as client:
        resp = client.post("/api/runs", json={"request": "   "})
    assert resp.status_code == 400


def test_approval_flow_via_api(seeded):
    with _client() as client:
        created = client.post(
            "/api/runs", json={"request": "Approve payment for invoice INV-1003"}
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        assert created.json()["status"] == "awaiting_approval"

        pending = client.get("/api/approvals")
        assert any(r["id"] == run_id for r in pending.json())

        approved = client.post(f"/api/approvals/{run_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert approved.json()["approval"] is True

        # Approving again must fail: the run is no longer awaiting approval.
        again = client.post(f"/api/approvals/{run_id}/approve")
        assert again.status_code == 400


def test_reject_flow_via_api(seeded):
    with _client() as client:
        created = client.post(
            "/api/runs",
            json={"request": "Pay invoice INV-1004 to Acme Office Supplies"},
        )
        run_id = created.json()["id"]
        rejected = client.post(f"/api/approvals/{run_id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"


def test_approve_unknown_run_404(seeded):
    with _client() as client:
        resp = client.post("/api/approvals/does-not-exist/approve")
    assert resp.status_code == 404


def test_metrics_endpoint(seeded):
    with _client() as client:
        client.post(
            "/api/runs", json={"request": "What is the status of invoice INV-1001?"}
        )
        resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] >= 1
    assert body["completed"] >= 1
    assert 0 <= body["autonomous_rate"] <= 1


def test_eval_endpoint_returns_measured_results(seeded):
    with _client() as client:
        resp = client.get("/api/eval")
        body = resp.json()
        if "error" in body:
            # Fresh checkout: run the eval once, then re-check.
            from app.eval import run_eval

            run_eval(verbose=False)
            body = client.get("/api/eval").json()
    assert resp.status_code == 200
    assert body["cases"] == 20
    assert body["routing_accuracy"] == 1.0
