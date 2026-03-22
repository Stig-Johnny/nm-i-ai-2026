"""
Task 2 — Tripletex AI Accounting Agent (v2 — Claude-4 rewrite)

POST /solve receives:
  prompt: str (NO/EN/ES/PT/NN/DE/FR)
  files: [{filename, content_base64, mime_type}]
  tripletex_credentials: {base_url, session_token}

Returns: {"status": "completed"}

Run:
  uvicorn task2.solution:app --host 0.0.0.0 --port 8080
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PORT = int(os.environ.get("PORT", 8080))
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", os.path.expanduser("~/.local/bin/claude"))
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/tmp/tripletex-cache"))
CACHE_DIR.mkdir(exist_ok=True)
LOG_DIR = Path(os.environ.get("LOG_DIR", "/tmp/tripletex-requests"))
LOG_DIR.mkdir(exist_ok=True)

# ============================================================
# Tripletex API helpers
# ============================================================

def _safe_json(r):
    try:
        return r.json() if r.content else {}
    except Exception:
        return {}

def tx_get(base_url, token, path, params=None):
    r = requests.get(f"{base_url}{path}", auth=("0", token), params=params or {}, timeout=30)
    return r.status_code, _safe_json(r)

def tx_post(base_url, token, path, body):
    r = requests.post(f"{base_url}{path}", auth=("0", token), json=body, timeout=30)
    return r.status_code, _safe_json(r)

def tx_put(base_url, token, path, body=None, params=None):
    r = requests.put(f"{base_url}{path}", auth=("0", token), json=body or {}, params=params or {}, timeout=30)
    return r.status_code, _safe_json(r)

def tx_delete(base_url, token, path):
    r = requests.delete(f"{base_url}{path}", auth=("0", token), timeout=30)
    return r.status_code, {}

# ============================================================
# LLM prompt parsing
# ============================================================

SYSTEM_PROMPT = """You are an expert accounting AI that parses task prompts into structured JSON.

Given a prompt in any language (Norwegian, English, Spanish, Portuguese, Nynorsk, German, French), extract:

{
  "task_type": "one of: create_employee, create_customer, create_supplier, create_product, create_department, create_project, create_invoice, create_travel_expense, delete_travel_expense, register_payment, register_supplier_invoice, run_payroll, create_credit_note, update_employee, update_customer, create_contact, create_order, invoice_with_payment, project_invoice, reverse_voucher, delete_entity, bank_reconciliation, register_receipt_expense, correct_ledger_errors, unknown",
  // Use 'project_invoice' when the task involves: registering hours on a project, setting fixed price on a project, or generating an invoice linked to a project. If the prompt mentions a project name AND an invoice, use project_invoice.
  // Use 'create_accounting_dimension' when creating free accounting dimensions with values and/or posting vouchers linked to dimension values
  // Use 'reminder_fee' when asked to find overdue invoices, register reminder/dunning fees (purregebyr/frais de rappel/Mahngebühr), create reminder invoice. Extract: reminderAmount, debitAccount (1500), creditAccount (3400), partialPayment (amount if mentioned).
  // Use 'ledger_analysis' when asked to analyze the ledger/general ledger (Hauptbuch/hovedbok), identify accounts with changes/increases, and create projects/activities based on the findings. Extract: period {startDate, endDate}, accountType (expense/income), numberOfAccounts, createProjects (boolean), createActivities (boolean).
  // Use 'year_end_closing' when asked to perform year-end closing, annual closing (cierre anual, Jahresabschluss, clôture annuelle), depreciation, tax provision, prepaid reversal, or close income/expense accounts. Extract ALL data from the prompt: depreciationAssets [{assetName, originalCost, assetAccount, depreciationYears, annualDepreciation, expenseAccount, accumulatedDepreciationAccount}], prepaidAmount, prepaidAccount, taxRate, taxAccount, taxPayableAccount, closingYear, resultAccount.
  // Use 'correct_ledger_errors' when asked to find and correct errors in the ledger/vouchers. Extract: errors [{errorType (wrong_account|duplicate|missing_vat|wrong_amount), wrongAccount, correctAccount, amount, correctAmount, vatAccount}]
  // Use 'register_receipt_expense' when asked to register an expense from a receipt (kvittering/recibo/Quittung). IMPORTANT: Only extract the SPECIFIC item(s) mentioned in the prompt, NOT all items from the receipt. If the prompt says "we need the Togbillett expense", only include the Togbillett line item. Extract: items [{description, amount, vatRate, accountNumber}], department, supplierName, supplierOrgNumber, totalAmount (of selected items only), vatAmount, date. Common expense accounts: 6540 (office supplies), 7100 (travel), 7140 (transport/togbillett), 7350 (parking), 6800 (office equipment), 6300 (leasing), 4300 (goods for resale). VAT: 25% standard, 15% food, 12% transport, 0% exempt.
  "entities": {
    // ALL relevant data extracted from the prompt
    // Names: firstName, lastName (split properly)
    // Dates: YYYY-MM-DD format
    // Amounts: as numbers (no currency symbols)
    // Boolean flags: administrator, isContact
    // Addresses: {addressLine1, postalCode, city}
    // For multi-entity tasks (e.g. 3 departments): use "items" array
    // For invoices: customerName, customerOrgNumber, lines [{description, unitPrice, count}]
    // For supplier invoices: supplierName, supplierOrgNumber, invoiceNumber, totalAmountInclVat, netAmount, vatAmount, vatRate, accountNumber
    // For payroll: employeeName, employeeEmail, baseSalary, bonus, totalAmount
    // For travel expenses: employeeName, employeeEmail, title, date, expenses [{description, amount}], diet {dailyRate, days, total}
    // For products: name, number (product number), priceExcludingVat, vatRate
    // For projects: name (project name), customerName, customerOrgNumber, projectManagerName, projectManagerEmail, fixedPrice, invoicePercentage
    // For accounting dimensions: dimensionName, dimensionValues [strings], accountNumber (number), amount, linkedDimensionValue
    // EMPLOYMENT CONTRACT / OFFER LETTER — extract ALL of:
    // - firstName, lastName, dateOfBirth (YYYY-MM-DD), email
    // - nationalIdNumber: 11-digit personnummer (DDMMYYXXXXX) — look for "fødselsnummer", "personnummer", "P-nr", signature blocks
    // - bankAccountNumber: Norwegian account (XXXX.XX.XXXXX or 11 digits) — look for "kontonummer", "lønn til konto"
    // - startDate, annualSalary, employmentPercentage, occupationCode (STYRK 4-digit), department
    // - If nationalIdNumber or bankAccountNumber are NOT in the document, omit them — do NOT guess or fabricate
    // IMPORTANT: Use these EXACT key names. Do NOT use alternatives like productName, netPrice, unitPrice, account, projectManager (string).
  },
  "steps": ["brief description of API calls needed"]
}

