"""Business logic used by the MCP tools.

Every function here is pure business logic over the store / vector store /
LLM. The MCP server (mcp_server.py) exposes these as tools, and the
LangGraph agents call them *through* the MCP layer, never directly.
"""

import re
from datetime import date, timedelta

from . import config
from .llm import get_llm
from .store import get_store
from .vectorstore import get_vector_store

INVOICE_RE = re.compile(r"INV-\d+", re.IGNORECASE)


def _today() -> date:
    return date.today()


def materialise_dates(invoice: dict) -> dict:
    """Turn relative day offsets into real dates (relative to today)."""
    out = dict(invoice)
    issued = _today() - timedelta(days=int(invoice.get("issued_days_ago", 0)))
    due = _today() + timedelta(days=int(invoice.get("due_in_days", 0)))
    out["issued_date"] = issued.isoformat()
    out["due_date"] = due.isoformat()
    out["overdue"] = due < _today() and invoice.get("status") == "pending"
    return out


def list_vendors() -> list[dict]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "seed" / "vendors.json"
    return json.loads(path.read_text())


def get_vendor(query: str) -> dict | None:
    q = query.strip().lower()
    for vendor in list_vendors():
        if q in vendor["name"].lower() or q == vendor["id"].lower():
            return vendor
    return None


def list_invoices(status: str | None = None) -> list[dict]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "seed" / "invoices.json"
    invoices = [materialise_dates(inv) for inv in json.loads(path.read_text())]
    if status:
        invoices = [i for i in invoices if i["status"] == status]
    return invoices


def get_invoice(invoice_id: str) -> dict | None:
    for inv in list_invoices():
        if inv["id"].upper() == invoice_id.strip().upper():
            return inv
    return None


def validate_invoice(invoice_id: str) -> dict:
    """Validate an invoice: exists, PO present, duplicate check, due date,
    amount vs the human-approval threshold."""
    inv = get_invoice(invoice_id)
    if inv is None:
        return {
            "invoice_id": invoice_id,
            "valid": False,
            "checks": [],
            "issues": [f"Invoice {invoice_id} not found."],
        }
    checks: list[str] = []
    issues: list[str] = []
    checks.append(f"Invoice {inv['id']} exists for vendor {inv['vendor_id']}.")
    if inv.get("po_number"):
        checks.append(f"Purchase order {inv['po_number']} is attached.")
    else:
        issues.append("No purchase order attached.")
    duplicates = [
        other
        for other in list_invoices()
        if other["id"] != inv["id"]
        and other["vendor_id"] == inv["vendor_id"]
        and other["po_number"] == inv["po_number"]
        and other["amount"] == inv["amount"]
    ]
    if duplicates:
        issues.append(
            f"Suspected duplicate: {duplicates[0]['id']} has the same vendor, "
            f"PO and amount. Do not pay twice."
        )
    else:
        checks.append("No duplicate invoice found for this vendor/PO/amount.")
    if inv["overdue"]:
        issues.append(f"Invoice is overdue (due {inv['due_date']}).")
    else:
        checks.append(f"Due date {inv['due_date']} is not overdue.")
    needs_approval = inv["amount"] > config.FINANCIAL_APPROVAL_THRESHOLD
    if needs_approval:
        checks.append(
            f"Amount INR {inv['amount']:,.0f} exceeds the INR "
            f"{config.FINANCIAL_APPROVAL_THRESHOLD:,.0f} human-approval "
            "threshold: payment needs a human approval."
        )
    return {
        "invoice_id": inv["id"],
        "vendor_id": inv["vendor_id"],
        "amount": inv["amount"],
        "currency": inv["currency"],
        "status": inv["status"],
        "due_date": inv["due_date"],
        "overdue": inv["overdue"],
        "needs_approval": needs_approval,
        "valid": not issues,
        "checks": checks,
        "issues": issues,
    }


