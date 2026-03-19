"""
run_game.py — One-command game runner for NM i AI 2026 warm-up.

Usage:
    python warmup/run_game.py easy
    python warmup/run_game.py medium
    python warmup/run_game.py hard
    python warmup/run_game.py expert
    python warmup/run_game.py nightmare

Requires Chrome with remote debugging enabled (port 18800 or 9222) and
logged in to app.ainm.no. Alternatively, set ACCESS_TOKEN env var to skip CDP.

Auto-retries on 429 (cooldown).
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

MAP_IDS = {
    "easy":      "3c7e90e6-e4bc-4095-a42b-e04eb6738809",
    "medium":    "0aba093f-a942-4a65-88ed-c60eb50b1c4a",
    "hard":      "9bb9b3de-7a56-4d5e-a4d4-637b08a526c8",
    "expert":    "c6acd676-ece3-4be5-ae24-9aff9e78f475",
    "nightmare": "8e5eeedd-767e-465d-94a4-67aef1b5b0d1",
}

CDP_PORT = int(os.environ.get("CDP_PORT", "18800"))


def get_token():
    """Get access_token — from env var or CDP cookie."""
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        return token

    # Try CDP on common ports
    import urllib.request
    for port in [CDP_PORT, 9222]:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/json/list", timeout=2)
            tabs = __import__("json").loads(resp.read())
            ws_url = next((t["webSocketDebuggerUrl"] for t in tabs if "ainm.no" in t.get("url", "")), None)
            if ws_url:
                import websockets
                async def _extract(ws_url):
                    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
                        import json
                        await ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
                        r = json.loads(await ws.recv())
                        for c in r["result"]["cookies"]:
                            if c["name"] == "access_token" and "ainm" in c["domain"]:
                                return c["value"]
                token = asyncio.run(_extract(ws_url))
                if token:
                    return token
        except Exception:
            pass

    raise RuntimeError("No access token found. Set ACCESS_TOKEN env var or open app.ainm.no in Chrome.")


def request_game_token(access_token, map_id, max_retries=5):
    """Request a game WS URL from the API."""
    import http.client, json, time
    for i in range(max_retries):
        conn = http.client.HTTPSConnection("api.ainm.no")
        conn.request("POST", "/games/request",
            body=json.dumps({"map_id": map_id}),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"})
        resp = conn.getresponse()
        body = resp.read().decode()
        if resp.status == 200:
            return json.loads(body)["ws_url"]
        elif resp.status == 429:
            retry = json.loads(body).get("retry_after", 62)
            print(f"Rate limited — waiting {retry}s (attempt {i+1}/{max_retries})...")
            time.sleep(retry + 1)
        else:
            raise RuntimeError(f"API error {resp.status}: {body}")
    raise RuntimeError("Max retries exceeded")


if __name__ == "__main__":
    difficulty = sys.argv[1].lower() if len(sys.argv) > 1 else "easy"
    if difficulty not in MAP_IDS:
        print(f"Unknown difficulty: {difficulty}. Choose: {', '.join(MAP_IDS)}")
        sys.exit(1)

    print(f"Getting token...")
    access_token = get_token()
    map_id = MAP_IDS[difficulty]

    print(f"Requesting {difficulty} game...")
    ws_url = request_game_token(access_token, map_id)

    # Import and run the bot
    from warmup.grocery_bot import run
    print(f"Starting {difficulty} game...")
    asyncio.run(run(ws_url))
