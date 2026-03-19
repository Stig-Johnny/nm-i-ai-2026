"""Reusable WebSocket client for NM i AI 2026 tasks."""

import asyncio
import json
import websockets


async def connect(url: str, handler, timeout: float = 120):
    """Connect to a WebSocket game server.

    Args:
        url: WebSocket URL from the platform
        handler: async function(ws, state_dict) -> action_dict
        timeout: max game duration in seconds
    """
    async with websockets.connect(url) as ws:
        try:
            async for message in ws:
                state = json.loads(message)
                action = await handler(ws, state)
                if action is not None:
                    await ws.send(json.dumps(action))
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
        except asyncio.TimeoutError:
            print("Timeout reached")


async def connect_with_raw(url: str, handler):
    """Connect and pass raw messages for non-JSON protocols."""
    async with websockets.connect(url) as ws:
        try:
            async for message in ws:
                response = await handler(ws, message)
                if response is not None:
                    if isinstance(response, dict):
                        await ws.send(json.dumps(response))
                    else:
                        await ws.send(response)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
