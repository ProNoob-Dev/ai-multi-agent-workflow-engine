# Invoice Approval Policy

## Approval threshold
Invoices up to INR 50,000 can be approved by the finance executive.
Invoices above INR 50,000 need a human-in-the-loop approval from the
finance manager before payment is released.

## Validation
Every invoice is validated against its purchase order: vendor, amount
and line items must match. Mismatches go to the review queue.

## Duplicate invoices
An invoice is flagged as a suspected duplicate when another invoice
from the same vendor has the same purchase order and amount. Duplicate
invoices are never paid twice; the second copy is held for review.

## Payment release
Payments are released only after validation passes and, where required,
human approval is recorded. All payments are logged in the ledger.