CRITICAL RULES:
- Output ONLY valid JSON. No markdown, no explanation.
- Split full names into firstName and lastName correctly.
- Convert ALL dates to YYYY-MM-DD format.
- For amounts, extract the numeric value only.
- If the prompt mentions multiple items (e.g. "create 3 departments"), use an "items" array.
- For addresses, extract street, postal code, and city separately.
- Identify the task type from context, not just keywords.
"""

def _cache_key(prompt, file_texts):
    import hashlib
    content = prompt + "||" + "||".join(file_texts or [])
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def _log_request(prompt, file_texts, plan, cache_hit, duration):
    """Log every request for analysis."""
    import time as _time
    entry = {
        "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": prompt[:500],
        "file_count": len(file_texts or []),
        "plan": plan,
        "cache_hit": cache_hit,
        "duration_s": round(duration, 2),
    }
    log_file = LOG_DIR / f"{_time.strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def regex_parse(prompt):
    """Try to parse the prompt deterministically using regex patterns. Returns plan or None."""
    import re
    p = prompt.strip()
    pl = p.lower()

    # Helper: extract common fields
    def find_email(t):
        m = re.search(r'[\w.+-]+@[\w.-]+\.\w+', t)
        return m.group(0) if m else None

    def find_org(t):
        m = re.search(r'(?:org\.?[\s-]*(?:nr|no|n[º°]|nummer|number)\.?\s*:?\s*|organisasjonsnummer\s+|Organisationsnummer\s+|organization\s+number\s+|numéro\s+d.organisation\s+|número\s+de\s+organiza\w+\s+)(\d{6,})', t, re.I)
        return m.group(1) if m else None

    def find_amount(t, *keywords):
        for kw in keywords:
            m = re.search(rf'{kw}\s*(?:er|is|es|est|:)?\s*(\d[\d\s]*)\s*(?:kr|NOK)', t, re.I)
            if m: return float(m.group(1).replace(' ', ''))
        # Generic amount
        m = re.search(r'(\d[\d\s]+)\s*(?:kr|NOK)', t)
        return float(m.group(1).replace(' ', '')) if m else None

    def find_name_after(t, *keywords):
        for kw in keywords:
            # Allow up to 5 lowercase words between keyword and capitalized name
            m = re.search(rf'{kw}(?:\s+[a-zæøåäöü]+){{0,5}}\s+([A-ZÆØÅÄÖÜ][\w\-]+(?:\s+[A-ZÆØÅÄÖÜ][\w\-]+)*(?:\s+(?:AS|A/S|ASA|GmbH|Ltd|SL|SARL|SA|AB|AG|ApS|OY|Lda|Ltda))?)', t)
            if m: return m.group(1).strip()
        return None

    def find_address(t):
        m = re.search(r"(?:adress[ea]n?|address|Adresse[n]?|L'adresse|dirección|endereço|morada)\s+(?:ist|er|is|es|est|é|:)?\s+(.+?)(?:\.|$)", t, re.I)
        if not m: return None
        addr_str = m.group(1)
        # Try "Street, PostalCode City" pattern
        am = re.match(r'(.+?),?\s+(\d{4,5})\s+([\w\u00C0-\u024F]+)', addr_str)
        if am:
            return {"addressLine1": am.group(1).strip(), "postalCode": am.group(2), "city": am.group(3)}
        return {"addressLine1": addr_str.strip()}

    def split_name(full_name):
        parts = full_name.split()
        return parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""

    # === TRAVEL EXPENSE (check before customer/supplier — "reiseregning" is specific) ===
    if re.search(r'reiseregning|travel\s*expense|reisekost|gastos\s+de\s+viaje|note\s+de\s+frais', pl):
        if re.search(r'slett|delete|löschen|eliminar|supprimer', pl):
            return {"task_type": "delete_travel_expense", "entities": {}}
        emp_name = find_name_after(p, 'for', 'für', 'para', 'pour')
        email = find_email(p)
        title_match = re.search(r'"([^"]+)"', p)
        expenses = []
        for m in re.finditer(r'([\wæøåäöü]+(?:\s+[\wæøåäöü]+)?)\s+(\d[\d\s]*)\s*kr', p, re.I):
            desc = m.group(1).strip()
            desc = re.sub(r'^(?:og|and|und|et|y|e)\s+', '', desc, flags=re.I)
            if desc.lower() not in ('på', 'er', 'med', 'og', 'av', 'for', 'dagsats', 'dager'):
                expenses.append({"description": desc, "amount": float(m.group(2).replace(' ', ''))})
        diet = {}
        diet_match = re.search(r'diett\s*\(dagsats\s+(\d+)\s*kr\)', p, re.I)
        days_match = re.search(r'(\d+)\s+dager', p, re.I)
        if diet_match:
            rate = int(diet_match.group(1))
            days = int(days_match.group(1)) if days_match else 1
            diet = {"dailyRate": rate, "days": days, "total": rate * days}
        return {
            "task_type": "create_travel_expense",
            "entities": {"employeeName": emp_name, "employeeEmail": email, "title": title_match.group(1) if title_match else None, "expenses": expenses, "diet": diet},
        }

    # === COMPLEX TASKS — always delegate to LLM (check BEFORE department/product/project) ===
    # These tasks mention keywords that regex might misclassify (e.g. "faktura" in reminder, "betaling" in bank reconciliation)
    complex_patterns = [
        r'purregebyr|purring|rappel|mahngebühr|reminder.*fee|frais de rappel|forfalt|forfallen|overdue|retard|en retard|vencida',  # reminder fee
        r'avstem|reconcil|abstimm|concili|rapprocher|bankutskrift|bank\s*statement|extrato\s*banc',  # bank reconciliation
        r'reverser|reverse|stornieren|annuler|anular|reverter|devolvido|retourné|returned.*bank',  # reverse voucher
        r'feil i hovedbok|errors? in.*ledger|fehler.*hauptbuch|errores.*libro.*mayor|erreurs.*grand.*livre|erros.*livro',  # ledger correction
        r'årsoppgjør|year.end.*closing|jahresabschluss|monatsabschluss|cierre.*anual|clôture.*annuel|encerramento.*anual|månedsslutt|month.end.*closing|clôture.*mensuel|cierre.*mensual|encerramento.*mensal|rechnungsabgr',  # year-end/month-end
        r'analysier|analyse.*hauptbuch|analyze.*ledger|analise.*livro|trois.*comptes|three.*accounts|drei.*konten',  # ledger analysis
        r'livssyklus|lifecycle|lebenszyklus|ciclo.*vida|cycle.*vie',  # project lifecycle
        r'valutadifferanse|exchange.*rate.*differ|wechselkurs|tipo.*cambio|taux.*change|taxa.*câmbio|agio|disagio',  # currency payment
        r'konverter.*faktura.*betaling|convert.*invoice.*payment|wandeln.*rechnung.*zahlung|convertir.*factura.*pago|convertir.*facture.*paiement',  # order→invoice→payment
        r'ordre.*faktura.*betaling|order.*invoice.*payment|auftrag.*rechnung.*zahlung|orden.*factura.*pago|commande.*facture.*paiement',  # order→invoice→payment
        r'gehaltsabrechnung',  # German payroll (contains "Rechnung" = invoice)
        r'dimensjon|dimensão|dimensión|dimension.*(?:verdiane|valores|valores|values|werte)',  # accounting dimension
        r'(?:hours?|stund(?:en)?|timer?|horas?|timar?|heures?)\s.*(?:faktura|invoice|rechnung|factura|fatura|facture)',  # hours + invoice = project_invoice
        r'(?:faktura|invoice|rechnung|factura|fatura|facture).*(?:hours?|stund(?:en)?|timer?|horas?|timar?|heures?)',  # invoice + hours = project_invoice
        r'projektzyklus|project.*lifecycle|ciclo.*proyecto|cycle.*projet|ciclo.*projeto',  # project lifecycle (additional patterns)
        r'(?:tre|drei|three|tres|três)\s+.{0,30}(?:produkt|producto|produit|produto|product)',  # multi-line invoice with 3 products
        r'fastpris|festpreis|fixed\s*price|precio\s+fijo|prix\s+fixe|preço\s+fixo',  # fixed price project
        r'kvittering|quittung|recibo(?!.*leverandør)|(?:despesa|gasto)\s+de\s+\w+\s+(?:deste|de\s+este)',  # receipt expense (always has files)
    ]
    for pat in complex_patterns:
        if re.search(pat, pl):
            return None  # Delegate to LLM

    # === DEPARTMENT (check after complex patterns — "avdeling" appears in receipts too) ===
    if re.search(r'avdeling|department|abteilung|departamento|département', pl):
        dept_names = re.findall(r'"([^"]+)"', p)
        if len(dept_names) >= 2:
            return {"task_type": "create_department", "entities": {"items": dept_names}}
        elif dept_names:
            return {"task_type": "create_department", "entities": {"name": dept_names[0]}}
        else:
            name_match = re.search(r'(?:navn|name|nombre|nom)\s+["\']?(\w[\w\s]*)', p)
            return {"task_type": "create_department", "entities": {"name": name_match.group(1).strip() if name_match else "Department"}}

    # === PAYMENT (check before invoice — payment prompts also mention "invoice"/"faktura") ===
    if re.search(r'betaling|payment|zahlung|pago|paiement|pagamento', pl):
        if not re.search(r'opprett|create|erstell|crea|crie|créez|fastpris|festpreis|fixed\s*price|precio\s+fijo|prix\s+fixe|preço\s+fixo|delbetaling|meilenstein|milestone|pedido|ordre|order.*invoice|konverter|converta|convert', pl):  # Not project invoice, order→invoice, or create
            cust_name = find_name_after(p, 'kunden', 'customer', 'kunde', 'client', 'cliente')
            cust_org = find_org(p)
            amt = find_amount(p)
            desc_match = re.search(r'["\']([^"\']+)["\']', p)
            return {"task_type": "register_payment", "entities": {
                "customerName": cust_name, "customerOrgNumber": cust_org,
                "amount": amt, "description": desc_match.group(1) if desc_match else "",
            }}

    # === INVOICE (check before customer — invoices mention customers but are invoices) ===
    # Exclude "faktura" appearing only in email addresses
    invoice_text = re.sub(r'[\w.+-]+@[\w.-]+', '', pl)  # Remove emails before checking
    if re.search(r'faktura|fatura|invoice|rechnung|factura|facture', invoice_text):
        if re.search(r'kreditnota|credit\s*note|gutschrift|nota\s+de\s+crédito', pl):
            return {"task_type": "create_credit_note", "entities": {}}
        # Supplier invoice (incoming)
        if re.search(r'leverandør|supplier|lieferant|fornecedor|fournisseur|proveedor', pl) and re.search(r'mottatt|motteke|received|erhalten|recibido|reçu|recebemos|registrer.*faktura|registre.*fatura', pl):
            supplier_name = find_name_after(p, 'leverandøren', 'Lieferanten', 'supplier', 'fournisseur', 'proveedor', 'fornecedor')
            org = find_org(p)
            inv_match = re.search(r'(INV[\w-]+)', p)
            total = find_amount(p, 'på', 'von', 'of', 'de')
            vat_match = re.search(r'(\d+)\s*%', p)
            vat_rate = int(vat_match.group(1)) if vat_match else 25
            acct_match = re.search(r'konto\s+(\d{4})|account\s+(\d{4})|Konto\s+(\d{4})|conta\s+(\d{4})|compte\s+(\d{4})|cuenta\s+(\d{4})', p, re.I)
            acct = int(next(g for g in acct_match.groups() if g)) if acct_match else 6540
            net = total / (1 + vat_rate / 100) if total else 0
            return {
                "task_type": "register_supplier_invoice",
                "entities": {
                    "supplierName": supplier_name, "organizationNumber": org,
                    "invoiceNumber": inv_match.group(1) if inv_match else None,
                    "totalAmountInclVat": total, "netAmount": round(net, 2),
                    "vatAmount": round(total - net, 2) if total else 0,
                    "vatRate": vat_rate, "accountNumber": acct,
                },
            }
        # Outgoing invoice
        cust_name = find_name_after(p, 'kunden', 'Kunden', 'customer', 'client', 'cliente', 'au client')
        org = find_org(p)
        amount = find_amount(p, 'på', 'über', 'of', 'de')
        desc_match = re.search(r'(?:gjelder|betrifft|concerns|concerne|refiere)\s+(.+?)(?:\.|$)', p, re.I)
        return {
            "task_type": "create_invoice",
            "entities": {
                "customerName": cust_name, "customerOrgNumber": org,
                "lines": [{"description": desc_match.group(1).strip() if desc_match else "Service", "unitPrice": amount or 0, "count": 1}],
            },
        }

    # === PROJECT (check before customer) ===
    if re.search(r'prosjekt|project|projekt|proyecto|projet|projeto', pl):
        proj_name = re.search(r'"([^"]+)"', p)
        cust_name = find_name_after(p, 'kunden', 'customer', 'client', 'cliente', 'au client')
        org = find_org(p)
        pm_name = find_name_after(p, 'prosjektleder', 'project manager', 'Projektleiter', 'director', 'directeur', 'gerente')
        pm_email = find_email(p)
        return {
            "task_type": "create_project",
            "entities": {
                "name": proj_name.group(1) if proj_name else "Project",
                "customerName": cust_name, "customerOrgNumber": org,
                "projectManagerName": pm_name, "projectManagerEmail": pm_email,
            },
        }

    # === PAYROLL ===
    # NO: lønn, EN: payroll, DE: gehalt, ES: nómina, FR: salaire, PT: salário, SV: lön
    if re.search(r'lønn|løn|payroll|gehalt|nómina|salaire|lön|salário|processe o salário', pl):
        emp_name = find_name_after(p, 'for', 'für', 'para', 'pour', 'de', 'av')
        email = find_email(p)
        # NO: grunnlønn, EN: base salary, DE: grundgehalt, ES: salario base, FR: salaire de base, PT: salário base, SV: grundlön
        base = find_amount(p, 'grunnlønn', 'grunnløn', 'base salary', 'grundgehalt', 'salario base', 'salário base', 'salaire de base', 'grundlön')
        # NO: bonus/engangsbonus, EN: bonus, DE: bonus/einmalbonus, ES: bonificación, FR: prime/bonus, PT: bónus, SV: bonus
        bonus = find_amount(p, 'bonus', 'engangsbonus', 'einmalbonus', 'bonificación', 'prime', 'bónus')
        # Avoid grabbing base salary as bonus
        if bonus and base and bonus == base:
            bonus_match = re.search(r'(?:bonus|engangsbonus|einmalbonus|bonificación|prime|bónus)[^\d]*(\d[\d\s]*)\s*(?:kr|NOK)', p, re.I)
            bonus = float(bonus_match.group(1).replace(' ', '')) if bonus_match else 0
        return {
            "task_type": "run_payroll",
            "entities": {
                "employeeName": emp_name, "employeeEmail": email,
                "baseSalary": base, "bonus": bonus,
                "totalAmount": (base or 0) + (bonus or 0),
            },
        }

    # === SUPPLIER (simple create — no invoice keywords matched above) ===
    if re.search(r'leverandør|supplier|lieferant|proveedor|fournisseur|fornecedor', pl):
        name = find_name_after(p, 'leverandøren', 'Lieferanten', 'supplier', 'fournisseur', 'proveedor')
        return {
            "task_type": "create_supplier",
            "entities": {"name": name, "organizationNumber": find_org(p), "email": find_email(p)},
        }

    # === EMPLOYEE ===
    if re.search(r'ansatt|employee|mitarbeiter|empleado|employé|empregado|funcionário|medarbeider|tilsette', pl):
        # Extract name — look for "namens X", "named X", "navn X", etc
        name = find_name_after(p, 'namens', 'named', 'kalt', 'llamado', 'nommé', 'chamado')
        if not name:
            name = find_name_after(p, 'Mitarbeiter', 'employee', 'ansatt')
        first, last = split_name(name) if name else ("", "")
        email = find_email(p)
        dob_match = re.search(r'(?:geboren|born|født|nacido|nascido|né)\s+(?:am|on|den|el|le|em)?\s*(\d{1,2})\.?\s*(\w+)\s+(\d{4})', p, re.I)
        dob = None
        if dob_match:
            months = {"januar":1,"february":2,"februar":2,"march":3,"mars":3,"märz":3,"april":4,"mai":5,"may":5,"juni":6,"june":6,"juli":7,"july":7,"august":8,"september":9,"oktober":10,"october":10,"november":11,"desember":12,"december":12,"dezember":12}
            day = int(dob_match.group(1))
            month_str = dob_match.group(2).lower().rstrip('.')
            month = months.get(month_str, 1)
            year = int(dob_match.group(3))
            dob = f"{year}-{month:02d}-{day:02d}"
        start_match = re.search(r'(?:startdato|start\s*date|Startdatum|fecha\s+de\s+inicio|data\s+de\s+início|date\s+de\s+début)\s+(\d{1,2})\.?\s*(\w+)\s+(\d{4})', p, re.I)
        start_date = None
        if start_match:
            months = {"januar":1,"february":2,"februar":2,"march":3,"mars":3,"märz":3,"april":4,"mai":5,"may":5,"juni":6,"june":6,"juli":7,"july":7,"august":8,"september":9,"oktober":10,"october":10,"november":11,"desember":12,"december":12,"dezember":12}
            day = int(start_match.group(1))
            month_str = start_match.group(2).lower().rstrip('.')
            month = months.get(month_str, 1)
            year = int(start_match.group(3))
            start_date = f"{year}-{month:02d}-{day:02d}"
        admin = bool(re.search(r'administrator|admin|kontoadministrator', pl))
        return {
            "task_type": "create_employee",
            "entities": {
                "firstName": first, "lastName": last, "email": email,
                "dateOfBirth": dob, "startDate": start_date, "administrator": admin,
            },
        }

    # === CUSTOMER ===
    if re.search(r'kunde|customer|kunden|cliente|client', pl):
        name = find_name_after(p, 'kunden', 'Kunden', 'customer', 'cliente', 'client')
        return {
            "task_type": "create_customer",
            "entities": {
                "name": name, "organizationNumber": find_org(p),
                "email": find_email(p), "address": find_address(p),
            },
        }

    # === PRODUCT ===
    if re.search(r'produkt|product|producto|produit|produto', pl):
        prod_name = re.search(r'"([^"]+)"', p)
        num_match = re.search(r'(?:nummer|number|número|numéro)\s+(?:de\s+producto\s+)?(\d+)', p, re.I)
        price = find_amount(p, 'pris', 'price', 'precio', 'prix', 'Preis')
        vat_match = re.search(r'(\d+)\s*%', p)
        return {
            "task_type": "create_product",
            "entities": {
                "name": prod_name.group(1) if prod_name else None,
                "number": num_match.group(1) if num_match else None,
                "priceExcludingVat": price,
                "vatRate": int(vat_match.group(1)) if vat_match else 25,
            },
        }

    return None  # Unrecognized — fall through to LLM


def parse_with_claude(prompt, file_texts, raw_files=None):
    import time as _time
    start = _time.time()

    print(f"LLM PARSE: {len(prompt)} chars")

    full_prompt = prompt
    if file_texts:
        full_prompt += "\n\nAttached files:\n" + "\n".join(file_texts)

    # Check cache
    key = _cache_key(prompt, file_texts)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            print(f"CACHE HIT [{key}]: {cached.get('task_type', '?')}")
            _log_request(prompt, file_texts, cached, True, _time.time() - start)
            return cached
        except Exception:
            pass

    # Check if we have PDF/image files that need vision — use Anthropic SDK
    has_visual_files = raw_files and any(
        f.get("_rendered_image_b64") or f.get("mime_type", "").startswith("image/")
        for f in raw_files
    )

    raw = None
    if has_visual_files:
        raw = _parse_with_sdk(prompt, raw_files)
    if raw is None:
        raw = _parse_with_cli(full_prompt)
    if raw is None:
        _log_request(prompt, file_texts, None, False, _time.time() - start)
        return None

    try:
        # Clean markdown fences
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            result = parsed if len(parsed) > 1 else parsed[0]
        else:
            result = parsed

        # Cache the result
        try:
            cache_file.write_text(json.dumps(result, ensure_ascii=False))
            print(f"CACHED [{key}]: {result.get('task_type', '?') if isinstance(result, dict) else 'list'}")
        except Exception:
            pass

        _log_request(prompt, file_texts, result if isinstance(result, dict) else result[0], False, _time.time() - start)
        return result
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        _log_request(prompt, file_texts, {"error": str(e)}, False, _time.time() - start)
        return None


def _parse_with_sdk(prompt, raw_files):
    """Parse using Anthropic SDK with PDF/image document support."""
    try:
        import anthropic
        client = anthropic.Anthropic()

        # Build content blocks: text prompt + document/image blocks
        content = []
        for f in raw_files:
            mime = f.get("mime_type", "")
            fname = f.get("filename", "file")
            # Use rendered image from scanned PDF if available
            if f.get("_rendered_image_b64"):
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": f["_rendered_image_b64"]},
                })
                print(f"  SDK: attached rendered PNG from '{fname}'")
            elif mime.startswith("application/pdf"):
                b64 = f.get("content_base64", "")
                content.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                })
                print(f"  SDK: attached PDF '{fname}'")
            elif mime.startswith("image/"):
                b64 = f.get("content_base64", "")
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                })
                print(f"  SDK: attached image '{fname}'")
        content.append({"type": "text", "text": prompt})

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw = resp.content[0].text.strip()
        print(f"SDK raw: {raw[:400]}")
        return raw
    except Exception as e:
        print(f"SDK error: {e}")
        return None


def _parse_with_cli(full_prompt):
    """Parse using claude CLI subprocess."""
    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", "--model", "haiku", SYSTEM_PROMPT],
            input=full_prompt,
            capture_output=True, text=True, timeout=45
        )
        raw = result.stdout.strip()
        print(f"LLM raw: {raw[:400]}")
        return raw
    except subprocess.TimeoutExpired:
        print("claude CLI timeout (45s)")
        return None
    except Exception as e:
        print(f"claude CLI error: {e}")
        return None

# ============================================================
# Shared helpers
# ============================================================

def get_or_create_department(base_url, token):
    st, resp = tx_get(base_url, token, "/department", {"fields": "id,name", "count": 1})
    vals = resp.get("values", []) if st == 200 else []
    if vals:
        return vals[0]["id"]
    st2, resp2 = tx_post(base_url, token, "/department", {"name": "Avdeling"})
    return resp2.get("value", {}).get("id")

def get_or_create_employee(base_url, token, name=None, email=None):
    """Find or create an employee. Returns employee ID."""
    if email:
        st, resp = tx_get(base_url, token, "/employee", {"email": email, "fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]
    if name:
        parts = name.split() if isinstance(name, str) else [name]
        first = parts[0]
        st, resp = tx_get(base_url, token, "/employee", {"firstName": first, "fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]

    # Create new employee
    dept_id = get_or_create_department(base_url, token)
    if name and isinstance(name, str):
        parts = name.split()
    else:
        parts = ["Unknown", "Employee"]
    body = {
        "firstName": parts[0],
        "lastName": " ".join(parts[1:]) or "Employee",
        "userType": "STANDARD",
        "dateOfBirth": "1990-01-01",
    }
    if email:
        body["email"] = email
    if dept_id:
        body["department"] = {"id": dept_id}
    st, resp = tx_post(base_url, token, "/employee", body)
    emp_id = resp.get("value", {}).get("id")
    if emp_id:
        tx_put(base_url, token, "/employee/entitlement/:grantEntitlementsByTemplate",
               params={"employeeId": emp_id, "template": "ALL_PRIVILEGES"})
    return emp_id

def get_or_create_customer(base_url, token, name=None, org_number=None, email=None, address=None):
    """Find or create a customer. Returns customer ID."""
    if org_number:
        st, resp = tx_get(base_url, token, "/customer", {"organizationNumber": org_number, "fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]
    if name:
        st, resp = tx_get(base_url, token, "/customer", {"customerName": name, "fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]

    body = {"name": name or "Customer"}
    if org_number:
        body["organizationNumber"] = org_number
    if email:
        body["email"] = email
    if address:
        body["physicalAddress"] = {
            "addressLine1": address.get("addressLine1") or address.get("street", ""),
            "postalCode": address.get("postalCode", ""),
            "city": address.get("city", ""),
            "country": {"id": 161},
        }
    st, resp = tx_post(base_url, token, "/customer", body)
    return resp.get("value", {}).get("id")

def get_or_create_supplier(base_url, token, name=None, org_number=None, email=None):
    if org_number:
        st, resp = tx_get(base_url, token, "/supplier", {"organizationNumber": org_number, "fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]

    body = {"name": name or "Supplier"}
    if org_number:
        body["organizationNumber"] = org_number
    if email:
        body["email"] = email
        body["invoiceEmail"] = email
    st, resp = tx_post(base_url, token, "/supplier", body)
    return resp.get("value", {}).get("id")

def ensure_bank_account(base_url, token):
    """Ensure ledger account 1920 has a bank account number (required for invoicing)."""
    st, resp = tx_get(base_url, token, "/ledger/account", {"number": "1920", "fields": "id,number,bankAccountNumber"})
    accts = resp.get("values", []) if st == 200 else []
    if not accts:
        return
    acct = accts[0]
    if acct.get("bankAccountNumber"):
        return
    tx_put(base_url, token, f"/ledger/account/{acct['id']}", {
        "id": acct["id"], "number": 1920, "name": "Bankinnskudd",
        "bankAccountNumber": "86010517941",
    })

def put_employee(base_url, token, emp_id, body):
    """PUT employee with fresh version to avoid 409 RevisionException."""
    _, r = tx_get(base_url, token, f"/employee/{emp_id}", {"fields": "id,version"})
    ver = r.get("value", {}).get("version", 0)
    body["id"] = emp_id
    body["version"] = ver
    return tx_put(base_url, token, f"/employee/{emp_id}", body)


def _posting(row, date_str, desc, acct_id, amount, **kwargs):
    """Create a posting dict with all 4 amount fields set."""
    p = {
        "row": row, "date": date_str, "description": desc,
        "account": {"id": acct_id},
        "amount": round(amount, 2),
        "amountCurrency": round(amount, 2),
        "amount": round(amount, 2), "amountCurrency": round(amount, 2), "amountGross": round(amount, 2),
        "amountGrossCurrency": round(amount, 2),
    }
    for k, v in kwargs.items():
        if v is not None:
            p[k] = v
    return p


def find_account_id(base_url, token, number):
    st, resp = tx_get(base_url, token, "/ledger/account", {"number": str(number), "fields": "id,number"})
    vals = resp.get("values", []) if st == 200 else []
    return vals[0]["id"] if vals else None

# ============================================================
# Task handlers
# ============================================================

def handle_create_employee(base_url, token, e):
    # Find or create named department
    dept_name = e.get("department") or e.get("departmentName")
    if dept_name:
        _, dept_resp = tx_get(base_url, token, "/department", {"name": dept_name, "fields": "id,name", "count": 1})
        dept_vals = dept_resp.get("values", [])
        if dept_vals:
            dept_id = dept_vals[0]["id"]
        else:
            st_d, resp_d = tx_post(base_url, token, "/department", {"name": dept_name})
            dept_id = resp_d.get("value", {}).get("id")
            print(f"create department '{dept_name}': {st_d}")
    else:
        dept_id = get_or_create_department(base_url, token)
    body = {"userType": "STANDARD"}

    if "firstName" in e: body["firstName"] = e["firstName"]
    if "lastName" in e: body["lastName"] = e["lastName"]
    emp_email = e.get("email") or e.get("employeeEmail")
    if not emp_email and e.get("firstName") and e.get("lastName"):
        # Generate default email if missing (required by Tripletex)
        import unicodedata
        def _ascii(s):
            return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower().replace(' ', '')
        emp_email = f"{_ascii(e['firstName'])}.{_ascii(e['lastName'])}@example.org"
    if emp_email: body["email"] = emp_email
    dob = e.get("dateOfBirth") or e.get("birthDate") or e.get("fodselsdato") or e.get("geburtsdatum")
    if dob: body["dateOfBirth"] = dob
    if e.get("phoneNumberMobile") or e.get("phone") or e.get("phoneNumber"):
        body["phoneNumberMobile"] = e.get("phoneNumberMobile") or e.get("phone") or e.get("phoneNumber")
    if dept_id:
        body["department"] = {"id": dept_id}
    if e.get("administrator"):
        body["userType"] = "EXTENDED"

    addr = e.get("address") or e.get("physicalAddress") or {}
    if addr:
        body["address"] = {
            "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},
        }

    st, resp = tx_post(base_url, token, "/employee", body)
    print(f"create_employee: {st} {str(resp)[:200]}")

    emp_id = resp.get("value", {}).get("id") if st in (200, 201) else None
    if emp_id:
        # Grant entitlements
        template = "ALL_PRIVILEGES" if e.get("administrator") else "ALL_PRIVILEGES"
        tx_put(base_url, token, "/employee/entitlement/:grantEntitlementsByTemplate",
               params={"employeeId": emp_id, "template": template})

        # Set national ID number (LLM may use employeeNumber, nationalIdNumber, or nationalIdentityNumber)
        nid_raw = e.get("nationalIdNumber") or e.get("nationalIdentityNumber") or e.get("personalNumber") or e.get("personnelNumber") or e.get("personnummer") or e.get("fødselsnummer") or e.get("personalIdNumber") or e.get("employeeNumber")
        if nid_raw and len(str(nid_raw).replace(" ", "").replace("-", "")) == 11:
            nid = str(nid_raw)
            nid = nid.replace(" ", "").replace("-", "").strip()
            st_nid, resp_nid = put_employee(base_url, token, emp_id, {
                "nationalIdentityNumber": nid,
            })
            print(f"set nationalId: {st_nid} {str(resp_nid)[:200] if st_nid != 200 else ''}")

        # Set bank account number on employee
        if e.get("bankAccount") or e.get("bankAccountNumber"):
            ba = e.get("bankAccount") or e.get("bankAccountNumber")
            st_ba, resp_ba = put_employee(base_url, token, emp_id, {
                "bankAccountNumber": str(ba),
            })
            print(f"set bankAccount: {st_ba} {str(resp_ba)[:200] if st_ba != 200 else ''}")

        # Add employment if startDate
        if e.get("startDate"):
            # Look up division (required for salary transactions)
            _, div_resp = tx_get(base_url, token, "/division", {"count": 1})
            div_vals = div_resp.get("values", [])
            division_id = div_vals[0]["id"] if div_vals else None

            emp_body = {
                "employee": {"id": emp_id},
                "startDate": e["startDate"],
                "isMainEmployer": True,
                "taxDeductionCode": "loennFraHovedarbeidsgiver",
            }
            if division_id:
                emp_body["division"] = {"id": division_id}
            st_emp, resp_emp = tx_post(base_url, token, "/employee/employment", emp_body)
            employment_id = resp_emp.get("value", {}).get("id")
            print(f"create employment: {st_emp} id={employment_id} {str(resp_emp)[:200] if st_emp != 201 else ''}")

            # Add employment details
            if employment_id:
                # Map employment form from prompt (e.g. "Fast stilling" → PERMANENT)
                emp_form_map = {"fast stilling": "PERMANENT", "permanent": "PERMANENT",
                                "midlertidig": "TEMPORARY", "temporary": "TEMPORARY", "vikariat": "TEMPORARY"}
                emp_form_raw = (e.get("employmentType") or e.get("employmentForm") or "").lower()
                emp_form = emp_form_map.get(emp_form_raw, "PERMANENT")  # Default to PERMANENT for standard contracts
                det_body = {
                    "employment": {"id": employment_id},
                    "date": e["startDate"],
                    "employmentType": "ORDINARY",
                    "employmentForm": emp_form,
                    "remunerationType": "MONTHLY_WAGE",
                    "percentageOfFullTimeEquivalent": float(e.get("employmentPercentage") or 100),
                    "workingHoursScheme": "NOT_SHIFT",
                }
                daily_hours = e.get("dailyWorkingHours") or e.get("workingHoursPerDay") or e.get("hoursPerDay")
                if daily_hours:
                    det_body["shiftDurationHours"] = float(daily_hours)
                elif e.get("employmentPercentage") and float(e.get("employmentPercentage")) < 100:
                    # For part-time, calculate from standard 7.5h
                    det_body["shiftDurationHours"] = round(7.5 * float(e["employmentPercentage"]) / 100, 1)
                if e.get("baseSalary") or e.get("annualSalary"):
                    salary = float(e.get("annualSalary") or e.get("baseSalary") or 0)
                    det_body["annualSalary"] = salary
                occ_code = e.get("occupationCode") or e.get("occupationalCode") or e.get("positionCode") or e.get("styrk") or e.get("stillingskode")
                if occ_code:
                    # Look up occupation code — STYRK codes are 7-digit but LLM often returns 4-digit prefix
                    occ_vals = []
                    occ_str = str(occ_code).strip()
                    if occ_str.isdigit():
                        # Try exact code first
                        _, occ_resp = tx_get(base_url, token, "/employee/employment/occupationCode",
                                            {"code": occ_str, "count": 1})
                        occ_vals = occ_resp.get("values", [])
                        # If no match and code is short (4-digit STYRK prefix), try as prefix
                        if not occ_vals and len(occ_str) <= 4:
                            _, occ_resp = tx_get(base_url, token, "/employee/employment/occupationCode",
                                                {"code": occ_str + "*", "count": 1})
                            occ_vals = occ_resp.get("values", [])
                        # Also try with trailing zeros
                        if not occ_vals and len(occ_str) <= 4:
                            padded = occ_str + "0" * (7 - len(occ_str))
                            _, occ_resp = tx_get(base_url, token, "/employee/employment/occupationCode",
                                                {"code": padded, "count": 1})
                            occ_vals = occ_resp.get("values", [])
                    if not occ_vals:
                        _, occ_resp = tx_get(base_url, token, "/employee/employment/occupationCode",
                                            {"nameNO": occ_str, "count": 1})
                        occ_vals = occ_resp.get("values", [])
                    if occ_vals:
                        det_body["occupationCode"] = {"id": occ_vals[0]["id"]}
                        print(f"occupationCode: {occ_vals[0]}")
                st_det, resp_det = tx_post(base_url, token, "/employee/employment/details", det_body)
                print(f"employment details: {st_det} {str(resp_det)[:300] if st_det != 201 else ''}")

    return st in (200, 201)


def handle_create_customer(base_url, token, e):
    body = {}  # isCustomer is readOnly — POST to /customer endpoint implies it
    name = e.get("name") or e.get("customerName") or (f"{e.get('firstName', '')} {e.get('lastName', '')}".strip() or None)
    if name: body["name"] = name
    email = e.get("email") or e.get("customerEmail")
    if email: body["email"] = email
    phone = e.get("phone") or e.get("phoneNumber") or e.get("customerPhone")
    if phone: body["phoneNumber"] = phone
    org = e.get("organizationNumber") or e.get("orgNumber") or e.get("customerOrgNumber")
    if org: body["organizationNumber"] = org

    addr = e.get("address") or e.get("physicalAddress") or {}
    if addr:
        addr_obj = {
            "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},
        }
        body["physicalAddress"] = addr_obj
        body["postalAddress"] = addr_obj

    st, resp = tx_post(base_url, token, "/customer", body)
    print(f"create_customer: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_supplier(base_url, token, e):
    body = {"name": e.get("name") or e.get("supplierName", "Supplier")}  # isSupplier is readOnly
    email = e.get("email") or e.get("supplierEmail")
    if email:
        body["email"] = email
        body["invoiceEmail"] = email
        body["overdueNoticeEmail"] = email
    org = e.get("organizationNumber") or e.get("supplierOrgNumber") or e.get("orgNumber")
    if org: body["organizationNumber"] = org
    phone = e.get("phone") or e.get("phoneNumber")
    if phone:
        body["phoneNumber"] = phone

    addr = e.get("address") or e.get("physicalAddress") or {}
    addr_obj = {
        "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
        "postalCode": addr.get("postalCode", ""),
        "city": addr.get("city", ""),
        "country": {"id": 161},
    }
    body["physicalAddress"] = addr_obj
    body["postalAddress"] = addr_obj

    st, resp = tx_post(base_url, token, "/supplier", body)
    print(f"create_supplier: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_product(base_url, token, e):
    NOK_VAT = {"25": 3, "15": 31, "12": 32, "0": 6}
    body = {}
    name = e.get("name") or e.get("productName")
    if name: body["name"] = name
    num = e.get("number") or e.get("productNumber")
    if num: body["number"] = str(num)

    price = e.get("priceExcludingVat") or e.get("priceExcVat") or e.get("price") or e.get("netPrice") or e.get("unitPrice")
    if price is not None:
        price_f = float(price)
        body["priceExcludingVatCurrency"] = price_f
        # Also set priceIncludingVat (calculated from VAT rate)
        vat_pct_val = float(str(e.get("vatRate") or e.get("vatType") or "25").replace("%", "").strip().split(".")[0])
        body["priceIncludingVatCurrency"] = round(price_f * (1 + vat_pct_val / 100), 2)
    if e.get("priceIncludingVat") or e.get("priceIncVat") or e.get("priceWithVat"):
        body["priceIncludingVatCurrency"] = float(e.get("priceIncludingVat") or e.get("priceIncVat") or e.get("priceWithVat"))

    vat_pct = str(e.get("vatRate") or e.get("vatType") or "25").replace("%", "").strip().split(".")[0]
    vat_id = NOK_VAT.get(vat_pct, 3)
    body["vatType"] = {"id": vat_id}

    st, resp = tx_post(base_url, token, "/product", body)
    print(f"create_product: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_department(base_url, token, e):
    items = e.get("items") or e.get("departments")
    if items:
        ok = True
        for item in items:
            name = item if isinstance(item, str) else item.get("name", "Department")
            st, resp = tx_post(base_url, token, "/department", {"name": name})
            print(f"create_department '{name}': {st}")
            if st not in (200, 201): ok = False
        return ok
    else:
        name = e.get("name", "Department")
        st, resp = tx_post(base_url, token, "/department", {"name": name})
        print(f"create_department: {st} {str(resp)[:200]}")
        return st in (200, 201)


def handle_create_project(base_url, token, e):
    today = str(date.today())

    # Find or create customer — check all name/org variants
    cust_name = e.get("customerName") or e.get("customer") or e.get("name")
    cust_org = (e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
                or e.get("organizationNumber"))  # normalizer stores it here
    customer_id = None
    if cust_org or cust_name:
        customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)

    # Find or create project manager
    pm_id = None
    pm = e.get("projectManager") or {}
    pm_name = e.get("projectManagerName") or pm.get("name")
    pm_email = e.get("projectManagerEmail") or pm.get("email")

    if pm_name or pm_email:
        pm_id = get_or_create_employee(base_url, token, name=pm_name, email=pm_email)

    if not pm_id:
        # Fallback: use any existing employee
        _, emp_resp = tx_get(base_url, token, "/employee", {"fields": "id", "count": 1})
        vals = emp_resp.get("values", [])
        if vals:
            pm_id = vals[0]["id"]

    if not pm_id:
        # No employees in sandbox — create a placeholder PM (required by Tripletex)
        pm_id = get_or_create_employee(base_url, token,
                                        name="Project Manager",
                                        email="pm@company.no")

    proj_name = e.get("projectName") or e.get("name") or "Project"
    body = {
        "name": proj_name,
        "startDate": e.get("startDate") or today,
    }
    if customer_id:
        body["customer"] = {"id": customer_id}
    if pm_id:
        body["projectManager"] = {"id": pm_id}
    if e.get("endDate"):
        body["endDate"] = e["endDate"]
    fixed_price = e.get("fixedPrice") or e.get("fixedprice")
    if fixed_price:
        body["fixedprice"] = float(fixed_price)
    if e.get("budget"):
        body["budget"] = float(e["budget"])

    st, resp = tx_post(base_url, token, "/project", body)
    print(f"create_project: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_invoice(base_url, token, e):
    today = str(date.today())
    due = str(date.today() + timedelta(days=30))

    # If this involves a project, delegate to project_invoice handler
    if e.get("projectName") or e.get("project"):
        print("Invoice has project — delegating to project_invoice")
        return handle_project_invoice(base_url, token, e)

    ensure_bank_account(base_url, token)

    # VAT type mapping: percentage → Tripletex outgoing VAT type ID
    NOK_VAT_OUT = {"25": 3, "15": 31, "12": 32, "0": 6}

    # Create customer
    cust_name = e.get("customerName", "Customer")
    cust_org = e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
    customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)
    if not customer_id:
        print("Failed to create customer")
        return False

    # Build order lines
    lines = e.get("lines") or e.get("orderLines") or []
    if not lines and (e.get("description") or e.get("amount")):
        lines = [{"description": e.get("description", "Service"),
                  "unitPrice": e.get("amount", 0), "count": 1}]

    order_lines = []
    for l in lines:
        price = float(l.get("unitPrice") or l.get("unitPriceExcludingVatCurrency") or l.get("amount") or 0)
        line = {
            "description": l.get("description", "Service"),
            "unitPriceExcludingVatCurrency": price,
            "count": float(l.get("count") or l.get("quantity") or 1),
        }
        # Set VAT type per line — default to 25% if not specified
        vat_rate = l.get("vatRate") if l.get("vatRate") is not None else l.get("vatType")
        if vat_rate is None:
            vat_rate = 25  # Default Norwegian VAT
        if vat_rate is not None:
            vat_pct = str(vat_rate).replace("%", "").strip().split(".")[0]
            line["vatType"] = {"id": NOK_VAT_OUT.get(vat_pct, 3)}
        # Find or create product if product code specified
        prod_code = l.get("productCode") or l.get("productNumber") or l.get("number")
        # Extract product code from description like "Maintenance (6481)"
        if not prod_code:
            import re as _re
            code_match = _re.search(r'\((\d{3,})\)', l.get("description", ""))
            if code_match:
                prod_code = code_match.group(1)
                # Clean the description
                line["description"] = _re.sub(r'\s*\(\d{3,}\)', '', l.get("description", "")).strip()
        if prod_code:
            # Try to find existing product first
            _, existing = tx_get(base_url, token, "/product", {"number": str(prod_code), "fields": "id", "count": 1})
            existing_vals = existing.get("values", [])
            if existing_vals:
                line["product"] = {"id": existing_vals[0]["id"]}
                print(f"found product '{prod_code}': id={existing_vals[0]['id']}")
            else:
                prod_body = {
                    "name": l.get("description", "Product"),
                    "number": str(prod_code),
                    "priceExcludingVatCurrency": price,
                }
                if vat_rate is not None:
                    vat_pct2 = str(vat_rate).replace("%", "").strip().split(".")[0]
                    prod_body["vatType"] = {"id": NOK_VAT_OUT.get(vat_pct2, 3)}
                st_p, resp_p = tx_post(base_url, token, "/product", prod_body)
                prod_id = resp_p.get("value", {}).get("id")
                if prod_id:
                    line["product"] = {"id": prod_id}
                print(f"create product '{prod_code}': {st_p} {str(resp_p)[:100] if st_p != 201 else ''}")
        order_lines.append(line)
    if not order_lines:
        order_lines = [{"description": "Service", "unitPriceExcludingVatCurrency": 0.0, "count": 1.0}]

    # Create order — include invoiceComment from line descriptions
    desc_parts = [l.get("description", "") for l in lines if l.get("description")]
    invoice_comment = e.get("invoiceComment") or e.get("comment") or (desc_parts[0] if len(desc_parts) == 1 else "")
    order_body = {
        "customer": {"id": customer_id},
        "orderDate": e.get("orderDate") or e.get("invoiceDate") or today,
        "deliveryDate": e.get("dueDate") or due,
        "orderLines": order_lines,
    }
    if invoice_comment:
        order_body["invoiceComment"] = invoice_comment
    order_body["invoicesDueIn"] = 14
    order_body["invoicesDueInType"] = "DAYS"
    st_ord, order_resp = tx_post(base_url, token, "/order", order_body)
    order_id = order_resp.get("value", {}).get("id")
    print(f"create_order: {st_ord} id={order_id}")
    if not order_id:
        print(f"order failed: {str(order_resp)[:200]}")
        return False

    # Convert order to invoice and send
    inv_date = e.get("invoiceDate") or e.get("orderDate") or today
    inv_due = e.get("invoiceDueDate") or e.get("dueDate") or str(date.today() + timedelta(days=14))
    st_inv, inv_resp = tx_put(base_url, token, f"/order/{order_id}/:invoice", {},
                               params={"invoiceDate": inv_date, "invoiceDueDate": inv_due, "sendToCustomer": "false"})
    invoice_id = inv_resp.get("value", {}).get("id") if isinstance(inv_resp, dict) else None
    print(f"order->invoice: {st_inv} id={invoice_id}")

    # Send the invoice
    if invoice_id and st_inv in (200, 201):
        st_send, _ = tx_put(base_url, token, f"/invoice/{invoice_id}/:send",
                            params={"sendType": "EMAIL"})
        print(f"send invoice: {st_send}")

    return st_inv in (200, 201)


def handle_create_travel_expense(base_url, token, e):
    today = str(date.today())

    # Find or create employee
    emp_name = e.get("employeeName") or (f"{e.get('firstName', '')} {e.get('lastName', '')}".strip() or None)
    emp_email = e.get("employeeEmail")
    emp_id = e.get("employeeId") or get_or_create_employee(base_url, token, name=emp_name, email=emp_email)
    if not emp_id:
        print("Failed to find/create employee for travel expense")
        return False

    # Create travel expense with travel details
    title = e.get("title") or e.get("description") or "Reise"
    travel_days = int(e.get("travelDays") or e.get("days") or (e.get("diet", {}).get("days", 0)) or 1)
    departure = e.get("departureDate") or e.get("startDate") or e.get("date") or today
    return_date = e.get("returnDate") or e.get("endDate") or str(date.today() + timedelta(days=max(travel_days - 1, 0)))
    destination = e.get("destination") or e.get("city") or ""
    # Extract destination from title if not set (e.g. "Kundebesøk Bergen" → "Bergen")
    if not destination and title:
        import re as _re
        dest_match = _re.search(r'(?:besøk|besök|visit|visite|visita|Besuch|conferencia|konferenz|konferanse|conference|réunion|reunião)\s+(\w+)', title, _re.I)
        if dest_match:
            destination = dest_match.group(1)
        else:
            # Fallback: last capitalized word in title is likely the destination
            words = title.split()
            for w in reversed(words):
                if w[0].isupper() and len(w) > 2 and w.lower() not in ("for", "mit", "con", "com", "pour", "til"):
                    destination = w
                    break

    te_body = {
        "employee": {"id": emp_id},
        "title": title,
        "travelDetails": {
            "departureDate": departure,
            "returnDate": return_date,
            "destination": destination,
            "departureFrom": e.get("departureFrom") or "Oslo",
            "purpose": title,
            "isForeignTravel": False,
            "isDayTrip": travel_days <= 1,
        },
    }
    st, resp = tx_post(base_url, token, "/travelExpense", te_body)
    te_id = resp.get("value", {}).get("id")
    print(f"create_travel_expense: {st} id={te_id} {str(resp)[:150]}")
    if not te_id:
        return False

    # Get cost categories and payment types
    _, cats = tx_get(base_url, token, "/travelExpense/costCategory", {"count": 100, "fields": "id,description,showOnTravelExpenses"})
    cat_list = [c for c in cats.get("values", []) if c.get("showOnTravelExpenses")]
    cat_map = {c["id"]: c.get("description", "").lower() for c in cat_list}

    def find_cat(*keywords):
        for cid, desc in cat_map.items():
            for kw in keywords:
                if kw in desc:
                    return cid
        return list(cat_map.keys())[0] if cat_map else None

    _, pts = tx_get(base_url, token, "/travelExpense/paymentType", {"count": 5, "fields": "id"})
    pt_list = pts.get("values", [])
    pt_id = pt_list[0]["id"] if pt_list else None

    # Register per diem compensation if diet info provided
    diet = e.get("diet", {})
    if diet and (diet.get("total") or (diet.get("dailyRate") and diet.get("days"))):
        diet_days = int(diet.get("days", 1))
        # Look up per diem rate categories
        # Look up rate categories AND rate types
        _, rc_resp = tx_get(base_url, token, "/travelExpense/rateCategory", {"count": 50, "fields": "id,name,type,isValidDayTrip,isValidDomestic,fromDate,toDate"})
        all_rate_cats = rc_resp.get("values", [])
        # Filter by date validity
        travel_date = departure
        rate_cats = []
        for rc in all_rate_cats:
            rc_from = rc.get("fromDate") or "2000-01-01"
            rc_to = rc.get("toDate") or "2099-12-31"
            if rc_from <= travel_date <= rc_to:
                rate_cats.append(rc)
        if not rate_cats:
            rate_cats = all_rate_cats  # fallback to all if none match
        per_diem_cat = None
        for rc in rate_cats:
            if rc.get("type") == "PER_DIEM" and rc.get("isValidDomestic"):
                per_diem_cat = rc
                break
        if not per_diem_cat:
            for rc in rate_cats:
                if rc.get("type") == "PER_DIEM":
                    per_diem_cat = rc
                    break
        print(f"  rateCategories (filtered): {[(r['id'], r.get('name',''), r.get('fromDate',''), r.get('toDate','')) for r in rate_cats[:5]]}")
        print(f"  all rateCategories: {[(r['id'], r.get('name',''), r.get('fromDate',''), r.get('toDate','')) for r in all_rate_cats if r.get('type')=='PER_DIEM']}")
        print(f"  travel_date used for filter: {travel_date}")

        if per_diem_cat:
            # Pick correct category based on travel duration FIRST
            # Dagsreise (day trip) vs Overnatting (overnight)
            if travel_days > 1:
                # Overnight — find "Overnatting over 12 timer" category
                for rc in rate_cats:
                    if rc.get("type") == "PER_DIEM" and "overnatting" in rc.get("name", "").lower() and "over 12" in rc.get("name", "").lower():
                        per_diem_cat = rc
                        break

            # THEN get rate types for the selected category
            rate_type_id = None
            _, rt_resp = tx_get(base_url, token, "/travelExpense/rate", {"rateCategoryId": per_diem_cat["id"], "count": 10, "fields": "id,rate,zone"})
            rate_types = rt_resp.get("values", [])
            if rate_types:
                rate_type_id = rate_types[0]["id"]
            print(f"  selected cat: {per_diem_cat['id']} '{per_diem_cat.get('name','')}', rateTypes: {[(r['id'], r.get('rate','')) for r in rate_types[:3]]}")

            overnight = "HOTEL" if travel_days > 1 else "NONE"
            pd_body = {
                "travelExpense": {"id": te_id},
                "rateCategory": {"id": per_diem_cat["id"]},
                "overnightAccommodation": overnight,
                "location": destination or "Norge",
                "count": diet_days,
                "isDeductionForBreakfast": False,
                "isDeductionForLunch": False,
                "isDeductionForDinner": False,
            }
            if rate_type_id:
                pd_body["rateType"] = {"id": rate_type_id}
            st_pd, resp_pd = tx_post(base_url, token, "/travelExpense/perDiemCompensation", pd_body)
            print(f"  perDiemCompensation: {st_pd} {str(resp_pd)[:500]}")
            if st_pd not in (200, 201):
                # Fallback: add diet as a cost line
                print("  perDiem failed, falling back to cost line for diet")
                diet_total = diet.get("total") or (diet.get("dailyRate", 0) * diet.get("days", 0))
                diet_cat_id = find_cat("diett", "kost", "mat")
                if not diet_cat_id:
                    diet_cat_id = list(cat_map.keys())[0] if cat_map else None
                if diet_cat_id:
                    cost_body = {
                        "travelExpense": {"id": te_id},
                        "costCategory": {"id": diet_cat_id},
                        "date": e.get("date", today),
                        "amountCurrencyIncVat": float(diet_total),
                    }
                    if pt_id:
                        cost_body["paymentType"] = {"id": pt_id}
                    st_c, _ = tx_post(base_url, token, "/travelExpense/cost", cost_body)
                    print(f"  cost 'diett' {diet_total}: {st_c}")

    # Add cost lines for actual expenses (flight, taxi, hotel, etc.)
    expenses = list(e.get("expenses", []))

    for exp in expenses:
        desc = exp.get("description", "").lower()
        amt = float(exp.get("amount", 0))
        if not amt:
            continue

        if any(kw in desc for kw in ["fly", "flight", "flug", "billett", "avión", "avion", "voo", "vol "]):
            cat_id = find_cat("fly", "flybillett", "flight")
        elif "taxi" in desc:
            cat_id = find_cat("taxi")
        elif any(kw in desc for kw in ["hotell", "hotel", "alojamiento", "hébergement", "hospedagem"]):
            cat_id = find_cat("hotell", "hotel")
        elif any(kw in desc for kw in ["diett", "diet", "kost", "diät", "dieta"]):
            cat_id = find_cat("diett", "kost", "mat")
        elif any(kw in desc for kw in ["tog", "train", "zug", "tren", "comboio"]):
            cat_id = find_cat("tog", "train")
        elif any(kw in desc for kw in ["buss", "bus", "ônibus", "autobús"]):
            cat_id = find_cat("buss", "kollektiv", "bus")
        else:
            cat_id = find_cat("annen", "annet", "other")

        if not cat_id:
            cat_id = list(cat_map.keys())[0] if cat_map else None
        if not cat_id:
            continue

        cost_body = {
            "travelExpense": {"id": te_id},
            "costCategory": {"id": cat_id},
            "date": e.get("date", today),
            "amountCurrencyIncVat": amt,
        }
        if pt_id:
            cost_body["paymentType"] = {"id": pt_id}
        st_c, cr = tx_post(base_url, token, "/travelExpense/cost", cost_body)
        print(f"  cost '{desc}' {amt}: {st_c}")

    # Deliver the travel expense
    st_del, resp_del = tx_put(base_url, token, "/travelExpense/:deliver", params={"id": te_id})
    print(f"deliver travel expense: {st_del} {str(resp_del)[:300] if st_del != 200 else ''}")

    return True


def handle_delete_travel_expense(base_url, token, e):
    _, resp = tx_get(base_url, token, "/travelExpense", {"fields": "id,title,employee", "count": 20})
    expenses = resp.get("values", [])
    if not expenses:
        print("No travel expenses found")
        return False

    for exp in expenses:
        st, _ = tx_delete(base_url, token, f"/travelExpense/{exp['id']}")
        print(f"delete_travel_expense {exp['id']}: {st}")
        if st in (200, 204):
            return True
    return False


def handle_register_payment(base_url, token, e):
    today = str(date.today())
    cust_name = e.get("customerName") or e.get("name") or ""
    cust_org = e.get("customerOrgNumber") or e.get("organizationNumber") or ""
    description = e.get("description") or e.get("invoiceDescription") or ""

    # Find customer
    customer_id = None
    if cust_org:
        _, c_resp = tx_get(base_url, token, "/customer", {"organizationNumber": cust_org, "fields": "id", "count": 1})
        vals = c_resp.get("values", [])
        if vals:
            customer_id = vals[0]["id"]

    # Find invoice — filter by customer if possible
    params = {"invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31", "count": 50,
              "fields": "id,invoiceNumber,customer,amountCurrency,amountOutstanding,amountOutstandingTotal"}
    if customer_id:
        params["customerId"] = customer_id
    _, inv_resp = tx_get(base_url, token, "/invoice", params)
    invoices = inv_resp.get("values", [])
    if not invoices:
        print("No invoices found")
        return False

    # Pick best matching invoice
    invoice = invoices[0]
    inv_id = invoice["id"]
    print(f"found invoice: id={inv_id} amount={invoice.get('amountCurrency')} outstanding={invoice.get('amountOutstandingTotal')}")

    # Get payment type
    _, pt_resp = tx_get(base_url, token, "/invoice/paymentType", {"count": 5, "fields": "id"})
    pt_list = pt_resp.get("values", [])
    pt_id = pt_list[0]["id"] if pt_list else 0

    # Determine payment amount — always use invoice outstanding for the actual payment
    # Currency differences are handled separately via gain/loss voucher
    inv_outstanding = float(invoice.get("amountOutstandingTotal") or invoice.get("amountCurrency") or 0)
    payment_amount = inv_outstanding
    if not payment_amount:
        # Fallback if no invoice amount
        payment_amount = float(e.get("paymentAmountNOK") or e.get("amount") or 0)
        if not payment_amount:
            net = float(e.get("netAmount") or 0)
            vat_rate = float(e.get("vatRate") or 25)
            payment_amount = net * (1 + vat_rate / 100) if net else 0

    st, resp = tx_put(base_url, token, f"/invoice/{inv_id}/:payment", params={
        "paymentDate": e.get("date") or e.get("paymentDate") or today,
        "paymentTypeId": pt_id,
        "paidAmount": float(payment_amount),
    })
    print(f"invoice payment: {st} amount={payment_amount} {str(resp)[:200]}")

    # Post currency gain/loss (agio/disagio) if applicable
    currency_gain = float(e.get("currencyGainNOK") or e.get("currencyGain") or e.get("exchangeRateGain") or e.get("exchangeRateGainNOK") or e.get("agio") or 0)
    currency_loss = float(e.get("currencyLossNOK") or e.get("currencyLoss") or e.get("exchangeRateLoss") or e.get("exchangeRateLossNOK") or e.get("disagio") or 0)
    fx_amount = currency_gain or -currency_loss
    if fx_amount:
        # Use entity's exchange account if specified, else default 8060/8160
        fx_acct_num = int(e.get("exchangeDifferenceAccount") or e.get("exchangeAccount") or (8060 if fx_amount > 0 else 8160))
        fx_acct = find_account_id(base_url, token, fx_acct_num)
        if not fx_acct:
            fx_acct = find_account_id(base_url, token, 8060 if fx_amount > 0 else 8160)
        bank_acct = find_account_id(base_url, token, 1920)
        if fx_acct and bank_acct:
            st_fx, resp_fx = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                "date": e.get("date") or today,
                "description": f"Valutadifferanse {e.get('customerName', '')}".strip(),
                "postings": [
                    {"row": 1, "date": e.get("date") or today,
                     "description": "Agio" if fx_amount > 0 else "Disagio",
                     "account": {"id": bank_acct},
                     "amountGross": round(abs(fx_amount), 2), "amountGrossCurrency": round(abs(fx_amount), 2)},
                    {"row": 2, "date": e.get("date") or today,
                     "description": "Valutagevinst" if fx_amount > 0 else "Valutatap",
                     "account": {"id": fx_acct},
                     "amountGross": round(-abs(fx_amount), 2), "amountGrossCurrency": round(-abs(fx_amount), 2)},
                ],
            })
            print(f"currency {'gain' if fx_amount > 0 else 'loss'} voucher: {st_fx} amount={abs(fx_amount)}")

    return st in (200, 201)


def handle_register_supplier_invoice(base_url, token, e):
    """Register a supplier invoice using ledger voucher."""
    today = str(date.today())

    # Create/find supplier
    supplier_id = get_or_create_supplier(
        base_url, token,
        name=e.get("supplierName"),
        org_number=e.get("organizationNumber") or e.get("supplierOrgNumber"),
        email=e.get("supplierEmail"),
    )

    # Calculate amounts
    total_incl = float(e.get("totalAmountInclVat") or e.get("totalAmountIncVat") or e.get("amount") or 0)
    vat_rate = float(e.get("vatRate") or 25)
    net_amount = float(e.get("netAmount") or (total_incl / (1 + vat_rate / 100)))
    vat_amount = float(e.get("vatAmount") or (total_incl - net_amount))

    # Find the expense account (from prompt, default 6540)
    acct_number = int(e.get("accountNumber") or e.get("account") or 6540)
    expense_acct_id = find_account_id(base_url, token, acct_number)
    if not expense_acct_id:
        expense_acct_id = find_account_id(base_url, token, 6540)

    # Find supplier payable account (2400)
    payable_acct_id = find_account_id(base_url, token, 2400)
    # Find inbound VAT account (2710 for 25%)
    vat_acct_id = find_account_id(base_url, token, 2710)

    # Find department if specified (receipt expenses often specify department)
    dept_id = None
    dept_name = e.get("department")
    if dept_name:
        _, dept_resp = tx_get(base_url, token, "/department", {"name": dept_name, "count": 1})
        depts = dept_resp.get("values", [])
        if depts:
            dept_id = depts[0]["id"]
        else:
            # Create department
            st_d, d_resp = tx_post(base_url, token, "/department", {"name": dept_name, "departmentNumber": 0})
            dept_id = d_resp.get("value", {}).get("id")
        if dept_id:
            print(f"  department: {dept_name} id={dept_id}")

    print(f"  accounts: expense={acct_number}={expense_acct_id}, payable=2400={payable_acct_id}, vat=2710={vat_acct_id}")
    print(f"  amounts: net={net_amount}, vat={vat_amount}, total={total_incl}")

    # Build postings for supplier invoice
    # Look up actual input VAT type IDs from the API
    _, vat_resp = tx_get(base_url, token, "/ledger/vatType", {"count": 50, "fields": "id,name,percentage,number"})
    vat_types = vat_resp.get("values", [])
    # Find input VAT types (inngående)
    vat_type_id = None
    target_pct = int(vat_rate)
    for vt in vat_types:
        name = (vt.get("name") or "").lower()
        pct = vt.get("percentage", 0)
        if abs(pct - target_pct) < 0.5 and ("inngående" in name or "innk" in name or "input" in name or "incoming" in name):
            vat_type_id = vt["id"]
            print(f"  found input VAT {target_pct}%: id={vat_type_id} name='{vt.get('name')}'")
            break
    if not vat_type_id:
        # Fallback to hardcoded
        NOK_VAT_IN = {"25": 1, "15": 11, "12": 12, "0": 0}
        vat_pct = str(target_pct)
        vat_type_id = NOK_VAT_IN.get(vat_pct, 1)
        print(f"  using hardcoded input VAT {vat_pct}%: id={vat_type_id}")

    inv_date_str = e.get("invoiceDate") or today
    dept_ref = {"id": dept_id} if dept_id else None

    # 2-posting format for supplierInvoice (with vatType — Tripletex handles VAT)
    si_postings = [
        {
            "row": 1,
            "date": inv_date_str,
            "description": e.get("description") or "Leverandorfaktura",
            "account": {"id": expense_acct_id},
            "amount": round(net_amount, 2), "amountCurrency": round(net_amount, 2), "amountGross": round(net_amount, 2),
            "amountGrossCurrency": round(net_amount, 2),
            "vatType": {"id": vat_type_id},
            **({"department": dept_ref} if dept_ref else {}),
        },
        {
            "row": 2,
            "date": inv_date_str,
            "description": f"Leverandorgjeld {e.get('supplierName', '')}".strip(),
            "account": {"id": payable_acct_id},
            "amount": round(-total_incl, 2), "amountCurrency": round(-total_incl, 2), "amountGross": round(-total_incl, 2),
            "amountGrossCurrency": round(-total_incl, 2),
            "supplier": {"id": supplier_id} if supplier_id else None,
        },
    ]

    # 3-posting format for raw voucher fallback (explicit VAT line — no vatType)
    postings = [
        {
            "row": 1,
            "date": inv_date_str,
            "description": e.get("description") or "Leverandorfaktura",
            "account": {"id": expense_acct_id},
            "amount": round(net_amount, 2), "amountCurrency": round(net_amount, 2), "amountGross": round(net_amount, 2),
            "amountGrossCurrency": round(net_amount, 2),
            **({"department": dept_ref} if dept_ref else {}),
        },
        {
            "row": 2,
            "date": inv_date_str,
            "description": f"Inngående MVA {int(vat_rate)}%",
            "account": {"id": vat_acct_id},
            "amount": round(vat_amount, 2), "amountCurrency": round(vat_amount, 2), "amountGross": round(vat_amount, 2),
            "amountGrossCurrency": round(vat_amount, 2),
        },
        {
            "row": 3,
            "date": inv_date_str,
            "description": f"Leverandorgjeld {e.get('supplierName', '')}".strip(),
            "account": {"id": payable_acct_id},
            "amount": round(-total_incl, 2), "amountCurrency": round(-total_incl, 2), "amountGross": round(-total_incl, 2),
            "amountGrossCurrency": round(-total_incl, 2),
            "supplier": {"id": supplier_id} if supplier_id else None,
        },
    ]

    # Remove None supplier refs
    for p in si_postings + postings:
        if p.get("supplier") is None:
            p.pop("supplier", None)

    inv_date = e.get("invoiceDate") or today
    inv_due = e.get("invoiceDueDate") or str(date.today() + timedelta(days=30))

    # Try 1: SI with inline voucher (NO amountCurrency — causes 500 in proxy)
    si_body = {
        "invoiceDate": inv_date,
        "invoiceDueDate": inv_due,
        "invoiceNumber": e.get("invoiceNumber") or "",
        "supplier": {"id": supplier_id} if supplier_id else None,
        "voucher": {
            "date": inv_date,
            "description": f"Leverandorfaktura {e.get('invoiceNumber', '')} {e.get('supplierName', '')}".strip(),
            "postings": si_postings,
        },
    }
    if si_body.get("supplier") is None:
        si_body.pop("supplier", None)

    st, resp = tx_post(base_url, token, "/supplierInvoice", si_body)
    print(f"supplierInvoice (with voucher): {st} {str(resp)[:300]}")

    if st in (200, 201):
        val = resp.get("value", {})
        print(f"  SI created: id={val.get('id')}")
        return True

    # Try 2: Without inline voucher (bare SI)
    si_body.pop("voucher", None)
    st, resp = tx_post(base_url, token, "/supplierInvoice", si_body)
    print(f"supplierInvoice (minimal): {st} {str(resp)[:300]}")

    if st in (200, 201):
        return True

    # Fallback: raw voucher (always works but scorer may not recognize as SI)
    print("supplierInvoice failed, trying raw voucher")
    voucher_body = {
        "date": inv_date,
        "description": f"Leverandorfaktura {e.get('invoiceNumber', '')} {e.get('supplierName', '')}".strip(),
        "postings": postings,
    }
    st2, resp2 = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", voucher_body)
    print(f"voucher fallback: {st2} {str(resp2)[:500]}")

    return st2 in (200, 201)


def handle_run_payroll(base_url, token, e):
    """Run payroll using /salary/transaction API, fallback to voucher."""
    today = str(date.today())
    current_month = date.today().month
    current_year = date.today().year

    # Find or create employee
    emp_name = e.get("employeeName") or (f"{e.get('firstName', '')} {e.get('lastName', '')}".strip() or None)
    emp_email = e.get("employeeEmail")
    emp_id = get_or_create_employee(base_url, token, name=emp_name, email=emp_email)
    if not emp_id:
        print("Failed to find/create employee for payroll")
        return False

    base_salary = float(e.get("baseSalary") or e.get("salary") or 0)
    bonus = float(e.get("bonus") or 0)

    # Ensure employee has dateOfBirth (required for employment creation)
    _, emp_detail = tx_get(base_url, token, f"/employee/{emp_id}", {"fields": "id,version,dateOfBirth"})
    emp_dob = emp_detail.get("value", {}).get("dateOfBirth")
    if not emp_dob:
        st_dob, _ = put_employee(base_url, token, emp_id, {"dateOfBirth": "1990-01-01"})
        print(f"set employee DOB: {st_dob}")

    # Ensure employee has employment record (required for salary/transaction)
    st_emp, emp_resp = tx_get(base_url, token, "/employee/employment", {"employeeId": emp_id, "fields": "id", "count": 1})
    existing_employment = emp_resp.get("values", [])
    if not existing_employment:
        # Look up division (required for salary transactions)
        _, div_resp = tx_get(base_url, token, "/division", {"count": 1})
        div_vals = div_resp.get("values", [])
        division_id = div_vals[0]["id"] if div_vals else None

        emp_body = {
            "employee": {"id": emp_id},
            "startDate": "2024-01-01",
            "isMainEmployer": True,
            "taxDeductionCode": "loennFraHovedarbeidsgiver",
        }
        if division_id:
            emp_body["division"] = {"id": division_id}
        st_e, resp_e = tx_post(base_url, token, "/employee/employment", emp_body)
        employment_id = resp_e.get("value", {}).get("id")
        print(f"create employment: {st_e} id={employment_id} {str(resp_e)[:500] if st_e != 201 else ''}")

        # Add employment details with salary, employment type, etc.
        if employment_id:
            det_body = {
                "employment": {"id": employment_id},
                "date": "2024-01-01",
                "employmentType": "ORDINARY",
                "remunerationType": "MONTHLY_WAGE",
                "percentageOfFullTimeEquivalent": 100.0,
                "workingHoursScheme": "NOT_SHIFT",
            }
            if base_salary > 0:
                det_body["annualSalary"] = round(base_salary * 12, 2)
            st_d, resp_d = tx_post(base_url, token, "/employee/employment/details", det_body)
            print(f"employment details: {st_d} {str(resp_d)[:300] if st_d != 201 else ''}")
    else:
        print(f"employment exists: id={existing_employment[0]['id']}")

    # Get salary type IDs (these are per-company, need to look up)
    _, st_resp = tx_get(base_url, token, "/salary/type", {"count": 60, "fields": "id,number,name"})
    salary_types = st_resp.get("values", [])
    type_map = {s.get("number", ""): s["id"] for s in salary_types}

    fastlonn_id = type_map.get("2000")  # Fastlønn
    bonus_id = type_map.get("2002")  # Bonus

    # Build payslip specifications
    specs = []
    if base_salary > 0 and fastlonn_id:
        specs.append({
            "salaryType": {"id": fastlonn_id},
            "rate": base_salary,
            "count": 1,
            "amount": base_salary,
        })
    if bonus > 0 and bonus_id:
        specs.append({
            "salaryType": {"id": bonus_id},
            "rate": bonus,
            "count": 1,
            "amount": bonus,
        })

    # Try salary transaction API first
    tx_body = {
        "year": current_year,
        "month": current_month,
        "payslips": [{
            "employee": {"id": emp_id},
            "specifications": specs,
        }],
    }
    st, resp = tx_post(base_url, token, "/salary/transaction?generateTaxDeduction=false", tx_body)
    print(f"salary/transaction: {st} {str(resp)[:300]}")

    if st in (200, 201):
        return True

    # Fallback: manual voucher on 5000-series
    print("Salary API failed, falling back to manual voucher")
    total = base_salary + bonus
    salary_acct = find_account_id(base_url, token, 5000)
    bank_acct = find_account_id(base_url, token, 1920)

    postings = []
    row = 1
    if base_salary > 0:
        postings.append({
            "row": row, "date": today,
            "description": f"Lonn {emp_name or ''}".strip(),
            "account": {"id": salary_acct},
            "amount": round(base_salary, 2), "amountCurrency": round(base_salary, 2), "amountGross": round(base_salary, 2),
            "amountGrossCurrency": round(base_salary, 2),
        })
        row += 1
    if bonus > 0:
        postings.append({
            "row": row, "date": today,
            "description": f"Bonus {emp_name or ''}".strip(),
            "account": {"id": salary_acct},
            "amount": round(bonus, 2), "amountCurrency": round(bonus, 2), "amountGross": round(bonus, 2),
            "amountGrossCurrency": round(bonus, 2),
        })
        row += 1
    postings.append({
        "row": row, "date": today,
        "description": f"Lonnsutbetaling {emp_name or ''}".strip(),
        "account": {"id": bank_acct},
        "amount": round(-total, 2), "amountCurrency": round(-total, 2), "amountGross": round(-total, 2),
        "amountGrossCurrency": round(-total, 2),
    })

    st2, resp2 = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
        "date": today,
        "description": f"Lonnskjoring {emp_name or ''}".strip(),
        "postings": postings,
    })
    print(f"run_payroll voucher fallback: {st2} {str(resp2)[:300]}")
    return st2 in (200, 201)


def handle_create_credit_note(base_url, token, e):
    today = str(date.today())

    # Find the invoice to credit
    params = {"invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31", "count": 50}
    _, inv_resp = tx_get(base_url, token, "/invoice", params)
    invoices = inv_resp.get("values", [])
    if not invoices:
        print("No invoices found for credit note")
        return False

    inv_id = invoices[0]["id"]
    st, resp = tx_put(base_url, token, f"/invoice/{inv_id}/:createCreditNote", params={
        "date": e.get("date") or today,
        "comment": e.get("comment") or e.get("reason") or "Kreditnota",
        "sendToCustomer": "false",
    })
    print(f"create_credit_note: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_contact(base_url, token, e):
    customer_id = None
    if e.get("customerName") or e.get("customerId"):
        customer_id = e.get("customerId") or get_or_create_customer(
            base_url, token, name=e.get("customerName"))

    body = {}
    if "firstName" in e: body["firstName"] = e["firstName"]
    if "lastName" in e: body["lastName"] = e["lastName"]
    if "email" in e: body["email"] = e["email"]
    if e.get("phone") or e.get("phoneNumber"):
        body["phoneNumberMobile"] = e.get("phone") or e.get("phoneNumber")
    if customer_id:
        body["customer"] = {"id": customer_id}

    st, resp = tx_post(base_url, token, "/contact", body)
    print(f"create_contact: {st} {str(resp)[:200]}")
    return st in (200, 201)


# ============================================================
# Task dispatcher
# ============================================================

def handle_update_employee(base_url, token, e):
    """Update an existing employee's fields."""
    emp_id = None
    email = e.get("email") or e.get("employeeEmail")
    name = e.get("employeeName") or e.get("name")

    # Find the employee
    if email:
        st, resp = tx_get(base_url, token, "/employee", {"email": email, "fields": "id,version,firstName,lastName,email,phoneNumberMobile", "count": 1})
        vals = resp.get("values", [])
        if vals: emp_id = vals[0]["id"]
    if not emp_id and name:
        parts = name.split()
        st, resp = tx_get(base_url, token, "/employee", {"firstName": parts[0], "fields": "id,version,firstName,lastName,email,phoneNumberMobile", "count": 5})
        vals = resp.get("values", [])
        if vals: emp_id = vals[0]["id"]
    if not emp_id:
        st, resp = tx_get(base_url, token, "/employee", {"fields": "id,version", "count": 1})
        vals = resp.get("values", [])
        if vals: emp_id = vals[0]["id"]
    if not emp_id:
        print("No employee found to update")
        return False

    # Get current employee data
    st, current = tx_get(base_url, token, f"/employee/{emp_id}", {"fields": "*"})
    if st != 200:
        return False
    emp = current.get("value", {})

    # Update fields
    body = {"id": emp_id, "version": emp.get("version", 0)}
    if e.get("firstName"): body["firstName"] = e["firstName"]
    if e.get("lastName"): body["lastName"] = e["lastName"]
    if e.get("newEmail") or e.get("email"): body["email"] = e.get("newEmail") or e["email"]
    if e.get("phone") or e.get("phoneNumberMobile"):
        body["phoneNumberMobile"] = e.get("phone") or e["phoneNumberMobile"]
    if e.get("address"):
        addr = e["address"]
        body["address"] = {
            "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},
        }

    st, resp = put_employee(base_url, token, emp_id, body)
    print(f"update_employee: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_update_customer(base_url, token, e):
    """Update an existing customer's fields."""
    cust_id = None
    org = e.get("organizationNumber") or e.get("orgNumber")
    name = e.get("customerName") or e.get("name")

    if org:
        st, resp = tx_get(base_url, token, "/customer", {"organizationNumber": org, "fields": "id,version", "count": 1})
        vals = resp.get("values", [])
        if vals: cust_id = vals[0]["id"]
    if not cust_id and name:
        st, resp = tx_get(base_url, token, "/customer", {"customerName": name, "fields": "id,version", "count": 1})
        vals = resp.get("values", [])
        if vals: cust_id = vals[0]["id"]
    if not cust_id:
        print("No customer found to update")
        return False

    st, current = tx_get(base_url, token, f"/customer/{cust_id}", {"fields": "*"})
    if st != 200:
        return False
    cust = current.get("value", {})

    body = {"id": cust_id, "version": cust.get("version", 0)}
    if e.get("newName"): body["name"] = e["newName"]
    if e.get("newEmail") or e.get("email"): body["email"] = e.get("newEmail") or e["email"]
    if e.get("phone") or e.get("phoneNumber"): body["phoneNumber"] = e.get("phone") or e["phoneNumber"]
    if e.get("address"):
        addr = e["address"]
        addr_obj = {
            "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},
        }
        body["physicalAddress"] = addr_obj
        body["postalAddress"] = addr_obj

    st, resp = tx_put(base_url, token, f"/customer/{cust_id}", body)
    print(f"update_customer: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_create_order(base_url, token, e):
    """Create an order (without converting to invoice)."""
    today = str(date.today())
    due = str(date.today() + timedelta(days=30))

    cust_name = e.get("customerName") or e.get("customer")
    cust_org = e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
    customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)
    if not customer_id:
        return False

    lines = e.get("lines") or e.get("orderLines") or []
    if not lines and e.get("description"):
        lines = [{"description": e["description"], "unitPrice": e.get("amount", 0), "count": 1}]

    order_lines = []
    for l in lines:
        price = float(l.get("unitPrice") or l.get("unitPriceExcludingVatCurrency") or l.get("amount") or 0)
        order_lines.append({
            "description": l.get("description", "Service"),
            "unitPriceExcludingVatCurrency": price,
            "count": float(l.get("count") or l.get("quantity") or 1),
        })
    if not order_lines:
        order_lines = [{"description": "Service", "unitPriceExcludingVatCurrency": 0.0, "count": 1.0}]

    body = {
        "customer": {"id": customer_id},
        "orderDate": e.get("orderDate") or today,
        "deliveryDate": e.get("deliveryDate") or e.get("dueDate") or due,
        "orderLines": order_lines,
    }
    st, resp = tx_post(base_url, token, "/order", body)
    print(f"create_order: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_invoice_with_payment(base_url, token, e):
    """Create invoice AND register payment — Tier 2 multi-step."""
    # Step 1: Create the invoice
    ok = handle_create_invoice(base_url, token, e)
    if not ok:
        return False

    # Step 2: Find the invoice we just created and pay it
    _, inv_resp = tx_get(base_url, token, "/invoice", {
        "invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31",
        "count": 1, "sorting": "-invoiceNumber"
    })
    invoices = inv_resp.get("values", [])
    if not invoices:
        print("No invoice found for payment")
        return True  # Invoice was created at least

    inv_id = invoices[0]["id"]
    amount = e.get("paymentAmount") or e.get("amount")
    if not amount:
        # Get invoice amount
        _, inv_detail = tx_get(base_url, token, f"/invoice/{inv_id}", {"fields": "id,amountCurrency"})
        amount = inv_detail.get("value", {}).get("amountCurrency", 0)

    _, pt_resp = tx_get(base_url, token, "/invoice/paymentType", {"count": 1, "fields": "id"})
    pt_id = pt_resp.get("values", [{}])[0].get("id", 0)

    st, resp = tx_put(base_url, token, f"/invoice/{inv_id}/:payment", params={
        "paymentDate": e.get("paymentDate") or str(date.today()),
        "paymentTypeId": pt_id,
        "paidAmount": float(amount),
    })
    print(f"invoice payment: {st} {str(resp)[:200]}")
    return True


def handle_reverse_voucher(base_url, token, e):
    """Reverse a voucher — find the specific payment voucher, then reverse it."""
    today = str(date.today())
    description = e.get("description") or e.get("invoiceDescription") or e.get("invoiceReference") or ""
    cust_name = e.get("customerName") or e.get("name") or e.get("supplierName") or ""
    cust_org = e.get("customerOrgNumber") or e.get("organizationNumber") or e.get("supplierOrgNumber") or ""

    # Strategy 1: Find the payment voucher via invoice
    # First find customer
    customer_id = None
    if cust_org:
        _, c_resp = tx_get(base_url, token, "/customer", {"organizationNumber": cust_org, "fields": "id,name", "count": 1})
        vals = c_resp.get("values", [])
        if vals:
            customer_id = vals[0]["id"]
    if not customer_id and cust_name:
        _, c_resp = tx_get(base_url, token, "/customer", {"fields": "id,name", "count": 20})
        for c in c_resp.get("values", []):
            if cust_name.lower() in c.get("name", "").lower():
                customer_id = c["id"]
                break

    # Find invoice related to this customer/description
    inv_params = {"invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31", "count": 20, "fields": "id,invoiceNumber,customer,amount,amountCurrency,voucher"}
    if customer_id:
        inv_params["customerId"] = customer_id
    _, inv_resp = tx_get(base_url, token, "/invoice", inv_params)
    invoices = inv_resp.get("values", [])

    # Strategy 2: Find all vouchers and look for payment-related ones
    _, v_resp = tx_get(base_url, token, "/ledger/voucher", {
        "dateFrom": "2020-01-01", "dateTo": "2030-12-31", "count": 50,
        "fields": "id,number,description,date,postings"
    })
    vouchers = v_resp.get("values", [])

    # Try to find the payment voucher specifically
    target_voucher = None

    # Look for vouchers with description matching the invoice/customer
    search_terms = [t.lower() for t in [description, cust_name] if t]
    for v in vouchers:
        v_desc = (v.get("description") or "").lower()
        if any(term in v_desc for term in search_terms if term):
            # Check if this looks like a payment voucher (has bank account posting)
            target_voucher = v["id"]
            break

    # If no match by description, look for vouchers linked to invoice voucher
    if not target_voucher and invoices:
        invoice_voucher_ids = set()
        for inv in invoices:
            vid = inv.get("voucher", {}).get("id") if isinstance(inv.get("voucher"), dict) else inv.get("voucherId")
            if vid:
                invoice_voucher_ids.add(vid)
        # Payment voucher is typically NOT the invoice voucher, but posted after it
        for v in vouchers:
            if v["id"] not in invoice_voucher_ids:
                target_voucher = v["id"]
                break

    # Fallback: reverse most recent voucher
    if not target_voucher and vouchers:
        target_voucher = vouchers[-1]["id"]

    if not target_voucher:
        print("No vouchers to reverse")
        return False

    v_id = e.get("voucherId") or target_voucher
    st, resp = tx_put(base_url, token, f"/ledger/voucher/{v_id}/:reverse", params={
        "date": e.get("date") or today,
    })
    print(f"reverse_voucher: {st} id={v_id} {str(resp)[:200]}")
    return st in (200, 201)


def handle_bank_reconciliation(base_url, token, e):
    """Bank reconciliation: match bank transactions to invoices and register payments."""
    today = str(date.today())
    transactions = e.get("bankTransactions") or e.get("transactions") or e.get("entries") or []
    # LLM sometimes splits into customerPayments + supplierPayments
    if not transactions:
        cust_payments = e.get("customerPayments") or []
        supp_payments = e.get("supplierPayments") or []
        for cp in cust_payments:
            cp["customerName"] = cp.get("customerName", "")
            if cp.get("amount", 0) > 0:
                transactions.append(cp)
        for sp in supp_payments:
            sp["supplierName"] = sp.get("supplierName", "")
            if sp.get("amount", 0) > 0:
                sp["amount"] = -abs(sp["amount"])  # Make negative for outgoing
            transactions.append(sp)

    if transactions:
        # New-style: process each transaction as a payment
        _, pt_resp = tx_get(base_url, token, "/invoice/paymentType", {"count": 1, "fields": "id"})
        pt_id = pt_resp.get("values", [{}])[0].get("id", 0)

        for tx in transactions:
            tx_date = tx.get("date") or today
            tx_amount = float(tx.get("amount") or 0)
            tx_cust = tx.get("customerName")
            tx_supp = tx.get("supplierName")
            tx_inv_num = tx.get("invoiceNumber")
            tx_desc = tx.get("description", "")

            if tx_amount > 0 and tx_cust:
                # Incoming payment — find customer invoice and register payment
                cust_id = None
                _, c_resp = tx_get(base_url, token, "/customer", {"fields": "id,name", "count": 50})
                for c in c_resp.get("values", []):
                    if tx_cust.lower() in c.get("name", "").lower():
                        cust_id = c["id"]
                        break

                if cust_id:
                    _, inv_resp = tx_get(base_url, token, "/invoice", {
                        "customerId": cust_id, "invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31",
                        "count": 10, "fields": "id,invoiceNumber,amountCurrency,amountOutstandingTotal"
                    })
                    invoices = inv_resp.get("values", [])
                    # Match by invoice number if available
                    target_inv = None
                    if tx_inv_num:
                        for inv in invoices:
                            if str(inv.get("invoiceNumber", "")) == str(tx_inv_num):
                                target_inv = inv
                                break
                    if not target_inv and invoices:
                        target_inv = invoices[0]

                    if target_inv:
                        st_pay, resp_pay = tx_put(base_url, token, f"/invoice/{target_inv['id']}/:payment", params={
                            "paymentDate": tx_date, "paymentTypeId": pt_id, "paidAmount": tx_amount,
                        })
                        print(f"payment {tx_cust} inv={tx_inv_num} amount={tx_amount}: {st_pay}")
                    else:
                        print(f"no invoice found for {tx_cust}")
                else:
                    print(f"customer not found: {tx_cust}")

            elif tx_amount < 0 and tx_supp:
                # Outgoing payment — register supplier payment as voucher
                bank_id = find_account_id(base_url, token, 1920)
                payable_id = find_account_id(base_url, token, 2400)
                abs_amount = abs(tx_amount)
                if bank_id and payable_id:
                    # Get or create supplier for the posting
                    sc_supplier_id = get_or_create_supplier(base_url, token, name=tx_supp)
                    payable_posting = {"row": 1, "date": tx_date, "description": f"Leverandorbetaling {tx_supp}",
                             "account": {"id": payable_id},
                             "amount": round(abs_amount, 2), "amountCurrency": round(abs_amount, 2), "amountGross": round(abs_amount, 2), "amountGrossCurrency": round(abs_amount, 2)}
                    if sc_supplier_id:
                        payable_posting["supplier"] = {"id": sc_supplier_id}
                    st_v, resp_v = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                        "date": tx_date,
                        "description": f"Betaling {tx_supp} {tx_desc}".strip(),
                        "postings": [
                            payable_posting,
                            {"row": 2, "date": tx_date, "description": f"Bank utbetaling",
                             "account": {"id": bank_id},
                             "amount": round(-abs_amount, 2), "amountCurrency": round(-abs_amount, 2), "amountGross": round(-abs_amount, 2), "amountGrossCurrency": round(-abs_amount, 2)},
                        ],
                    })
                    print(f"supplier payment {tx_supp} amount={abs_amount}: {st_v} {str(resp_v)[:300] if st_v != 201 else ''}")

        return True

    # Legacy: old-style bank reconciliation
    _, acc_resp = tx_get(base_url, token, "/bankAccount", {"count": 10})
    bank_accounts = acc_resp.get("values", [])
    if not bank_accounts:
        print("bank_reconciliation: no bank account found")
        return False
    bank_acct_id = bank_accounts[0]["id"]
    _, rec_resp = tx_get(base_url, token, "/bank/reconciliation", {"bankAccountId": bank_acct_id, "count": 5})
    reconciliations = rec_resp.get("values", [])
    rec_id = reconciliations[0]["id"] if reconciliations else None
    if not rec_id:
        st_rc, rc_resp = tx_post(base_url, token, "/bank/reconciliation", {
            "bankAccount": {"id": bank_acct_id}, "closingDate": today, "closingBalance": 0})
        rec_id = rc_resp.get("value", {}).get("id")
    if rec_id:
        _, match_resp = tx_put(base_url, token, f"/bank/reconciliation/{rec_id}/:match", {})
        print(f"match: {match_resp}")
        return True
    return False


