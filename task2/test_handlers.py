"""
TDD tests for the full handler flow.
Mocks Tripletex API, verifies correct endpoints called with correct data.

Run: python3 task2/test_handlers.py
"""
import json
import sys
import re
from unittest.mock import patch, MagicMock
from datetime import date

sys.path.insert(0, '.')
from task2.solution import (
    regex_parse, parse_with_claude, execute_plan,
    handle_create_customer, handle_create_supplier, handle_create_employee,
    handle_create_department, handle_create_product, handle_create_project,
    handle_create_invoice, handle_create_travel_expense,
    handle_register_supplier_invoice, handle_run_payroll,
)


class TripletexMock:
    """Records all API calls for verification."""
    def __init__(self):
        self.calls = []  # (method, path, body_or_params)
        self.next_id = 1000
        self.departments = [{"id": 1, "name": "Avdeling"}]
        self.employees = []
        self.customers = []
        self.payment_types = [{"id": 99}]
        self.cost_categories = [
            {"id": 10, "description": "Mat", "showOnTravelExpenses": True},
            {"id": 11, "description": "Fly", "showOnTravelExpenses": True},
            {"id": 12, "description": "Taxi", "showOnTravelExpenses": True},
            {"id": 13, "description": "Hotell", "showOnTravelExpenses": True},
            {"id": 14, "description": "Tog", "showOnTravelExpenses": True},
        ]
        self.salary_types = [
            {"id": 200, "number": "2000", "name": "Fastlønn"},
            {"id": 202, "number": "2002", "name": "Bonus"},
        ]
        self.accounts = {
            1920: {"id": 500, "number": 1920, "name": "Bankinnskudd", "bankAccountNumber": "86010517941"},
            2400: {"id": 501, "number": 2400, "name": "Leverandørgjeld"},
            2710: {"id": 502, "number": 2710, "name": "Inngående MVA"},
            5000: {"id": 503, "number": 5000, "name": "Lønn til ansatte"},
            6540: {"id": 504, "number": 6540, "name": "Inventar"},
            7000: {"id": 505, "number": 7000, "name": "Drivstoff"},
        }

    def _make_id(self):
        self.next_id += 1
        return self.next_id

    def get(self, base_url, token, path, params=None):
        self.calls.append(("GET", path, params))
        if "/department" in path:
            return 200, {"values": self.departments}
        if "/employee" in path and "email" in (params or {}):
            return 200, {"values": self.employees}
        if "/employee" in path:
            return 200, {"values": self.employees or [{"id": 1}]}
        if "/customer" in path:
            return 200, {"values": self.customers}
        if "/supplier" in path:
            return 200, {"values": []}
        if "/invoice/paymentType" in path:
            return 200, {"values": self.payment_types}
        if "/invoice" in path:
            return 200, {"values": []}
        if "/travelExpense/costCategory" in path:
            return 200, {"values": self.cost_categories}
        if "/travelExpense/paymentType" in path:
            return 200, {"values": [{"id": 50}]}
        if "/salary/type" in path:
            return 200, {"values": self.salary_types}
        if "/ledger/account" in path:
            num = int((params or {}).get("number", 0))
            acct = self.accounts.get(num)
            return 200, {"values": [acct] if acct else []}
        return 200, {"values": []}

    def post(self, base_url, token, path, body):
        self.calls.append(("POST", path, body))
        new_id = self._make_id()
        if "/salary/transaction" in path:
            return 422, {"status": 422, "message": "No employment"}
        return 201, {"value": {"id": new_id}}

    def put(self, base_url, token, path, body=None, params=None):
        self.calls.append(("PUT", path, params or body))
        new_id = self._make_id()
        return 200, {"value": {"id": new_id}}

    def delete(self, base_url, token, path):
        self.calls.append(("DELETE", path, None))
        return 200, {}


def run_handler_with_mock(prompt):
    """Parse prompt and run handler with mocked API. Returns (plan, mock)."""
    mock = TripletexMock()

    # Parse
    prompt_no_email = re.sub(r'[\w.+-]+@[\w.-]+', '', prompt.lower())
    actions = len(re.findall(r'\b(?:opprett|create|registrer|registe|slett|delete|send|generer|generate|gere|faktura|fatura|invoice|rechnung|factura|betaling|payment|oppdater|update|reverser|reverse|kjør|run|konverter|convert|créez|erstellen|crea|envoyez|senden)\b', prompt_no_email))
    is_complex = len(prompt) > 200 or actions >= 2

    if not is_complex:
        plan = regex_parse(prompt)
    else:
        plan = regex_parse(prompt)  # Still use regex for test — LLM not available in tests

    if not plan:
        return None, mock

    # Patch API functions and run handler
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put), \
         patch('task2.solution.tx_delete', mock.delete):
        execute_plan("https://mock/v2", "mock-token", plan, prompt)

    return plan, mock


