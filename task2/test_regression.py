"""
Regression tests — one test per REAL competition/production prompt.
Every prompt that has ever hit our server gets a test here.
Tests verify both parsing AND handler API calls using mocks.

Run: python3 task2/test_regression.py

RULE: When a new prompt comes in from competition, add a test here BEFORE fixing bugs.
"""
import json
import sys
import re
from unittest.mock import patch

sys.path.insert(0, '.')
from task2.solution import regex_parse, execute_plan


class APIMock:
    """Records API calls for verification."""
    def __init__(self):
        self.calls = []
        self._id = 1000

    def _next_id(self):
        self._id += 1
        return self._id

    def get(self, base_url, token, path, params=None):
        self.calls.append(("GET", path, params))
        if "/department" in path: return 200, {"values": [{"id": 1, "name": "Avdeling"}]}
        if "/employee" in path: return 200, {"values": []}
        if "/customer" in path:
            org = (params or {}).get("organizationNumber", "")
            if org:
                return 200, {"values": [{"id": 5001, "name": "Customer"}]}
            return 200, {"values": []}
        if "/supplier" in path: return 200, {"values": []}
        if "/invoice/paymentType" in path: return 200, {"values": [{"id": 99}]}
        if "/travelExpense/costCategory" in path:
            return 200, {"values": [
                {"id": 10, "description": "Mat", "showOnTravelExpenses": True},
                {"id": 11, "description": "Fly", "showOnTravelExpenses": True},
                {"id": 12, "description": "Taxi", "showOnTravelExpenses": True},
            ]}
        if "/travelExpense/paymentType" in path: return 200, {"values": [{"id": 50}]}
        if "/travelExpense/rateCategory" in path or "/rateCategory" in path:
            return 200, {"values": [
                {"id": 60, "name": "Diett innland", "type": "PER_DIEM", "isValidDomestic": True},
                {"id": 61, "name": "Nattillegg", "type": "ACCOMMODATION_ALLOWANCE", "isValidDomestic": True},
            ]}
        if "/salary/type" in path:
            return 200, {"values": [
                {"id": 200, "number": "2000", "name": "Fastlønn"},
                {"id": 202, "number": "2002", "name": "Bonus"},
            ]}
        if "/ledger/account" in path:
            num = int((params or {}).get("number", 0))
            accts = {1920: 500, 2400: 501, 2710: 502, 5000: 503, 6540: 504, 7000: 505}
            aid = accts.get(num)
            return 200, {"values": [{"id": aid, "number": num, "name": f"Acct {num}", "bankAccountNumber": "86010517941"}] if aid else []}
        if "/activity" in path: return 200, {"values": [{"id": 77, "name": "Fakturerbart arbeid"}]}
        if "/invoice" in path and "paymentType" not in path:
            cust_id = (params or {}).get("customerId")
            if cust_id:
                return 200, {"values": [{"id": 9001, "invoiceNumber": 1, "amountCurrency": 41125, "amountOutstandingTotal": 41125}]}
            return 200, {"values": [{"id": 9001, "invoiceNumber": 1, "amountCurrency": 10000, "amountOutstandingTotal": 10000}]}
        return 200, {"values": []}

    def post(self, base_url, token, path, body):
        self.calls.append(("POST", path, body))
        if "/salary/transaction" in path: return 422, {"message": "No employment"}
        return 201, {"value": {"id": self._next_id()}}

    def put(self, base_url, token, path, body=None, params=None):
        self.calls.append(("PUT", path, params or body))
        return 200, {"value": {"id": self._next_id()}}

    def delete(self, base_url, token, path):
        self.calls.append(("DELETE", path, None))
        return 200, {}


def run(prompt):
    """Parse + execute with mocked API. Returns (plan, mock)."""
    mock = APIMock()
    # Use regex for short, LLM-eligible prompts
    plan = regex_parse(prompt)
    if not plan:
        return None, mock
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put), \
         patch('task2.solution.tx_delete', mock.delete):
        execute_plan("https://mock/v2", "tok", plan, prompt)
    return plan, mock