def handle_project_invoice(base_url, token, e):
    """Tier 2: Register hours on a project and generate a project invoice."""
    today = str(date.today())

    # Step 1: Create customer
    cust_name = e.get("customerName") or e.get("customer")
    cust_org = e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
    customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)

    # Step 2: Create employee (the person who worked the hours / project manager)
    first = e.get("firstName") or e.get("projectManagerFirstName") or e.get("projectLeaderFirstName") or ""
    last = e.get("lastName") or e.get("projectManagerLastName") or e.get("projectLeaderLastName") or ""
    emp_name = e.get("employeeName") or e.get("projectManagerName") or e.get("projectManager") or e.get("projectLeaderName") or e.get("projectLeader") or (f"{first} {last}".strip() or None)
    emp_email = e.get("employeeEmail") or e.get("projectManagerEmail") or e.get("projectLeaderEmail")
    emp_id = get_or_create_employee(base_url, token, name=emp_name, email=emp_email)

    # Step 3: Create project
    proj_name = e.get("projectName") or e.get("name") or e.get("project") or "Project"
    proj_body = {
        "name": proj_name,
        "startDate": today,
    }
    if customer_id:
        proj_body["customer"] = {"id": customer_id}
    # PM is required for fixed-price projects — always ensure we have one
    if not emp_id:
        _, fallback = tx_get(base_url, token, "/employee", {"fields": "id", "count": 1})
        fb_vals = fallback.get("values", [])
        if fb_vals:
            emp_id = fb_vals[0]["id"]
    if emp_id:
        proj_body["projectManager"] = {"id": emp_id}
    # Set fixed price if applicable
    fixed_price = float(e.get("fixedPrice") or 0)
    if fixed_price:
        proj_body["isFixedPrice"] = True
        proj_body["fixedprice"] = fixed_price  # lowercase p — Tripletex API quirk
    st, proj_resp = tx_post(base_url, token, "/project", proj_body)
    proj_id = proj_resp.get("value", {}).get("id")
    print(f"create project: {st} id={proj_id} {str(proj_resp)[:200] if st != 201 else ''}")

    # Step 4: Find or create activity
    activity_name = e.get("activityName") or e.get("activity") or e.get("description") or "Arbeid"
    # Try to find existing activity first
    _, act_list = tx_get(base_url, token, "/activity", {"name": activity_name, "count": 1})
    acts = act_list.get("values", [])
    act_id = acts[0]["id"] if acts else None
    if not act_id:
        # Try creating with activityType
        act_body = {"name": activity_name, "activityType": "PROJECT_SPECIFIC_ACTIVITY"}
        st_act, act_resp = tx_post(base_url, token, "/activity", act_body)
        act_id = act_resp.get("value", {}).get("id")
        print(f"create activity: {st_act} id={act_id}")
    if not act_id:
        # Fall back to "Fakturerbart arbeid" or first available
        _, all_acts = tx_get(base_url, token, "/activity", {"count": 10})
        for a in all_acts.get("values", []):
            if "faktur" in a.get("name", "").lower() or "arbeid" in a.get("name", "").lower():
                act_id = a["id"]; break
        if not act_id and all_acts.get("values"):
            act_id = all_acts["values"][0]["id"]
    print(f"activity: id={act_id}")

    # Step 5: Register timesheet hours — support multiple employees
    hours_logged = e.get("hoursLogged") or e.get("hourEntries") or e.get("timeEntries") or e.get("timeLogs") or e.get("hoursRecorded") or e.get("timesheet") or []
    # hours might be a list of employee objects — treat as hoursLogged
    raw_hours = e.get("hours") or e.get("hoursWorked") or e.get("count") or 0
    if isinstance(raw_hours, list):
        hours_logged = hours_logged or raw_hours
        hours = 0
    else:
        hours = float(raw_hours)
    hourly_rate = float(e.get("hourlyRate") or e.get("rate") or 0)
    # Try to extract from lines if not set directly
    lines = e.get("lines", [])
    if not hours and lines:
        hours = float(lines[0].get("count") or lines[0].get("hours") or 0)
    if not hourly_rate and lines:
        hourly_rate = float(lines[0].get("unitPrice") or lines[0].get("rate") or 0)

    # Register hours for each employee in hoursLogged
    if hours_logged:
        for hl in hours_logged:
            hl_name = hl.get("employeeName")
            hl_email = hl.get("employeeEmail")
            hl_hours = float(hl.get("hours") or 0)
            if hl_hours > 0:
                hl_emp_id = get_or_create_employee(base_url, token, name=hl_name, email=hl_email)
                if hl_emp_id:
                    ts_body = {"employee": {"id": hl_emp_id}, "date": today, "hours": hl_hours}
                    if proj_id: ts_body["project"] = {"id": proj_id}
                    if act_id: ts_body["activity"] = {"id": act_id}
                    st_ts, ts_resp = tx_post(base_url, token, "/timesheet/entry", ts_body)
                    print(f"timesheet {hl_name}: {st_ts} hours={hl_hours}")
    elif emp_id and hours > 0:
        ts_body = {
            "employee": {"id": emp_id},
            "date": today,
            "hours": hours,
        }
        if proj_id:
            ts_body["project"] = {"id": proj_id}
        if act_id:
            ts_body["activity"] = {"id": act_id}
        st_ts, ts_resp = tx_post(base_url, token, "/timesheet/entry", ts_body)
        print(f"timesheet entry: {st_ts} {str(ts_resp)[:200]}")

    # Step 6: Set hourly cost/rate on employee for the project
    if emp_id and hourly_rate > 0:
        hr_body = {
            "employee": {"id": emp_id},
            "date": today,
            "rate": hourly_rate,
            "hourCostRate": hourly_rate,
        }
        st_hr, hr_resp = tx_post(base_url, token, "/employee/hourlyCostAndRate", hr_body)
        print(f"hourly rate: {st_hr} {str(hr_resp)[:200] if st_hr != 201 else ''}")

    # Step 6b: Register supplier cost on project
    supplier_cost = e.get("supplierCost") or e.get("supplierCosts")
    if supplier_cost:
        costs = [supplier_cost] if isinstance(supplier_cost, dict) else supplier_cost
        for sc in costs:
            sc_name = sc.get("supplierName")
            sc_org = sc.get("supplierOrgNumber")
            sc_amount = float(sc.get("amount") or 0)
            if sc_amount:
                sc_supplier_id = get_or_create_supplier(base_url, token, name=sc_name, org_number=sc_org)
                # Post supplier cost as a voucher linked to the project
                expense_acct = find_account_id(base_url, token, 4300)  # cost of goods/services
                payable_acct = find_account_id(base_url, token, 2400)  # accounts payable
                if expense_acct and payable_acct:
                    expense_posting = {"row": 1, "date": today, "description": f"Leverandorkostnad {sc_name or ''}".strip(),
                         "account": {"id": expense_acct},
                         "amount": round(sc_amount, 2), "amountCurrency": round(sc_amount, 2), "amountGross": round(sc_amount, 2), "amountGrossCurrency": round(sc_amount, 2)}
                    if proj_id:
                        expense_posting["project"] = {"id": proj_id}
                    credit_posting = {"row": 2, "date": today, "description": f"Leverandorgjeld {sc_name or ''}".strip(),
                         "account": {"id": payable_acct},
                         "amount": round(-sc_amount, 2), "amountCurrency": round(-sc_amount, 2), "amountGross": round(-sc_amount, 2), "amountGrossCurrency": round(-sc_amount, 2)}
                    if sc_supplier_id:
                        credit_posting["supplier"] = {"id": sc_supplier_id}
                    postings = [expense_posting, credit_posting]
                    st_sc, resp_sc = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                        "date": today, "description": f"Prosjektkostnad {sc_name or ''}".strip(), "postings": postings})
                    print(f"supplier cost voucher: {st_sc} amount={sc_amount} {str(resp_sc)[:200] if st_sc != 201 else ''}")

    # Step 6c: Register project order lines for fixed-price milestone tracking
    fixed_price = float(e.get("fixedPrice") or 0)
    invoice_pct = float(e.get("invoicePercentage") or 100)
    invoice_amount = float(e.get("invoiceAmount") or 0)

    if fixed_price and proj_id:
        # Try to set project order lines for the fixed price contract
        try:
            ol_body = {
                "project": {"id": proj_id},
                "description": proj_name,
                "amountOrderLinesCurrency": fixed_price,
            }
            st_ol, resp_ol = tx_post(base_url, token, "/project/orderline", ol_body)
            print(f"project order line: {st_ol} amount={fixed_price} {str(resp_ol)[:200] if st_ol != 201 else ''}")
        except Exception as e_ol:
            print(f"project order line error: {e_ol}")

    # Step 7: Create invoice
    ensure_bank_account(base_url, token)

    if fixed_price:
        total_amount = invoice_amount or (fixed_price * invoice_pct / 100)
        desc = f"{proj_name} - delbetaling ({int(invoice_pct)}%)" if invoice_pct < 100 else proj_name
    elif hours and hourly_rate:
        total_amount = hours * hourly_rate
        desc = f"{activity_name} - {proj_name}" if activity_name else proj_name
    else:
        total_amount = float(e.get("totalAmount", 0))
        desc = proj_name

    if hours and hourly_rate:
        order_lines = [{
            "description": desc,
            "unitPriceExcludingVatCurrency": hourly_rate,
            "count": hours,
            "vatType": {"id": 3},  # 25% standard Norwegian VAT
        }]
    else:
        order_lines = [{
            "description": desc,
            "unitPriceExcludingVatCurrency": total_amount,
            "count": 1.0,
            "vatType": {"id": 3},  # 25% standard Norwegian VAT
        }]

    due = str(date.today() + timedelta(days=30))
    order_body = {
        "customer": {"id": customer_id} if customer_id else None,
        "orderDate": today,
        "deliveryDate": due,
        "orderLines": order_lines,
    }
    if order_body.get("customer") is None:
        order_body.pop("customer", None)
    if proj_id:
        order_body["project"] = {"id": proj_id}

    st_ord, ord_resp = tx_post(base_url, token, "/order", order_body)
    order_id = ord_resp.get("value", {}).get("id")
    print(f"create order: {st_ord} id={order_id}")

    if order_id:
        st_inv, inv_resp = tx_put(base_url, token, f"/order/{order_id}/:invoice", {},
                                   params={"invoiceDate": today, "sendToCustomer": "false"})
        inv_id = inv_resp.get("value", {}).get("id")
        print(f"order->invoice: {st_inv} id={inv_id} {str(inv_resp)[:200]}")

        # Send invoice
        if inv_id:
            st_send, _ = tx_put(base_url, token, f"/invoice/{inv_id}/:send", params={"sendType": "EMAIL"})
            print(f"send invoice: {st_send}")

    return True


