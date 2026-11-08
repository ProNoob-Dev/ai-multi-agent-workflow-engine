# Contributing

Thanks for your interest in contributing to the Multi-Agent Workflow Engine.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the app

```bash
uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000> for the dashboard.

## Running the eval

```bash
python -m app.eval
```

The eval runs a golden set of 20 labelled workflows and writes
`data/eval_results.json`. If you change routing, agents, or the HITL rules,
re-run the eval and update the results table in `README.md` with the new
measured numbers — never write a number you did not measure.

## Tests and lint

```bash
pytest -q
ruff check app tests scripts
ruff format app tests scripts
```

All three must pass before a pull request is opened. New behaviour needs a
test: routing changes go in `tests/test_routing.py`, HITL changes in
`tests/test_hitl.py`, saga changes in `tests/test_saga.py`, checkpoint
changes in `tests/test_checkpoint.py`, MCP tool changes in
`tests/test_mcp_tools.py`, and API changes in `tests/test_api.py`.

## Ground rules

- **No financial action without a human approval.** The HITL gate in
  `app/graph.py` is load-bearing: any change that lets a payment, credit, or
  transfer execute without `approval is True` will fail the tests. Keep it
  that way.
- **Mock LLM by default.** The deterministic mock provider is what makes the
  tests and the eval reproducible. Azure OpenAI is an opt-in env switch, and
  no credentials are ever committed.
- **No invented numbers.** Every performance figure in the README or the docs
  site must come from a test or eval run you actually performed. If a path is
  untested (for example Docker on a machine without Docker), say so.
- Keep the dashboard and the docs site in the same deep-navy AI look, and
  keep the README honest about limitations.
