"""
CDP token extraction — get access_token from Chrome browser.

Requires Chrome running with --remote-debugging-port=9222
and logged in to app.ainm.no.
"""

import asyncio
import json
import http.client
import time
import urllib.request

import websockets


def get_chrome_ws_url():
    """Find the ainm.no tab's WebSocket debugger URL."""
    resp = urllib.request.urlopen("http://localhost:9222/json/list")
    tabs = json.loads(resp.read())
    for t in tabs:
        if "ainm.no" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("No ainm.no tab found in Chrome. Open app.ainm.no first.")


async def _get_access_token(ws_url):
    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        r = json.loads(await ws.recv())
        for c in r["result"]["cookies"]:
            if c["name"] == "access_token" and "ainm" in c["domain"]:
                return c["value"]
    raise RuntimeError("No access_token cookie found. Are you logged in?")


def get_access_token():
    """Get the ainm.no access token from Chrome cookies via CDP."""
    ws_url = get_chrome_ws_url()
    return asyncio.run(_get_access_token(ws_url))


def request_game(token, map_id, max_retries=5):
    """Request a game token from the API. Handles cooldown automatically."""
    for _ in range(max_retries):
        conn = http.client.HTTPSConnection("api.ainm.no")
        conn.request("POST", "/games/request",
            body=json.dumps({"map_id": map_id}),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            })
        resp = conn.getresponse()
        body = resp.read().decode()

        if resp.status == 200:
            return json.loads(body)["ws_url"]
        elif resp.status == 429:
            retry = json.loads(body).get("retry_after", 60)
            print(f"Cooldown — waiting {retry}s...")
            time.sleep(retry + 1)
        else:
            raise RuntimeError(f"API error {resp.status}: {body}")

    raise RuntimeError("Too many retries")


MAP_IDS = {
    "easy": "3c7e90e6-e4bc-4095-a42b-e04eb6738809",
    "medium": "0aba093f-a942-4a65-88ed-c60eb50b1c4a",
    "hard": "9bb9b3de-7a56-4d5e-a4d4-637b08a526c8",
    "expert": "c6acd676-ece3-4be5-ae24-9aff9e78f475",
    "nightmare": "8e5eeedd-767e-465d-94a4-67aef1b5b0d1",
}