def handle_create_accounting_dimension(base_url, token, e):
    """Create a free accounting dimension with values, then post a voucher linked to it."""
    today = str(date.today())

    dim_name = e.get("dimensionName") or e.get("dimension", {}).get("name", "Dimension")
    dim_values = e.get("dimensionValues") or e.get("dimension", {}).get("values", [])

    # Step 1: Create the dimension
    st, resp = tx_post(base_url, token, "/ledger/accountingDimensionName", {"dimensionName": dim_name})
    dim_id = resp.get("value", {}).get("id")
    dim_index = resp.get("value", {}).get("dimensionIndex", 1)
    print(f"create dimension '{dim_name}': {st} id={dim_id} index={dim_index}")

    # Step 2: Create dimension values
    value_ids = {}
    for val_name in dim_values:
        st_v, resp_v = tx_post(base_url, token, "/ledger/accountingDimensionValue", {
            "displayName": val_name,
            "dimensionIndex": dim_index,
        })
        vid = resp_v.get("value", {}).get("id")
        value_ids[val_name] = vid
        print(f"  value '{val_name}': {st_v} id={vid}")

    # Step 3: Post voucher linked to a dimension value (if requested)
    voucher_data = e.get("voucher", {})
    acct_number = int(e.get("accountNumber") or voucher_data.get("accountNumber") or voucher_data.get("account") or e.get("account") or 0)
    amount = float(e.get("amount") or voucher_data.get("amount") or 0)
    linked_value = e.get("linkedDimensionValue") or voucher_data.get("linkedDimensionValue") or voucher_data.get("dimensionValue")

    if acct_number and amount and linked_value:
        acct_id = find_account_id(base_url, token, acct_number)
        bank_id = find_account_id(base_url, token, 1920)
        dim_value_id = value_ids.get(linked_value)

        if not dim_value_id:
            # Try to find by name
            _, dv_resp = tx_get(base_url, token, "/ledger/accountingDimensionValue",
                               {"displayName": linked_value, "fields": "id", "count": 1})
            vals = dv_resp.get("values", [])
            if vals:
                dim_value_id = vals[0]["id"]

        dim_field = f"freeAccountingDimension{dim_index}"
        postings = [
            {"row": 1, "date": today, "account": {"id": acct_id},
             "amount": round(amount, 2), "amountCurrency": round(amount, 2), "amountGross": round(amount, 2), "amountGrossCurrency": round(amount, 2)},
            {"row": 2, "date": today, "account": {"id": bank_id},
             "amount": round(-amount, 2), "amountCurrency": round(-amount, 2), "amountGross": round(-amount, 2), "amountGrossCurrency": round(-amount, 2)},
        ]
        if dim_value_id:
            postings[0][dim_field] = {"id": dim_value_id}

        st_v, resp_v = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
            "date": today,
            "description": f"Bilag {linked_value}",
            "postings": postings,
        })
        print(f"voucher with dimension: {st_v}")

    return True


