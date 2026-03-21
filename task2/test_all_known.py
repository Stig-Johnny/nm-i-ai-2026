"""
Replay ALL known competition prompts through the server.
Verifies task_type detection and tracks results.
Run: python3 task2/test_all_known.py

This is the master verification — every prompt ever seen gets tested.
"""
import json, sys, os, re, time
sys.path.insert(0, '.')

# Force reimport
for mod in list(sys.modules):
    if 'task2' in mod: del sys.modules[mod]
from task2.solution import regex_parse, parse_with_claude

# All known prompts with expected task types
KNOWN_PROMPTS = [
    # Suppliers
    ("Registrer leverandøren Havbris AS med organisasjonsnummer 846635408. E-post: faktura@havbris.no.", "create_supplier"),
    ("Registrer leverandøren Sjøbris AS med organisasjonsnummer 811212717. E-post: faktura@sjbris.no.", "create_supplier"),
    ("Registrer leverandøren Vestfjord AS med organisasjonsnummer 914908787. E-post: faktura@vestfjord.no.", "create_supplier"),
    ("Registrieren Sie den Lieferanten Brückentor GmbH mit der Organisationsnummer 959331863. E-Mail: faktura@brckentorgmbh.no.", "create_supplier"),
    ("Registrieren Sie den Lieferanten Waldstein GmbH mit der Organisationsnummer 891505019. E-Mail: faktura@waldsteingmbh.no.", "create_supplier"),

    # Customers
    ("Create the customer Brightstone Ltd with organization number 853284882. The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.", "create_customer"),
    ("Erstellen Sie den Kunden Bergwerk GmbH mit der Organisationsnummer 946768693. Die Adresse ist Solveien 5, 3015 Drammen. E-Mail: post@bergwerk.no.", "create_customer"),

    # Departments
    ("Create three departments in Tripletex: \"Innkjøp\", \"Drift\", and \"Kundeservice\".", "create_department"),
    ("Opprett tre avdelinger i Tripletex: \"Økonomi\", \"Markedsføring\" og \"Kvalitetskontroll\".", "create_department"),
    ('Créez trois départements dans Tripletex : "Økonomi", "Kvalitetskontroll" et "Markedsføring".', "create_department"),

    # Products
    ("Crea el producto \"Mantenimiento\" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.", "create_product"),

    # Projects
    ("Crea el proyecto \"Actualización Sierra\" vinculado al cliente Sierra SL (org. nº 953403188). El director del proyecto es Ana Romero (ana.romero@example.org).", "create_project"),
    ("Erstellen Sie das Projekt \"Implementierung Eichenhof\" verknüpft mit dem Kunden Eichenhof GmbH (Org.-Nr. 887635463). Projektleiter ist Leon Richter (leon.richter@example.org).", "create_project"),

    # Employee
    ("Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.", "create_employee"),

    # Travel expense
    ("Registrer en reiseregning for Magnus Haugen (magnus.haugen@example.org) for \"Kundebesøk Bergen\". Reisen varte 4 dager med diett (dagsats 800 kr). Utlegg: flybillett 5050 kr og taxi 750 kr.", "create_travel_expense"),

    # Invoices (simple)
    ("Opprett og send en faktura til kunden Testfirma AS (org.nr. 987654321) på 15000 NOK uten MVA. Fakturaen gjelder Konsulentbistand.", "create_invoice"),
    ("Erstellen und senden Sie eine Rechnung an den Kunden Bergwerk GmbH (Org.-Nr. 868341580) über 18200 NOK ohne MwSt. Die Rechnung betrifft Analysebericht.", "create_invoice"),
    ('Créez et envoyez une facture au client Prairie SARL (nº org. 818016662) de 7200 NOK hors TVA. La facture concerne Rapport d\'analyse.', "create_invoice"),
    ("Crea y envía una factura al cliente Luna SL (org. nº 931597922) por 5450 NOK sin IVA. La factura es por Sesión de formación.", "create_invoice"),

    # Invoices (multi-product with VAT) — should be create_invoice with products
    ("Create an invoice for the customer Ridgepoint Ltd (org no. 885181066) with three product lines: Software License (7496) at 15050 NOK with 25% VAT, Training Session (9589) at 4900 NOK with 15% VAT (food), and Web Design (5228) at 3550 NOK with 0% VAT (exempt).", "create_invoice"),
    ("Crea una factura para el cliente Sierra SL (org. nº 832052582) con tres líneas de producto: Sesión de formación (6481) a 28400 NOK con 25 % IVA, Diseño web (5795) a 11400 NOK con 15 % IVA (alimentos), y Mantenimiento (3074) a 3800 NOK con 0 % IVA (exento).", "create_invoice"),

    # Invoice with payment
    ("Opprett ein ordre for kunden Strandvik AS (org.nr 911845016) med produkta Skylagring (7865) til 38500 kr og Datarådgjeving (3949) til 18500 kr. Konverter ordren til faktura og registrer full betaling.", "invoice_with_payment"),
    ("Erstellen Sie einen Auftrag für den Kunden Waldstein GmbH (Org.-Nr. 975687821) mit den Produkten Netzwerkdienst (4366) zu 32750 NOK und Beratungsstunden (3402) zu 17450 NOK. Wandeln Sie den Auftrag in eine Rechnung um und registrieren Sie die vollständige Zahlung.", "invoice_with_payment"),

    # Supplier invoices
    ("Vi har mottatt faktura INV-2026-3624 fra leverandøren Tindra AS (org.nr 983514650) på 42100 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 6540). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).", "register_supplier_invoice"),
    ("Vi har mottatt faktura INV-2026-8584 fra leverandøren Snøhetta AS (org.nr 852796316) på 11950 kr inklusiv MVA. Beløpet gjelder kontortjenester (konto 7000). Registrer leverandørfakturaen med korrekt inngående MVA (25 %).", "register_supplier_invoice"),

    # Payroll
    ("Kjør lønn for Erik Nilsen (erik.nilsen@example.org) for denne måneden. Grunnlønn er 53350 kr. Legg til en engangsbonus på 11050 kr i tillegg til grunnlønnen. Dersom lønns-API-et ikke fungerer, kan du bruke manuelle bilag på lønnskontoer (5000-serien) for å registrere lønnskostnaden.", "run_payroll"),
    ("Run payroll for Daniel Smith (daniel.smith@example.org) for this month. The base salary is 54850 NOK. Add a one-time bonus of 6800 NOK on top of the base salary. If the salary API is unavailable, you can use manual vouchers on salary accounts (5000-series) to record the payroll expense.", "run_payroll"),
    ("Ejecute la nómina de María Rodríguez (maria.rodriguez@example.org) para este mes. El salario base es de 58750 NOK. Añada una bonificación única de 10750 NOK además del salario base.", "run_payroll"),
    ("Processe o salário de Lucas Santos (lucas.santos@example.org) para este mês. O salário base é de 59600 NOK. Adicione um bónus único de 12900 NOK além do salário base.", "run_payroll"),
    ("Processe o salário de Sofia Sousa (sofia.sousa@example.org) para este mês. O salário base é de 30200 NOK. Adicione um bónus único de 13750 NOK além do salário base.", "run_payroll"),

    # Project invoice (hourly)
    ('Registe 23 horas para Tiago Santos (tiago.santos@example.org) na atividade "Analyse" do projeto "Integração de plataforma" para Floresta Lda (org. nº 889395338). Taxa horária: 1050 NOK/h. Gere uma fatura de projeto ao cliente com base nas horas registadas.', "project_invoice"),

    # Project invoice (fixed price)
    ("Sett fastpris 374900 kr på prosjektet \"Datasikkerhet\" for Snøhetta AS (org.nr 840786692). Prosjektleder er Jonas Larsen (jonas.larsen@example.org). Fakturer kunden for 75 % av fastprisen som en delbetaling.", "project_invoice"),

    # Register payment
    ("Der Kunde Windkraft GmbH (Org.-Nr. 954808483) hat eine offene Rechnung über 47600 NOK ohne MwSt. für \"Systementwicklung\". Registrieren Sie die vollständige Zahlung dieser Rechnung.", "register_payment"),
]