def posts(mock, path_contains):
    return [(m, p, b) for m, p, b in mock.calls if m == "POST" and path_contains in p]


# ============================================================
# REAL PROMPTS FROM PRODUCTION — iClaw-E server logs
# ============================================================

def test_R01_create_customer_en():
    """Round 1: Create customer Brightstone Ltd (EN)"""
    p, m = run("Create the customer Brightstone Ltd with organization number 853284882. The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.")
    assert p["task_type"] == "create_customer"
    c = posts(m, "/customer")
    assert len(c) == 1
    b = c[0][2]
    assert b["name"] == "Brightstone Ltd"
    assert b["organizationNumber"] == "853284882"
    assert b["email"] == "post@brightstone.no"
    assert b["physicalAddress"]["addressLine1"] == "Parkveien 61"
    assert b["physicalAddress"]["postalCode"] == "5003"
    assert b["physicalAddress"]["city"] == "Bergen"
    assert b["physicalAddress"]["country"]["id"] == 161
    assert b["postalAddress"]["addressLine1"] == "Parkveien 61"
    assert b.get("isCustomer") == True


def test_R02_create_customer_de():
    """Round 1: Create customer Bergwerk GmbH (DE) — with address"""
    p, m = run("Erstellen Sie den Kunden Bergwerk GmbH mit der Organisationsnummer 946768693. Die Adresse ist Solveien 5, 3015 Drammen. E-Mail: post@bergwerk.no.")
    assert p["task_type"] == "create_customer"
    b = posts(m, "/customer")[0][2]
    assert b["name"] == "Bergwerk GmbH"
    assert b["organizationNumber"] == "946768693"
    assert b["email"] == "post@bergwerk.no"
    assert b["physicalAddress"]["addressLine1"] == "Solveien 5", f"Got: {b['physicalAddress']['addressLine1']}"
    assert b["physicalAddress"]["postalCode"] == "3015"
    assert b["physicalAddress"]["city"] == "Drammen"


def test_R03_create_department_fr():
    """Round 1: 3 departments (FR)"""
    p, m = run('Créez trois départements dans Tripletex : "Økonomi", "Kvalitetskontroll" et "Markedsføring".')
    assert p["task_type"] == "create_department"
    d = posts(m, "/department")
    assert len(d) == 3
    names = sorted([x[2]["name"] for x in d])
    assert names == sorted(["Økonomi", "Kvalitetskontroll", "Markedsføring"])


def test_R04_create_department_no():
    """Round 1: 3 departments (NO)"""
    p, m = run('Opprett tre avdelinger i Tripletex: "Økonomi", "Markedsføring" og "Kvalitetskontroll".')
    assert p["task_type"] == "create_department"
    d = posts(m, "/department")
    assert len(d) == 3
    names = sorted([x[2]["name"] for x in d])
    assert names == sorted(["Økonomi", "Markedsføring", "Kvalitetskontroll"])


def test_R05_create_department_en():
    """Round 1: 3 departments (EN)"""
    p, m = run('Create three departments in Tripletex: "Innkjøp", "Drift", and "Kundeservice".')
    assert p["task_type"] == "create_department"
    d = posts(m, "/department")
    assert len(d) == 3
    names = sorted([x[2]["name"] for x in d])
    assert names == sorted(["Innkjøp", "Drift", "Kundeservice"])


def test_R06_create_product_es():
    """Round 1: Product Mantenimiento (ES)"""
    p, m = run('Crea el producto "Mantenimiento" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.')
    assert p["task_type"] == "create_product"
    b = posts(m, "/product")[0][2]
    assert b["name"] == "Mantenimiento"
    assert b["number"] == "7266"
    assert b["priceExcludingVatCurrency"] == 650.0
    assert b["vatType"]["id"] == 3  # 25%