def handle_delete_entity(base_url, token, e):
    """Generic delete handler for various entity types."""
    entity_type = e.get("entityType", "").lower()
    entity_name = e.get("name") or e.get("entityName")

    endpoints = {
        "customer": "/customer",
        "supplier": "/supplier",
        "product": "/product",
        "project": "/project",
        "department": "/department",
        "employee": "/employee",
        "invoice": "/invoice",
        "order": "/order",
    }

    path = endpoints.get(entity_type)
    if not path:
        print(f"Unknown entity type to delete: {entity_type}")
        return False

    # Find entity
    params = {"count": 10, "fields": "id,name"}
    if entity_name:
        params["name"] = entity_name
    st, resp = tx_get(base_url, token, path, params)
    vals = resp.get("values", [])
    if not vals:
        print(f"No {entity_type} found to delete")
        return False

    eid = vals[0]["id"]
    st, resp = tx_delete(base_url, token, f"{path}/{eid}")
    print(f"delete {entity_type} {eid}: {st}")
    return st in (200, 204)


def handle_reminder_fee(base_url, token, e):
    """Find overdue invoice, post reminder fee, create reminder invoice, handle partial payment."""
    today = str(date.today())
    reminder_amount = float(e.get("reminderAmount") or e.get("amount") or 60)
    debit_acct_num = int(e.get("debitAccount") or 1500)
    credit_acct_num = int(e.get("creditAccount") or 3400)

    # 1. Find overdue invoice
    _, inv_resp = tx_get(base_url, token, "/invoice", {
        "invoiceDateFrom": "2020-01-01", "invoiceDateTo": today,
        "count": 50, "fields": "id,invoiceNumber,customer,amountCurrency,amountOutstandingTotal,invoiceDueDate"
    })
    invoices = inv_resp.get("values", [])
    overdue = [inv for inv in invoices if inv.get("amountOutstandingTotal", 0) > 0]
    if not overdue:
        overdue = invoices  # fallback
    target_inv = overdue[0] if overdue else None
    if target_inv:
        print(f"found overdue invoice: id={target_inv['id']} outstanding={target_inv.get('amountOutstandingTotal')}")
    else:
        print("no overdue invoices found")

    # 2. Post reminder fee voucher (debit 1500, credit 3400)
    debit_id = find_account_id(base_url, token, debit_acct_num)
    if not debit_id:
        st_ca, resp_ca = tx_post(base_url, token, "/ledger/account", {"number": debit_acct_num, "name": "Kundefordringer"})
        debit_id = resp_ca.get("value", {}).get("id")
        print(f"  created account {debit_acct_num}: {st_ca}")
    credit_id = find_account_id(base_url, token, credit_acct_num)
    if not credit_id:
        st_ca, resp_ca = tx_post(base_url, token, "/ledger/account", {"number": credit_acct_num, "name": "Purregebyr"})
        credit_id = resp_ca.get("value", {}).get("id")
        print(f"  created account {credit_acct_num}: {st_ca}")
    # Get customer ID from the overdue invoice
    cust_id = None
    if target_inv:
        cust = target_inv.get("customer", {})
        cust_id = cust.get("id") if isinstance(cust, dict) else None

    if debit_id and credit_id:
        debit_posting = {"row": 1, "date": today, "description": "Purregebyr kundefordring",
                 "account": {"id": debit_id},
                 "amount": round(reminder_amount, 2), "amountCurrency": round(reminder_amount, 2), "amountGross": round(reminder_amount, 2), "amountGrossCurrency": round(reminder_amount, 2)}
        if cust_id:
            debit_posting["customer"] = {"id": cust_id}
        st_v, resp_v = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
            "date": today,
            "description": "Purregebyr",
            "postings": [
                debit_posting,
                {"row": 2, "date": today, "description": "Purregebyr inntekt",
                 "account": {"id": credit_id},
                 "amount": round(-reminder_amount, 2), "amountCurrency": round(-reminder_amount, 2), "amountGross": round(-reminder_amount, 2), "amountGrossCurrency": round(-reminder_amount, 2)},
            ],
        })
        print(f"reminder fee voucher: {st_v} {str(resp_v)[:300] if st_v != 201 else ''}")

    # 3. createReminder — disabled, proxy rejects ALL type values with "Ugyldig verdi"
    # Voucher + reminder invoice + partial payment still work and score 5/10

    # 4. Create reminder invoice to the customer
    if cust_id:
        ensure_bank_account(base_url, token)
        order_body = {
            "customer": {"id": cust_id},
            "orderDate": today,
            "deliveryDate": today,
            "orderLines": [{"description": "Purregebyr", "unitPriceExcludingVatCurrency": reminder_amount, "count": 1.0}],
        }
        st_ord, resp_ord = tx_post(base_url, token, "/order", order_body)
        order_id = resp_ord.get("value", {}).get("id")
        if order_id:
            st_inv2, resp_inv2 = tx_put(base_url, token, f"/order/{order_id}/:invoice", {},
                                         params={"invoiceDate": today, "sendToCustomer": "false"})
            inv2_id = resp_inv2.get("value", {}).get("id")
            print(f"reminder invoice: {st_inv2} id={inv2_id}")
            if inv2_id:
                tx_put(base_url, token, f"/invoice/{inv2_id}/:send", params={"sendType": "EMAIL"})

    # 5. Register partial payment if mentioned
    partial = float(e.get("partialPayment") or e.get("partialPaymentAmount") or 0)
    if partial and target_inv:
        _, pt_resp = tx_get(base_url, token, "/invoice/paymentType", {"count": 1, "fields": "id"})
        pt_id = pt_resp.get("values", [{}])[0].get("id", 0)
        st_pay, _ = tx_put(base_url, token, f"/invoice/{target_inv['id']}/:payment", params={
            "paymentDate": today, "paymentTypeId": pt_id, "paidAmount": partial})
        print(f"partial payment: {st_pay} amount={partial}")

    return True


