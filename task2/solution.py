"""
Task 2 — LLM Task (placeholder until docs drop at 18:15 CET)
=============================================================
No API keys needed — we use Claude Code subscription.
For LLM inference, iClaw-E reasons directly as the agent.

If the task requires programmatic inference at scale (batch calls),
we'll use claude CLI or spawn sub-agents via sessions_spawn.

Replace `solve()` with actual task logic once docs are live.

Run:
    python task2/solution.py --url wss://...
    python task2/solution.py --file input.json  # offline test
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import websockets


def solve(state: dict) -> dict:
    """
    Core solver — pure function: state in, action out.

    TODO: implement once docs are live at 18:15.

    Common LLM task patterns:
      - Classification: state["text"] → {"label": "..."}
      - Generation:     state["prompt"] → {"response": "..."}
      - QA:            state["question"], state["context"] → {"answer": "..."}
      - Multi-choice:  state["question"], state["choices"] → {"choice": 0}
    """
    if not hasattr(solve, "_logged"):
        print(f"[task2] First state keys: {list(state.keys())}")
        solve._logged = True

    msg_type = state.get("type", "")
    if msg_type == "game_over":
        return None

    # === PLACEHOLDER — replace with actual logic at 18:15 ===
    print(f"[task2] Unknown state: {json.dumps(state)[:200]}")
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
