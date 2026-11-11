"""Docs-site invariants for the animated architecture upgrade.

The Pages site is static HTML/JS, so these tests read the files and assert
the structure the simulation, the layers section and the moments need.
They do not run a browser; the browser check lives in scripts/verify_sim.py.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HTML = (DOCS / "index.html").read_text()
CSS = (DOCS / "assets" / "style.css").read_text()
SIM_JS = DOCS / "assets" / "sim.js"


def test_simulation_section_present():
    assert 'id="sim"' in HTML
    assert "Watch a workflow run" in HTML
    for control in ("sim-play", "sim-step", "sim-reset"):
        assert f'id="{control}"' in HTML, f"missing control {control}"
    assert 'id="sim-trace"' in HTML
    assert 'id="sim-narration"' in HTML


def test_simulation_has_three_scenarios():
    # Scenario buttons carry the real requests the repo's golden set uses.
    assert 'data-scenario="validate"' in HTML
    assert 'data-scenario="approve"' in HTML
    assert 'data-scenario="approve-fail"' in HTML
    assert "INV-1001" in HTML
    assert "INV-1003" in HTML


def test_simulation_nodes_present():
    for node in ("sim-node-request", "sim-node-router", "sim-node-agents",
                 "sim-node-mcp", "sim-node-hitl", "sim-node-saga",
                 "sim-node-result"):
        assert f'id="{node}"' in HTML, f"missing node {node}"
    # All four agents are named; only the active one lights up at runtime.
    for agent in ("InvoiceAgent", "ReportAgent", "DataLookupAgent",
                  "PolicyAgent"):
        assert agent in HTML
    assert 'id="sim-particle"' in HTML
    assert 'id="sim-approve"' in HTML
    assert 'id="sim-reject"' in HTML


def test_sim_js_exists_and_parses():
    assert SIM_JS.exists(), "docs/assets/sim.js missing"
    proc = subprocess.run(
        ["node", "--check", str(SIM_JS)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_sim_js_defines_scenarios_and_steps():
    src = SIM_JS.read_text()
    for scenario in ("validate", "approve", "approve-fail"):
        assert scenario in src, f"scenario {scenario} missing from sim.js"
    for term in ("HITL", "saga", "compensat", "trace",
                 "prefers-reduced-motion"):
        assert term in src, f"{term} missing from sim.js"


def test_layers_section_present():
    assert 'id="layers"' in HTML
    assert 'data-moment="line-carries-colour"' in HTML
    for tech in ("FastAPI", "LangGraph", "MCP", "PostgreSQL", "Langfuse"):
        assert tech in HTML, f"{tech} missing from layers section"


def test_statement_section_present():
    assert 'data-moment="letters-assemble"' in HTML
    assert "Money waits for a human" in HTML


def test_moments_loader_wired():
    assert 'assets/moments/moments.js' in HTML
    assert (DOCS / "assets" / "moments" / "moments.js").exists()
    assert (DOCS / "assets" / "moments" / "lib.js").exists()
    for moment in ("letters-assemble", "line-carries-colour"):
        assert (DOCS / "assets" / "moments" / moment / "moment.js").exists()
        assert (DOCS / "assets" / "moments" / moment / "moment.css").exists()


def test_no_violet_accent():
    # taste-skill: never violet in the page's own design.
    assert "#7c5cff" not in CSS.lower()
    assert "#7c5cff" not in HTML.lower()


def test_hero_entrance_marked():
    assert 'data-enter' in HTML


def test_moments_meta_valid():
    for moment in ("letters-assemble", "line-carries-colour"):
        meta = json.loads(
            (DOCS / "assets" / "moments" / moment / "meta.json").read_text())
        assert meta["id"] == moment
        assert "software" in meta["pages"]


def test_dashboard_untouched_by_docs_upgrade():
    # The app still serves its own static dashboard; the upgrade is docs-only.
    assert (ROOT / "app" / "static" / "index.html").exists()
    assert (ROOT / "app" / "static" / "app.js").exists()
