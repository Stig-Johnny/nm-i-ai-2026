"""
Smoke test: POST to /solve endpoint to catch crashes in the full request path.
Covers: FastAPI routing, parse_with_claude, _log_request, execute_plan — the full chain.

Run: python3 task2/test_server_smoke.py
"""
import sys, json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, '.')

# Ensure log dir exists before importing
import os
os.makedirs("/tmp/tripletex-requests", exist_ok=True)

from task2.solution import app, tx_get, tx_post, tx_put, tx_delete, regex_parse

_id = 1000
def _next():
    global _id; _id += 1; return _id

def mock_get(base_url, token, path, params=None):
    if "/department" in path: return 200, {"values": [{"id": 1, "name": "Avdeling"}]}
    if "/employee" in path: return 200, {"values": []}
    if "/customer" in path: return 200, {"values": []}
    if "/supplier" in path: return 200, {"values": []}
    if "/travelExpense/rateCategory" in path:
        return 200, {"values": [{"id": 60, "name": "Diett", "type": "PER_DIEM", "isValidDomestic": True}]}
    if "/travelExpense/costCategory" in path:
        return 200, {"values": [{"id": 10, "description": "Fly", "showOnTravelExpenses": True}]}
    if "/travelExpense/paymentType" in path: return 200, {"values": [{"id": 50}]}
    if "/salary/type" in path:
        return 200, {"values": [{"id": 200, "number": "2000", "name": "Fastlønn"}, {"id": 202, "number": "2002", "name": "Bonus"}]}
    if "/ledger/account" in path:
        return 200, {"values": [{"id": 500, "number": 1920, "name": "Bank", "bankAccountNumber": "123"}]}
    if "/activity" in path: return 200, {"values": [{"id": 77, "name": "Arbeid"}]}
    if "/product" in path: return 200, {"values": []}
    if "/employee/employment" in path: return 200, {"values": []}
    if "/invoice" in path: return 200, {"values": []}
    if "/bankAccount" in path: return 200, {"values": [{"id": 1, "number": "1920"}]}
    return 200, {"values": []}

def mock_post(base_url, token, path, body):
    if "/salary/transaction" in path: return 422, {"message": "No employment"}
    return 201, {"value": {"id": _next()}}

def mock_put(base_url, token, path, body=None, params=None):
    return 200, {"value": {"id": _next()}}

def mock_delete(base_url, token, path):
    return 200, {}


PROMPTS = [
    # Simple regex-parseable
    "Create the customer Brightstone Ltd with organization number 853284882. The address is Parkveien 61, 5003 Bergen. Email: post@brightstone.no.",
    'Create three departments in Tripletex: "Innkjøp", "Drift", and "Kundeservice".',
    "Registrer leverandøren Sjøbris AS med organisasjonsnummer 811212717. E-post: faktura@sjbris.no.",
    'Crea el producto "Mantenimiento" con número de producto 7266. El precio es 650 NOK sin IVA, utilizando la tasa estándar del 25 %.',
    "Wir haben einen neuen Mitarbeiter namens Anna Schneider, geboren am 6. August 2000. Bitte legen Sie ihn als Mitarbeiter mit der E-Mail anna.schneider@example.org und dem Startdatum 17. March 2026 an.",
    "Kjør lønn for Erik Nilsen (erik.nilsen@example.org) for denne måneden. Grunnlønn er 53350 kr. Legg til en engangsbonus på 11050 kr i tillegg til grunnlønnen.",
    "Processe o salário de Lucas Santos (lucas.santos@example.org) para este mês. O salário base é de 59600 NOK. Adicione um bónus único de 12900 NOK além do salário base.",
]


if __name__ == "__main__":
    client = TestClient(app)
    passed = 0
    failed = 0

    for prompt in PROMPTS:
        short = prompt[:60]
        try:
            # Mock parse_with_claude to use regex_parse (avoids calling claude CLI)
            def mock_parse(prompt, file_texts=None, raw_files=None):
                return regex_parse(prompt)

            with patch('task2.solution.tx_get', mock_get), \
                 patch('task2.solution.tx_post', mock_post), \
                 patch('task2.solution.tx_put', mock_put), \
                 patch('task2.solution.tx_delete', mock_delete), \
                 patch('task2.solution.parse_with_claude', mock_parse):
                resp = client.post("/solve", json={
                    "prompt": prompt,
                    "files": [],
                    "tripletex_credentials": {"base_url": "http://test", "session_token": "tok"}
                })
            if resp.status_code == 200:
                passed += 1
            else:
                print(f"  FAIL | HTTP {resp.status_code} | {short}")
                failed += 1
        except Exception as e:
            print(f"  FAIL | CRASH: {e} | {short}")
            failed += 1

    print(f"\nSmoke test: {passed}/{passed+failed} passed")
    if failed == 0:
        print("ALL ENDPOINTS OK — no crashes in full request path")
