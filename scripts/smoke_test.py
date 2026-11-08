"""HTTP-only smoke test for the running server.

Used by CI after starting uvicorn: checks the health endpoint, the
dashboard page, one autonomous run end to end, and the metrics endpoint.
Run: python scripts/smoke_test.py [--base-url http://127.0.0.1:8000]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def get(base: str, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def post_json(base: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    status, body = get(base, "/api/health")
    assert status == 200, f"health: HTTP {status}"
    assert json.loads(body)["status"] == "ok", "health: status not ok"
    print("health: ok")

    status, body = get(base, "/")
    assert status == 200, f"dashboard: HTTP {status}"
    assert "Multi-Agent Workflow Engine" in body, "dashboard: title missing"
    print("dashboard: ok")

    status, run = post_json(
        base, "/api/runs", {"request": "What is the status of invoice INV-1001?"}
    )
    assert status == 200, f"create run: HTTP {status}"
    assert run["status"] == "completed", f"run not completed: {run['status']}"
    assert "INV-1001" in run["result"], "run result missing invoice id"
    print(f"run: ok ({run['id']}, agent={run['agent']})")

    status, body = get(base, "/api/metrics")
    assert status == 200, f"metrics: HTTP {status}"
    metrics = json.loads(body)
    assert metrics["total_runs"] >= 1, "metrics: no runs recorded"
    print("metrics: ok")

    print("smoke test: ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
