"""
Automated game runner — gets token from Chrome CDP and runs the bot.

Usage:
    python warmup/run_game.py easy
    python warmup/run_game.py medium
    python warmup/run_game.py hard
    python warmup/run_game.py expert
    python warmup/run_game.py nightmare
"""

import asyncio
import json
import sys
import time
import http.client
import urllib.request
import importlib

import websockets

MAP_IDS = {
    "easy": "3c7e90e6-e4bc-4095-a42b-e04eb6738809",
    "medium": "0aba093f-a942-4a65-88ed-c60eb50b1c4a",
    "hard": "9bb9b3de-7a56-4d5e-a4d4-637b08a526c8",
    "expert": "c6acd676-ece3-4be5-ae24-9aff9e78f475",
    "nightmare": "8e5eeedd-767e-465d-94a4-67aef1b5b0d1",
}


async def get_access_token() -> str:
    """Get access token from Chrome via CDP."""
    resp = urllib.request.urlopen("http://localhost:9222/json/list")
    tabs = json.loads(resp.read())
    page_ws = None
    for t in tabs:
        if "ainm.no" in t.get("url", ""):
            page_ws = t["webSocketDebuggerUrl"]
            break
    if not page_ws:
        raise RuntimeError("No ainm.no tab found in Chrome. Open app.ainm.no first.")

    async with websockets.connect(page_ws, max_size=10_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        r = json.loads(await ws.recv())
        for c in r["result"]["cookies"]:
            if c["name"] == "access_token" and "ainm" in c["domain"]:
                return c["value"]
    raise RuntimeError("No access_token cookie found. Are you logged in?")


def request_game(token: str, map_id: str) -> str:
    """Request a game token from the API. Handles cooldown."""
    for attempt in range(5):
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
            data = json.loads(body)
            return data["ws_url"]
        elif resp.status == 429:
            retry = json.loads(body).get("retry_after", 60)
            print(f"Cooldown — waiting {retry}s...")
            time.sleep(retry + 1)
        else:
            raise RuntimeError(f"API error {resp.status}: {body}")

    raise RuntimeError("Too many retries")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <{'|'.join(MAP_IDS.keys())}>")
        sys.exit(1)

    difficulty = sys.argv[1].lower()
    if difficulty not in MAP_IDS:
        print(f"Unknown difficulty: {difficulty}. Choose from: {', '.join(MAP_IDS.keys())}")
        sys.exit(1)

    print(f"=== Running {difficulty.upper()} ===")

    # Get auth token
    token = asyncio.run(get_access_token())
    print("Got access token")

    # Request game
    ws_url = request_game(token, MAP_IDS[difficulty])
    print(f"Got game URL")

    # Import and run the bot
    sys.path.insert(0, ".")
    from warmup.grocery_bot import run
    asyncio.run(run(ws_url))


if __name__ == "__main__":
    main()
