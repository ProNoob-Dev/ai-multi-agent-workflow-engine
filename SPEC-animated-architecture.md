# SPEC — Animated architecture for the Multi-Agent Workflow Engine site

## What this is
Upgrade the EXISTING Pages site (`docs/index.html`) of
https://github.com/ProNoob-Dev/ai-multi-agent-workflow-engine with an animated,
recruiter-ready architecture explanation. No rebuild: the repo, the FastAPI
dashboard (`app/static/`), the API and the 34 tests stay as they are.

## Fact sheet (from the repo, nothing invented)
- One router classifies a request: `invoice`, `report`, `lookup`, `policy`.
- Four agents: InvoiceAgent, ReportAgent, DataLookupAgent, PolicyAgent.
- Every tool call goes through a FastMCP server (`/mcp`): `lookup_invoice`,
  `validate_invoice`, `search_policy`, `draft_report`, `list_vendors`,
  `reserve_payment`, `post_ledger_entry`, and more. Agents never touch data.
- Financial actions pause at a LangGraph `interrupt()` (HITL gate) until a human
  approves or rejects in the review queue. A rejection leaves zero side effects.
- A payment is a 3-step saga: reserve funds, post ledger entry, notify vendor.
  A failure runs compensations in reverse (reverse ledger, release reservation).
  Steps are idempotent; checkpoints (Postgres/SQLite) resume exactly once.
- Measured eval, 20-case golden set, mock provider, 8 Nov 2026: routing 100%,
  agent 100%, outcome 100%, autonomous resolution 85.0% (17/20), 3 cases need
  approval by design. Production at BDO: 88% across 100+ workflows — a
  different number, kept separate.
- Stack: Python, FastAPI, LangGraph, FastMCP, PostgreSQL/SQLite checkpoints,
  Redis (cache/sessions in the stack), Qdrant (optional policy RAG),
  OpenTelemetry + Langfuse tracing, Docker, GitHub Actions CI.

## User rules (binding)
1. No static boxes-and-arrows diagram. The animation IS the explanation:
   data moves and changes shape.
2. Live, playable workflow simulation on the Pages site:
   - a request enters as a moving particle;
   - the LangGraph router lights up and routes it to the right domain agent;
   - the agent calls MCP tools;
   - a HITL gate VISIBLY holds the flow for approval;
   - a failure triggers the compensating saga;
   - the Langfuse trace fills in.
   - Play + step-through controls. Agents light up only when active.
3. Scroll-triggered assembly of the architecture layers, each labelled with
   its tech and what it does. Hover any component: what it does and why.
4. Keep the existing dashboard working. Do not break existing tests.

## Scope
IN:
- New "Watch a workflow run" simulation section in `docs/index.html`
  (3 scenarios, Play/Step/Reset, particle flow, HITL approve/reject,
  saga failure path, live trace panel).
- New "Architecture, layer by layer" section (4 chapters, pinned frame,
  stack assembles as you scroll; hover explains each layer).
- Statement section "Money waits for a human." (letters-assemble moment).
- `docs/assets/sim.js` (simulation engine) + simulation CSS in
  `docs/assets/style.css`; kit moments copied under
  `docs/assets/moments/` (letters-assemble, line-carries-colour) + loader.
- README: recruiter-facing "Architecture" section + sim screenshot +
  screen recording (`docs/demo/architecture-sim.webm`).
- New screenshots of the animated site in `docs/screenshots/`.
- Tests: `tests/test_docs_site.py` (site invariants, JS parses, scenarios).
OUT (do not do):
- No recolor of the whole site, no hero rebuild, no dashboard changes,
  no API changes, no new dependencies, no backend behaviour change.

## Acceptance criteria
- [ ] `pytest -q` passes (34 existing + new docs-site tests).
- [ ] Simulation: all 3 scenarios run end to end in a headless browser;
  HITL holds until Approve/Reject; failure scenario compensates in reverse;
  trace rows fill in with step, tool, latency, tokens.
- [ ] Reduced motion: simulation jumps to final states, nothing animates;
  layers section shows finished stack.
- [ ] taste-skill gate: `GATE: PASS` (max 3 rounds). Copy-lint 0 FAIL.
- [ ] Real screenshots + screen recording in the repo; README updated.
- [ ] CI green after push; Pages site serves the new sections.

## Assumptions
- The existing deep-navy palette stays (live identity, shared with the
  dashboard); only the violet accent `#7c5cff` is swapped for the existing
  blue `#38bdf8` to honour taste-skill "never violet".
- System font stack stays (no new external dependency).
- The existing "How it works" SVG section stays; the simulation is added
  after it as its own section.
- Playwright is not installed as an npm package; drive the Playwright
  chromium via `puppeteer-core` if available, else via Chrome DevTools
  Protocol over `--remote-debugging-port` for screenshots/video
  (ffmpeg can assemble frames if needed).

## Tasks
1. RED: `tests/test_docs_site.py` — simulation section + scenarios + JS
   syntax checks (fails before the build).
2. Simulation markup + CSS (nodes, particle, trace panel, controls).
3. `docs/assets/sim.js` — engine: scenarios, play/step/reset, HITL hold,
   saga failure, trace fill, reduced-motion path.
4. Architecture layers section (line-carries-colour moment + stack SVG).
5. Statement section (letters-assemble moment) + moment loader wiring.
6. Accent swap (violet out), hero entrance (data-enter + CSS), figcaption
   removal (house rule 1), copy-lint fixes for new copy.
7. Headless verification of all 3 scenarios + screenshots (1440/390) +
   screen recording; README update.
8. Five-axis review, full test suite, gate to PASS, push.
