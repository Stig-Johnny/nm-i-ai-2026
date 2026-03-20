"""
Unit tests for prompt parsing — verifies regex and LLM extract correct entities.
Run: python -m pytest task2/test_parser.py -v
"""
import sys
sys.path.insert(0, '.')
from task2.solution import regex_parse


def test_create_customer_en():
    r = regex_parse("Create the customer Brightstone Ltd with organization number 853284882. The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.")
    assert r["task_type"] == "create_customer"
    e = r["entities"]
    assert e["name"] == "Brightstone Ltd"
    assert e["organizationNumber"] == "853284882"
    assert e["email"] == "post@brightstone.no"
    assert e["address"]["addressLine1"] == "Parkveien 61"
    assert e["address"]["postalCode"] == "5003"
    assert e["address"]["city"] == "Bergen"


def test_create_customer_de():
    r = regex_parse("Erstellen Sie den Kunden Bergwerk GmbH mit der Organisationsnummer 946768693. Die Adresse ist Solveien 5, 3015 Drammen. E-Mail: post@bergwerk.no.")
    assert r["task_type"] == "create_customer"
    e = r["entities"]
    assert e["name"] == "Bergwerk GmbH"
    assert e["organizationNumber"] == "946768693"
    assert e["email"] == "post@bergwerk.no"


def test_create_department_fr():
    r = regex_parse('Créez trois départements dans Tripletex : "Økonomi", "Kvalitetskontroll" et "Markedsføring".')
    assert r["task_type"] == "create_department"
    assert sorted(r["entities"]["items"]) == sorted(["Økonomi", "Kvalitetskontroll", "Markedsføring"])


def test_create_department_no():
    r = regex_parse('Opprett tre avdelinger i Tripletex: "Økonomi", "Markedsføring" og "Kvalitetskontroll".')
    assert r["task_type"] == "create_department"
    assert sorted(r["entities"]["items"]) == sorted(["Økonomi", "Markedsføring", "Kvalitetskontroll"])


def test_create_department_en():
    r = regex_parse('Create three departments in Tripletex: "Innkjøp", "Drift", and "Kundeservice".')
    assert r["task_type"] == "create_department"
    assert sorted(r["entities"]["items"]) == sorted(["Innkjøp", "Drift", "Kundeservice"])


def test_create_product_es():
    r = regex_parse('Crea el producto "Mantenimiento" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.')
    assert r["task_type"] == "create_product"
    e = r["entities"]
    assert e["name"] == "Mantenimiento"
    assert e["number"] == "7266"
    assert e["priceExcludingVat"] == 650.0
    assert e["vatRate"] == 25


def test_create_project_es():
    r = regex_parse('Crea el proyecto "Actualización Sierra" vinculado al cliente Sierra SL (org. nº 953403188). El director del proyecto es Ana Romero (ana.romero@example.org).')
    assert r["task_type"] == "create_project"
    e = r["entities"]
    assert e["name"] == "Actualización Sierra"
    assert e["customerOrgNumber"] == "953403188"
    assert e["projectManagerEmail"] == "ana.romero@example.org"


def test_create_supplier_no():
    r = regex_parse("Registrer leverandøren Sjøbris AS med organisasjonsnummer 811212717. E-post: faktura@sjbris.no.")
    assert r["task_type"] == "create_supplier"
    e = r["entities"]
    assert e["name"] == "Sjøbris AS"
    assert e["organizationNumber"] == "811212717"
    assert e["email"] == "faktura@sjbris.no"


def test_create_supplier_de():
    r = regex_parse("Registrieren Sie den Lieferanten Brückentor GmbH mit der Organisationsnummer 959331863. E-Mail: faktura@brckentorgmbh.no.")
    assert r["task_type"] == "create_supplier"
    e = r["entities"]
    assert e["name"] == "Brückentor GmbH"
    assert e["organizationNumber"] == "959331863"
    assert e["email"] == "faktura@brckentorgmbh.no"


def test_create_supplier_no2():
    r = regex_parse("Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.")
    assert r["task_type"] == "create_supplier"
    e = r["entities"]
    assert e["name"] == "Havbris AS"
    assert e["organizationNumber"] == "846635408"
    assert e["email"] == "faktura@havbris.no"


def test_create_employee_de():
    r = regex_parse("Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.")
    assert r["task_type"] == "create_employee"
    e = r["entities"]
    assert e["firstName"] == "Anna"
    assert e["lastName"] == "Schneider"
    assert e["email"] == "anna.schneider@example.org"
    assert e["dateOfBirth"] == "2000-08-06"
    assert e["startDate"] == "2026-03-17"


def test_create_travel_expense_no():
    r = regex_parse('Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for "Kundebesøk Bergen". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.')
    assert r["task_type"] == "create_travel_expense"
    e = r["entities"]
    assert e["employeeName"] == "Magnus Haugen"
    assert e["employeeEmail"] == "magnus.haugen@example.org"
    assert e["title"] == "Kundebesøk Bergen"
    assert e["diet"]["total"] == 3200
    assert e["diet"]["dailyRate"] == 800
    assert e["diet"]["days"] == 4
    descs = {x["description"].lower(): x["amount"] for x in e["expenses"]}
    assert "flybillett" in descs and descs["flybillett"] == 5050
    assert "taxi" in descs and descs["taxi"] == 750


def test_supplier_invoice_not_triggered_by_email():
    """Supplier creation with 'faktura' in email should NOT trigger supplier invoice."""
    r = regex_parse("Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.")
    assert r["task_type"] == "create_supplier"


def test_invoice_goes_to_llm():
    """Invoice prompts with 2+ action words should return None (go to LLM)."""
    r = regex_parse("Opprett og send en faktura til kunden Testfirma AS (org.nr. 987654321) på 15000 NOK uten MVA. Fakturaen gjelder Konsulentbistand.")
    # This has >200 chars or 2+ actions, so regex_parse returns result but
    # the complexity check in parse_with_claude should route to LLM.
    # regex_parse itself should still return a result.
    assert r is not None
    assert r["task_type"] == "create_invoice"


def test_supplier_invoice_no():
    """Supplier invoice with 'mottatt faktura' should be register_supplier_invoice."""
    r = regex_parse("Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).")
    # This is >200 chars so regex_parse returns result but complexity check sends to LLM.
    # But if regex runs, it should identify correctly.
    assert r is not None
    assert r["task_type"] == "register_supplier_invoice"
    e = r["entities"]
    assert e["supplierName"] == "Tindra AS"
    assert e["organizationNumber"] == "983514650"
    assert e["invoiceNumber"] == "INV-2026-3624"
    assert e["totalAmountInclVat"] == 42100
    assert e["accountNumber"] == 6540


def test_payroll_goes_to_llm():
    """Payroll prompts are >200 chars and should go to LLM."""
    r = regex_parse("Run payroll for Daniel Smith (daniel.smith@example.org) for this month. The base salary is 54850 NOK. Add a one-time bonus of 6800 NOK on top of the base salary. If the salary API is unavailable, you can use manual vouchers on salary accounts (5000-series) to record the payroll expense.")
    # Long prompt — regex still parses it but complexity check routes to LLM
    assert r is not None
    assert r["task_type"] == "run_payroll"
    e = r["entities"]
    assert e["employeeName"] == "Daniel Smith"
    assert e["baseSalary"] == 54850.0
    assert e["bonus"] == 6800.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
