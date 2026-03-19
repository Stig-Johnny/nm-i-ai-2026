# Coding Patterns

Agreed conventions for the competition. Both Claude-5 and iClaw-E follow these.

## Project Structure

```
nm-i-ai-2026/
├── task1/
│   ├── solution.py      # Main entry point
│   ├── model.py         # Model/inference logic
│   └── utils.py         # Task-specific helpers
├── task2/
│   └── solution.py
├── task3/
│   └── solution.py
├── shared/
│   ├── ws_client.py     # WebSocket client (if tasks use WS)
│   ├── api_client.py    # HTTP submission client (if tasks use API)
│   └── token.py         # CDP token extraction
├── warmup/
│   ├── grocery_bot.py
│   └── run_game.py
└── docs/
```

Each task is self-contained. `shared/` has reusable code.

## Entry Point Pattern

Every task solution follows the same structure:

```python
"""
Task N — [Description]
Run: python taskN/solution.py --url "wss://..."
     python taskN/solution.py --file input.json
"""

import asyncio
import json
import sys

# === Config ===
# Constants, model paths at the top

# === Core Logic ===
def solve(state: dict) -> dict:
    """Pure function: state in, action out. No side effects."""
    pass

# === Transport ===
async def run_ws(url: str):
    """WebSocket game loop."""
    import websockets
    async with websockets.connect(url) as ws:
        async for msg in ws:
            state = json.loads(msg)
            if state.get("type") == "game_over":
                print(f"Score: {state.get('score')}")
                break
            action = solve(state)
            await ws.send(json.dumps(action))

def run_http(endpoint: str, data: dict) -> dict:
    """HTTP submission."""
    import requests
    resp = requests.post(endpoint, json=data)
    return resp.json()

# === Main ===
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="WebSocket URL")
    parser.add_argument("--file", help="Input file")
    args = parser.parse_args()

    if args.url:
        asyncio.run(run_ws(args.url))
    elif args.file:
        with open(args.file) as f:
            data = json.load(f)
        print(json.dumps(solve(data), indent=2))
```

## Git Workflow (Competition Mode)

During the 69-hour competition, speed beats process:

- **Push directly to main** — no PRs, no reviews
- **Prefix commits:** `task1:`, `task2:`, `task3:`, `shared:`, `docs:`
- **Never force push** — always pull before push
- **Coordinate via Discord** — "I'm working on task2, don't touch it"

```bash
# Before pushing
git pull origin main --rebase
git push origin main

# If conflict
git stash
git pull origin main --rebase
git stash pop
# resolve and push
```

## Naming Conventions

- **Files:** `snake_case.py`
- **Functions:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE`
- **No type annotations** — speed over correctness during competition

## Dependencies

All deps go in `requirements.txt`. Install once at start:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Currently installed:
- `websockets`, `aiohttp` — networking
- `numpy`, `scipy` — math
- `torch`, `torchvision` — CV models
- `scikit-learn`, `xgboost`, `pandas` — ML
- `optuna` — hyperparameter tuning
- `requests` — HTTP

Add new deps with `pip install X && pip freeze | grep X >> requirements.txt`.

## LLM Access

We use **Claude Code subscription** (not API keys). For LLM tasks, Claude reasons directly within the agent — no SDK calls needed.

If a task requires programmatic LLM calls at scale, we use Claude Code's built-in tools or spawn sub-agents.

## Error Handling

Minimal during competition:

```python
# NO - don't wrap internal logic
# If it crashes, we want to see the traceback
```

## Logging

Print to stdout. No logging framework:

```python
print(f"Round {rnd} | Score {score} | Action: {action}")
```

Print every 50th round or on significant events. Don't spam every round.

## Testing

No unit tests during competition. Test by running against the platform:

```bash
python warmup/run_game.py easy    # warm-up
python task1/solution.py --url "wss://..."  # real task
```

Save one game replay/output for debugging:

```bash
python task1/solution.py --url "wss://..." 2>&1 | tee task1/last_run.log
```

## Communication Protocol

When working on a task, post to Discord:

```
Starting task2 — LLM classification. Don't touch task2/.
```

When done:

```
task2: baseline submitted, score 45. Pushed to main. Free to optimize.
```

When blocked:

```
task1: stuck on image format. Need help parsing base64 with alpha channel.
```
