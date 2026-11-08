"""MCP tool tests: every tool call goes through the MCP server layer."""

from app.mcp_server import call_tool_sync


def test_lookup_invoice(seeded):
    inv = call_tool_sync("lookup_invoice", {"invoice_id": "INV-1001"})
    assert inv["id"] == "INV-1001"
    assert inv["amount"] == 18450
    assert inv["vendor_id"] == "VEN-001"


def test_lookup_invoice_missing(seeded):
    inv = call_tool_sync("lookup_invoice", {"invoice_id": "INV-9999"})
    assert "error" in inv


def test_validate_invoice_duplicate(seeded):
    # INV-1007 duplicates INV-1002 (same vendor, PO and amount).
    result = call_tool_sync("validate_invoice", {"invoice_id": "INV-1007"})
    assert result["valid"] is False
    assert any("duplicate" in i.lower() for i in result["issues"])


def test_validate_invoice_overdue(seeded):
    result = call_tool_sync("validate_invoice", {"invoice_id": "INV-1005"})
    assert result["overdue"] is True
    assert any("overdue" in i.lower() for i in result["issues"])


def test_validate_invoice_threshold(seeded):
    # INV-1006 is INR 85,000 > the 50,000 approval threshold.
    result = call_tool_sync("validate_invoice", {"invoice_id": "INV-1006"})
    assert result["needs_approval"] is True


def test_search_policy_returns_right_doc_first(seeded):
    hits = call_tool_sync("search_policy", {"query": "expense reimbursement limit"})
    items = hits["items"]
    assert items, "expected at least one policy hit"
    assert items[0]["title"] == "Expense Policy"
    assert "Reimbursement limit" in items[0]["section"]


def test_search_policy_leave(seeded):
    hits = call_tool_sync("search_policy", {"query": "carry forward leave days"})
    assert hits["items"][0]["title"] == "Leave Policy"


def test_draft_report(seeded):
    report = call_tool_sync(
        "draft_report", {"report_type": "Monthly spend report", "period": "this month"}
    )
    assert report["figures"]["total_invoices"] == 12
    assert report["figures"]["pending_count"] == 9
    assert "Monthly spend report" in report["text"]


def test_list_vendors(seeded):
    vendors = call_tool_sync("list_vendors", {})
    assert len(vendors["items"]) == 8


def test_ledger_idempotency(seeded):
    key = "test-key-1"
    first = call_tool_sync(
        "post_ledger_entry",
        {
            "entry": {"type": "payment", "invoice_id": "INV-1001", "amount": 100},
            "idempotency_key": key,
        },
    )
    second = call_tool_sync(
        "post_ledger_entry",
        {
            "entry": {"type": "payment", "invoice_id": "INV-1001", "amount": 100},
            "idempotency_key": key,
        },
    )
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["id"] == second["id"]
    ledger = call_tool_sync("get_ledger", {})
    assert len(ledger["items"]) == 1


def test_reserve_payment_idempotency(seeded):
    first = call_tool_sync(
        "reserve_payment",
        {"invoice_id": "INV-1001", "amount": 1000, "idempotency_key": "res-1"},
    )
    second = call_tool_sync(
        "reserve_payment",
        {"invoice_id": "INV-1001", "amount": 1000, "idempotency_key": "res-1"},
    )
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["id"] == second["id"]