def search_policies(query: str, top_k: int = 3) -> list[dict]:
    """RAG retrieval over the seeded policy documents."""
    hits = get_vector_store().search(query, top_k=top_k)
    return [
        {
            "doc_id": h["id"],
            "title": h["metadata"].get("title", h["id"]),
            "section": h["metadata"].get("section", ""),
            "excerpt": h["text"][:400],
            "score": h["score"],
        }
        for h in hits
    ]


def report_figures() -> dict:
    invoices = list_invoices()
    pending = [i for i in invoices if i["status"] == "pending"]
    approved = [i for i in invoices if i["status"] == "approved"]
    paid = [i for i in invoices if i["status"] == "paid"]
    overdue = [i for i in pending if i["overdue"]]
    by_vendor: dict[str, float] = {}
    for inv in invoices:
        by_vendor[inv["vendor_id"]] = by_vendor.get(inv["vendor_id"], 0) + inv["amount"]
    top_vendor_id = max(by_vendor, key=by_vendor.get) if by_vendor else None
    top_vendor = get_vendor(top_vendor_id) if top_vendor_id else None
    return {
        "total_invoices": len(invoices),
        "pending_count": len(pending),
        "pending_total_inr": sum(i["amount"] for i in pending),
        "approved_count": len(approved),
        "approved_total_inr": sum(i["amount"] for i in approved),
        "paid_count": len(paid),
        "paid_total_inr": sum(i["amount"] for i in paid),
        "overdue_count": len(overdue),
        "overdue_total_inr": sum(i["amount"] for i in overdue),
        "top_vendor": top_vendor["name"] if top_vendor else "n/a",
        "top_vendor_total_inr": by_vendor.get(top_vendor_id, 0) if top_vendor_id else 0,
    }


def draft_report(report_type: str, period: str) -> dict:
    figures = report_figures()
    text = get_llm().draft_report(report_type, period, figures)
    return {
        "report_type": report_type,
        "period": period,
        "figures": figures,
        "text": text,
    }


# --- Ledger / reservations (the saga's side effects) ---


def reserve_payment(invoice_id: str, amount: float, idempotency_key: str) -> dict:
    """Reserve money for a payment. Idempotent on the key: calling twice
    with the same key returns the original reservation, never a second one."""
    store = get_store()
    existing = store.get("reservations", idempotency_key)
    if existing:
        return dict(existing, duplicate=True)
    reservation = {
        "id": f"RES-{idempotency_key[:8]}",
        "invoice_id": invoice_id,
        "amount": amount,
        "status": "reserved",
        "idempotency_key": idempotency_key,
    }
    store.put("reservations", idempotency_key, reservation)
    return dict(reservation, duplicate=False)


def reverse_payment(reservation_id: str) -> dict:
    store = get_store()
    for key, res in store.list("reservations"):
        if res["id"] == reservation_id:
            res = dict(res, status="reversed")
            store.put("reservations", key, res)
            return res
    return {"id": reservation_id, "status": "not_found"}


def post_ledger_entry(entry: dict, idempotency_key: str) -> dict:
    """Post a ledger entry. Idempotent on the key."""
    store = get_store()
    existing = store.get("ledger", idempotency_key)
    if existing:
        return dict(existing, duplicate=True)
    record = dict(entry)
    record["id"] = f"LED-{idempotency_key[:8]}"
    record["idempotency_key"] = idempotency_key
    record.setdefault("status", "posted")
    store.put("ledger", idempotency_key, record)
    return dict(record, duplicate=False)


def reverse_ledger_entry(entry_id: str) -> dict:
    store = get_store()
    for key, entry in store.list("ledger"):
        if entry["id"] == entry_id:
            entry = dict(entry, status="reversed")
            store.put("ledger", key, entry)
            return entry
    return {"id": entry_id, "status": "not_found"}


def ledger_entries() -> list[dict]:
    return [v for _, v in get_store().list("ledger")]