def find_calls(mock, method, path_contains):
    return [(m, p, b) for m, p, b in mock.calls if m == method and path_contains in p]


# ============================================================
# Tests
# ============================================================

def test_create_customer_api_calls():
    """Customer: POST /customer with name, org, email, address."""
    _, mock = run_handler_with_mock(
        "Create the customer Brightstone Ltd with organization number 853284882. "
        "The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.")

    posts = find_calls(mock, "POST", "/customer")
    assert len(posts) == 1, f"Expected 1 POST /customer, got {len(posts)}"
    body = posts[0][2]
    assert body["name"] == "Brightstone Ltd"
    assert body["organizationNumber"] == "853284882"
    assert body["email"] == "post@brightstone.no"
    assert body["physicalAddress"]["addressLine1"] == "Parkveien 61"
    assert body["physicalAddress"]["postalCode"] == "5003"
    assert body["physicalAddress"]["city"] == "Bergen"
    assert body["physicalAddress"]["country"]["id"] == 161
    assert body["postalAddress"]["addressLine1"] == "Parkveien 61"
    assert body.get("isCustomer") == True
    print("  PASS | create_customer: correct POST body")


def test_create_supplier_api_calls():
    """Supplier: POST /supplier with name, org, email, invoiceEmail, isSupplier."""
    _, mock = run_handler_with_mock(
        "Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.")

    posts = find_calls(mock, "POST", "/supplier")
    assert len(posts) == 1
    body = posts[0][2]
    assert body["name"] == "Havbris AS"
    assert body["organizationNumber"] == "846635408"
    assert body["email"] == "faktura@havbris.no"
    assert body["invoiceEmail"] == "faktura@havbris.no"
    assert body.get("isSupplier") == True
    print("  PASS | create_supplier: correct POST body")


def test_create_supplier_de():
    """German supplier: correct name and org extraction."""
    _, mock = run_handler_with_mock(
        "Registrieren Sie den Lieferanten Brückentor GmbH mit der Organisationsnummer 959331863. E-Mail: faktura@brckentorgmbh.no.")

    posts = find_calls(mock, "POST", "/supplier")
    assert len(posts) == 1
    body = posts[0][2]
    assert body["name"] == "Brückentor GmbH"
    assert body["organizationNumber"] == "959331863"
    print("  PASS | create_supplier_de: correct name and org")


def test_create_employee_api_calls():
    """Employee: POST with firstName, lastName, email, DOB, department, employment."""
    _, mock = run_handler_with_mock(
        "Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. "
        "Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.")

    emp_posts = find_calls(mock, "POST", "/employee")
    # Should have POST /employee (create) and POST /employee/employment (start date)
    assert len(emp_posts) >= 1, f"Expected POST /employee, got {len(emp_posts)}"
    body = emp_posts[0][2]
    assert body["firstName"] == "Anna"
    assert body["lastName"] == "Schneider"
    assert body["email"] == "anna.schneider@example.org"
    assert body["dateOfBirth"] == "2000-08-06"
    assert body["department"]["id"] == 1  # From mock

    # Should also create employment
    employment_posts = find_calls(mock, "POST", "/employee/employment")
    assert len(employment_posts) == 1
    assert employment_posts[0][2]["startDate"] == "2026-03-17"

    # Should grant entitlements
    entitlement_puts = find_calls(mock, "PUT", "/entitlement")
    assert len(entitlement_puts) >= 1
    print("  PASS | create_employee: correct POST body + employment + entitlements")


def test_create_department_multi():
    """3 departments: 3 separate POST /department calls."""
    _, mock = run_handler_with_mock(
        'Opprett tre avdelinger i Tripletex: "Økonomi", "Markedsføring" og "Kvalitetskontroll".')

    posts = find_calls(mock, "POST", "/department")
    assert len(posts) == 3, f"Expected 3 POST /department, got {len(posts)}"
    names = sorted([p[2]["name"] for p in posts])
    assert names == sorted(["Økonomi", "Markedsføring", "Kvalitetskontroll"])
    print("  PASS | create_department_multi: 3 correct POST calls")


def test_create_product_api_calls():
    """Product: POST /product with name, number, price, vatType."""
    _, mock = run_handler_with_mock(
        'Crea el producto "Mantenimiento" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.')

    posts = find_calls(mock, "POST", "/product")
    assert len(posts) == 1
    body = posts[0][2]
    assert body["name"] == "Mantenimiento"
    assert body["number"] == "7266"
    assert body["priceExcludingVatCurrency"] == 650.0
    assert body["vatType"]["id"] == 3  # 25% = VAT type 3
    print("  PASS | create_product: correct POST body with VAT")


def test_create_project_api_calls():
    """Project: POST /project with name, customer, project manager."""
    _, mock = run_handler_with_mock(
        'Crea el proyecto "Actualización Sierra" vinculado al cliente Sierra SL (org. nº 953403188). '
        'El director del proyecto es Ana Romero (ana.romero@example.org).')

    proj_posts = find_calls(mock, "POST", "/project")
    assert len(proj_posts) == 1
    body = proj_posts[0][2]
    assert body["name"] == "Actualización Sierra"
    assert "customer" in body  # Customer should be linked
    assert "projectManager" in body  # PM should be linked
    print("  PASS | create_project: correct POST body with customer + PM")