def test_R07_create_project_es():
    """Round 1: Project Actualización Sierra (ES) — verify PM name"""
    p, m = run('Crea el proyecto "Actualización Sierra" vinculado al cliente Sierra SL (org. nº 953403188). El director del proyecto es Ana Romero (ana.romero@example.org).')
    assert p["task_type"] == "create_project"
    proj = posts(m, "/project")
    assert len(proj) == 1
    assert proj[0][2]["name"] == "Actualización Sierra"
    assert proj[0][2].get("customer") is not None
    assert proj[0][2].get("projectManager") is not None
    # Verify the employee (PM) was created with correct name
    emp = [x for x in posts(m, "/employee") if "/employment" not in x[1] and "/entitlement" not in x[1]]
    assert len(emp) >= 1, "PM employee should be created"
    pm_body = emp[0][2]
    assert pm_body["firstName"] == "Ana", f"PM firstName: {pm_body.get('firstName')}"
    assert pm_body["lastName"] == "Romero", f"PM lastName: {pm_body.get('lastName')}"
    assert pm_body.get("email") == "ana.romero@example.org"


def test_R08_create_supplier_no_sjobris():
    """Round 1: Supplier Sjøbris AS (NO)"""
    p, m = run("Registrer leverandøren Sjøbris AS med organisasjonsnummer 811212717. E-post: faktura@sjbris.no.")
    assert p["task_type"] == "create_supplier"
    b = posts(m, "/supplier")[0][2]
    assert b["name"] == "Sjøbris AS"
    assert b["organizationNumber"] == "811212717"
    assert b["email"] == "faktura@sjbris.no"
    assert b["invoiceEmail"] == "faktura@sjbris.no"
    assert b.get("isSupplier") == True


def test_R09_create_supplier_de_bruckentor():
    """Round 1: Supplier Brückentor GmbH (DE)"""
    p, m = run("Registrieren Sie den Lieferanten Brückentor GmbH mit der Organisationsnummer 959331863. E-Mail: faktura@brckentorgmbh.no.")
    assert p["task_type"] == "create_supplier"
    b = posts(m, "/supplier")[0][2]
    assert b["name"] == "Brückentor GmbH"
    assert b["organizationNumber"] == "959331863"


def test_R10_create_supplier_de_waldstein():
    """Round 1: Supplier Waldstein GmbH (DE)"""
    p, m = run("Registrieren Sie den Lieferanten Waldstein GmbH mit der Organisationsnummer 891505019. E-Mail: faktura@waldsteingmbh.no.")
    assert p["task_type"] == "create_supplier"
    b = posts(m, "/supplier")[0][2]
    assert b["name"] == "Waldstein GmbH"
    assert b["organizationNumber"] == "891505019"


def test_R11_create_supplier_no_havbris():
    """Round 1: Supplier Havbris AS (NO)"""
    p, m = run("Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.")
    assert p["task_type"] == "create_supplier"
    b = posts(m, "/supplier")[0][2]
    assert b["name"] == "Havbris AS"
    assert b["organizationNumber"] == "846635408"


def test_R12_create_employee_de():
    """Round 1: Employee Anna Schneider (DE)"""
    p, m = run("Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.")
    assert p["task_type"] == "create_employee"
    emp = posts(m, "/employee")
    main = [x for x in emp if "/employment" not in x[1] and "/entitlement" not in x[1]]
    assert len(main) == 1
    b = main[0][2]
    assert b["firstName"] == "Anna"
    assert b["lastName"] == "Schneider"
    assert b["email"] == "anna.schneider@example.org"
    assert b["dateOfBirth"] == "2000-08-06"
    # Employment + details
    empl = [x for x in emp if x[1] == "/employee/employment"]
    assert len(empl) == 1, f"Expected 1 employment POST, got {len(empl)}"
    assert empl[0][2]["startDate"] == "2026-03-17"
    details = [x for x in emp if "/employment/details" in x[1]]
    assert len(details) == 1, "Should create employment details"


