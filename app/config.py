"""Configuration for the Multi-Agent Workflow Engine.

All settings come from environment variables with safe defaults.
No secrets are ever hardcoded here.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Storage ---
# JSON-file store is the default. Set DATABASE_URL (Postgres) to switch.
STORE_PATH = os.environ.get("STORE_PATH", str(BASE_DIR / "data" / "store.json"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
CHECKPOINT_PATH = os.environ.get(
    "CHECKPOINT_PATH", str(BASE_DIR / "data" / "checkpoints.db")
)

# --- Vector search ---
# Qdrant is used when QDRANT_URL is set; otherwise an in-memory store.
QDRANT_URL = os.environ.get("QDRANT_URL", "")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")

# --- LLM ---
# Mock provider is the default. Azure OpenAI activates when all three are set.
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

# --- Observability (all optional) ---
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
OTEL_ENABLED = os.environ.get("OTEL_ENABLED", "false").lower() == "true"

# --- App ---
APP_TITLE = "AI Multi-Agent Workflow Engine"
APP_VERSION = "1.0.0"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# Estimated cost model for the mock provider (USD per token).
# This is an estimate for display only, not a real bill.
MOCK_COST_PER_TOKEN_USD = 0.15 / 1_000_000

# Financial actions above this amount always need human approval,
# even if a request does not explicitly ask for payment.
FINANCIAL_APPROVAL_THRESHOLD = float(
    os.environ.get("FINANCIAL_APPROVAL_THRESHOLD", "50000")
)
CURRENCY = "INR"