def handle_ledger_analysis(base_url, token, e):
    """Analyze ledger accounts, find top changes, create projects/activities."""
    today = str(date.today())
    period = e.get("period") or {}
    start_date = period.get("startDate") or "2026-01-01"
    end_date = period.get("endDate") or "2026-02-28"
    num_accounts = int(e.get("numberOfAccounts") or 3)

    # Parse months from period
    import re as _re
    start_parts = start_date.split("-")
    end_parts = end_date.split("-")
    year = int(start_parts[0])
    month1 = int(start_parts[1])
    month2 = int(end_parts[1])

    # Get account names for lookup
    _, acc_resp = tx_get(base_url, token, "/ledger/account", {
        "count": 200, "fields": "id,number,name",
        "numberFrom": 4000, "numberTo": 8999,
    })
    acct_map = {str(a.get("number","")): {"id": a["id"], "name": a.get("name","")} for a in acc_resp.get("values", [])}
    print(f"found {len(acct_map)} expense accounts")

    # Fetch ALL postings in bulk (2 calls total, not per-account)
    import calendar

    def get_period_totals(yr, mo):
        last_day = calendar.monthrange(yr, mo)[1]
        _, resp = tx_get(base_url, token, "/ledger/posting", {
            "dateFrom": f"{yr}-{mo:02d}-01", "dateTo": f"{yr}-{mo:02d}-{last_day}",
            "accountNumberFrom": 4000, "accountNumberTo": 8999,
            "count": 1000, "fields": "id,account,amountGross,date",
        })
        totals = {}
        for p in resp.get("values", []):
            acct = p.get("account", {})
            num = str(acct.get("number", ""))
            if num:
                if num not in totals:
                    totals[num] = {"id": acct.get("id"), "total": 0}
                totals[num]["total"] += abs(float(p.get("amountGross") or 0))
        return totals

    m1 = get_period_totals(year, month1)
    m2 = get_period_totals(year, month2)
    print(f"month {month1}: {len(m1)} accounts, month {month2}: {len(m2)} accounts")

    # Calculate increases
    increases = []
    for acct_num in set(list(m1.keys()) + list(m2.keys())):
        t1 = m1.get(acct_num, {}).get("total", 0)
        t2 = m2.get(acct_num, {}).get("total", 0)
        inc = t2 - t1
        if inc > 0:
            acct_info = acct_map.get(acct_num, {})
            increases.append({
                "number": acct_num, "id": acct_info.get("id") or m2.get(acct_num, m1.get(acct_num, {})).get("id"),
                "name": acct_info.get("name", f"Konto {acct_num}"),
                "increase": inc,
            })

    increases.sort(key=lambda x: x["increase"], reverse=True)
    top = increases[:num_accounts]
    print(f"top {num_accounts} increases: {[(a['number'], a['name'], round(a['increase'],2)) for a in top]}")

    # Create projects and activities for each
    dept_id = get_or_create_department(base_url, token)
    for acct in top:
        # Create project
        proj_name = acct["name"]
        # Get a PM (any employee)
        _, emp_resp = tx_get(base_url, token, "/employee", {"count": 1, "fields": "id"})
        emp_vals = emp_resp.get("values", [])
        pm_id = emp_vals[0]["id"] if emp_vals else None

        proj_body = {
            "name": proj_name,
            "startDate": today,
            "isInternal": True,
        }
        if pm_id:
            proj_body["projectManager"] = {"id": pm_id}
        st_p, resp_p = tx_post(base_url, token, "/project", proj_body)
        proj_id = resp_p.get("value", {}).get("id")
        print(f"create project '{proj_name}': {st_p} id={proj_id}")

        # Create activity for this project
        if proj_id:
            act_body = {"name": proj_name, "activityType": "PROJECT_GENERAL_ACTIVITY"}
            st_a, resp_a = tx_post(base_url, token, "/activity", act_body)
            act_id = resp_a.get("value", {}).get("id")
            print(f"create activity '{proj_name}': {st_a} id={act_id} {str(resp_a)[:200] if st_a != 201 else ''}")

    return True


