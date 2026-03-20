# Tripletex Task Analysis — 2026-03-20

## Current Score: 8.6 raw, 34.5 normalized, Rank #82

## Submission Results Today

| Time | Score | Checks | Response Time | Task Type (from logs) | Notes |
|------|-------|--------|---------------|----------------------|-------|
| 10:45 | 0/8 | 6 failed | 90.7s | run_payroll | Voucher approach wrong, needs /salary/transaction |
| 10:17 | 0/13 | 6 failed | 211.8s | unknown (T2?) | Never reached our server — old URL? LLM timeout? |
| 11:17 | Rate limited | - | - | - | Platform instability per Erik |
| 11:27 | Rate limited | - | - | - | Platform instability per Erik |

## Task Types — Known Status

### Working (score > 0 on old server)
| Task | Best Score | Max | Issues |
|------|-----------|-----|--------|
| create_employee | 8/8 (100%) | 8 | None — perfect |
| create_department | 7/7 (100%) | 7 | Multi-dept works |
| create_product | 7/7 (100%) | 7 | VAT mapping works |
| create_project | 7/7 (100%) | 7 | PM + customer linking works |
| create_supplier | 6/7 (86%) | 7 | Missing 1 field — bankAccount? isSupplier? |
| create_customer | 5/8 (63%) | 8 | Missing 3 fields — phone? country? |
| create_invoice | variable | ? | Some 422 errors, needs bank acct setup |

### Not Working (0 score)
| Task | Issue | Fix Status |
|------|-------|------------|
| create_travel_expense | 422 on old server (date field) | FIXED in new server (201) |
| register_supplier_invoice | No handler | ADDED — uses voucher API |
| run_payroll | No handler / wrong approach | ADDED — salary/transaction + voucher fallback |

### Unknown / Not Seen
- create_credit_note
- register_payment
- update_employee
- update_customer
- create_contact
- create_order
- reverse_voucher
- bank_reconciliation
- All Tier 3 tasks (opens Saturday)

## Architecture

```
Competition Platform
  → POST /solve
  → Cloudflare trycloudflare tunnel
  → localhost:9002 (MacBook Air M4)
  → regex_parse() (0ms) or claude -p --model haiku (5-8s)
  → Tripletex API calls via tx-proxy
  → Return {"status": "completed"}
```

## Speed Optimization
- Regex parser: 0ms for 19/19 known prompt patterns
- Haiku LLM fallback: 5-8s for unknown patterns
- Request logging to /tmp/tripletex-requests/ for analysis
- Cache for LLM results (by prompt hash)

## Key Learnings
1. Voucher postings need `row: 1, 2, ...` (not 0) + `sendToLedger=true`
2. `/salary/transaction` API is 403 in sandbox but available in competition
3. `/incomingInvoice` is 403 — use vouchers for supplier invoices
4. Email addresses containing "faktura" break invoice regex detection
5. Platform rate limits are per-task-type (10/day) but also unstable today
6. Competition uses tx-proxy-*.a.run.app as base_url, fresh creds per task
7. `isSupplier: true` and `isCustomer: true` should be set explicitly