if __name__ == "__main__":
    print(f"Testing {len(KNOWN_PROMPTS)} known prompts...\n")

    results = {"pass": 0, "fail": 0, "llm_needed": 0}

    for prompt, expected_type in KNOWN_PROMPTS:
        # Check complexity — would this go to LLM?
        prompt_no_email = re.sub(r'[\w.+-]+@[\w.-]+', '', prompt.lower())
        actions = len(re.findall(r'\b(?:opprett|create|registrer|registe|slett|delete|send|generer|generate|gere|faktura|fatura|invoice|rechnung|factura|betaling|payment|oppdater|update|reverser|reverse|kjør|run|konverter|convert|créez|erstellen|crea|envoyez|senden)\b', prompt_no_email))
        is_complex = len(prompt) > 200 or actions >= 2

        if is_complex:
            # Would go to LLM in production — can't test offline
            results["llm_needed"] += 1
            print(f"  LLM  | {expected_type:30} | {prompt[:60]}")
            continue

        # Test regex parse
        parsed = regex_parse(prompt)
        if not parsed:
            results["fail"] += 1
            print(f"  FAIL | {expected_type:30} | NO PARSE | {prompt[:60]}")
            continue

        got_type = parsed.get("task_type", "unknown")
        if got_type == expected_type:
            results["pass"] += 1
        else:
            results["fail"] += 1
            print(f"  FAIL | expected={expected_type:25} got={got_type:25} | {prompt[:60]}")

    print(f"\nResults: {results['pass']} pass, {results['fail']} fail, {results['llm_needed']} need LLM")
    print(f"Total: {len(KNOWN_PROMPTS)} prompts")