def test_R13_create_travel_expense_no():
    """Round 1: Travel expense Magnus Haugen with diet + fly + taxi"""
    p, m = run('Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for "Kundebesøk Bergen". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.')
    assert p["task_type"] == "create_travel_expense"
    # Main travel expense
    te = [x for x in posts(m, "/travelExpense") if "/cost" not in x[1]]
    assert len(te) >= 1
    assert te[0][2]["title"] == "Kundebesøk Bergen"
    # 2 cost lines (flight + taxi) — diet registered as perDiemCompensation
    costs = posts(m, "/travelExpense/cost")
    assert len(costs) == 2, f"Expected 2 costs, got {len(costs)}"
    amounts = sorted([c[2]["amountCurrencyIncVat"] for c in costs])
    assert amounts == sorted([5050.0, 750.0])
    # Per diem compensation for diet
    pd = posts(m, "/travelExpense/perDiemCompensation")
    assert len(pd) >= 1, "Expected perDiemCompensation for diet"
    assert pd[0][2]["count"] == 4  # 4 days of per diem


def test_R14_supplier_invoice_tindra():
    """Round 1: Supplier invoice Tindra AS 42100 incl VAT, konto 6540"""
    p, m = run("Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")
    assert p["task_type"] == "register_supplier_invoice"
    # Supplier created
    sup = posts(m, "/supplier")
    assert len(sup) >= 1
    assert sup[0][2]["name"] == "Tindra AS"
    # SupplierInvoice created via POST /supplierInvoice
    si = posts(m, "/supplierInvoice")
    assert len(si) >= 1, "Should POST to /supplierInvoice"
    body = si[0][2]
    assert body.get("invoiceNumber") == "INV-2026-3624"
    postings = body.get("voucher", {}).get("postings", [])
    assert len(postings) == 2  # expense with vatType + credit
    expense = [p for p in postings if p["amountGross"] > 0]
    assert abs(expense[0]["amountGross"] - 33680) < 1


def test_R15_supplier_invoice_snohetta():
    """Round 1: Supplier invoice Snøhetta AS 11950 incl VAT, konto 7000"""
    p, m = run("Vi har mottatt faktura INV-2026-8584 fra leverandøren Snøhetta AS (org.nr 852796316) på 11950 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 7000). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")
    assert p["task_type"] == "register_supplier_invoice"
    si = posts(m, "/supplierInvoice")
    assert len(si) >= 1
    postings = si[0][2].get("voucher", {}).get("postings", [])
    expense = [p for p in postings if p["amountGross"] > 0]
    assert len(expense) == 1
    assert abs(expense[0]["amountGross"] - 9560) < 1  # 11950/1.25


# ============================================================
# REAL COMPETITION REQUESTS — our server (Claude-4)
# ============================================================

def test_C01_payroll_erik_nilsen():
    """Competition 10:45 AM: Payroll Erik Nilsen (scored 0/8)"""
    p, m = run("Kjør lønn for Erik Nilsen (erik.nilsen@example.org) for denne måneden. Grunnlønn er 53350 kr. Legg til en engangsbonus på 11050 kr i tillegg til grunnlønnen. Dersom lønns-API-et ikke fungerer, kan du bruke manuelle bilag på lønnskontoer (5000-serien) for å registrere lønnskostnaden.")
    assert p["task_type"] == "run_payroll"
    e = p["entities"]
    assert e["employeeName"] == "Erik Nilsen"
    assert e["employeeEmail"] == "erik.nilsen@example.org"
    assert e["baseSalary"] == 53350.0
    assert e["bonus"] == 11050.0
    assert e["totalAmount"] == 64400.0
    # Should try salary/transaction first
    sal = posts(m, "/salary/transaction")
    assert len(sal) >= 1
    # Should fall back to voucher
    vouch = posts(m, "/ledger/voucher")
    assert len(vouch) == 1
    postings = vouch[0][2]["postings"]
    total = sum(p["amountGross"] for p in postings)
    assert abs(total) < 0.01


def test_C02_payroll_daniel_smith():
    """Competition variant: Payroll Daniel Smith (EN)"""
    p, m = run("Run payroll for Daniel Smith (daniel.smith@example.org) for this month. The base salary is 54850 NOK. Add a one-time bonus of 6800 NOK on top of the base salary. If the salary API is unavailable, you can use manual vouchers on salary accounts (5000-series) to record the payroll expense.")
    assert p["task_type"] == "run_payroll"
    e = p["entities"]
    assert e["baseSalary"] == 54850.0
    assert e["bonus"] == 6800.0
    assert e["totalAmount"] == 61650.0


