"""
Task 2 — Tripletex AI Accounting Agent

POST /solve receives:
  prompt: str (Norwegian/EN/ES/PT/NN/DE/FR)
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
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ============================================================
# Config
# ============================================================

PORT = int(os.environ.get("PORT", 8080))
ANTHROPIC_MODEL = "claude-opus-4-5"

# ============================================================
# Tripletex client helpers
# ============================================================

def resolve_base_url(base_url):
    """If tx-proxy.ainm.no doesn't resolve, we can't do anything. Just return as-is."""
    import socket
    try:
        host = base_url.split("/")[2].split(":")[0]
        socket.getaddrinfo(host, 443)
        return base_url, True
    except Exception as e:
        print(f"DNS resolution failed for {base_url}: {e}")
        return base_url, False


def tx_get(base_url, token, path, params=None):
    r = requests.get(f"{base_url}{path}", auth=("0", token), params=params or {}, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_post(base_url, token, path, body):
    r = requests.post(f"{base_url}{path}", auth=("0", token), json=body, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_put(base_url, token, path, body):
    r = requests.put(f"{base_url}{path}", auth=("0", token), json=body, timeout=30)
    return r.status_code, r.json() if r.content else {}

def tx_delete(base_url, token, path):
    r = requests.delete(f"{base_url}{path}", auth=("0", token), timeout=30)
    return r.status_code, {}

# ============================================================
# LLM: parse prompt → structured plan
# ============================================================

SYSTEM_PROMPT = """You are an AI accounting assistant for the Tripletex accounting system.

You receive a task prompt in Norwegian (or other languages) describing what accounting operation to perform.
You have access to the Tripletex v2 REST API.

Your job is to output a JSON plan with these fields:
{
  "task_type": string,  // e.g. "create_employee", "create_customer", "create_invoice", "register_payment", "create_travel_expense", "delete_travel_expense", "create_project", "create_department", "create_product"
  "entities": {
    // extracted entity data from the prompt
    // for employees: firstName, lastName, email, administrator (bool)
    // for customers: name, email, phone, organizationNumber
    // for products: name, price, unit, vatType
    // for invoices: customerName, orderDate, dueDate, lines [{description, unitPrice, count}]
    // for travel_expenses: employeeId/Name, date, description, amount
    // for projects: name, customerName, startDate, endDate
    // for departments: name
  },
  "steps": [string]  // ordered list of API calls needed
}

