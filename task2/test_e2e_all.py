"""
End-to-end test: every known prompt → regex or LLM parse → handler → verify API calls.
Uses mocked API but real parsing (regex path only, LLM tested separately).

Run: python3 task2/test_e2e_all.py
"""
import json, sys, re
from unittest.mock import patch

sys.path.insert(0, '.')
from task2.solution import regex_parse, execute_plan, parse_with_claude

# Reuse APIMock from test_regression
class APIMock:
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
        if "/product" in path: return 200, {"values": []}
        if "/invoice" in path: return 200, {"values": []}
        if "/employee/employment" in path: return 200, {"values": []}
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


def posts(mock, path_substr):
    return [(m, p, b) for m, p, b in mock.calls if m == "POST" and path_substr in p]


REGEX_WHITELIST = {
    "create_department", "create_product", "create_customer", "create_employee",
    "create_supplier", "create_project", "run_payroll",
    "register_payment", "create_invoice", "register_supplier_invoice",
}

def run_prompt(prompt):
    """Parse + execute with mocked API (simulates production whitelist + complexity filter)."""
    import re as _re
    mock = APIMock()
    plan = regex_parse(prompt)
    # Apply whitelist like production — non-whitelisted types go to LLM
    if plan and plan.get("task_type") not in REGEX_WHITELIST:
        plan = None
    # Complexity guard: long prompts with 3+ actions → force LLM
    if plan and len(prompt) > 200:
        prompt_no_email = _re.sub(r'[\w.+-]+@[\w.-]+', '', prompt.lower())
        action_verbs = set(_re.findall(r'\b(?:opprett|create|registrer|registe|slett|delete|send|generer|generate|gere|oppdater|update|reverser|reverse|kjør|run|konverter|convert|créez|erstellen|envoyez|senden|fakturer|sett\s+fastpris|set\s+fixed|completa|configura)\b', prompt_no_email))
        if len(action_verbs) >= 2:
            plan = None
    if not plan:
        return None, mock
    with patch('task2.solution.tx_get', mock.get), \
         patch('task2.solution.tx_post', mock.post), \
         patch('task2.solution.tx_put', mock.put), \
         patch('task2.solution.tx_delete', mock.delete):
        execute_plan("http://test", "tok", plan, prompt)
    return plan, mock


# ====== ALL KNOWN PROMPTS WITH EXPECTED BEHAVIOR ======

