"""
Task 2 — LLM Task (placeholder until docs drop at 18:15 CET)
=============================================================
Replace `solve()` with the actual task logic once docs are live.

Run:
    python task2/solution.py --url wss://...
    python task2/solution.py --file input.json  # offline test
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import websockets

# Load env / API keys
try:
    from shared.api_keys import get_anthropic_key
    ANTHROPIC_KEY = get_anthropic_key()
except Exception:
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def get_client():
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def solve(state: dict) -> dict:
    """
    Core solver — pure function: state in, action out.

    TODO: implement once docs are live at 18:15.

    Common patterns for LLM tasks:
      - Classification:  state has "text" → return {"label": "..."}
      - Generation:      state has "prompt" → return {"response": "..."}
      - QA:             state has "question", "context" → return {"answer": "..."}
      - Multi-choice:   state has "question", "choices" → return {"choice": 0}
    """
    # Print state structure on first call (helps understand format quickly)
    if not hasattr(solve, "_logged"):
        print(f"[task2] First state keys: {list(state.keys())}")
        solve._logged = True

    msg_type = state.get("type", "")
    if msg_type == "game_over":
        return None

    # === PLACEHOLDER — replace with actual logic ===
    client = get_client()
    
    # Example: answer a question
    question = state.get("question") or state.get("text") or state.get("prompt") or str(state)
    
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": question}]
        )
        answer = resp.content[0].text.strip()
        # TODO: adapt key name to actual task format
        return {"answer": answer}
    except Exception as e:
        print(f"[task2] API error: {e}")
        return {"answer": ""}


async def run(url: str):
    print(f"[task2] Connecting to {url[:60]}...")
    async with websockets.connect(url) as ws:
        rnd = 0
        async for message in ws:
            state = json.loads(message)
            if state.get("type") == "game_over":
                print(f"[task2] Game over — score: {state.get('score', '?')}")
                break
            rnd += 1
            if rnd % 10 == 0:
                print(f"[task2] Round {rnd} | Score {state.get('score', '?')}")
            action = solve(state)
            if action is not None:
                await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="WebSocket URL")
    parser.add_argument("--file", help="Input file for offline test")
    args = parser.parse_args()

    if args.url:
        asyncio.run(run(args.url))
    elif args.file:
        with open(args.file) as f:
            data = json.load(f)
        print(json.dumps(solve(data), indent=2))
    else:
        parser.print_help()
