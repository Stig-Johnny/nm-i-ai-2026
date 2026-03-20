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

def tx_get(base_url, token, path, params=None):
    r = requests.get(f"{base_url}{path}", auth=("0", token), params=params or {}, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_post(base_url, token, path, body):
    r = requests.post(f"{base_url}{path}", auth=("0", token), json=body, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_put(base_url, token, path, body=None, params=None):
    r = requests.put(f"{base_url}{path}", auth=("0", token), json=body or {}, params=params or {}, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_delete(base_url, token, path):
    r = requests.delete(f"{base_url}{path}", auth=("0", token), timeout=30)
    return r.status_code, {}

# ============================================================
# LLM prompt parsing
# ============================================================

SYSTEM_PROMPT = """You are an expert accounting AI that parses task prompts into structured JSON.

Given a prompt in any language (Norwegian, English, Spanish, Portuguese, Nynorsk, German, French), extract:

{
  "task_type": "one of: create_employee, create_customer, create_supplier, create_product, create_department, create_project, create_invoice, create_travel_expense, delete_travel_expense, register_payment, register_supplier_invoice, run_payroll, create_credit_note, update_employee, update_customer, create_contact, create_order, invoice_with_payment, project_invoice, reverse_voucher, delete_entity, bank_reconciliation, unknown",
  // Use 'project_invoice' when the task involves: registering hours on a project, setting fixed price on a project, or generating an invoice linked to a project. If the prompt mentions a project name AND an invoice, use project_invoice.
  // Use 'create_accounting_dimension' when creating free accounting dimensions with values and/or posting vouchers linked to dimension values
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
        m = re.search(r'(?:org\.?\s*(?:nr|n[º°]|nummer|number)\.?\s*:?\s*|organisasjonsnummer\s+|Organisationsnummer\s+|organization\s+number\s+|numéro\s+d.organisation\s+|número\s+de\s+organiza\w+\s+)(\d{6,})', t, re.I)
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
        m = re.search(r"(?:adress[ea]|address|Adresse|L'adresse)\s+(?:ist|er|is|es|est|:)?\s+(.+?)(?:\.|$)", t, re.I)
        if not m: return None
        addr_str = m.group(1)
        # Try "Street, PostalCode City" pattern
        am = re.match(r'(.+?),?\s+(\d{4,5})\s+(\w+)', addr_str)
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

    # === DEPARTMENT (check before customer — "departments" is specific) ===
    if re.search(r'avdeling|department|abteilung|departamento|département', pl):
        dept_names = re.findall(r'"([^"]+)"', p)
        if len(dept_names) >= 2:
            return {"task_type": "create_department", "entities": {"items": dept_names}}
        elif dept_names:
            return {"task_type": "create_department", "entities": {"name": dept_names[0]}}
        else:
            name_match = re.search(r'(?:navn|name|nombre|nom)\s+["\']?(\w[\w\s]*)', p)
            return {"task_type": "create_department", "entities": {"name": name_match.group(1).strip() if name_match else "Department"}}

    # === INVOICE (check before customer — invoices mention customers but are invoices) ===
    # Exclude "faktura" appearing only in email addresses
    invoice_text = re.sub(r'[\w.+-]+@[\w.-]+', '', pl)  # Remove emails before checking
    if re.search(r'faktura|invoice|rechnung|factura|facture', invoice_text):
        if re.search(r'kreditnota|credit\s*note|gutschrift|nota\s+de\s+crédito', pl):
            return {"task_type": "create_credit_note", "entities": {}}
        # Supplier invoice (incoming)
        if re.search(r'leverandør|supplier|lieferant', pl) and re.search(r'mottatt|received|erhalten|recibido|reçu|registrer.*faktura', pl):
            supplier_name = find_name_after(p, 'leverandøren', 'Lieferanten', 'supplier', 'fournisseur', 'proveedor')
            org = find_org(p)
            inv_match = re.search(r'(INV[\w-]+)', p)
            total = find_amount(p, 'på', 'von', 'of', 'de')
            vat_match = re.search(r'(\d+)\s*%', p)
            vat_rate = int(vat_match.group(1)) if vat_match else 25
            acct_match = re.search(r'konto\s+(\d{4})|account\s+(\d{4})|Konto\s+(\d{4})', p, re.I)
            acct = int((acct_match.group(1) or acct_match.group(2) or acct_match.group(3))) if acct_match else 6540
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
    if re.search(r'lønn|payroll|gehalt|nómina|salaire|lön', pl):
        emp_name = find_name_after(p, 'for', 'für', 'para', 'pour')
        email = find_email(p)
        base = find_amount(p, 'grunnlønn', 'base salary', 'grundgehalt', 'salario base')
        bonus = find_amount(p, 'bonus', 'engangsbonus')
        # Avoid grabbing base salary as bonus
        if bonus and base and bonus == base:
            # Re-extract bonus specifically
            bonus_match = re.search(r'(?:bonus|engangsbonus)[^\d]*(\d[\d\s]*)\s*(?:kr|NOK)', p, re.I)
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
    if re.search(r'ansatt|employee|mitarbeiter|empleado|employé|empregado|medarbeider', pl):
        # Extract name — look for "namens X", "named X", "navn X", etc
        name = find_name_after(p, 'namens', 'named', 'kalt', 'llamado', 'nommé', 'chamado')
        if not name:
            name = find_name_after(p, 'Mitarbeiter', 'employee', 'ansatt')
        first, last = split_name(name) if name else ("", "")
        email = find_email(p)
        dob_match = re.search(r'(?:geboren|born|født|nacido|né)\s+(?:am|on|den|el|le)?\s*(\d{1,2})\.?\s*(\w+)\s+(\d{4})', p, re.I)
        dob = None
        if dob_match:
            months = {"januar":1,"february":2,"februar":2,"march":3,"mars":3,"märz":3,"april":4,"mai":5,"may":5,"juni":6,"june":6,"juli":7,"july":7,"august":8,"september":9,"oktober":10,"october":10,"november":11,"desember":12,"december":12,"dezember":12}
            day = int(dob_match.group(1))
            month_str = dob_match.group(2).lower().rstrip('.')
            month = months.get(month_str, 1)
            year = int(dob_match.group(3))
            dob = f"{year}-{month:02d}-{day:02d}"
        start_match = re.search(r'(?:startdato|start\s*date|Startdatum|fecha\s+de\s+inicio)\s+(\d{1,2})\.?\s*(\w+)\s+(\d{4})', p, re.I)
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

    # === PAYMENT ===
    if re.search(r'betaling|payment|zahlung|pago|paiement', pl):
        return {"task_type": "register_payment", "entities": {"amount": find_amount(p)}}

    return None  # Unrecognized — fall through to LLM


def parse_with_claude(prompt, file_texts):
    import time as _time
    start = _time.time()

    # Always use LLM for parsing — regex is fragile across 7 languages
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

    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", "--model", "haiku", SYSTEM_PROMPT],
            input=full_prompt,
            capture_output=True, text=True, timeout=45
        )
        raw = result.stdout.strip()
        print(f"LLM raw: {raw[:400]}")

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
    except subprocess.TimeoutExpired:
        print("claude CLI timeout (45s)")
        _log_request(prompt, file_texts, None, False, _time.time() - start)
        return None
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        _log_request(prompt, file_texts, {"error": str(e)}, False, _time.time() - start)
        return None
    except Exception as e:
        print(f"claude CLI error: {e}")
        _log_request(prompt, file_texts, {"error": str(e)}, False, _time.time() - start)
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

def find_account_id(base_url, token, number):
    st, resp = tx_get(base_url, token, "/ledger/account", {"number": str(number), "fields": "id,number"})
    vals = resp.get("values", []) if st == 200 else []
    return vals[0]["id"] if vals else None

# ============================================================
# Task handlers
# ============================================================

def handle_create_employee(base_url, token, e):
    dept_id = get_or_create_department(base_url, token)
    body = {"userType": "STANDARD"}

    if "firstName" in e: body["firstName"] = e["firstName"]
    if "lastName" in e: body["lastName"] = e["lastName"]
    if "email" in e: body["email"] = e["email"]
    if e.get("dateOfBirth"): body["dateOfBirth"] = e["dateOfBirth"]
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

        # Add employment if startDate
        if e.get("startDate"):
            tx_post(base_url, token, "/employee/employment", {
                "employee": {"id": emp_id},
                "startDate": e["startDate"],
            })

    return st in (200, 201)


def handle_create_customer(base_url, token, e):
    body = {"isCustomer": True}
    name = e.get("name") or e.get("customerName")
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
    body = {"name": e.get("name") or e.get("supplierName", "Supplier"), "isSupplier": True}
    email = e.get("email") or e.get("supplierEmail")
    if email:
        body["email"] = email
        body["invoiceEmail"] = email
    org = e.get("organizationNumber") or e.get("supplierOrgNumber") or e.get("orgNumber")
    if org: body["organizationNumber"] = org
    if "phone" in e or "phoneNumber" in e:
        body["phoneNumber"] = e.get("phone") or e.get("phoneNumber")

    addr = e.get("address") or e.get("physicalAddress") or {}
    if addr:
        body["physicalAddress"] = {
            "addressLine1": addr.get("street") or addr.get("addressLine1", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},
        }

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
        body["priceExcludingVatCurrency"] = float(price)
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

    # Find or create customer
    customer_id = None
    cust_name = e.get("customerName")
    cust_org = e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
    if cust_org or cust_name:
        customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)

    # Find or create project manager
    pm_id = None
    pm = e.get("projectManager") or {}
    pm_name = e.get("projectManagerName") or pm.get("name")
    pm_first = e.get("projectManagerFirstName") or pm.get("firstName") or (pm_name.split()[0] if pm_name else None)
    pm_email = e.get("projectManagerEmail") or pm.get("email")

    if pm_first or pm_email:
        pm_id = get_or_create_employee(base_url, token, name=pm_name or pm_first, email=pm_email)

    if not pm_id:
        st, resp = tx_get(base_url, token, "/employee", {"fields": "id", "count": 1})
        vals = resp.get("values", [])
        if vals: pm_id = vals[0]["id"]

    body = {
        "name": e.get("name") or e.get("projectName", "Project"),
        "startDate": e.get("startDate", today),
    }
    if customer_id: body["customer"] = {"id": customer_id}
    if pm_id: body["projectManager"] = {"id": pm_id}
    if e.get("endDate"): body["endDate"] = e["endDate"]

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
        # Set VAT type per line if specified
        vat_rate = l.get("vatRate") if l.get("vatRate") is not None else l.get("vatType")
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

    # Create order
    order_body = {
        "customer": {"id": customer_id},
        "orderDate": e.get("orderDate") or e.get("invoiceDate") or today,
        "deliveryDate": e.get("dueDate") or due,
        "orderLines": order_lines,
    }
    st_ord, order_resp = tx_post(base_url, token, "/order", order_body)
    order_id = order_resp.get("value", {}).get("id")
    print(f"create_order: {st_ord} id={order_id}")
    if not order_id:
        print(f"order failed: {str(order_resp)[:200]}")
        return False

    # Convert order to invoice
    inv_date = e.get("invoiceDate") or e.get("orderDate") or today
    st_inv, inv_resp = tx_put(base_url, token, f"/order/{order_id}/:invoice", {},
                               params={"invoiceDate": inv_date, "sendToCustomer": "false"})
    print(f"order->invoice: {st_inv} {str(inv_resp)[:200]}")
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

    # Create travel expense
    title = e.get("title") or e.get("description") or "Reise"
    te_body = {
        "employee": {"id": emp_id},
        "title": title,
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

    # Add cost lines
    expenses = list(e.get("expenses", []))
    diet = e.get("diet", {})
    if diet and (diet.get("total") or (diet.get("dailyRate") and diet.get("days"))):
        total = diet.get("total") or (diet.get("dailyRate", 0) * diet.get("days", 0))
        expenses.insert(0, {"description": "Diett", "amount": total})

    for exp in expenses:
        desc = exp.get("description", "").lower()
        amt = float(exp.get("amount", 0))
        if not amt:
            continue

        if "fly" in desc or "flight" in desc or "billett" in desc:
            cat_id = find_cat("fly", "flybillett", "flight")
        elif "taxi" in desc:
            cat_id = find_cat("taxi")
        elif "hotell" in desc or "hotel" in desc:
            cat_id = find_cat("hotell", "hotel")
        elif "diett" in desc or "diet" in desc or "kost" in desc:
            cat_id = find_cat("diett", "kost", "mat")
        elif "tog" in desc or "train" in desc:
            cat_id = find_cat("tog", "train")
        elif "buss" in desc or "bus" in desc:
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

    # Find invoice
    params = {"invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-12-31", "count": 50}
    _, inv_resp = tx_get(base_url, token, "/invoice", params)
    invoices = inv_resp.get("values", [])
    if not invoices:
        print("No invoices found")
        return False

    # Get payment type
    _, pt_resp = tx_get(base_url, token, "/invoice/paymentType", {"count": 5, "fields": "id"})
    pt_list = pt_resp.get("values", [])
    pt_id = pt_list[0]["id"] if pt_list else 0

    invoice = invoices[0]
    inv_id = invoice["id"]
    amount = e.get("amount") or e.get("paidAmount") or invoice.get("amountCurrency", 0)

    st, resp = tx_put(base_url, token, f"/invoice/{inv_id}/:payment", params={
        "paymentDate": e.get("date") or e.get("paymentDate") or today,
        "paymentTypeId": pt_id,
        "paidAmount": float(amount),
    })
    print(f"register_payment: {st} {str(resp)[:200]}")
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

    # Build postings for supplier invoice
    # Pattern: expense with vatType (Tripletex auto-calculates VAT) + credit with supplier
    NOK_VAT_IN = {"25": 1, "15": 11, "12": 12, "0": 0}
    vat_pct = str(int(vat_rate)).replace("%", "").strip()
    vat_type_id = NOK_VAT_IN.get(vat_pct, 1)

    postings = [
        {
            "row": 1,
            "date": e.get("invoiceDate") or today,
            "description": e.get("description") or "Leverandorfaktura",
            "account": {"id": expense_acct_id},
            "amountGross": round(net_amount, 2),
            "amountGrossCurrency": round(net_amount, 2),
            "vatType": {"id": vat_type_id},
        },
        {
            "row": 2,
            "date": e.get("invoiceDate") or today,
            "description": f"Leverandorgjeld {e.get('supplierName', '')}".strip(),
            "account": {"id": payable_acct_id},
            "amountGross": round(-total_incl, 2),
            "amountGrossCurrency": round(-total_incl, 2),
            "supplier": {"id": supplier_id} if supplier_id else None,
        },
    ]

    # Remove None supplier refs
    for p in postings:
        if p.get("supplier") is None:
            p.pop("supplier", None)

    inv_date = e.get("invoiceDate") or today
    inv_due = e.get("invoiceDueDate") or str(date.today() + timedelta(days=30))

    # Try proper /supplierInvoice endpoint first (creates a real supplier invoice)
    si_body = {
        "invoiceDate": inv_date,
        "invoiceDueDate": inv_due,
        "invoiceNumber": e.get("invoiceNumber") or "",
        "supplier": {"id": supplier_id} if supplier_id else None,
        "voucher": {
            "date": inv_date,
            "description": f"Leverandorfaktura {e.get('invoiceNumber', '')} {e.get('supplierName', '')}".strip(),
            "postings": postings,
        },
    }
    if si_body.get("supplier") is None:
        si_body.pop("supplier", None)

    st, resp = tx_post(base_url, token, "/supplierInvoice", si_body)
    print(f"register_supplier_invoice: {st} {str(resp)[:300]}")

    if st in (200, 201):
        return True

    # Fallback: raw voucher
    print("supplierInvoice failed, falling back to voucher")
    voucher_body = {
        "date": inv_date,
        "description": f"Leverandorfaktura {e.get('invoiceNumber', '')} {e.get('supplierName', '')}".strip(),
        "postings": postings,
    }
    st2, resp2 = tx_post(base_url, token, "/ledger/voucher?sendToLedger=true", voucher_body)
    print(f"voucher fallback: {st2}")
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
            "amountGross": round(base_salary, 2),
            "amountGrossCurrency": round(base_salary, 2),
        })
        row += 1
    if bonus > 0:
        postings.append({
            "row": row, "date": today,
            "description": f"Bonus {emp_name or ''}".strip(),
            "account": {"id": salary_acct},
            "amountGross": round(bonus, 2),
            "amountGrossCurrency": round(bonus, 2),
        })
        row += 1
    postings.append({
        "row": row, "date": today,
        "description": f"Lonnsutbetaling {emp_name or ''}".strip(),
        "account": {"id": bank_acct},
        "amountGross": round(-total, 2),
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

    st, resp = tx_put(base_url, token, f"/employee/{emp_id}", body)
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

    cust_name = e.get("customerName")
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
    """Reverse a voucher — Tier 2/3."""
    today = str(date.today())

    # Find voucher to reverse
    _, v_resp = tx_get(base_url, token, "/ledger/voucher", {
        "dateFrom": "2020-01-01", "dateTo": "2030-12-31", "count": 10
    })
    vouchers = v_resp.get("values", [])
    if not vouchers:
        print("No vouchers to reverse")
        return False

    v_id = e.get("voucherId") or vouchers[0]["id"]
    st, resp = tx_put(base_url, token, f"/ledger/voucher/{v_id}/:reverse", params={
        "date": e.get("date") or today,
    })
    print(f"reverse_voucher: {st} {str(resp)[:200]}")
    return st in (200, 201)


def handle_project_invoice(base_url, token, e):
    """Tier 2: Register hours on a project and generate a project invoice."""
    today = str(date.today())

    # Step 1: Create customer
    cust_name = e.get("customerName")
    cust_org = e.get("customerOrgNumber") or e.get("customerOrganizationNumber")
    customer_id = get_or_create_customer(base_url, token, name=cust_name, org_number=cust_org)

    # Step 2: Create employee (the person who worked the hours / project manager)
    first = e.get("firstName") or e.get("projectManagerFirstName") or e.get("projectLeaderFirstName") or ""
    last = e.get("lastName") or e.get("projectManagerLastName") or e.get("projectLeaderLastName") or ""
    emp_name = e.get("employeeName") or e.get("projectManagerName") or e.get("projectManager") or e.get("projectLeaderName") or e.get("projectLeader") or (f"{first} {last}".strip() or None)
    emp_email = e.get("employeeEmail") or e.get("projectManagerEmail") or e.get("projectLeaderEmail")
    emp_id = get_or_create_employee(base_url, token, name=emp_name, email=emp_email)

    # Step 3: Create project
    proj_name = e.get("projectName", "Project")
    proj_body = {
        "name": proj_name,
        "startDate": today,
    }
    if customer_id:
        proj_body["customer"] = {"id": customer_id}
    if emp_id:
        proj_body["projectManager"] = {"id": emp_id}
    # Set fixed price if applicable
    fixed_price = float(e.get("fixedPrice") or 0)
    if fixed_price:
        proj_body["isFixedPrice"] = True
        proj_body["fixedPrice"] = fixed_price
    st, proj_resp = tx_post(base_url, token, "/project", proj_body)
    proj_id = proj_resp.get("value", {}).get("id")
    print(f"create project: {st} id={proj_id} {str(proj_resp)[:200] if st != 201 else ''}")

    # Step 4: Find or create activity
    activity_name = e.get("activityName") or e.get("activity", "Arbeid")
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

    # Step 5: Register timesheet hours
    hours = float(e.get("hours") or e.get("hoursWorked") or e.get("count") or 0)
    hourly_rate = float(e.get("hourlyRate") or e.get("rate") or 0)
    # Try to extract from lines if not set directly
    lines = e.get("lines", [])
    if not hours and lines:
        hours = float(lines[0].get("count") or lines[0].get("hours") or 0)
    if not hourly_rate and lines:
        hourly_rate = float(lines[0].get("unitPrice") or lines[0].get("rate") or 0)
    if emp_id and hours > 0:
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
            "costRate": hourly_rate,
        }
        if proj_id:
            hr_body["project"] = {"id": proj_id}
        if act_id:
            hr_body["activity"] = {"id": act_id}
        st_hr, hr_resp = tx_post(base_url, token, "/employee/hourlyCostAndRate", hr_body)
        print(f"hourly rate: {st_hr} {str(hr_resp)[:150]}")

    # Step 7: Create invoice
    ensure_bank_account(base_url, token)

    # Handle fixed price projects
    fixed_price = float(e.get("fixedPrice") or 0)
    invoice_pct = float(e.get("invoicePercentage") or 100)
    invoice_amount = float(e.get("invoiceAmount") or 0)

    if fixed_price:
        total_amount = invoice_amount or (fixed_price * invoice_pct / 100)
        desc = f"{proj_name} - delbetaling ({int(invoice_pct)}%)" if invoice_pct < 100 else proj_name
    elif hours and hourly_rate:
        total_amount = hours * hourly_rate
        desc = f"{activity_name} - {proj_name}" if activity_name else proj_name
    else:
        total_amount = float(e.get("totalAmount", 0))
        desc = proj_name

    order_lines = [{
        "description": desc,
        "unitPriceExcludingVatCurrency": hourly_rate or total_amount,
        "count": hours or 1.0,
    }]

    order_body = {
        "customer": {"id": customer_id} if customer_id else None,
        "orderDate": today,
        "deliveryDate": today,
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
        print(f"order->invoice: {st_inv} {str(inv_resp)[:200]}")

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
             "amountGross": round(amount, 2), "amountGrossCurrency": round(amount, 2)},
            {"row": 2, "date": today, "account": {"id": bank_id},
             "amountGross": round(-amount, 2), "amountGrossCurrency": round(-amount, 2)},
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


HANDLERS = {
    "create_employee": handle_create_employee,
    "create_customer": handle_create_customer,
    "create_supplier": handle_create_supplier,
    "create_product": handle_create_product,
    "create_department": handle_create_department,
    "create_project": handle_create_project,
    "create_invoice": handle_create_invoice,
    "create_travel_expense": handle_create_travel_expense,
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
    "project_invoice": handle_project_invoice,
    "create_accounting_dimension": handle_create_accounting_dimension,
    "accounting_dimension": handle_create_accounting_dimension,
    "register_hours_and_invoice": handle_project_invoice,
    "timesheet_and_invoice": handle_project_invoice,
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

def execute_plan(base_url, token, plan, prompt):
    task_type = plan.get("task_type", "unknown")
    entities = plan.get("entities", {})
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
                    import pdfminer.high_level as pdfm
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name
                    text = pdfm.extract_text(tmp_path)
                    Path(tmp_path).unlink(missing_ok=True)
                    texts.append(f"[{name}]: {text[:2000]}")
                except ImportError:
                    texts.append(f"[{name}]: PDF file (pdfminer not available)")
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

    file_texts = extract_file_texts(files)

    # Parse prompt with LLM
    plan = parse_with_claude(prompt, file_texts)
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


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
