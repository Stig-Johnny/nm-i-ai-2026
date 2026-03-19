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

def parse_prompt_with_llm(prompt, file_texts):
    full_prompt = prompt
    if file_texts:
        full_prompt += "\n\nAttached files:\n" + "\n".join(file_texts)
    
    # Use claude CLI (Claude Code subscription — no API key needed)
    try:
        result = subprocess.run(
            ["/Users/claude/.local/bin/claude", "-p", SYSTEM_PROMPT],
            input=full_prompt,
            capture_output=True, text=True, timeout=60
        )
        raw = result.stdout.strip()
        # Strip markdown fences if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"claude CLI error: {e}, stdout: {result.stdout[:200] if 'result' in dir() else ''}")
        # Fallback: simple keyword parser
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
    body = {}
    if "firstName" in e: body["firstName"] = e["firstName"]
    if "lastName" in e: body["lastName"] = e["lastName"]
    if "email" in e: body["email"] = e["email"]
    
    status, resp = tx_post(base_url, token, "/employee", body)
    print(f"create_employee: {status} {str(resp)[:200]}")
    
    if status in (200, 201) and e.get("administrator"):
        emp_id = resp.get("value", {}).get("id")
        if emp_id:
            # Set administrator role
            tx_put(base_url, token, f"/employee/{emp_id}", {
                **body, "id": emp_id, "administrator": True
            })
    return status in (200, 201)


def create_customer(base_url, token, e):
    body = {"isCustomer": True}
    if "name" in e: body["name"] = e["name"]
    if "email" in e: body["email"] = e["email"]
    if "phone" in e: body["phoneNumber"] = e["phone"]
    if "organizationNumber" in e: body["organizationNumber"] = e["organizationNumber"]
    
    status, resp = tx_post(base_url, token, "/customer", body)
    print(f"create_customer: {status} {str(resp)[:200]}")
    return status in (200, 201)


def create_product(base_url, token, e):
    body = {}
    if "name" in e: body["name"] = e["name"]
    if "price" in e: body["costExcludingVatCurrency"] = e["price"]
    if "priceIncVat" in e: body["priceIncludingVatCurrency"] = e["priceIncVat"]
    
    status, resp = tx_post(base_url, token, "/product", body)
    print(f"create_product: {status} {str(resp)[:200]}")
    return status in (200, 201)


def create_invoice(base_url, token, e):
    # Find or create customer
    customer_name = e.get("customerName", "")
    _, cust_resp = tx_get(base_url, token, "/customer", {"name": customer_name, "fields": "id,name", "count": 5})
    customers = cust_resp.get("values", [])
    
    if not customers:
        # Create customer
        _, cust_resp = tx_post(base_url, token, "/customer", {"name": customer_name, "isCustomer": True})
        customer_id = cust_resp.get("value", {}).get("id")
    else:
        customer_id = customers[0]["id"]
    
    if not customer_id:
        print("No customer ID found")
        return False
    
    # Create order first
    from datetime import date
    today = str(date.today())
    order_body = {
        "customer": {"id": customer_id},
        "orderDate": e.get("orderDate", today),
    }
    lines = e.get("lines", [])
    if lines:
        order_body["orderLines"] = [
            {"description": l.get("description", ""), "unitPriceExcludingVatCurrency": l.get("unitPrice", 0), "count": l.get("count", 1)}
            for l in lines
        ]
    
    _, order_resp = tx_post(base_url, token, "/order", order_body)
    order_id = order_resp.get("value", {}).get("id")
    print(f"create_order: order_id={order_id}")
    
    if not order_id:
        return False
    
    # Create invoice
    inv_body = {
        "invoiceDate": e.get("orderDate", today),
        "invoiceDueDate": e.get("dueDate", today),
        "customer": {"id": customer_id},
        "orders": [{"id": order_id}]
    }
    status, inv_resp = tx_post(base_url, token, "/invoice", inv_body)
    print(f"create_invoice: {status} {str(inv_resp)[:200]}")
    return status in (200, 201)


def create_project(base_url, token, e):
    customer_name = e.get("customerName", "")
    customer_id = None
    
    if customer_name:
        _, cust_resp = tx_get(base_url, token, "/customer", {"name": customer_name, "fields": "id,name", "count": 5})
        customers = cust_resp.get("values", [])
        if customers:
            customer_id = customers[0]["id"]
    
    body = {"name": e.get("name", "Project")}
    if customer_id:
        body["customer"] = {"id": customer_id}
    from datetime import date
    body["startDate"] = e.get("startDate", str(date.today()))
    
    status, resp = tx_post(base_url, token, "/project", body)
    print(f"create_project: {status} {str(resp)[:200]}")
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
    # Find invoice
    _, inv_resp = tx_get(base_url, token, "/invoice", {"fields": "id,invoiceNumber,amountCurrency", "count": 10})
    invoices = inv_resp.get("values", [])
    
    if not invoices:
        print("No invoices found")
        return False
    
    invoice = invoices[0]
    inv_id = invoice["id"]
    amount = e.get("amount") or invoice.get("amountCurrency", 0)
    
    from datetime import date
    status, resp = tx_post(base_url, token, f"/invoice/{inv_id}/:payment", {
        "paymentDate": e.get("date", str(date.today())),
        "paymentTypeId": 1,  # default payment type
        "paidAmount": amount
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
    
    if plan and base_url and token:
        execute_plan(base_url, token, plan, prompt)
    else:
        print("No plan or missing credentials")
    
    return JSONResponse({"status": "completed"})


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
