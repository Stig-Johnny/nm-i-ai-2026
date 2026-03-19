"""
Task 2 — Language Model
=======================
Scaffold for LLM-based tasks: text classification, generation, QA, RAG, etc.
Replace `respond()` with actual task logic once docs are live.

Typical patterns:
  - Server sends text prompt / document each round
  - Respond with label, generated text, or structured JSON

Run:
    python task2/solution.py --url wss://... --token TOKEN
"""

import asyncio
import json
import os
import sys
from typing import Any

import websockets


# ---------- model setup (choose one approach) ----------

def build_claude_client():
    """Use Anthropic Claude via API (fast, no GPU needed)."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        pass
    return None


def build_openai_client():
    """Use OpenAI API as fallback."""
    try:
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            return openai.OpenAI(api_key=api_key)
    except ImportError:
        pass
    return None


_claude = None
_openai = None


def get_clients():
    global _claude, _openai
    if _claude is None:
        _claude = build_claude_client()
    if _openai is None:
        _openai = build_openai_client()
    return _claude, _openai


# ---------- main logic ----------

SYSTEM_PROMPT = """You are a competition assistant for NM i AI 2026.
Answer precisely and concisely. Return only the requested format."""


def call_llm(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 256) -> str:
    """Call LLM and return text response."""
    claude, openai_client = get_clients()

    if claude:
        msg = claude.messages.create(
            model="claude-haiku-4-5",  # fast + cheap
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    if openai_client:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()

    # Fallback: no API key
    print("WARNING: No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
    return "unknown"


def respond(state: dict[str, Any]) -> dict[str, Any]:
    """
    Main response function.
    
    Args:
        state: Game state dict from server.
    
    Returns:
        Action dict to send back.
    
    TODO: Replace with actual task logic once docs are live.
    """
    # ---- Example: text classification ----
    text = state.get("text") or state.get("input") or state.get("prompt") or ""
    task_type = state.get("task") or state.get("type") or ""

    if text:
        answer = call_llm(f"Task: {task_type}\nInput: {text}\nAnswer:")
        return {"answer": answer}

    print(f"Unknown state keys: {list(state.keys())}")
    return {"answer": "unknown"}


async def run(url: str):
    print(f"Connecting to {url}")
    # Pre-warm LLM clients
    get_clients()
    print(f"Claude: {'✓' if _claude else '✗'}  OpenAI: {'✓' if _openai else '✗'}")

    async with websockets.connect(url) as ws:
        async for message in ws:
            state = json.loads(message)
            msg_type = state.get("type", "")

            if msg_type == "game_over":
                print(f"Game over — score: {state.get('score', '?')}")
                break

            action = respond(state)
            print(f"Round {state.get('round', '?')} → {action}")
            await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="WebSocket URL")
    args = parser.parse_args()
    asyncio.run(run(args.url))