def test_C03_project_invoice_tiago():
    """Competition 12:11 PM: T2 project invoice (scored 0/8).
    This is a COMPLEX prompt (256 chars, 3 action words) — in production it goes to LLM
    which returns project_invoice. Regex alone returns create_project (partial).
    We test that regex at least gets the org number right, and that the complexity
    detection would route this to LLM."""
    prompt = 'Registe 23 horas para Tiago Santos (tiago.santos@example.org) na atividade "Analyse" do projeto "Integração de plataforma" para Floresta Lda (org. nº 889395338). Taxa horária: 1050 NOK/h. Gere uma fatura de projeto ao cliente com base nas horas registadas.'
    # Verify complexity detection routes to LLM
    import re as _re
    prompt_no_email = _re.sub(r'[\w.+-]+@[\w.-]+', '', prompt.lower())
    actions = len(_re.findall(r'\b(?:opprett|create|registrer|registe|slett|delete|send|generer|generate|gere|faktura|fatura|invoice|rechnung|factura|betaling|payment|oppdater|update|reverser|reverse|kjør|run|konverter|convert|créez|erstellen|crea|envoyez|senden)\b', prompt_no_email))
    is_complex = len(prompt) > 200 or actions >= 2
    assert is_complex, f"Should be complex: {len(prompt)} chars, {actions} actions"
    # Regex parse still extracts some useful data
    p = regex_parse(prompt)
    assert p is not None
    assert p["entities"].get("customerOrgNumber") == "889395338"
    assert p["entities"].get("projectManagerEmail") == "tiago.santos@example.org"


# ============================================================
# INVOICE TESTS (go through LLM but regex also parses them)
# ============================================================

def test_R16_invoice_de():
    """Round 1: Invoice Bergwerk GmbH 18200 NOK (DE)"""
    p, _ = run("Erstellen und senden Sie eine Rechnung an den Kunden Bergwerk GmbH (Org.-Nr. 868341580) über 18200 NOK ohne MwSt. Die Rechnung betrifft Analysebericht.")
    assert p["task_type"] == "create_invoice"
    e = p["entities"]
    assert e.get("customerName") == "Bergwerk GmbH" or e.get("customerOrgNumber") == "868341580"
    lines = e.get("lines", [])
    assert len(lines) >= 1
    assert lines[0].get("unitPrice") == 18200 or lines[0].get("amount") == 18200


def test_R17_invoice_fr():
    """Round 1: Invoice Prairie SARL 7200 NOK (FR)"""
    p, _ = run("Créez et envoyez une facture au client Prairie SARL (nº org. 818016662) de 7200 NOK hors TVA. La facture concerne Rapport d'analyse.")
    assert p["task_type"] == "create_invoice"
    e = p["entities"]
    assert e.get("customerName") == "Prairie SARL"
    lines = e.get("lines", [])
    assert lines[0].get("unitPrice") == 7200


def test_R18_invoice_no():
    """Round 1: Invoice Testfirma AS 15000 NOK (NO)"""
    p, _ = run("Opprett og send en faktura til kunden Testfirma AS (org.nr. 987654321) på 15000 NOK uten MVA. Fakturaen gjelder Konsulentbistand.")
    assert p["task_type"] == "create_invoice"
    e = p["entities"]
    assert e.get("customerName") == "Testfirma AS"
    assert e.get("customerOrgNumber") == "987654321"
    lines = e.get("lines", [])
    assert lines[0].get("unitPrice") == 15000
    assert "Konsulentbistand" in lines[0].get("description", "")


# ============================================================
# Register payment tests
# ============================================================

