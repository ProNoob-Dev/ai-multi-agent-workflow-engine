"""Router + domain agents.

The Router is a deterministic keyword classifier (no model call), so
routing is identical on every run and fully testable. The four domain
agents do their work by calling tools on the MCP server — they never
touch the business logic directly.
"""

import re
import time

from .llm import estimate_tokens
from .mcp_server import call_tool_sync
from .services import INVOICE_RE

INTENTS = ("invoice", "report", "lookup", "policy")
AGENT_FOR_INTENT = {
    "invoice": "InvoiceAgent",
    "report": "ReportAgent",
    "lookup": "DataLookupAgent",
    "policy": "PolicyAgent",
}


def _has(text: str, *words: str) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _word(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text.lower()) for w in words)


def classify_intent(request: str) -> str:
    """Ordered rule-based routing. Checked against the 20-case golden set."""
    text = request.lower()
    # 1. Explicit payment actions.
    if (
        _word(text, "pay")
        or "approve payment" in text
        or "release payment" in text
        or "make payment" in text
        or "process payment" in text
    ):
        return "invoice"
    # 2. Reports.
    if _word(text, "report") or "summar" in text:
        return "report"
    # 3. Policy / handbook questions.
    if _has(
        text,
        "policy",
        "leave",
        "reimburse",
        "travel",
        "hotel",
        "carry forward",
        "allowed",
        "guideline",
        "handbook",
        "threshold",
        "share",
    ):
        return "policy"
    # 4. Invoice validation signals.
    if _has(text, "validate", "validation", "duplicate", "overdue"):
        return "invoice"
    # 5. Data lookup signals.
    if _has(
        text,
        "status",
        "how much",
        "owe",
        "list",
        "total",
        "find",
        "show",
        "balance",
        "where",
    ):
        return "lookup"
    # 6. Any invoice mention falls back to the invoice agent.
    if "invoice" in text:
        return "invoice"
    return "lookup"


def wants_payment(request: str) -> bool:
    text = request.lower()
    return bool(
        _word(text, "pay")
        or "approve payment" in text
        or "release payment" in text
        or "make payment" in text
        or "process payment" in text
    )


def _tool_call(state: dict, name: str, arguments: dict) -> dict:
    started = time.perf_counter()
    result = call_tool_sync(name, arguments)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    state["tool_calls"] = state.get("tool_calls", []) + [
        {"tool": name, "arguments": arguments, "duration_ms": duration_ms}
    ]
    state["steps"] = state.get("steps", []) + [f"Called MCP tool {name}"]
    return result


def _tokens(state: dict, text: str) -> int:
    n = estimate_tokens(text)
    state["tokens"] = state.get("tokens", 0) + n
    return n


# --- Domain agents (LangGraph node functions) ---


def invoice_agent(state: dict) -> dict:
    request = state["request"]
    match = INVOICE_RE.search(request)
    if not match:
        return {
            "agent": "InvoiceAgent",
            "result": (
                "I need an invoice ID to work with (for example INV-1001). "
                "Please resend the request with the invoice number."
            ),
            "status": "completed",
            "steps": state.get("steps", []) + ["No invoice ID found in request"],
        }
    invoice_id = match.group(0).upper()
    validation = _tool_call(state, "validate_invoice", {"invoice_id": invoice_id})
    _tokens(state, str(validation))
    lines = [f"Invoice {invoice_id} validation:"]
    lines += [f"- {c}" for c in validation.get("checks", [])]
    lines += [f"- ISSUE: {i}" for i in validation.get("issues", [])]
    if validation.get("valid") is False and validation.get("issues"):
        return {
            "agent": "InvoiceAgent",
            "result": "\n".join(lines),
            "status": "completed",
            "needs_approval": False,
            "steps": state.get("steps", [])
            + [f"Validated {invoice_id}: blocked by issues"],
        }
    if wants_payment(request):
        action = {
            "type": "approve_payment",
            "invoice_id": invoice_id,
            "amount": validation.get("amount"),
            "currency": validation.get("currency", "INR"),
            "vendor_id": validation.get("vendor_id"),
        }
        return {
            "agent": "InvoiceAgent",
            "result": "\n".join(lines)
            + "\nPayment is proposed and is waiting for human approval.",
            "status": "awaiting_approval",
            "needs_approval": True,
            "financial_action": action,
            "steps": state.get("steps", [])
            + [
                (
                    f"Proposed payment of {action['currency']} "
                    f"{action['amount']:,.0f} for {invoice_id} — needs approval"
                )
            ],
        }
    return {
        "agent": "InvoiceAgent",
        "result": "\n".join(lines),
        "status": "completed",
        "needs_approval": False,
        "steps": state.get("steps", []) + [f"Validated {invoice_id}"],
    }


def report_agent(state: dict) -> dict:
    request = state["request"]
    text = request.lower()
    if "quarterly" in text:
        report_type, period = "Quarterly vendor spend report", "this quarter"
    elif "overdue" in text:
        report_type, period = "Overdue invoices report", "as of today"
    elif "approved" in text:
        report_type, period = "Approved payments report", "this month"
    else:
        report_type, period = "Monthly spend report", "this month"
    draft = _tool_call(
        state, "draft_report", {"report_type": report_type, "period": period}
    )
    _tokens(state, str(draft))
    figures = draft.get("figures", {})
    summary = (
        f"{report_type} ({period}): {figures.get('total_invoices', 0)} invoices, "
        f"INR {figures.get('pending_total_inr', 0):,.0f} pending, "
        f"INR {figures.get('approved_total_inr', 0):,.0f} approved, "
        f"INR {figures.get('paid_total_inr', 0):,.0f} paid, "
        f"{figures.get('overdue_count', 0)} overdue."
    )
    return {
        "agent": "ReportAgent",
        "result": draft.get("text", "") + "\n\n" + summary,
        "status": "completed",
        "needs_approval": False,
        "steps": state.get("steps", []) + [f"Drafted {report_type}"],
    }


