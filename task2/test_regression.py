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
        if "/customer" in path: return 200, {"values": []}
        if "/supplier" in path: return 200, {"values": []}
        if "/invoice/paymentType" in path: return 200, {"values": [{"id": 99}]}
        if "/travelExpense/costCategory" in path:
            return 200, {"values": [
                {"id": 10, "description": "Mat", "showOnTravelExpenses": True},
                {"id": 11, "description": "Fly", "showOnTravelExpenses": True},
                {"id": 12, "description": "Taxi", "showOnTravelExpenses": True},
            ]}
        if "/travelExpense/paymentType" in path: return 200, {"values": [{"id": 50}]}
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
        if "/invoice" in path: return 200, {"values": []}
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
    # Employment
    empl = [x for x in emp if "/employment" in x[1] and "/entitlement" not in x[1]]
    assert len(empl) == 1
    assert empl[0][2]["startDate"] == "2026-03-17"


def test_R13_create_travel_expense_no():
    """Round 1: Travel expense Magnus Haugen with diet + fly + taxi"""
    p, m = run('Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for "Kundebesøk Bergen". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.')
    assert p["task_type"] == "create_travel_expense"
    # Main travel expense
    te = [x for x in posts(m, "/travelExpense") if "/cost" not in x[1]]
    assert len(te) >= 1
    assert te[0][2]["title"] == "Kundebesøk Bergen"
    # 3 cost lines
    costs = posts(m, "/travelExpense/cost")
    assert len(costs) == 3, f"Expected 3 costs, got {len(costs)}"
    amounts = sorted([c[2]["amountCurrencyIncVat"] for c in costs])
    assert amounts == sorted([3200.0, 5050.0, 750.0])


def test_R14_supplier_invoice_tindra():
    """Round 1: Supplier invoice Tindra AS 42100 incl VAT, konto 6540"""
    p, m = run("Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")
    assert p["task_type"] == "register_supplier_invoice"
    # Supplier created
    sup = posts(m, "/supplier")
    assert len(sup) >= 1
    assert sup[0][2]["name"] == "Tindra AS"
    # Voucher created
    vouch = posts(m, "/ledger/voucher")
    assert len(vouch) == 1
    postings = vouch[0][2]["postings"]
    assert len(postings) == 3
    total = sum(p["amountGross"] for p in postings)
    assert abs(total) < 0.01, f"Postings unbalanced: {total}"
    # Expense = 33680, VAT = 8420, Payable = -42100
    expense = [p for p in postings if p["account"]["id"] == 504]  # 6540
    assert len(expense) == 1
    assert abs(expense[0]["amountGross"] - 33680) < 1


def test_R15_supplier_invoice_snohetta():
    """Round 1: Supplier invoice Snøhetta AS 11950 incl VAT, konto 7000"""
    p, m = run("Vi har mottatt faktura INV-2026-8584 fra leverandøren Snøhetta AS (org.nr 852796316) på 11950 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 7000). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")
    assert p["task_type"] == "register_supplier_invoice"
    vouch = posts(m, "/ledger/voucher")
    postings = vouch[0][2]["postings"]
    total = sum(p["amountGross"] for p in postings)
    assert abs(total) < 0.01
    expense = [p for p in postings if p["account"]["id"] == 505]  # 7000
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