def test_register_payment_en():
    """Register payment: finds correct invoice by customer, uses invoice amount"""
    p, m = run("The customer Ironbridge Ltd (org no. 985423849) has an outstanding invoice for 32900 NOK excluding VAT for \"Web Design\". Register full payment on this invoice.")
    assert p is not None, "Should parse register_payment"
    assert p["task_type"] == "register_payment"
    # Should look up customer by org number
    gets = [(method, path, params) for method, path, params in m.calls if method == "GET"]
    cust_gets = [g for g in gets if "/customer" in g[1] and g[2] and g[2].get("organizationNumber") == "985423849"]
    assert len(cust_gets) >= 1, "Should look up customer by org number"
    # Should filter invoices by customerId
    inv_gets = [g for g in gets if "/invoice" in g[1] and "paymentType" not in g[1] and g[2] and g[2].get("customerId")]
    assert len(inv_gets) >= 1, "Should filter invoices by customerId"
    # Should call payment endpoint
    puts = [(method, path, params) for method, path, params in m.calls if method == "PUT" and ":payment" in path]
    assert len(puts) >= 1, "Should call invoice/:payment"
    # Payment amount should use invoice amount (41125 incl VAT), not prompt amount (32900)
    payment_amount = puts[0][2].get("paidAmount", 0)
    assert payment_amount == 41125, f"Payment should be invoice amount 41125, got {payment_amount}"


def test_register_payment_de():
    """Register payment: German prompt — task type + org number correct"""
    p, m = run('Der Kunde Windkraft GmbH (Org.-Nr. 954808483) hat eine offene Rechnung über 47600 NOK ohne MwSt. für "Systementwicklung". Registrieren Sie die vollständige Zahlung dieser Rechnung.')
    assert p is not None
    assert p["task_type"] == "register_payment"
    e = p["entities"]
    assert e.get("customerOrgNumber") == "954808483"
    assert e.get("amount") == 47600.0