def lookup_agent(state: dict) -> dict:
    request = state["request"]
    text = request.lower()
    match = INVOICE_RE.search(request)
    if match:
        inv = _tool_call(
            state, "lookup_invoice", {"invoice_id": match.group(0).upper()}
        )
        _tokens(state, str(inv))
        if inv.get("error"):
            return {
                "agent": "DataLookupAgent",
                "result": inv["error"],
                "status": "completed",
                "needs_approval": False,
                "steps": state.get("steps", []) + ["Invoice lookup failed"],
            }
        result = (
            f"Invoice {inv['id']}: {inv['description']}, "
            f"{inv['currency']} {inv['amount']:,.0f}, status {inv['status']}, "
            f"due {inv['due_date']}, vendor {inv['vendor_id']}."
        )
        return {
            "agent": "DataLookupAgent",
            "result": result,
            "citations": [inv["id"]],
            "status": "completed",
            "needs_approval": False,
            "steps": state.get("steps", []) + [f"Looked up {inv['id']}"],
        }
    if "pending" in text or "list" in text:
        items = _tool_call(state, "list_invoices", {"status": "pending"})
        _tokens(state, str(items))
        rows = items.get("items", []) if isinstance(items, dict) else items
        lines = [f"Pending invoices ({len(rows)}):"]
        for inv in rows:
            lines.append(
                f"- {inv['id']}: {inv['currency']} {inv['amount']:,.0f} "
                f"({inv['vendor_id']}, due {inv['due_date']})"
            )
        return {
            "agent": "DataLookupAgent",
            "result": "\n".join(lines),
            "citations": [inv["id"] for inv in rows],
            "status": "completed",
            "needs_approval": False,
            "steps": state.get("steps", []) + ["Listed pending invoices"],
        }
    if "vendor" in text or "how much" in text or "owe" in text or "total" in text:
        items = _tool_call(state, "list_invoices", {})
        _tokens(state, str(items))
        rows = items.get("items", []) if isinstance(items, dict) else items
        by_vendor: dict[str, float] = {}
        for inv in rows:
            if inv["status"] == "pending":
                by_vendor[inv["vendor_id"]] = (
                    by_vendor.get(inv["vendor_id"], 0) + inv["amount"]
                )
        vendors = _tool_call(state, "list_vendors", {})
        _tokens(state, str(vendors))
        rows_v = vendors.get("items", []) if isinstance(vendors, dict) else vendors
        matched = [v for v in rows_v if v["name"].lower() in text]
        vendor_name = matched[0] if matched else None
        if vendor_name:
            total = by_vendor.get(vendor_name["id"], 0)
            result = (
                f"{vendor_name['name']}: payment terms {vendor_name['payment_terms']}, "
                f"pending amount INR {total:,.0f}."
            )
            return {
                "agent": "DataLookupAgent",
                "result": result,
                "citations": [vendor_name["id"]],
                "status": "completed",
                "needs_approval": False,
                "steps": state.get("steps", []) + ["Looked up vendor"],
            }
        total_pending = sum(by_vendor.values())
        return {
            "agent": "DataLookupAgent",
            "result": f"Total pending across all vendors: INR {total_pending:,.0f}.",
            "status": "completed",
            "needs_approval": False,
            "steps": state.get("steps", []) + ["Summed pending invoices"],
        }
    items = _tool_call(state, "list_invoices", {})
    _tokens(state, str(items))
    rows = items.get("items", []) if isinstance(items, dict) else items
    return {
        "agent": "DataLookupAgent",
        "result": f"There are {len(rows)} invoices in the system "
        f"({sum(1 for r in rows if r['status'] == 'pending')} pending).",
        "status": "completed",
        "needs_approval": False,
        "steps": state.get("steps", []) + ["Listed invoices"],
    }


def policy_agent(state: dict) -> dict:
    request = state["request"]
    hits = _tool_call(state, "search_policy", {"query": request, "top_k": 3})
    _tokens(state, str(hits))
    items = hits.get("items", []) if isinstance(hits, dict) else hits
    if not items:
        return {
            "agent": "PolicyAgent",
            "result": "No matching policy found for that question.",
            "status": "completed",
            "needs_approval": False,
            "steps": state.get("steps", []) + ["Policy search returned nothing"],
        }
    lines = ["Based on company policy:"]
    citations = []
    for hit in items:
        lines.append(f"- {hit['title']} ({hit['section']}): {hit['excerpt']}")
        citations.append(f"{hit['title']} — {hit['section']}")
    return {
        "agent": "PolicyAgent",
        "result": "\n".join(lines),
        "citations": citations,
        "status": "completed",
        "needs_approval": False,
        "steps": state.get("steps", []) + [f"Retrieved {len(items)} policy excerpts"],
    }