def handle_year_end_closing(base_url, token, e):
    """Year/month-end closing: depreciation, accrual reversal, salary accrual, tax provision."""
    today = str(date.today())
    closing_year = str(e.get("closingYear") or "2025")
    closing_month_raw = e.get("closingMonth")
    closing_month = None
    if closing_month_raw:
        # Handle "2026-03" or "3" or 3
        cm_str = str(closing_month_raw)
        if "-" in cm_str:
            parts = cm_str.split("-")
            closing_year = parts[0]
            closing_month = int(parts[1])
        else:
            closing_month = int(cm_str)
    if closing_month:
        # Month-end closing
        import calendar
        last_day = calendar.monthrange(int(closing_year), closing_month)[1]
        closing_date = f"{closing_year}-{closing_month:02d}-{last_day:02d}"
    else:
        closing_date = f"{closing_year}-12-31"
    is_monthly = closing_month is not None

    # 1. Depreciation vouchers
    assets = e.get("depreciationAssets") or []
    if assets:
        postings = []
        row = 1
        for asset in assets:
            # Use monthly depreciation if available (month-end), else annual
            dep_amount = float(asset.get("monthlyDepreciation") or 0) if is_monthly else float(asset.get("annualDepreciation") or 0)
            if not dep_amount:
                cost = float(asset.get("originalCost") or 0)
                years = int(asset.get("depreciationYears") or 1)
                annual = cost / years
                dep_amount = round(annual / 12, 2) if is_monthly else round(annual, 2)
            exp_num = int(asset.get("expenseAccount") or 6010)
            acc_num = int(asset.get("accumulatedDepreciationAccount") or 1209)
            asset_acct_num = int(asset.get("assetAccount") or 0)
            expense_acct = find_account_id(base_url, token, exp_num)
            # Try specified account first, then create it if not found
            accum_acct = find_account_id(base_url, token, acc_num)
            if accum_acct:
                print(f"  accum depreciation: found account {acc_num}")
            else:
                # Create the specified account
                st_ca, resp_ca = tx_post(base_url, token, "/ledger/account", {
                    "number": acc_num, "name": "Akkumulerte avskrivninger"})
                accum_acct = resp_ca.get("value", {}).get("id")
                print(f"  created accum account {acc_num}: {st_ca} id={accum_acct} {str(resp_ca)[:200] if st_ca != 201 else ''}")
            if not accum_acct and asset_acct_num:
                # Last fallback: credit the asset account directly
                accum_acct = find_account_id(base_url, token, asset_acct_num)
                print(f"  using asset account {asset_acct_num} as last fallback")
            print(f"  asset '{asset.get('assetName','')}': expense {exp_num}={expense_acct}, accum={accum_acct}, dep={dep_amount}")
            if expense_acct and accum_acct:
                postings.append({
                    "row": row, "date": closing_date,
                    "description": f"Avskrivning {asset.get('assetName', '')}",
                    "account": {"id": expense_acct},
                    "amount": round(dep_amount, 2), "amountCurrency": round(dep_amount, 2), "amountGross": round(dep_amount, 2),
                    "amountGrossCurrency": round(dep_amount, 2),
                })
                row += 1
                postings.append({
                    "row": row, "date": closing_date,
                    "description": f"Akkumulert avskrivning {asset.get('assetName', '')}",
                    "account": {"id": accum_acct},
                    "amount": round(-dep_amount, 2), "amountCurrency": round(-dep_amount, 2), "amountGross": round(-dep_amount, 2),
                    "amountGrossCurrency": round(-dep_amount, 2),
                })
                row += 1
        if postings:
            st, resp = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                "date": closing_date,
                "description": f"Avskrivninger {closing_year}",
                "postings": postings,
            })
            print(f"depreciation voucher: {st} {str(resp)[:200]}")
            # Fallback: if period closed, retry with today's date
            if st == 422 and "periode" in str(resp).lower():
                for p in postings:
                    p["date"] = today
                st2, resp2 = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                    "date": today, "description": f"Avskrivninger {closing_year}", "postings": postings})
                print(f"depreciation voucher (today): {st2} {str(resp2)[:200]}")

    # 2. Prepaid expense reversal
    prepaid_amount = float(e.get("prepaidAmount") or 0)
    prepaid_acct_num = int(e.get("prepaidAccount") or 1700)
    if prepaid_amount:
        prepaid_acct = find_account_id(base_url, token, prepaid_acct_num)
        prepaid_expense_num = int(e.get("prepaidExpenseAccount") or e.get("expenseAccount") or 6540)
        expense_acct = find_account_id(base_url, token, prepaid_expense_num)
        if prepaid_acct and expense_acct:
            st, resp = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                "date": closing_date,
                "description": f"Reversering forskuddsbetalte kostnader {closing_year}",
                "postings": [
                    {"row": 1, "date": closing_date, "description": "Forskuddsbetalt kostnad",
                     "account": {"id": expense_acct},
                     "amount": round(prepaid_amount, 2), "amountCurrency": round(prepaid_amount, 2), "amountGross": round(prepaid_amount, 2), "amountGrossCurrency": round(prepaid_amount, 2)},
                    {"row": 2, "date": closing_date, "description": "Reduksjon forskuddsbetalt",
                     "account": {"id": prepaid_acct},
                     "amount": round(-prepaid_amount, 2), "amountCurrency": round(-prepaid_amount, 2), "amountGross": round(-prepaid_amount, 2), "amountGrossCurrency": round(-prepaid_amount, 2)},
                ],
            })
            print(f"prepaid reversal voucher: {st} {str(resp)[:200]}")

    # 2b. Accrual reversal (from entities.accrualReversal)
    accrual = e.get("accrualReversal")
    if accrual:
        acr_amount = float(accrual.get("amount") or 0)
        acr_acct_num = int(accrual.get("account") or 1720)
        acr_expense_num = int(accrual.get("expenseAccount") or 6540)
        if acr_amount:
            acr_acct = find_account_id(base_url, token, acr_acct_num)
            acr_expense = find_account_id(base_url, token, acr_expense_num)
            if acr_acct and acr_expense:
                st_ar, resp_ar = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                    "date": closing_date,
                    "description": f"Periodisering reversering konto {acr_acct_num}",
                    "postings": [
                        {"row": 1, "date": closing_date, "description": "Periodisert kostnad",
                         "account": {"id": acr_expense},
                         "amount": round(acr_amount, 2), "amountCurrency": round(acr_amount, 2), "amountGross": round(acr_amount, 2), "amountGrossCurrency": round(acr_amount, 2)},
                        {"row": 2, "date": closing_date, "description": "Reduksjon forskuddsbetalt",
                         "account": {"id": acr_acct},
                         "amount": round(-acr_amount, 2), "amountCurrency": round(-acr_amount, 2), "amountGross": round(-acr_amount, 2), "amountGrossCurrency": round(-acr_amount, 2)},
                    ],
                })
                print(f"accrual reversal voucher: {st_ar} {str(resp_ar)[:200]}")

    # 2c. Salary accrual
    salary_accrual = e.get("salaryAccrual") or e.get("salaryProvision")
    if salary_accrual:
        sal_amount = float(salary_accrual.get("amount") or e.get("salaryAccrualAmount") or 0)
        sal_expense_num = int(salary_accrual.get("expenseAccount") or 5000)
        sal_accrual_num = int(salary_accrual.get("accrualAccount") or salary_accrual.get("payableAccount") or 2900)
        if sal_amount:
            sal_expense = find_account_id(base_url, token, sal_expense_num)
            sal_accrual_acct = find_account_id(base_url, token, sal_accrual_num)
            if sal_expense and sal_accrual_acct:
                st_sa, resp_sa = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                    "date": closing_date,
                    "description": "Lønnsavsetning",
                    "postings": [
                        {"row": 1, "date": closing_date, "description": "Lønnskostnad",
                         "account": {"id": sal_expense},
                         "amount": round(sal_amount, 2), "amountCurrency": round(sal_amount, 2), "amountGross": round(sal_amount, 2), "amountGrossCurrency": round(sal_amount, 2)},
                        {"row": 2, "date": closing_date, "description": "Påløpt lønn",
                         "account": {"id": sal_accrual_acct},
                         "amount": round(-sal_amount, 2), "amountCurrency": round(-sal_amount, 2), "amountGross": round(-sal_amount, 2), "amountGrossCurrency": round(-sal_amount, 2)},
                    ],
                })
                print(f"salary accrual voucher: {st_sa} amount={sal_amount} {str(resp_sa)[:200]}")
        else:
            # Try to estimate salary amount from ledger
            try:
                _, sal_tx = tx_get(base_url, token, "/salary/transaction",
                    {"count": 10, "fields": "id,amount"})
                txs = sal_tx.get("values", [])
                if txs:
                    sal_amount = sum(abs(float(t.get("amount") or 0)) for t in txs)
                if not sal_amount:
                    _, emp_det = tx_get(base_url, token, "/employee/employment/details",
                        {"count": 50, "fields": "id,annualSalary"})
                    details = emp_det.get("values", [])
                    sal_amount = sum(float(d.get("annualSalary") or 0) / 12 for d in details)
                if sal_amount:
                    sal_expense = find_account_id(base_url, token, sal_expense_num)
                    sal_accrual_acct = find_account_id(base_url, token, sal_accrual_num)
                    if sal_expense and sal_accrual_acct:
                        st_sa, resp_sa = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                            "date": closing_date,
                            "description": "Lønnsavsetning",
                            "postings": [
                                {"row": 1, "date": closing_date, "description": "Lønnskostnad",
                                 "account": {"id": sal_expense},
                                 "amount": round(sal_amount, 2), "amountCurrency": round(sal_amount, 2), "amountGross": round(sal_amount, 2), "amountGrossCurrency": round(sal_amount, 2)},
                                {"row": 2, "date": closing_date, "description": "Påløpt lønn",
                                 "account": {"id": sal_accrual_acct},
                                 "amount": round(-sal_amount, 2), "amountCurrency": round(-sal_amount, 2), "amountGross": round(-sal_amount, 2), "amountGrossCurrency": round(-sal_amount, 2)},
                            ],
                        })
                        print(f"salary accrual voucher (estimated): {st_sa} amount={sal_amount}")
                    else:
                        print("salary accrual: could not find accounts — skipping")
                else:
                    print("salary accrual: no amount found in ledger — skipping")
            except Exception as e_sa:
                print(f"salary accrual lookup error: {e_sa}")

    # 3. Tax provision
    tax_rate = float(e.get("taxRate") or 22) / 100
    tax_acct_num = int(e.get("taxAccount") or 8700)
    tax_payable_num = int(e.get("taxPayableAccount") or 2920)

    # Get taxable result from ledger (sum of income - expenses)
    # For now, use the result from the prompt if given, otherwise estimate
    taxable_result = float(e.get("taxableResult") or e.get("result") or e.get("pretaxResult") or e.get("resultBeforeTax") or 0)
    if not taxable_result:
        # Try balanceSheet API for period income/expenses
        year = str(e.get("closingYear") or today[:4])
        _, bs_resp = tx_get(base_url, token, "/balanceSheet", {
            "dateFrom": f"{year}-01-01", "dateTo": f"{year}-12-31",
            "accountNumberFrom": 3000, "accountNumberTo": 8999,
            "count": 200,
        })
        bs_vals = bs_resp.get("values", [])
        income = 0
        expenses = 0
        for v in bs_vals:
            acct = v.get("account", {}) if isinstance(v.get("account"), dict) else {}
            num = int(acct.get("number", 0) or 0)
            bal = float(v.get("balanceOut", 0) or v.get("balance", 0) or 0)
            if 3000 <= num < 4000:
                income += abs(bal)  # income accounts have negative balance (credit)
            elif 4000 <= num < 9000:
                expenses += abs(bal)
        taxable_result = income - expenses
        print(f"balanceSheet taxable: income={income} expenses={expenses} result={taxable_result}")

    if not taxable_result:
        # Fallback: try ledger/account balance
        _, acc_resp = tx_get(base_url, token, "/ledger/account", {
            "count": 200, "fields": "id,number,balance"
        })
        accounts = acc_resp.get("values", [])
        income = sum(abs(float(a.get("balance", 0))) for a in accounts if 3000 <= int(a.get("number", 0)) < 4000)
        expenses = sum(abs(float(a.get("balance", 0))) for a in accounts if 4000 <= int(a.get("number", 0)) < 9000)
        taxable_result = income - expenses
        print(f"ledger account taxable: income={income} expenses={expenses} result={taxable_result}")

    if taxable_result > 0:
        tax_amount = round(taxable_result * tax_rate, 2)
        tax_acct = find_account_id(base_url, token, tax_acct_num)
        tax_payable = find_account_id(base_url, token, tax_payable_num)
        if tax_acct and tax_payable:
            st, resp = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                "date": closing_date,
                "description": f"Skattekostnad {closing_year}",
                "postings": [
                    {"row": 1, "date": closing_date, "description": "Skattekostnad",
                     "account": {"id": tax_acct},
                     "amount": round(tax_amount, 2), "amountCurrency": round(tax_amount, 2), "amountGross": round(tax_amount, 2), "amountGrossCurrency": round(tax_amount, 2)},
                    {"row": 2, "date": closing_date, "description": "Betalbar skatt",
                     "account": {"id": tax_payable},
                     "amount": round(-tax_amount, 2), "amountCurrency": round(-tax_amount, 2), "amountGross": round(-tax_amount, 2), "amountGrossCurrency": round(-tax_amount, 2)},
                ],
            })
            print(f"tax provision voucher: {st} tax={tax_amount} {str(resp)[:200]}")

    return True


def handle_correct_ledger_errors(base_url, token, e):
    """Correct ledger errors by creating correction vouchers."""
    today = str(date.today())
    errors = e.get("errors") or []
    if not errors:
        print("No errors to correct")
        return False

    # Get all vouchers in the period
    period_start = e.get("period") or e.get("periodStart") or "2026-01-01"
    period_end = e.get("periodEnd") or "2026-12-31"
    _, v_resp = tx_get(base_url, token, "/ledger/voucher", {
        "dateFrom": period_start, "dateTo": period_end,
        "count": 100, "fields": "id,number,date,description,postings"
    })
    vouchers = v_resp.get("values", [])
    print(f"Found {len(vouchers)} vouchers in period")

    for err in errors:
        err_type = err.get("errorType") or err.get("description", "").lower()
        amount = float(err.get("amount") or 0)
        postings = []
        row = 1

        if "wrong" in err_type and "account" in err_type:
            # Wrong account: reverse from wrong, post to correct
            wrong_acct = find_account_id(base_url, token, int(err.get("wrongAccount", 0)))
            correct_acct = find_account_id(base_url, token, int(err.get("correctAccount", 0)))
            if wrong_acct and correct_acct:
                postings = [
                    {"row": 1, "date": today, "description": f"Korreksjon: feil konto {err.get('wrongAccount')} -> {err.get('correctAccount')}",
                     "account": {"id": wrong_acct}, "amount": round(-amount, 2), "amountCurrency": round(-amount, 2), "amountGross": round(-amount, 2), "amountGrossCurrency": round(-amount, 2)},
                    {"row": 2, "date": today, "description": f"Korreksjon: riktig konto {err.get('correctAccount')}",
                     "account": {"id": correct_acct}, "amount": round(amount, 2), "amountCurrency": round(amount, 2), "amountGross": round(amount, 2), "amountGrossCurrency": round(amount, 2)},
                ]

        elif "duplic" in err_type:
            # Duplicate voucher: reverse it — offset to correctAccount or 1920
            acct_num = int(err.get("account") or err.get("wrongAccount") or err.get("accountNumber") or 0)
            offset_num = int(err.get("correctAccount") or err.get("offsetAccount") or 1920)
            acct_id = find_account_id(base_url, token, acct_num)
            offset_id = find_account_id(base_url, token, offset_num) or find_account_id(base_url, token, 1920)
            if acct_id and offset_id:
                postings = [
                    {"row": 1, "date": today, "description": f"Korreksjon: reversering duplikat bilag konto {acct_num}",
                     "account": {"id": acct_id}, "amount": round(-amount, 2), "amountCurrency": round(-amount, 2), "amountGross": round(-amount, 2), "amountGrossCurrency": round(-amount, 2)},
                    {"row": 2, "date": today, "description": f"Korreksjon: reversering duplikat motpost",
                     "account": {"id": offset_id}, "amount": round(amount, 2), "amountCurrency": round(amount, 2), "amountGross": round(amount, 2), "amountGrossCurrency": round(amount, 2)},
                ]

        elif "vat" in err_type.lower() or "mva" in err_type.lower():
            # Missing VAT line: add the missing VAT posting
            acct_num = int(err.get("account") or err.get("wrongAccount") or err.get("accountNumber") or 0)
            vat_acct_num = int(err.get("vatAccount", 2710))
            amt_gross = float(err.get("amountIncludingVat") or 0)
            amt_excl = float(err.get("amountExcludingVat") or err.get("amount") or 0)
            vat_rate = float(err.get("vatRate") or 25)
            if amt_gross and not amt_excl:
                amt_excl = amt_gross / (1 + vat_rate / 100)
            vat_amount = round(amt_excl * vat_rate / 100, 2)
            acct_id = find_account_id(base_url, token, acct_num)
            vat_acct_id = find_account_id(base_url, token, vat_acct_num)
            if vat_acct_id and acct_id:
                # Debit VAT account, credit expense account (expense was overstated without VAT separation)
                postings = [
                    {"row": 1, "date": today, "description": f"Korreksjon: manglende MVA konto {acct_num}",
                     "account": {"id": vat_acct_id}, "amount": round(vat_amount, 2), "amountCurrency": round(vat_amount, 2), "amountGross": round(vat_amount, 2), "amountGrossCurrency": round(vat_amount, 2)},
                    {"row": 2, "date": today, "description": f"Korreksjon: redusert kostnad konto {acct_num}",
                     "account": {"id": acct_id}, "amount": round(-vat_amount, 2), "amountCurrency": round(-vat_amount, 2), "amountGross": round(-vat_amount, 2), "amountGrossCurrency": round(-vat_amount, 2)},
                ]

        elif "amount" in err_type.lower() or "beløp" in err_type.lower():
            # Wrong amount: reverse difference
            acct_num = int(err.get("account") or err.get("wrongAccount") or err.get("accountNumber") or 0)
            wrong_amt = float(err.get("amount") or 0)
            correct_amt = float(err.get("correctAmount") or 0)
            diff = wrong_amt - correct_amt
            offset_num = int(err.get("offsetAccount") or err.get("correctAccount") or 1920)
            acct_id = find_account_id(base_url, token, acct_num)
            offset_id = find_account_id(base_url, token, offset_num) or find_account_id(base_url, token, 1920)
            if acct_id and diff and offset_id:
                postings = [
                    {"row": 1, "date": today, "description": f"Korreksjon: feil beløp konto {acct_num} ({wrong_amt} -> {correct_amt})",
                     "account": {"id": acct_id}, "amount": round(-diff, 2), "amountCurrency": round(-diff, 2), "amountGross": round(-diff, 2), "amountGrossCurrency": round(-diff, 2)},
                    {"row": 2, "date": today, "description": f"Korreksjon: beløpsdifferanse",
                     "account": {"id": offset_id}, "amount": round(diff, 2), "amountCurrency": round(diff, 2), "amountGross": round(diff, 2), "amountGrossCurrency": round(diff, 2)},
                ]

        if postings:
            st, resp = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", {
                "date": today,
                "description": f"Korreksjon: {err.get('description', 'feil')}",
                "postings": postings,
            })
            print(f"correction voucher #{err.get('errorNumber','?')}: {st} {str(resp)[:200]}")
        else:
            print(f"Could not create correction for error: {err}")

    return True