def test_invoice_with_payment_correction():
    """LLM returns create_order but prompt has invoice+payment → corrected to invoice_with_payment"""
    from task2.solution import execute_plan, normalize_entities
    mock = APIMock()
    plan = {
        "task_type": "create_order",
        "entities": {"customerName": "Test AS", "customerOrgNumber": "123", "lines": [{"description": "X", "unitPrice": 1000, "count": 1}]}
    }
    prompt = "Opprett ein ordre for kunden Test AS. Konverter ordren til faktura og registrer full betaling."
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put), \
         patch('task2.solution.tx_delete', mock.delete):
        execute_plan("http://test", "tok", plan, prompt)
    # Should have order creation + invoice conversion + payment
    post_paths = [p for m, p, b in mock.calls if m == "POST"]
    put_paths = [p for m, p, b in mock.calls if m == "PUT"]
    assert any("/order" in p for p in post_paths), "Should create order"
    assert any(":invoice" in p for p in put_paths), "Should convert to invoice"
    assert any(":payment" in p for p in put_paths), "Should register payment"


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    tests = sorted([f for f in dir() if f.startswith('test_') and callable(eval(f))])
    passed = failed = 0
    for t in tests:
        try:
            eval(f"{t}()")
            passed += 1
            doc = eval(f"{t}.__doc__") or ""
            print(f"  PASS | {t}: {doc.strip()}")
        except AssertionError as e:
            print(f"  FAIL | {t}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR  | {t}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    if failed:
        sys.exit(1)


def test_C05_accounting_dimension_nn():
    """Competition: Accounting dimension Prosjekttype (scored 0/13)"""
    # This goes through LLM, can't test parsing offline. But we can verify the handler works.
    from task2.solution import handle_create_accounting_dimension
    mock = APIMock()
    entities = {
        "dimensionName": "Prosjekttype",
        "dimensionValues": ["Utvikling", "Internt"],
        "accountNumber": "7000",
        "amount": 39700,
        "linkedDimensionValue": "Internt",
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_create_accounting_dimension("https://mock/v2", "tok", entities)
    assert result == True
    # Should create dimension
    dim_posts = posts(mock, "/ledger/accountingDimensionName")
    assert len(dim_posts) == 1
    assert dim_posts[0][2]["dimensionName"] == "Prosjekttype"
    # Should create 2 values
    val_posts = posts(mock, "/ledger/accountingDimensionValue")
    assert len(val_posts) == 2
    # Should create voucher
    vouch_posts = posts(mock, "/ledger/voucher")
    assert len(vouch_posts) == 1
    total = sum(p["amountGross"] for p in vouch_posts[0][2]["postings"])
    assert abs(total) < 0.01


def test_C06_accounting_dimension_nested_voucher():
    """Competition: Accounting dimension with nested voucher object in entities"""
    from task2.solution import handle_create_accounting_dimension
    mock = APIMock()
    entities = {
        "dimensionName": "Kostsenter",
        "dimensionValues": ["Markedsføring", "Drift"],
        "voucher": {"accountNumber": "6340", "amount": 43650, "linkedDimensionValue": "Markedsføring"},
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_create_accounting_dimension("https://mock/v2", "tok", entities)
    assert result == True
    vouch_posts = posts(mock, "/ledger/voucher")
    assert len(vouch_posts) == 1, "Should create voucher even when data is nested"


def test_C07_invoice_multi_vat_de():
    """Competition 01:53: Invoice with 3 lines at different VAT rates (scored 3/8).
    LLM parses this — we test the handler directly with expected LLM output."""
    from task2.solution import handle_create_invoice
    mock = APIMock()
    entities = {
        "customerName": "Brückentor GmbH",
        "customerOrgNumber": "804379010",
        "lines": [
            {"description": "Schulung", "productCode": "2626", "unitPrice": 17300, "count": 1, "vatRate": 25},
            {"description": "Beratungsstunden", "productCode": "7746", "unitPrice": 12850, "count": 1, "vatRate": 15},
            {"description": "Cloud-Speicher", "productCode": "5675", "unitPrice": 7050, "count": 1, "vatRate": 0},
        ],
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_create_invoice("https://mock/v2", "tok", entities)
    assert result == True
    prod_posts = posts(mock, "/product")
    assert len(prod_posts) == 3, f"Expected 3 products, got {len(prod_posts)}"
    ord_posts = posts(mock, "/order")
    assert len(ord_posts) == 1
    order_lines = ord_posts[0][2].get("orderLines", [])
    assert len(order_lines) == 3, f"Expected 3 order lines, got {len(order_lines)}"
    vat_ids = [ol.get("vatType", {}).get("id") for ol in order_lines]
    assert 3 in vat_ids, f"Missing 25% VAT (id=3): {vat_ids}"
    assert 31 in vat_ids, f"Missing 15% VAT (id=31): {vat_ids}"
    assert 6 in vat_ids, f"Missing 0% VAT (id=6): {vat_ids}"


def test_C08_project_fixed_price_invoice():
    """Competition 14:05: Fixed price project 75% partial invoice (scored 6/8).
    LLM returned create_invoice but should delegate to project_invoice."""
    from task2.solution import handle_create_invoice
    mock = APIMock()
    entities = {
        "customerName": "Stormberg AS",
        "customerOrgNumber": "834028719",
        "projectName": "Digital transformasjon",
        "projectLeaderFirstName": "Hilde",
        "projectLeaderLastName": "Hansen",
        "projectLeaderEmail": "hilde.hansen@example.org",
        "fixedPrice": 203000,
        "invoicePercentage": 75,
        "lines": [{"description": "Digital transformasjon - delbetaling (75%)", "unitPrice": 152250, "count": 1}],
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_create_invoice("https://mock/v2", "tok", entities)
    assert result == True
    # Should have delegated to project_invoice — check project was created
    proj_posts = posts(mock, "/project")
    assert len(proj_posts) >= 1, "Project should be created"
    assert proj_posts[0][2]["name"] == "Digital transformasjon"
    # Invoice should exist
    ord_posts = posts(mock, "/order")
    assert len(ord_posts) >= 1, "Order should be created for invoice"
    # Invoice amount should be 75% of 203000 = 152250
    order_lines = ord_posts[0][2].get("orderLines", [])
    assert len(order_lines) >= 1
    amount = order_lines[0].get("unitPriceExcludingVatCurrency", 0) * order_lines[0].get("count", 1)
    assert abs(amount - 152250) < 1, f"Invoice amount should be 152250, got {amount}"


def test_C09_create_product_alt_keys():
    """Competition 15:05: Product with productName/netPrice keys (scored 0/7)"""
    from task2.solution import handle_create_product
    mock = APIMock()
    entities = {
        "productName": "Cloud-Speicher",
        "productNumber": "9235",
        "netPrice": 28800,
        "vatRate": 25,
        "priceWithVat": 36000,
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post):
        result = handle_create_product("https://mock/v2", "tok", entities)
    assert result == True
    p = posts(mock, "/product")
    assert len(p) == 1
    b = p[0][2]
    assert b["name"] == "Cloud-Speicher", f"name: {b.get('name')}"
    assert b["number"] == "9235"
    assert b["priceExcludingVatCurrency"] == 28800.0
    assert b["vatType"]["id"] == 3  # 25%


def test_C10_invoice_product_code_in_description():
    """Competition 15:48: Product codes embedded in description (scored 5/8).
    LLM sometimes returns 'Maintenance (6481)' instead of separate productNumber."""
    from task2.solution import handle_create_invoice
    mock = APIMock()
    # Simulate LLM returning codes in description (no productNumber)
    entities = {
        "customerName": "Rivière SARL",
        "customerOrgNumber": "909579791",
        "lines": [
            {"description": "Maintenance (6481)", "unitPrice": 28100, "count": 1, "vatRate": 25},
            {"description": "Design web (2618)", "unitPrice": 12600, "count": 1, "vatRate": 15},
            {"description": "Développement système (8754)", "unitPrice": 1800, "count": 1, "vatRate": 0},
        ],
    }
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_create_invoice("https://mock/v2", "tok", entities)
    assert result == True
    # Products should be created from extracted codes
    prod_posts = posts(mock, "/product")
    assert len(prod_posts) == 3, f"Expected 3 products from description codes, got {len(prod_posts)}"
    prod_numbers = [p[2].get("number") for p in prod_posts]
    assert "6481" in prod_numbers
    assert "2618" in prod_numbers
    assert "8754" in prod_numbers
    # Descriptions should be cleaned (no code in parens)
    ord_posts = posts(mock, "/order")
    descs = [ol.get("description", "") for ol in ord_posts[0][2].get("orderLines", [])]
    assert all("(" not in d for d in descs), f"Descriptions still have codes: {descs}"


def test_C11_project_invoice_fixed_price_order_has_project():
    """Competition: Fixed price project invoice must link project to order"""
    from task2.solution import handle_project_invoice, normalize_entities
    mock = APIMock()
    entities = normalize_entities({
        "projectName": "Digital transformasjon",
        "customerName": "Strandvik AS",
        "customerOrgNumber": "883822684",
        "projectManagerName": "Jorunn Brekke",
        "projectManagerEmail": "jorunn.brekke@example.org",
        "fixedPrice": 318800,
        "invoicePercentage": 50,
    })
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put):
        result = handle_project_invoice("https://mock/v2", "tok", entities)
    assert result == True
    # Project must be created with correct name
    proj = posts(mock, "/project")
    assert len(proj) >= 1
    assert proj[0][2]["name"] == "Digital transformasjon", f"project name: {proj[0][2].get('name')}"
    assert proj[0][2].get("isFixedPrice") == True
    # Order must reference the project
    ord_posts = posts(mock, "/order")
    assert len(ord_posts) >= 1
    assert ord_posts[0][2].get("project") is not None, "Order must reference project"
    # Invoice amount should be 50% of 318800 = 159400
    order_lines = ord_posts[0][2].get("orderLines", [])
    assert len(order_lines) >= 1
    amount = order_lines[0].get("unitPriceExcludingVatCurrency", 0) * order_lines[0].get("count", 1)
    assert abs(amount - 159400) < 1, f"Invoice amount: {amount} != 159400"