Output ONLY valid JSON, no markdown, no explanation.
"""

def _parse_llm_output(raw, prompt):
    """Parse LLM JSON output into a plan dict."""
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw.strip())
    if isinstance(parsed, list) and parsed:
        # Return list of plans for multi-step tasks
        plans = [p for p in parsed if isinstance(p, dict)]
        return plans if len(plans) > 1 else (plans[0] if plans else simple_parse(prompt))
    if isinstance(parsed, dict):
        return parsed
    return simple_parse(prompt)


def _gemini_parse(full_prompt):
    """Use Google Gemini API (Application Default Credentials — works in Cloud Run)."""
    import google.generativeai as genai
    from google.auth import default as gauth_default
    credentials, project = gauth_default()
    genai.configure(credentials=credentials)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\nTask:\n{full_prompt}")
    return response.text


def parse_prompt_with_llm(prompt, file_texts):
    full_prompt = prompt
    if file_texts:
        full_prompt += "\n\nAttached files:\n" + "\n".join(file_texts)
    
    # In Cloud Run: use Gemini (ADC) — in local: use claude CLI
    in_cloud_run = bool(os.environ.get("K_SERVICE"))
    
    if in_cloud_run:
        try:
            raw = _gemini_parse(full_prompt)
            print(f"Gemini raw output: {raw[:300]}")
            return _parse_llm_output(raw, prompt)
        except Exception as e:
            print(f"Gemini error: {e}")
            return simple_parse(prompt)
    else:
        try:
            result = subprocess.run(
                ["/Users/claude/.local/bin/claude", "-p", SYSTEM_PROMPT],
                input=full_prompt,
                capture_output=True, text=True, timeout=60
            )
            raw = result.stdout.strip()
            print(f"LLM raw output: {raw[:300]}")
            return _parse_llm_output(raw, prompt)
        except Exception as e:
            print(f"claude CLI error: {e}")
            return simple_parse(prompt)

# ============================================================
# Task executor
# ============================================================

def execute_plan(base_url, token, plan, prompt):
    task_type = plan.get("task_type", "")
    entities = plan.get("entities", {})
    
    print(f"Executing: {task_type} | entities: {json.dumps(entities)[:200]}")
    
    if task_type == "create_employee":
        return create_employee(base_url, token, entities)
    elif task_type == "create_customer":
        return create_customer(base_url, token, entities)
    elif task_type == "create_supplier":
        return create_supplier(base_url, token, entities)
    elif task_type == "create_product":
        return create_product(base_url, token, entities)
    elif task_type == "create_invoice":
        return create_invoice(base_url, token, entities)
    elif task_type == "create_project":
        return create_project(base_url, token, entities)
    elif task_type == "create_department":
        return create_department(base_url, token, entities)
    elif task_type == "create_travel_expense":
        return create_travel_expense(base_url, token, entities)
    elif task_type == "delete_travel_expense":
        return delete_travel_expense(base_url, token, entities)
    elif task_type == "register_payment":
        return register_payment(base_url, token, entities)
    else:
        # Generic: try to handle with LLM guidance
        print(f"Unknown task type: {task_type}, trying generic handler")
        return generic_handler(base_url, token, plan, prompt)


def create_employee(base_url, token, e):
    # Try progressively simpler bodies if 422
    bodies = []
    
    # Full body
    b1 = {}
    if "firstName" in e: b1["firstName"] = e["firstName"]
    if "lastName" in e: b1["lastName"] = e["lastName"]
    if "email" in e: b1["email"] = e["email"]
    if e.get("dateOfBirth"): b1["dateOfBirth"] = e["dateOfBirth"]
    if e.get("administrator") is True: b1["administrator"] = True
    bodies.append(b1)
    
    # Without dateOfBirth
    b2 = {k: v for k, v in b1.items() if k != "dateOfBirth"}
    if b2 != b1: bodies.append(b2)
    
    # Without email
    b3 = {k: v for k, v in b2.items() if k not in ("email", "administrator")}
    bodies.append(b3)
    
    status, resp = 422, {}
    for body in bodies:
        status, resp = tx_post(base_url, token, "/employee", body)
        vm = resp.get("validationMessages", []) if isinstance(resp, dict) else []
        print(f"create_employee attempt {list(body.keys())}: {status} {[m.get('message','') for m in vm]}")
        if status in (200, 201):
            break
    
    if status in (200, 201):
        emp_id = resp.get("value", {}).get("id")
        # Set administrator role if requested
        if emp_id and e.get("administrator") is True:
            tx_put(base_url, token, f"/employee/{emp_id}", {
                "id": emp_id, "firstName": e.get("firstName", ""), 
                "lastName": e.get("lastName", ""), "administrator": True
            })
        # Add employment if startDate provided
        if emp_id and e.get("startDate"):
            from datetime import date
            emp_body = {
                "employee": {"id": emp_id},
                "startDate": e["startDate"],
            }
            _, emp_resp = tx_post(base_url, token, f"/employee/{emp_id}/employment", emp_body)
            print(f"create_employment: {_} {str(emp_resp)[:100]}")
    
    return status in (200, 201)


def create_customer(base_url, token, e):
    body = {"isCustomer": True}
    if "name" in e: body["name"] = e["name"]
    if "email" in e: body["email"] = e["email"]
    if "phone" in e: body["phoneNumber"] = e["phone"]
    if "organizationNumber" in e: body["organizationNumber"] = e["organizationNumber"]
    
    # Include physical address if provided
    addr = e.get("address", {})
    if addr:
        body["physicalAddress"] = {
            "addressLine1": addr.get("street", ""),
            "postalCode": addr.get("postalCode", ""),
            "city": addr.get("city", ""),
            "country": {"id": 161},  # Norway
        }
    
    status, resp = tx_post(base_url, token, "/customer", body)
    print(f"create_customer: {status} {str(resp)[:200]}")
    return status in (200, 201)


def create_supplier(base_url, token, e):
    body = {"isSupplier": True}
    if "name" in e: body["name"] = e["name"]
    if "email" in e: body["email"] = e["email"]
    if "phone" in e: body["phoneNumber"] = e["phone"]
    if "organizationNumber" in e: body["organizationNumber"] = e["organizationNumber"]
    if "bankAccountNumber" in e: body["bankAccountNumber"] = e["bankAccountNumber"]
    
    status, resp = tx_post(base_url, token, "/supplier", body)
    print(f"create_supplier: {status} {json.dumps(resp.get('value', resp))[:500]}")
    
    # If email wasn't stored, try PUT to update
    if status in (200, 201) and e.get("email"):
        sup_id = resp.get("value", {}).get("id")
        sup_ver = resp.get("value", {}).get("version", 0)
        stored_email = resp.get("value", {}).get("email", "")
        print(f"Supplier email stored: '{stored_email}'")
        if sup_id and not stored_email:
            put_body = {"id": sup_id, "version": sup_ver, "name": body["name"],
                        "organizationNumber": body.get("organizationNumber", ""),
                        "email": e["email"]}
            _, pu = tx_put(base_url, token, f"/supplier/{sup_id}", put_body)
            print(f"PUT supplier email: {_} {str(pu)[:200]}")
    
    return status in (200, 201)


def create_product(base_url, token, e):
    body = {}
    if "name" in e: body["name"] = e["name"]
    num = e.get("number") or e.get("productNumber") or e.get("product_number")
    if num: body["number"] = str(num)
    
    # Price: prefer explicit priceExcludingVatCurrency
    price = e.get("price") or e.get("priceExcludingVat") or e.get("priceExcVat")
    if price and e.get("priceExcludingVat") is True:
        body["priceExcludingVatCurrency"] = float(price)
    elif price:
        body["priceExcludingVatCurrency"] = float(price)
    if e.get("priceIncVat"):
        body["priceIncludingVatCurrency"] = float(e["priceIncVat"])
    
    # Get vatType ID — look up 25% rate
    _, vt_resp = tx_get(base_url, token, "/product/vatType", {"fields": "id,name,number", "count": 20})
    vat_types = vt_resp.get("values", [])
    vat_id = None
    vat_pct = str(e.get("vatType", "25")).replace("%", "").strip()
    for vt in vat_types:
        nm = str(vt.get("name", "")).lower()
        num = str(vt.get("number", ""))
        if vat_pct in nm or vat_pct == num or ("25" in nm and vat_pct == "25"):
            vat_id = vt["id"]
            break
    if not vat_id and vat_types:
        # Default to first/standard
        vat_id = vat_types[0]["id"]
    if vat_id:
        body["vatType"] = {"id": vat_id}
    
    status, resp = tx_post(base_url, token, "/product", body)
    print(f"create_product: {status} {str(resp)[:300]}")
    return status in (200, 201)


def create_invoice(base_url, token, e):
    from datetime import date, timedelta
    today = str(date.today())
    due = str(date.today() + timedelta(days=30))
    
    # Find or create customer
    customer_name = e.get("customerName", "")
    customer_id = None
    
    if e.get("customerOrgNumber"):
        _, cr = tx_get(base_url, token, "/customer", {"organizationNumber": e["customerOrgNumber"], "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
        if customers:
            customer_id = customers[0]["id"]
    if not customer_id and customer_name:
        _, cr = tx_get(base_url, token, "/customer", {"name": customer_name, "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
        if customers:
            customer_id = customers[0]["id"]
    if not customer_id:
        _, cr = tx_post(base_url, token, "/customer", {"name": customer_name or "Customer", "isCustomer": True})
        customer_id = cr.get("value", {}).get("id")
    
    if not customer_id:
        print("No customer ID found")
        return False
    
    # Create order
    order_body = {
        "customer": {"id": customer_id},
        "orderDate": e.get("orderDate", today),
        "deliveryDate": e.get("dueDate", due),
        "isPrioritizeAmountsIncludingVat": False,
    }
    lines = e.get("lines", [])
    if lines:
        order_body["orderLines"] = [
            {
                "description": l.get("description", "Service"),
                "unitPriceExcludingVatCurrency": float(l.get("unitPrice", 0)),
                "count": float(l.get("count", 1)),
            }
            for l in lines
        ]
    else:
        order_body["orderLines"] = [{"description": "Service", "unitPriceExcludingVatCurrency": float(e.get("amount", 0)), "count": 1.0}]
    
    st_ord, order_resp = tx_post(base_url, token, "/order", order_body)
    order_id = order_resp.get("value", {}).get("id")
    print(f"create_order: {st_ord} id={order_id} resp={str(order_resp)[:200]}")
    
    if not order_id:
        return False
    
    # Create invoice from order via PUT /order/{id}/:invoice
    inv_date = e.get("orderDate", today)
    due_date = e.get("dueDate", due)
    
    # Method 1: PUT /order/{id}/:invoice (no sendToCustomer — avoids email validation)
    r = requests.put(
        f"{base_url}/order/{order_id}/:invoice",
        auth=("0", token),
        params={"invoiceDate": inv_date},
        timeout=30
    )
    print(f"PUT order/:invoice: {r.status_code} {r.text[:500]}")
    
    if r.status_code in (200, 201):
        return True
    
    # Method 2: POST /invoice with invoiceLines directly (no order)
    if customer_id:
        lines = []
        for line in e.get("lines", []):
            lines.append({
                "description": line.get("description", "Service"),
                "count": line.get("count", 1),
                "unitPriceExcludingVatCurrency": line.get("unitPrice") or line.get("unitPriceExcludingVatCurrency") or 0,
            })
        if not lines:
            lines = [{"description": e.get("description", "Service"), "count": 1, "unitPriceExcludingVatCurrency": 0}]
        
        inv_body2 = {
            "invoiceDate": inv_date,
            "invoiceDueDate": due_date,
            "customer": {"id": customer_id},
            "invoiceLines": lines
        }
        status2, inv_resp2 = tx_post(base_url, token, "/invoice", inv_body2)
        print(f"POST /invoice direct: {status2} {str(inv_resp2)[:300]}")
        if status2 in (200, 201):
            return True
    
    return False


def create_project(base_url, token, e):
    from datetime import date
    customer_id = None
    
    # Find customer by org number first, then by name
    if e.get("customerOrgNumber"):
        _, cr = tx_get(base_url, token, "/customer", {"organizationNumber": e["customerOrgNumber"], "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
        if not customers and e.get("customerName"):
            _, cr = tx_get(base_url, token, "/customer", {"name": e["customerName"], "fields": "id,name", "count": 5})
            customers = cr.get("values", [])
    elif e.get("customerName"):
        _, cr = tx_get(base_url, token, "/customer", {"name": e["customerName"], "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
    else:
        customers = []
    
    if customers:
        customer_id = customers[0]["id"]
    elif e.get("customerName"):
        _, cr2 = tx_post(base_url, token, "/customer", {"name": e["customerName"], "isCustomer": True})
        customer_id = cr2.get("value", {}).get("id")
    
    # Find project manager by email or name (handle both combined and split name)
    pm_id = None
    pm_first = e.get("projectManagerFirstName") or (e.get("projectManagerName", "").split() or [""])[0]
    pm_last = e.get("projectManagerLastName") or (" ".join(e.get("projectManagerName", "").split()[1:]) if e.get("projectManagerName") else "")
    pm_email = e.get("projectManagerEmail")
    
    if pm_email:
        _, er = tx_get(base_url, token, "/employee", {"email": pm_email, "fields": "id", "count": 5})
        employees = er.get("values", [])
        if employees:
            pm_id = employees[0]["id"]
    if not pm_id and pm_first:
        _, er = tx_get(base_url, token, "/employee", {"firstName": pm_first, "fields": "id", "count": 5})
        emps = er.get("values", [])
        if emps:
            pm_id = emps[0]["id"]
    
    # If still no PM, create the employee first
    if not pm_id and (pm_first or pm_email):
        pm_body = {}
        if pm_first: pm_body["firstName"] = pm_first
        if pm_last: pm_body["lastName"] = pm_last
        if pm_email: pm_body["email"] = pm_email
        _, pm_resp = tx_post(base_url, token, "/employee", pm_body)
        pm_id = pm_resp.get("value", {}).get("id")
        print(f"created PM employee: {pm_id}")
    
    # Fall back to any employee in the system
    if not pm_id:
        _, er2 = tx_get(base_url, token, "/employee", {"fields": "id", "count": 1})
        emps2 = er2.get("values", [])
        if emps2:
            pm_id = emps2[0]["id"]
    
    body = {
        "name": e.get("name") or e.get("projectName", "Project"),
        "startDate": e.get("startDate", str(date.today())),
    }
    if customer_id:
        body["customer"] = {"id": customer_id}
    if pm_id:
        body["projectManager"] = {"id": pm_id}
    if e.get("endDate"):
        body["endDate"] = e["endDate"]
    
    status, resp = tx_post(base_url, token, "/project", body)
    print(f"create_project: {status} {str(resp)[:200]}")
    
    if status == 422:
        # Try without optional fields
        body2 = {"name": body["name"], "startDate": body["startDate"]}
        if pm_id:
            body2["projectManager"] = {"id": pm_id}
        status, resp = tx_post(base_url, token, "/project", body2)
        print(f"create_project (no customer): {status} {str(resp)[:200]}")
    
    return status in (200, 201)


def create_department(base_url, token, e):
    body = {"name": e.get("name", "Department")}
    status, resp = tx_post(base_url, token, "/department", body)
    print(f"create_department: {status} {str(resp)[:200]}")
    return status in (200, 201)


def create_travel_expense(base_url, token, e):
    # Need employee ID
    emp_name = e.get("employeeName", "")
    emp_id = e.get("employeeId")
    
    if not emp_id and emp_name:
        _, emp_resp = tx_get(base_url, token, "/employee", {"firstName": emp_name.split()[0], "fields": "id,firstName,lastName", "count": 5})
        employees = emp_resp.get("values", [])
        if employees:
            emp_id = employees[0]["id"]
    
    if not emp_id:
        # Get any employee
        _, emp_resp = tx_get(base_url, token, "/employee", {"fields": "id,firstName,lastName", "count": 1})
        employees = emp_resp.get("values", [])
        if employees:
            emp_id = employees[0]["id"]
    
    from datetime import date
    body = {
        "employee": {"id": emp_id or 0},
        "date": e.get("date", str(date.today())),
    }
    if "description" in e:
        body["comment"] = e["description"]
    
    status, resp = tx_post(base_url, token, "/travelExpense", body)
    print(f"create_travel_expense: {status} {str(resp)[:200]}")
    return status in (200, 201)


def delete_travel_expense(base_url, token, e):
    # Find and delete travel expense
    emp_name = e.get("employeeName", "")
    _, te_resp = tx_get(base_url, token, "/travelExpense", {"fields": "id,employee,comment", "count": 10})
    expenses = te_resp.get("values", [])
    
    if not expenses:
        print("No travel expenses found to delete")
        return False
    
    # Delete the first matching one (or all if unspecified)
    for exp in expenses:
        exp_id = exp.get("id")
        if exp_id:
            status, _ = tx_delete(base_url, token, f"/travelExpense/{exp_id}")
            print(f"delete_travel_expense {exp_id}: {status}")
            if status in (200, 204):
                return True
    return False


def register_payment(base_url, token, e):
    from datetime import date
    today = str(date.today())
    
    # Find customer first
    customer_id = None
    if e.get("organizationNumber") or e.get("customerOrgNumber"):
        org_num = e.get("organizationNumber") or e.get("customerOrgNumber")
        _, cr = tx_get(base_url, token, "/customer", {"organizationNumber": org_num, "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
        if customers:
            customer_id = customers[0]["id"]
    if not customer_id and e.get("customerName"):
        _, cr = tx_get(base_url, token, "/customer", {"name": e["customerName"], "fields": "id,name", "count": 5})
        customers = cr.get("values", [])
        if customers:
            customer_id = customers[0]["id"]
    
    # GET /invoice requires invoiceDateFrom+invoiceDateTo
    from datetime import timedelta
    date_from = "2020-01-01"  # wide range to catch competition-pre-created invoices
    date_to = "2030-12-31"
    
    params = {"invoiceDateFrom": date_from, "invoiceDateTo": date_to, "count": 50}
    if customer_id:
        params["customerId"] = customer_id
    _, inv_resp = tx_get(base_url, token, "/invoice", params)
    invoices = inv_resp.get("values", [])
    
    # Retry without customer filter if none found
    if not invoices and customer_id:
        params2 = {"invoiceDateFrom": date_from, "invoiceDateTo": date_to, "count": 50}
        _, inv_resp2 = tx_get(base_url, token, "/invoice", params2)
        invoices = inv_resp2.get("values", [])
    
    print(f"Invoices found: {len(invoices)} resp={str(inv_resp)[:200]}")
    
    if not invoices:
        print("No invoices found — cannot register payment")
        return False
    
    # Pay the first unpaid or matching invoice
    amount = e.get("amount") or e.get("amountExVat")
    invoice = invoices[0]
    inv_id = invoice["id"]
    pay_amount = amount or invoice.get("amountRemainingCurrency") or invoice.get("amountCurrency", 0)
    
    status, resp = tx_post(base_url, token, f"/invoice/{inv_id}/:payment", {
        "paymentDate": e.get("date", today),
        "paymentTypeId": 1,
        "paidAmount": float(pay_amount)
    })
    print(f"register_payment: {status} {str(resp)[:200]}")
    return status in (200, 201)


def simple_parse(prompt):
    p = prompt.lower()
    entities = {}
    
    # Extract names (look for patterns)
    import re
    # Name patterns
    name_match = re.search(r'navn\s+([A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+)*)', prompt)
    if name_match:
        parts = name_match.group(1).split()
        entities["firstName"] = parts[0]
        entities["lastName"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', prompt)
    if email_match:
        entities["email"] = email_match.group(0)
    
    entities["administrator"] = any(w in p for w in ["administrator", "admin", "kontoadministrator"])
    
    # Task type detection
    if any(w in p for w in ["ansatt", "employee", "medarbeider"]):
        return {"task_type": "create_employee", "entities": entities, "steps": []}
    if any(w in p for w in ["leverandør", "leverandor", "supplier"]):
        return {"task_type": "create_supplier", "entities": entities, "steps": []}
    if any(w in p for w in ["kunde", "customer", "klient"]):
        return {"task_type": "create_customer", "entities": entities, "steps": []}
    if any(w in p for w in ["faktura", "invoice"]):
        return {"task_type": "create_invoice", "entities": entities, "steps": []}
    if any(w in p for w in ["prosjekt", "project"]):
        return {"task_type": "create_project", "entities": entities, "steps": []}
    if any(w in p for w in ["avdeling", "department"]):
        return {"task_type": "create_department", "entities": entities, "steps": []}
    if any(w in p for w in ["reiseregning", "travel expense", "reise"]):
        return {"task_type": "create_travel_expense", "entities": entities, "steps": []}
    if any(w in p for w in ["produkt", "product", "vare"]):
        return {"task_type": "create_product", "entities": entities, "steps": []}
    return {"task_type": "unknown", "entities": entities, "steps": []}


def generic_handler(base_url, token, plan, prompt):
    print(f"Generic handler for: {prompt[:100]}")
    return True  # Return completed, score 0 better than timeout

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
                # Try pdfminer or just note it
                try:
                    import pdfminer.high_level as pdfm
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name
                    text = pdfm.extract_text(tmp_path)
                    Path(tmp_path).unlink(missing_ok=True)
                    texts.append(f"[{name}]: {text[:2000]}")
                except ImportError:
                    texts.append(f"[{name}]: PDF file (could not parse)")
            elif "image" in mime:
                texts.append(f"[{name}]: Image file (attached)")
            else:
                try:
                    texts.append(f"[{name}]: {data.decode('utf-8')[:1000]}")
                except:
                    texts.append(f"[{name}]: Binary file")
        except Exception as e:
            texts.append(f"[{f.get('filename','?')}]: Error reading: {e}")
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
    print(f"PROMPT: {prompt[:300]}")
    print(f"Files: {[f['filename'] for f in files]}")
    print(f"Base URL: {base_url}")
    
    # Extract text from files
    file_texts = extract_file_texts(files)
    
    # Parse prompt with LLM
    plan = parse_prompt_with_llm(prompt, file_texts)
    print(f"Plan: {json.dumps(plan, indent=2)[:500] if plan else 'None'}")
    
    print(f"raw request body keys: {list(body.keys())}")
    print(f"full body sample: {json.dumps(body)[:500]}")
    
    if plan and base_url and token:
        resolved_url, dns_ok = resolve_base_url(base_url)
        if not dns_ok:
            print(f"WARNING: DNS failed for {base_url} — API calls will fail")
        plans = plan if isinstance(plan, list) else [plan]
        for p in plans:
            try:
                execute_plan(resolved_url, token, p, prompt)
            except Exception as e:
                print(f"execute_plan error: {e}")
    else:
        print("No plan or missing credentials")
    
    return JSONResponse({"status": "completed"})


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
