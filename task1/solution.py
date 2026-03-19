"""
Task 1 — Computer Vision
========================
Scaffold for image classification / object detection tasks.
Replace the `predict()` function with the actual task logic once docs are live.

Typical pattern:
  - Server sends image (base64 or URL) each round
  - Respond with label / bounding boxes / embeddings

Run:
    python task1/solution.py --url wss://... --token TOKEN
"""

import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import websockets

# ---------- lazy imports (heavy, load once) ----------
_model = None
_transform = None


def load_model():
    global _model, _transform
    if _model is not None:
        return _model, _transform

    # Try torch first, fall back to simpler approach
    try:
        import torch
        import torchvision.models as models
        import torchvision.transforms as T

        _model = models.efficientnet_b0(weights="IMAGENET1K_V1")
        _model.eval()
        _transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        print("Loaded EfficientNet-B0 (ImageNet)")
    except ImportError:
        print("torch not available — using placeholder model")
        _model = None
        _transform = None

    return _model, _transform


def decode_image(data: str | bytes):
    """Decode base64 or raw bytes to PIL Image."""
    try:
        from PIL import Image
        if isinstance(data, str):
            if data.startswith("data:"):
                data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
        else:
            raw = data
        return Image.open(BytesIO(raw)).convert("RGB")
    except Exception as e:
        print(f"Image decode error: {e}")
        return None


def predict(state: dict[str, Any]) -> dict[str, Any]:
    """
    Main prediction function.
    
    Args:
        state: Game state dict from server. Inspect actual format at kickoff.
    
    Returns:
        Action dict to send back.
    
    TODO: Replace with actual task logic once docs are live.
    """
    model, transform = load_model()

    # ---- Example: image classification ----
    image_data = state.get("image") or state.get("data") or state.get("input")
    if image_data and model:
        import torch
        img = decode_image(image_data)
        if img:
            tensor = transform(img).unsqueeze(0)
            with torch.no_grad():
                logits = model(tensor)
                pred = int(logits.argmax(1).item())
            return {"prediction": pred}

    # ---- Fallback ----
    print(f"Unknown state keys: {list(state.keys())}")
    return {"prediction": 0}


async def run(url: str):
    print(f"Connecting to {url}")
    async with websockets.connect(url) as ws:
        async for message in ws:
            state = json.loads(message)
            msg_type = state.get("type", "")

            if msg_type == "game_over":
                score = state.get("score", "?")
                print(f"Game over — score: {score}")
                break

            action = predict(state)
            await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="WebSocket URL")
    args = parser.parse_args()

    # Pre-load model
    load_model()
    asyncio.run(run(args.url))