TESTS = [
    # --- CUSTOMERS ---
    {
        "prompt": "Create the customer Brightstone Ltd with organization number 853284882. The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.",
        "task_type": "create_customer",
        "checks": lambda p, m: (
            len(posts(m, "/customer")) >= 1
            and posts(m, "/customer")[0][2].get("name") == "Brightstone Ltd"
            and posts(m, "/customer")[0][2].get("organizationNumber") == "853284882"
            and posts(m, "/customer")[0][2].get("email") == "post@brightstone.no"
        ),
    },
    {
        "prompt": 'Erstellen Sie den Kunden Bergwerk GmbH mit der Organisationsnummer 946768693. Die Adresse ist Solveien 5, 3015 Drammen. E-Mail: post@bergwerk.no.',
        "task_type": "create_customer",
        "checks": lambda p, m: (
            posts(m, "/customer")[0][2].get("name") == "Bergwerk GmbH"
            and posts(m, "/customer")[0][2].get("organizationNumber") == "946768693"
            and "Solveien 5" in str(posts(m, "/customer")[0][2])
        ),
    },

    # --- DEPARTMENTS ---
    {
        "prompt": 'Create three departments in Tripletex: "Innkjøp", "Drift", and "Kundeservice".',
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },
    {
        "prompt": 'Opprett tre avdelinger i Tripletex: "Økonomi", "Markedsføring" og "Kvalitetskontroll".',
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },
    {
        "prompt": 'Créez trois départements dans Tripletex : "Økonomi", "Kvalitetskontroll" et "Markedsføring".',
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },

    # --- PRODUCTS ---
    {
        "prompt": 'Crea el producto "Mantenimiento" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.',
        "task_type": "create_product",
        "checks": lambda p, m: (
            posts(m, "/product")[0][2].get("name") == "Mantenimiento"
            and str(posts(m, "/product")[0][2].get("number")) == "7266"
        ),
    },

    # --- PROJECTS ---
    {
        "prompt": 'Crea el proyecto "Actualización Sierra" vinculado al cliente Sierra SL (org. nº 953403188). El director del proyecto es Ana Romero (ana.romero@example.org).',
        "task_type": "create_project",
        "checks": lambda p, m: (
            len(posts(m, "/project")) >= 1
            and "Actualización Sierra" in str(posts(m, "/project")[0][2])
        ),
    },

    # --- SUPPLIERS ---
    {
        "prompt": "Registrer leverandøren Sjøbris AS med organisasjonsnummer 811212717. E-post: faktura@sjbris.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: (
            posts(m, "/supplier")[0][2].get("name") == "Sjøbris AS"
            and posts(m, "/supplier")[0][2].get("organizationNumber") == "811212717"
            and posts(m, "/supplier")[0][2].get("email") == "faktura@sjbris.no"
            and posts(m, "/supplier")[0][2].get("invoiceEmail") == "faktura@sjbris.no"
            and posts(m, "/supplier")[0][2].get("overdueNoticeEmail") == "faktura@sjbris.no"
        ),
    },
    {
        "prompt": "Registrieren Sie den Lieferanten Brückentor GmbH mit der Organisationsnummer 959331863. E-Mail: faktura@brckentorgmbh.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: (
            posts(m, "/supplier")[0][2].get("name") == "Brückentor GmbH"
            and posts(m, "/supplier")[0][2].get("overdueNoticeEmail") == "faktura@brckentorgmbh.no"
        ),
    },
    {
        "prompt": "Registrieren Sie den Lieferanten Waldstein GmbH mit der Organisationsnummer 891505019. E-Mail: faktura@waldsteingmbh.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: posts(m, "/supplier")[0][2].get("name") == "Waldstein GmbH",
    },
    {
        "prompt": "Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: posts(m, "/supplier")[0][2].get("name") == "Havbris AS",
    },
    {
        "prompt": "Registrer leverandøren Vestfjord AS med organisasjonsnummer 914908787. E-post: faktura@vestfjord.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: posts(m, "/supplier")[0][2].get("name") == "Vestfjord AS",
    },

    # --- EMPLOYEE ---
    {
        "prompt": "Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.",
        "task_type": "create_employee",
        "checks": lambda p, m: (
            posts(m, "/employee")[0][2].get("firstName") == "Anna"
            and posts(m, "/employee")[0][2].get("lastName") == "Schneider"
            and posts(m, "/employee")[0][2].get("dateOfBirth") == "2000-08-06"
            and posts(m, "/employee")[0][2].get("email") == "anna.schneider@example.org"
        ),
    },

    # --- TRAVEL EXPENSE ---
    {
        "prompt": 'Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for "Kundebesøk Bergen". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.',
        "task_type": "create_travel_expense",
        "checks": lambda p, m: True,
        "complex": True,  # Goes to LLM — travel expense not in regex whitelist
    },

    # --- SUPPLIER INVOICES ---
    {
        "prompt": "Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).",
        "task_type": "register_supplier_invoice",
        "checks": lambda p, m: (
            posts(m, "/supplierInvoice")[0][2].get("invoiceNumber") == "INV-2026-3624"
        ),
    },

    # --- INVOICES ---
    {
        "prompt": "Opprett og send en faktura til kunden Testfirma AS (org.nr. 987654321) på 15000 NOK uten MVA. Fakturaen gjelder Konsulentbistand.",
        "task_type": "create_invoice",
        "checks": lambda p, m: len(posts(m, "/order")) >= 1,  # creates order then converts
        "complex": True,
    },

    # --- PAYROLL (all languages) ---
    {
        "prompt": "Kjør lønn for Erik Nilsen (erik.nilsen@example.org) for denne måneden. Grunnlønn er 53350 kr. Legg til en engangsbonus på 11050 kr i tillegg til grunnlønnen.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 53350.0
            and p["entities"]["bonus"] == 11050.0
        ),
    },
    {
        "prompt": "Run payroll for Daniel Smith (daniel.smith@example.org) for this month. The base salary is 54850 NOK. Add a one-time bonus of 6800 NOK on top of the base salary.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 54850.0
            and p["entities"]["bonus"] == 6800.0
        ),
    },
    {
        "prompt": "Ejecute la nómina de María Rodríguez (maria.rodriguez@example.org) para este mes. El salario base es de 58750 NOK. Añada una bonificación única de 10750 NOK además del salario base.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 58750.0
            and p["entities"]["bonus"] == 10750.0
            and p["entities"]["employeeName"] == "María Rodríguez"
        ),
    },
    {
        "prompt": "Processe o salário de Lucas Santos (lucas.santos@example.org) para este mês. O salário base é de 59600 NOK. Adicione um bónus único de 12900 NOK além do salário base.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 59600.0
            and p["entities"]["bonus"] == 12900.0
            and p["entities"]["employeeName"] == "Lucas Santos"
        ),
    },
    {
        "prompt": "Processe o salário de Sofia Sousa (sofia.sousa@example.org) para este mês. O salário base é de 30200 NOK. Adicione um bónus único de 13750 NOK além do salário base.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 30200.0
            and p["entities"]["bonus"] == 13750.0
        ),
    },
    # --- REGISTER PAYMENT (multilingual) ---
    {
        "prompt": "The customer Windmill Ltd (org no. 830362894) has an outstanding invoice for 32200 NOK excluding VAT for \"System Development\". Register full payment on this invoice.",
        "task_type": "register_payment",
        "checks": lambda p, m: (
            p["entities"]["amount"] == 32200.0
            and p["entities"]["customerOrgNumber"] == "830362894"
        ),
    },
    {
        "prompt": "O cliente Floresta Lda (org. nº 906739542) tem uma fatura pendente de 6800 NOK sem IVA por \"Consultoria de dados\". Registe o pagamento total desta fatura.",
        "task_type": "register_payment",
        "checks": lambda p, m: (
            p["entities"]["amount"] == 6800.0
            and p["entities"]["customerOrgNumber"] == "906739542"
        ),
    },

    # --- REGISTER SUPPLIER INVOICE (multilingual) ---
    {
        "prompt": "Vi har mottatt faktura INV-2026-9382 fra leverandøren Stormberg AS (org.nr 877462137) på 61600 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).",
        "task_type": "register_supplier_invoice",
        "checks": lambda p, m: (
            p["entities"]["invoiceNumber"] == "INV-2026-9382"
            and p["entities"]["totalAmountInclVat"] == 61600.0
            and p["entities"]["vatRate"] == 25
            and p["entities"]["accountNumber"] == 6540
        ),
    },
    {
        "prompt": "Wir haben die Rechnung INV-2026-8810 vom Lieferanten Sonnental GmbH (Org.-Nr. 988926221) über 8050 NOK einschließlich MwSt. erhalten. Der Betrag betrifft Bürodienstleistungen (Konto 6540). Registrieren Sie die Lieferantenrechnung mit korrekter Vorsteuer (25 %).",
        "task_type": "register_supplier_invoice",
        "checks": lambda p, m: (
            p["entities"]["invoiceNumber"] == "INV-2026-8810"
            and p["entities"]["totalAmountInclVat"] == 8050.0
            and p["entities"]["accountNumber"] == 6540
        ),
    },
    {
        "prompt": "Recebemos a fatura INV-2026-5787 do fornecedor Luz do Sol Lda (org. nº 945810149) no valor de 35950 NOK com IVA incluído. O montante refere-se a serviços de escritório (conta 6540). Registe a fatura do fornecedor com o IVA dedutível correto (25 %).",
        "task_type": "register_supplier_invoice",
        "checks": lambda p, m: (
            p["entities"]["invoiceNumber"] == "INV-2026-5787"
            and p["entities"]["totalAmountInclVat"] == 35950.0
            and p["entities"]["accountNumber"] == 6540
        ),
    },

    # --- CREATE INVOICE (multilingual) ---
    {
        "prompt": "Crea y envía una factura al cliente Luna SL (org. nº 844920520) por 20200 NOK sin IVA. La factura es por Servicio de red.",
        "task_type": "create_invoice",
        "checks": lambda p, m: (
            p["entities"]["customerOrgNumber"] == "844920520"
            and p["entities"]["lines"][0]["unitPrice"] == 20200.0
        ),
    },

    # --- CREATE CUSTOMER (multilingual) ---
    {
        "prompt": "Create the customer Greenfield Ltd with organization number 872154442. The address is Sjøgata 85, 7010 Trondheim. Email: post@greenfield.no.",
        "task_type": "create_customer",
        "checks": lambda p, m: (
            posts(m, "/customer")[0][2].get("name") == "Greenfield Ltd"
            and posts(m, "/customer")[0][2].get("organizationNumber") == "872154442"
            and posts(m, "/customer")[0][2].get("email") == "post@greenfield.no"
        ),
    },
    {
        "prompt": "Crea el cliente Río Verde SL con número de organización 993179469. La dirección es Nygata 91, 3015 Drammen. Correo: post@rio.no.",
        "task_type": "create_customer",
        "checks": lambda p, m: (
            posts(m, "/customer")[0][2].get("name") == "Río Verde SL"
            and posts(m, "/customer")[0][2].get("organizationNumber") == "993179469"
        ),
    },

    # --- CREATE PRODUCT (multilingual) ---
    {
        "prompt": "Create the product \"Training Session\" with product number 2451. The price is 20350 NOK excluding VAT, using the standard 25% VAT rate.",
        "task_type": "create_product",
        "checks": lambda p, m: (
            posts(m, "/product")[0][2].get("name") == "Training Session"
            and str(posts(m, "/product")[0][2].get("number")) == "2451"
        ),
    },
    {
        "prompt": "Opprett produktet \"Analyserapport\" med produktnummer 1908. Prisen er 18050 kr eksklusiv MVA, og standard MVA-sats på 25 % skal nyttast.",
        "task_type": "create_product",
        "checks": lambda p, m: (
            posts(m, "/product")[0][2].get("name") == "Analyserapport"
            and str(posts(m, "/product")[0][2].get("number")) == "1908"
        ),
    },

    # --- CREATE DEPARTMENT (multilingual) ---
    {
        "prompt": "Create three departments in Tripletex: \"Drift\", \"Innkjøp\", and \"Salg\".",
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },
    {
        "prompt": "Crie três departamentos no Tripletex: \"Økonomi\", \"Innkjøp\" e \"Regnskap\".",
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },
    {
        "prompt": "Erstellen Sie drei Abteilungen in Tripletex: \"Utvikling\", \"Innkjøp\" und \"Økonomi\".",
        "task_type": "create_department",
        "checks": lambda p, m: len(posts(m, "/department")) == 3,
    },

    # --- CREATE EMPLOYEE (multilingual) ---
    {
        "prompt": "Temos um novo funcionário chamado Inês Almeida, nascido em 13. February 1990. Crie-o como funcionário com o e-mail ines.almeida@example.org e data de início 1. April 2026.",
        "task_type": "create_employee",
        "checks": lambda p, m: (
            posts(m, "/employee")[0][2].get("firstName") == "Inês"
            and posts(m, "/employee")[0][2].get("lastName") == "Almeida"
            and posts(m, "/employee")[0][2].get("email") == "ines.almeida@example.org"
        ),
    },

    # --- PAYROLL (more languages) ---
    {
        "prompt": "Run payroll for Victoria Lewis (victoria.lewis@example.org) for this month. The base salary is 52050 NOK. Add a one-time bonus of 7200 NOK on top of the base salary.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 52050.0
            and p["entities"]["bonus"] == 7200.0
        ),
    },
    {
        "prompt": "Køyr løn for Gunnhild Aasen (gunnhild.aasen@example.org) for denne månaden. Grunnløn er 51800 kr. Legg til ein eingongsbonus på 5700 kr i tillegg til grunnløna.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 51800.0
            and p["entities"]["bonus"] == 5700.0
        ),
    },
    {
        "prompt": "Processe o salário de Ana Ferreira (ana.ferreira@example.org) para este mês. O salário base é de 41750 NOK. Adicione um bónus único de 6750 NOK além do salário base.",
        "task_type": "run_payroll",
        "checks": lambda p, m: (
            p["entities"]["baseSalary"] == 41750.0
            and p["entities"]["bonus"] == 6750.0
        ),
    },

    # --- SUPPLIER (more languages) ---
    {
        "prompt": "Registrer leverandøren Bergvik AS med organisasjonsnummer 852000139. E-post: faktura@bergvik.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: (
            posts(m, "/supplier")[0][2].get("name") == "Bergvik AS"
            and posts(m, "/supplier")[0][2].get("email") == "faktura@bergvik.no"
        ),
    },
    {
        "prompt": "Enregistrez le fournisseur Rivière SARL avec le numéro d'organisation 853420409. E-mail : faktura@riviresarl.no.",
        "task_type": "create_supplier",
        "checks": lambda p, m: (
            posts(m, "/supplier")[0][2].get("name") == "Rivière SARL"
            and posts(m, "/supplier")[0][2].get("organizationNumber") == "853420409"
        ),
    },

    # --- COMPLEX TASKS (go to LLM) ---
    {
        "prompt": "El cliente Luna SL (org. nº 982580110) ha reclamado sobre la factura por \"Almacenamiento en la nube\" (31750 NOK sin IVA). Emita una nota de crédito completa que revierta la factura original.",
        "task_type": "create_credit_note",
        "checks": lambda p, m: True,
        "complex": True,
    },
    {
        "prompt": "Vi sendte en faktura på 4644 EUR til Stormberg AS (org.nr 917157812) da kursen var 11.51 NOK/EUR. Kunden har nå betalt, men kursen er 10.84 NOK/EUR. Registrer betalingen med korrekt valutadifferanse.",
        "task_type": "currency_payment",
        "checks": lambda p, m: True,
        "complex": True,
    },
    {
        "prompt": "En av kundene dine har en forfalt faktura. Finn den forfalte fakturaen og bokfør et purregebyr pa 55 kr. Debet kundefordringer (1500), kredit purregebyr (3400).",
        "task_type": "reminder_fee",
        "checks": lambda p, m: True,
        "complex": True,
    },

    # --- PROJECT INVOICE (must NOT be misclassified as register_payment) ---
    {
        "prompt": 'Sett fastpris 203000 kr på prosjektet "Digital transformasjon" for Stormberg AS (org.nr 834028719). Prosjektleder er Hilde Hansen (hilde.hansen@example.org). Fakturer kunden for 75 % av fastprisen som en delbetaling.',
        "task_type": "project_invoice",
        "checks": lambda p, m: True,
        "complex": True,  # Goes to LLM — regex should NOT match as register_payment
    },

    # --- TRAVEL EXPENSE ---
    {
        "prompt": 'Registrer en reiseregning for Sigurd Hansen (sigurd.hansen@example.org) for "Kundebesøk Kristiansand". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 3800 kr og taxi 200 kr.',
        "task_type": "create_travel_expense",
        "checks": lambda p, m: True,
        "complex": True,  # Goes to LLM
    },

    # --- MONTH-END CLOSING (multilingual) ---
    {
        "prompt": "Führen Sie den Monatsabschluss für März 2026 durch. Buchen Sie die Rechnungsabgrenzung (3400 NOK pro Monat von Konto 1700 auf Aufwand). Erfassen Sie die monatliche Abschreibung für eine Anlage mit Anschaffungskosten 289700 NOK und Nutzungsdauer 7 Jahre (lineare Abschreibung auf Konto 6020).",
        "task_type": "year_end_closing",
        "checks": lambda p, m: True,
        "complex": True,
    },
    {
        "prompt": "Perform month-end closing for March 2026. Post accrual reversal (6250 NOK per month from account 1700 to expense). Record monthly depreciation for a fixed asset with acquisition cost 77500 NOK and useful life 6 years (straight-line depreciation to account 6010).",
        "task_type": "year_end_closing",
        "checks": lambda p, m: True,
        "complex": True,
    },

    # --- EMPLOYEE FROM OFFER LETTER (PDF) ---
    {
        "prompt": "Has recibido una carta de oferta (ver PDF adjunto) para un nuevo empleado. Completa la incorporacion: crea el empleado, asigna el departamento correcto, configura los detalles de empleo con porcentaje y salario anual, y configura las horas de trabajo estandar.",
        "task_type": "create_employee",
        "checks": lambda p, m: True,
        "complex": True,  # PDF task — needs LLM
    },
]


if __name__ == "__main__":
    passed = 0
    failed = 0

    for t in TESTS:
        prompt = t["prompt"]
        expected = t["task_type"]
        is_complex = t.get("complex", False)
        short = prompt[:60]

        plan, mock = run_prompt(prompt)

        if plan is None:
            # Check if it would go to LLM (complex)
            if is_complex:
                print(f"  LLM  | {expected:30} | {short}")
                passed += 1
                continue
            print(f"  FAIL | {expected:30} | NO PARSE | {short}")
            failed += 1
            continue

        if plan["task_type"] != expected:
            print(f"  FAIL | expected={expected:25} got={plan['task_type']:25} | {short}")
            failed += 1
            continue

        # Run checks
        try:
            if t["checks"](plan, mock):
                passed += 1
            else:
                print(f"  FAIL | {expected:30} | CHECK FAILED | {short}")
                failed += 1
        except Exception as e:
            print(f"  FAIL | {expected:30} | ERROR: {e} | {short}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"E2E Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