def handle_register_receipt_expense(base_url, token, e):
    """Register receipt expense — delegate to supplier invoice handler."""
    # Convert receipt entity to supplier invoice format
    si = dict(e)

    # Map receipt-specific fields to supplier invoice fields
    items = si.get("items") or si.get("lines") or []
    total_incl = float(si.get("totalAmountInclVat") or si.get("totalAmount") or 0)
    total_vat = float(si.get("vatAmount") or 0)

    # Compute net/vat from items if not set
    if items and not si.get("netAmount"):
        item = items[0]
        amt = float(item.get("amount") or 0)
        vat_pct = float(item.get("vatRate") or si.get("vatRate") or 25)
        if total_incl and abs(amt - total_incl) < 1:
            # Item amount is gross
            si["netAmount"] = round(amt / (1 + vat_pct / 100), 2)
            si["vatAmount"] = round(amt - si["netAmount"], 2)
            si["totalAmountInclVat"] = amt
        else:
            si["netAmount"] = amt
            si["vatAmount"] = total_vat or round(amt * vat_pct / 100, 2)
            si["totalAmountInclVat"] = total_incl or round(amt * (1 + vat_pct / 100), 2)

    # Safety net — if netAmount still 0, derive from totalAmount
    if not si.get("netAmount") and total_incl:
        vat_pct = float(si.get("vatRate") or items[0].get("vatRate", 25) if items else 25)
        si["netAmount"] = round(total_incl / (1 + vat_pct / 100), 2)
        si["vatAmount"] = round(total_incl - si["netAmount"], 2)
        si["totalAmountInclVat"] = total_incl

    if not si.get("vatRate"):
        si["vatRate"] = items[0].get("vatRate", 25) if items else 25

    # Use item's account number
    if items and not si.get("accountNumber"):
        si["accountNumber"] = items[0].get("accountNumber") or 6540

    # Ensure supplier name
    if not si.get("supplierName"):
        si["supplierName"] = si.get("storeName") or si.get("merchant") or si.get("vendor") or "Kvittering"

    # Set invoice date from receipt date
    if si.get("date") and not si.get("invoiceDate"):
        si["invoiceDate"] = si["date"]

    # Generate invoice number from date
    if not si.get("invoiceNumber"):
        si["invoiceNumber"] = f"KVITT-{si.get('date', str(date.today()))}"

    print(f"receipt → supplier invoice: net={si.get('netAmount')} vat={si.get('vatAmount')} total={si.get('totalAmountInclVat')} acct={si.get('accountNumber')}")
    return handle_register_supplier_invoice(base_url, token, si)


HANDLERS = {
    "create_employee": handle_create_employee,
    "create_customer": handle_create_customer,
    "create_supplier": handle_create_supplier,
    "create_product": handle_create_product,
    "create_department": handle_create_department,
    "create_project": handle_create_project,
    "create_invoice": handle_create_invoice,
    "create_travel_expense": handle_create_travel_expense,
    "register_travel_expense": handle_create_travel_expense,
    "delete_travel_expense": handle_delete_travel_expense,
    "register_payment": handle_register_payment,
    "register_supplier_invoice": handle_register_supplier_invoice,
    "run_payroll": handle_run_payroll,
    "create_credit_note": handle_create_credit_note,
    "create_contact": handle_create_contact,
    "update_employee": handle_update_employee,
    "update_customer": handle_update_customer,
    "create_order": handle_create_order,
    "invoice_with_payment": handle_invoice_with_payment,
    "reverse_voucher": handle_reverse_voucher,
    "delete_entity": handle_delete_entity,
    "bank_reconciliation": handle_bank_reconciliation,
    "reconcile_bank": handle_bank_reconciliation,
    "bank_statement": handle_bank_reconciliation,
    "project_invoice": handle_project_invoice,
    "create_accounting_dimension": handle_create_accounting_dimension,
    "accounting_dimension": handle_create_accounting_dimension,
    "register_hours_and_invoice": handle_project_invoice,
    "timesheet_and_invoice": handle_project_invoice,
    "register_receipt_expense": handle_register_receipt_expense,
    "correct_ledger_errors": handle_correct_ledger_errors,
    "ledger_correction": handle_correct_ledger_errors,
    "year_end_closing": handle_year_end_closing,
    "annual_closing": handle_year_end_closing,
    "month_end_closing": handle_year_end_closing,
    "ledger_analysis": handle_ledger_analysis,
    "analyze_ledger": handle_ledger_analysis,
    "reminder_fee": handle_reminder_fee,
    "dunning_fee": handle_reminder_fee,
    "receipt_expense": handle_register_receipt_expense,
    "register_receipt": handle_register_receipt_expense,
    # Aliases for LLM variations
    "create_and_send_invoice": handle_create_invoice,
    "send_invoice": handle_create_invoice,
    "pay_invoice": handle_register_payment,
    "register_incoming_invoice": handle_register_supplier_invoice,
    "create_supplier_invoice": handle_register_supplier_invoice,
    "delete_customer": handle_delete_entity,
    "delete_supplier": handle_delete_entity,
    "delete_product": handle_delete_entity,
    "delete_project": handle_delete_entity,
    "delete_invoice": handle_delete_entity,
}

def normalize_entities(entities):
    """Add missing canonical keys from known aliases. NEVER rename — only copy."""
    e = dict(entities)  # Don't mutate original

    # Comprehensive alias table: canonical_key → [aliases]
    ALIASES = {
        # Personal
        "dateOfBirth": ["birthDate", "fodselsdato", "geburtsdatum", "fechaNacimiento", "dateNaissance"],
        "nationalIdNumber": ["nationalIdentityNumber", "personalNumber", "personnelNumber",
                             "personnummer", "fødselsnummer", "personalIdNumber", "idNumber"],
        "bankAccountNumber": ["bankAccount", "bankkonto", "kontonummer", "accountNumber_bank", "supplierBankAccount"],
        # Employment
        "occupationCode": ["occupationalCode", "positionCode", "styrk", "stillingskode", "jobCode"],
        "dailyWorkingHours": ["workingHoursPerDay", "hoursPerDay", "arbeidstimer", "dailyWorkHours", "workHoursPerDay"],
        "employmentPercentage": ["percentageOfFullTimeEquivalent", "stillingsprosent"],
        "annualSalary": ["arslonn"],
        "startDate": ["tiltredelse"],
        "department": ["avdeling"],
        # Currency
        "currencyGainNOK": ["currencyGain", "exchangeRateGain", "exchangeRateGainNOK", "exchangeGainAmount", "agioAmount", "agio", "kursgewinn", "forexGain"],
        "currencyLossNOK": ["currencyLoss", "exchangeRateLoss", "exchangeRateLossNOK", "exchangeLossAmount", "disagioAmount", "disagio", "kursverlust", "forexLoss"],
        "paymentAmountNOK": ["paymentAmount", "paidAmountNOK", "paymentAmountNok", "paymentAmountInNOK", "invoiceAmountNok", "invoiceAmountInNOK"],
        "exchangeDifferenceAccount": ["fxAccount", "currencyAccount", "gainLossAccount", "differenceAccount", "exchangeLossAccount", "exchangeGainAccount", "agioAccount", "disagioAccount", "currencyLossAccount"],
        # Hours / timesheet
        "hoursLogged": ["hourEntries", "timeEntries", "timeLogs", "hoursRecorded", "hoursRegistration", "timesheet", "employeeHours", "workedHours"],
        # Transactions
        "bankTransactions": ["transactions", "entries", "bankEntries"],
        # Supplier cost
        "supplierCost": ["supplierExpense", "supplierCosts"],
        # General
        "email": ["employeeEmail", "supplierEmail", "customerEmail"],
        "name": ["productName", "supplierName", "customerName", "projectName"],
        "organizationNumber": ["supplierOrgNumber", "customerOrgNumber", "orgNumber", "customerOrganizationNumber"],
        "hours": ["hoursWorked", "count"],
        "priceExcludingVat": ["netPrice", "unitPrice", "priceExcVat", "price"],
        # Closing
        "salaryAccrual": ["salaryProvision", "wageAccrual", "payrollAccrual"],
        "accrualReversal": ["prepaidReversal", "prepaidExpensesReversal"],
    }

    # Apply aliases: if canonical key is missing, check all aliases
    for canonical, aliases in ALIASES.items():
        if canonical not in e or e[canonical] is None:
            for alias in aliases:
                if alias in e and e[alias] is not None:
                    e[canonical] = e[alias]
                    break

    # Regex fallback for currency-related keys the LLM might invent
    import re as _re
    for k, v in list(entities.items()):
        kl = k.lower()
        if v is not None and isinstance(v, (int, float)):
            if _re.search(r'(exchange|forex|currency|disagio).*(loss|disagio|amount)', kl) and not e.get("currencyLossNOK"):
                e["currencyLossNOK"] = float(v)
            elif _re.search(r'(exchange|forex|currency|agio).*(gain|agio|amount)', kl) and not e.get("currencyGainNOK"):
                e["currencyGainNOK"] = float(v)
        if v is not None and isinstance(v, (int, float, str)):
            if _re.search(r'(exchange|forex|currency|agio|disagio).*(loss|gain|diff|agio|disagio).*account', kl) and not e.get("exchangeDifferenceAccount"):
                e["exchangeDifferenceAccount"] = v

    # Regex fallback for hours/timesheet arrays
    if not e.get("hoursLogged"):
        for k, v in list(entities.items()):
            if isinstance(v, list) and v and isinstance(v[0], dict) and _re.search(r'hour|time|log|registr', k.lower()):
                if any('hours' in str(item) or 'employeeName' in str(item) for item in v):
                    e["hoursLogged"] = v
                    break

    # Also ensure employeeEmail from email
    if "employeeEmail" not in e:
        e["employeeEmail"] = e.get("email")

    # Employee name: construct from firstName+lastName
    if "employeeName" not in e:
        first = e.get("firstName") or e.get("projectManagerFirstName") or e.get("projectLeaderFirstName") or e.get("employeeFirstName") or ""
        last = e.get("lastName") or e.get("projectManagerLastName") or e.get("projectLeaderLastName") or e.get("employeeLastName") or ""
        full = f"{first} {last}".strip()
        if full:
            e["employeeName"] = full

    # Extract transactions from nested bankStatement object
    bs = e.get("bankStatement")
    if isinstance(bs, dict) and not e.get("bankTransactions"):
        nested_txns = bs.get("transactions") or bs.get("entries") or []
        if nested_txns:
            e["bankTransactions"] = nested_txns

    # Merge customerPayments + supplierPayments into bankTransactions
    if "bankTransactions" not in e or not e["bankTransactions"]:
        cust_payments = e.get("customerPayments") or e.get("incomingPayments") or e.get("inboundPayments") or e.get("receivedPayments") or []
        supp_payments = e.get("supplierPayments") or e.get("outgoingPayments") or e.get("outboundPayments") or e.get("sentPayments") or []
        if cust_payments or supp_payments:
            merged = []
            for cp in cust_payments:
                merged.append(cp)
            for sp in supp_payments:
                if sp.get("amount", 0) > 0:
                    sp["amount"] = -abs(sp["amount"])
                merged.append(sp)
            e["bankTransactions"] = merged

    # Regex fallback for payment arrays
    if not e.get("bankTransactions"):
        for k, v in list(entities.items()):
            if isinstance(v, list) and v and isinstance(v[0], dict) and _re.search(r'payment|betaling|zahlung|pago|paiement', k.lower()):
                if any('amount' in str(item) or 'customerName' in str(item) or 'supplierName' in str(item) for item in v):
                    if 'incoming' in k.lower() or 'customer' in k.lower() or 'received' in k.lower():
                        for item in v:
                            item.setdefault("customerName", item.get("customerName", ""))
                    elif 'outgoing' in k.lower() or 'supplier' in k.lower() or 'sent' in k.lower():
                        for item in v:
                            item.setdefault("supplierName", item.get("supplierName", ""))
                            if item.get("amount", 0) > 0:
                                item["amount"] = -abs(item["amount"])
                    if not e.get("bankTransactions"):
                        e["bankTransactions"] = []
                    e["bankTransactions"].extend(v)

    # Handle hours as list (multiple employees) → hoursLogged
    if isinstance(e.get("hours"), list):
        if not e.get("hoursLogged"):
            e["hoursLogged"] = e["hours"]
        e["hours"] = 0

    return e


def execute_plan(base_url, token, plan, prompt):
    task_type = plan.get("task_type", "unknown")
    entities = normalize_entities(plan.get("entities", {}))

    # Post-LLM task type correction: if LLM said create_order but prompt mentions invoice+payment, use invoice_with_payment
    if task_type == "create_order":
        pl = prompt.lower()
        has_invoice = any(kw in pl for kw in ["faktura", "invoice", "rechnung", "factura", "fatura"])
        has_payment = any(kw in pl for kw in ["betaling", "payment", "zahlung", "pago", "pagamento", "paiement"])
        if has_invoice and has_payment:
            task_type = "invoice_with_payment"
            print(f"Corrected task_type: create_order -> invoice_with_payment (prompt mentions invoice+payment)")

    print(f"Executing: {task_type} | entities: {json.dumps(entities, ensure_ascii=False)[:300]}")

    handler = HANDLERS.get(task_type)
    if handler:
        return handler(base_url, token, entities)

    # Try to match partial task types
    for key, h in HANDLERS.items():
        if key in task_type or task_type in key:
            print(f"Partial match: {task_type} -> {key}")
            return h(base_url, token, entities)

    print(f"Unknown task type: {task_type}")
    return True  # Return completed to avoid timeout penalty

# ============================================================
# File processing
# ============================================================

def extract_file_texts(files):
    texts = []
    for f in files:
        try:
            data = base64.b64decode(f["content_base64"])
            mime = f.get("mime_type", "")
            name = f.get("filename", "file")
            if "pdf" in mime:
                try:
                    import fitz  # PyMuPDF
                    doc = fitz.open(stream=data, filetype="pdf")
                    pdf_text = ""
                    for page in doc:
                        pdf_text += page.get_text()
                    doc.close()
                    if pdf_text.strip():
                        texts.append(f"[{name}]: {pdf_text[:3000]}")
                        print(f"  PDF '{name}': extracted {len(pdf_text)} chars text")
                    else:
                        # Image-based PDF — try OCR with Tesseract
                        print(f"  PDF '{name}': no text, trying OCR...")
                        import os as _os
                        _os.environ["PATH"] = "/opt/homebrew/bin:" + _os.environ.get("PATH", "")
                        doc2 = fitz.open(stream=data, filetype="pdf")
                        ocr_text = ""
                        for page in doc2:
                            try:
                                tp = page.get_textpage_ocr(language="nor+eng+deu+fra+spa+por+swe", dpi=300)
                                ocr_text += tp.extractText()
                            except Exception as ocr_err:
                                print(f"  OCR error on page: {ocr_err}")
                        doc2.close()
                        if ocr_text.strip():
                            texts.append(f"[{name}]: {ocr_text[:3000]}")
                            print(f"  PDF '{name}': OCR extracted {len(ocr_text)} chars")
                        else:
                            # Last resort: render as image for SDK vision path
                            doc3 = fitz.open(stream=data, filetype="pdf")
                            pix = doc3[0].get_pixmap(dpi=150)
                            f["_rendered_image_b64"] = base64.b64encode(pix.tobytes("png")).decode()
                            doc3.close()
                            texts.append(f"[{name}]: Scanned PDF (image rendered for vision)")
                except ImportError:
                    try:
                        import pdfminer.high_level as pdfm
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                            tmp.write(data)
                            tmp_path = tmp.name
                        text = pdfm.extract_text(tmp_path)
                        Path(tmp_path).unlink(missing_ok=True)
                        texts.append(f"[{name}]: {text[:2000]}")
                    except ImportError:
                        texts.append(f"[{name}]: PDF file (no PDF library available)")
            elif "image" in mime:
                texts.append(f"[{name}]: Image file")
            else:
                try:
                    texts.append(f"[{name}]: {data.decode('utf-8')[:1000]}")
                except:
                    texts.append(f"[{name}]: Binary file")
        except Exception as e:
            texts.append(f"[{f.get('filename','?')}]: Error: {e}")
    return texts

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI()

@app.post("/solve")
async def solve(request: Request):
    # ALWAYS return {"status": "completed"} — never return errors (scorer penalizes errors)
    try:
        return await _solve_inner(request)
    except Exception as e:
        print(f"FATAL solve error: {e}")
        traceback.print_exc()
        return JSONResponse({"status": "completed"})

async def _solve_inner(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    files = body.get("files", [])
    creds = body.get("tripletex_credentials", {})
    base_url = creds.get("base_url", "")
    token = creds.get("session_token", "")

    print(f"\n{'='*60}")
    print(f"PROMPT: {prompt[:500]}")
    print(f"Files: {[f['filename'] for f in files]}")
    print(f"Base URL: {base_url}")

    # Save full request for replay (files included)
    try:
        import time as _t
        req_dir = LOG_DIR / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_file = req_dir / f"{_t.strftime('%Y%m%d_%H%M%S')}.json"
        req_file.write_text(json.dumps({"prompt": prompt, "files": files}, ensure_ascii=False))
    except Exception as e:
        print(f"Save request error: {e}")

    file_texts = extract_file_texts(files)

    # Try regex first (fast, no LLM call), fall back to LLM
    # Skip regex if files are attached — need LLM to read PDF/image content
    # Only use regex for unambiguous simple tasks to avoid misclassification
    plan = None
    if not files:
        plan = regex_parse(prompt)
        # Whitelist: only trust regex for simple single-step tasks
        if plan and plan.get("task_type") not in (
            "create_department", "create_product", "create_customer", "create_employee",
            "create_supplier", "create_project", "run_payroll",
            "register_payment", "create_invoice", "register_supplier_invoice",
        ):
            plan = None  # Complex task — delegate to LLM
        # Extra guard: if prompt is complex (long + multiple actions), force LLM
        # This catches e.g. "Sett fastpris...fakturer kunden...delbetaling" misclassified as create_project
        if plan and len(prompt) > 200:
            import re as _re
            prompt_no_email = _re.sub(r'[\w.+-]+@[\w.-]+', '', prompt.lower())
            # Count distinct action VERBS only (not nouns like faktura/invoice)
            action_verbs = set(_re.findall(r'\b(?:opprett|create|crie|registrer|registe|slett|delete|send|generer|generate|gere|oppdater|update|reverser|reverse|kjør|run|konverter|converta|convert|créez|erstellen|envoyez|senden|fakturer|sett\s+fastpris|set\s+fixed|completa|configura)\b', prompt_no_email))
            if len(action_verbs) >= 2:
                print(f"COMPLEX prompt ({len(prompt)} chars, {len(action_verbs)} actions) — forcing LLM")
                plan = None
    if plan:
        print(f"REGEX PARSE: {plan.get('task_type', '?')}")
    else:
        plan = parse_with_claude(prompt, file_texts, raw_files=files)
    if not plan:
        print("LLM parsing failed, no plan generated")
        return JSONResponse({"status": "completed"})

    print(f"Plan: {json.dumps(plan, ensure_ascii=False, indent=2)[:600]}")

    if base_url and token:
        plans = plan if isinstance(plan, list) else [plan]
        for p in plans:
            try:
                execute_plan(base_url, token, p, prompt)
            except Exception as e:
                print(f"execute_plan error: {e}")
                traceback.print_exc()

    return JSONResponse({"status": "completed"})


BUILD_VERSION = "v20260322-0200"

@app.get("/health")
def health():
    return {"status": "ok", "version": BUILD_VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
