"""MCP tool server (FastMCP, streamable HTTP).

All tool calls in this system go through this server. The LangGraph
agents never touch the business logic directly — they call tools here,
and this server delegates to app.services.

Run standalone for external clients:
    python -m app.mcp_server        # serves on http://127.0.0.1:8001/mcp
Inside the app it is mounted at /mcp (see app/main.py).
"""

import asyncio
import json

from fastmcp import Client, FastMCP

from . import services

mcp = FastMCP("workflow-tools")


@mcp.tool
def list_vendors() -> list:
    """List all vendors on the approved vendor list."""
    return services.list_vendors()


@mcp.tool
def lookup_vendor(query: str) -> dict:
    """Look up a vendor by name or vendor ID."""
    vendor = services.get_vendor(query)
    return vendor or {"error": f"Vendor not found for query: {query}"}


@mcp.tool
def list_invoices(status: str = "") -> list:
    """List seeded invoices, optionally filtered by status
    (pending / approved / paid)."""
    return services.list_invoices(status or None)


@mcp.tool
def lookup_invoice(invoice_id: str) -> dict:
    """Fetch one invoice by ID (e.g. INV-1001)."""
    inv = services.get_invoice(invoice_id)
    return inv or {"error": f"Invoice {invoice_id} not found."}


@mcp.tool
def validate_invoice(invoice_id: str) -> dict:
    """Validate an invoice: PO match, duplicate check, due date and the
    human-approval threshold."""
    return services.validate_invoice(invoice_id)


@mcp.tool
def search_policy(query: str, top_k: int = 3) -> list:
    """Search the company policy documents (RAG) and return cited excerpts."""
    return services.search_policies(query, top_k=top_k)


@mcp.tool
def draft_report(report_type: str, period: str) -> dict:
    """Draft a business report from the ledger/invoice figures."""
    return services.draft_report(report_type, period)


@mcp.tool
def reserve_payment(invoice_id: str, amount: float, idempotency_key: str) -> dict:
    """Reserve money for a payment. Idempotent on idempotency_key."""
    return services.reserve_payment(invoice_id, amount, idempotency_key)


@mcp.tool
def reverse_payment(reservation_id: str) -> dict:
    """Reverse (compensate) a payment reservation."""
    return services.reverse_payment(reservation_id)


@mcp.tool
def post_ledger_entry(entry: dict, idempotency_key: str) -> dict:
    """Post a ledger entry. Idempotent on idempotency_key."""
    return services.post_ledger_entry(entry, idempotency_key)


@mcp.tool
def reverse_ledger_entry(entry_id: str) -> dict:
    """Reverse (compensate) a ledger entry."""
    return services.reverse_ledger_entry(entry_id)


@mcp.tool
def get_ledger() -> list:
    """List all ledger entries."""
    return services.ledger_entries()


def _normalize(value):
    """Normalise any MCP tool payload to a dict.

    FastMCP returns tool results in several shapes depending on the tool:
    a dict, a list, or {"result": <value>}. Callers always get a dict;
    list payloads arrive under the "items" key.
    """
    if isinstance(value, dict):
        if set(value.keys()) == {"result"}:
            inner = value["result"]
            return {"items": inner} if isinstance(inner, list) else {"result": inner}
        return value
    if isinstance(value, list):
        return {"items": value}
    if value is None:
        return {}
    return {"result": value}


def call_tool_sync(name: str, arguments: dict) -> dict:
    """Call an MCP tool synchronously via an in-memory client.

    The agents are synchronous LangGraph nodes, so each tool call opens a
    short-lived in-process MCP client session. The tool still executes
    inside the MCP server layer — the agent never calls services directly.
    """

    async def _call():
        async with Client(mcp) as client:
            result = await client.call_tool(name, arguments)
            if result.data is not None:
                return _normalize(result.data)
            # Fall back to the text payload.
            texts = [c.text for c in result.content if hasattr(c, "text")]
            if not texts:
                return {}
            try:
                return _normalize(json.loads(texts[0]))
            except ValueError:
                return {"result": texts[0]}

    return asyncio.run(_call())


if __name__ == "__main__":
    # Standalone MCP server on streamable HTTP for external clients.
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount

    starlette_app = Starlette(routes=[Mount("/", app=mcp.http_app(path="/mcp"))])
    uvicorn.run(starlette_app, host="127.0.0.1", port=8001)