def test_create_travel_expense_api_calls():
    """Travel expense: POST /travelExpense + 3x POST /travelExpense/cost (diet + fly + taxi)."""
    _, mock = run_handler_with_mock(
        'Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for "Kundebesøk Bergen". '
        'Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.')

    # Should create travel expense
    te_posts = find_calls(mock, "POST", "/travelExpense")
    # Filter out /travelExpense/cost calls
    te_main = [p for p in te_posts if "/cost" not in p[1]]
    assert len(te_main) >= 1, "Expected POST /travelExpense"
    assert te_main[0][2]["title"] == "Kundebesøk Bergen"

    # Should create 3 cost lines
    cost_posts = find_calls(mock, "POST", "/travelExpense/cost")
    assert len(cost_posts) == 3, f"Expected 3 costs (diet+fly+taxi), got {len(cost_posts)}"
    amounts = sorted([p[2]["amountCurrencyIncVat"] for p in cost_posts])
    assert amounts == sorted([3200.0, 5050.0, 750.0]), f"Wrong amounts: {amounts}"
    print("  PASS | create_travel_expense: 1 expense + 3 costs with correct amounts")


def test_register_supplier_invoice_api_calls():
    """Supplier invoice: POST /supplier + POST /ledger/voucher with balanced postings."""
    _, mock = run_handler_with_mock(
        "Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) "
        "på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). "
        "Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")

    # Should create supplier
    sup_posts = find_calls(mock, "POST", "/supplier")
    assert len(sup_posts) >= 1
    assert sup_posts[0][2]["name"] == "Tindra AS"

    # Should create voucher
    voucher_posts = find_calls(mock, "POST", "/ledger/voucher")
    assert len(voucher_posts) == 1
    body = voucher_posts[0][2]
    assert "Tindra AS" in body["description"] or "INV-2026-3624" in body["description"]

    postings = body["postings"]
    assert len(postings) == 3, f"Expected 3 postings (expense+VAT+payable), got {len(postings)}"

    # Verify amounts balance to 0
    total = sum(p["amountGross"] for p in postings)
    assert abs(total) < 0.01, f"Postings don't balance: total={total}"

    # Expense posting: 33680 (42100 / 1.25)
    expense = [p for p in postings if p["amountGross"] > 0 and p["account"]["id"] == 504]  # 6540
    assert len(expense) == 1
    assert abs(expense[0]["amountGross"] - 33680) < 1

    # VAT posting: 8420
    vat = [p for p in postings if p["amountGross"] > 0 and p["account"]["id"] == 502]  # 2710
    assert len(vat) == 1
    assert abs(vat[0]["amountGross"] - 8420) < 1

    # Payable posting: -42100
    payable = [p for p in postings if p["amountGross"] < 0]
    assert len(payable) == 1
    assert abs(payable[0]["amountGross"] + 42100) < 1
    print("  PASS | register_supplier_invoice: supplier + balanced voucher (expense+VAT+payable)")


def test_run_payroll_api_calls():
    """Payroll: tries /salary/transaction first, falls back to voucher."""
    _, mock = run_handler_with_mock(
        "Run payroll for Daniel Smith (daniel.smith@example.org) for this month. "
        "The base salary is 54850 NOK. Add a one-time bonus of 6800 NOK on top of the base salary. "
        "If the salary API is unavailable, you can use manual vouchers on salary accounts (5000-series).")

    # Should try salary/transaction first
    sal_posts = find_calls(mock, "POST", "/salary/transaction")
    assert len(sal_posts) >= 1, "Should try /salary/transaction"

    # Should fall back to voucher (since mock returns 422 for salary)
    voucher_posts = find_calls(mock, "POST", "/ledger/voucher")
    assert len(voucher_posts) == 1, "Should create fallback voucher"

    body = voucher_posts[0][2]
    postings = body["postings"]
    # Should have base salary + bonus debit + bank credit
    assert len(postings) >= 2

    total = sum(p["amountGross"] for p in postings)
    assert abs(total) < 0.01, f"Voucher doesn't balance: {total}"

    debit_total = sum(p["amountGross"] for p in postings if p["amountGross"] > 0)
    assert abs(debit_total - 61650) < 1, f"Total salary wrong: {debit_total} != 61650"
    print("  PASS | run_payroll: salary/transaction attempted + balanced voucher fallback")


# ============================================================
# Run all tests
# ============================================================

if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith('test_') and callable(eval(f))]
    passed = failed = 0
    for t in sorted(tests):
        try:
            eval(f"{t}()")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL | {t}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR  | {t}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed+failed} passed")
    if failed:
        sys.exit(1)
