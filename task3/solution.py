"""
Task 3 — Machine Learning
==========================
Scaffold for tabular ML / supervised learning tasks.
Replace `predict()` with actual task logic once docs are live.

Typical patterns:
  - Server sends feature vector each round
  - Respond with predicted label or value
  - OR: receive training data in first round, then predict

Run:
    python task3/solution.py --url wss://... --token TOKEN
"""

import asyncio
import json
import sys
from typing import Any

import numpy as np
import websockets


# ---------- model setup ----------

class MLModel:
    """Wrapper for sklearn/xgboost model with online learning support."""

    def __init__(self):
        self.model = None
        self.is_fitted = False
        self.feature_names = None
        self.classes_ = None

    def fit(self, X, y):
        """Train on provided data."""
        try:
            import xgboost as xgb
            self.model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                use_label_encoder=False,
                eval_metric="logloss",
                n_jobs=-1,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            self.model = GradientBoostingClassifier(n_estimators=100)

        self.model.fit(X, y)
        self.is_fitted = True
        print(f"Model trained on {len(X)} samples")

    def predict(self, x: list | np.ndarray) -> Any:
        """Predict single sample."""
        if not self.is_fitted:
            return None
        x = np.array(x).reshape(1, -1)
        return self.model.predict(x)[0]

    def predict_proba(self, x: list | np.ndarray) -> list:
        """Return class probabilities."""
        if not self.is_fitted or not hasattr(self.model, "predict_proba"):
            return []
        x = np.array(x).reshape(1, -1)
        return self.model.predict_proba(x)[0].tolist()


_ml_model = MLModel()
_training_data = []  # (features, label) pairs accumulated across rounds


def process_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Main prediction function.
    
    Args:
        state: Game state dict from server.
    
    Returns:
        Action dict to send back.
    
    TODO: Replace with actual task logic once docs are live.
    """
    msg_type = state.get("type", "")

    # ---- Training data batch ----
    if msg_type == "training_data" or "train" in state:
        data = state.get("data") or state.get("train") or []
        for sample in data:
            features = sample.get("features") or sample.get("x")
            label = sample.get("label") or sample.get("y")
            if features is not None and label is not None:
                _training_data.append((features, label))

        if len(_training_data) > 0:
            X = np.array([s[0] for s in _training_data])
            y = np.array([s[1] for s in _training_data])
            _ml_model.fit(X, y)

        return {"status": "trained", "samples": len(_training_data)}

    # ---- Single prediction ----
    features = state.get("features") or state.get("x") or state.get("input")
    if features is not None:
        if _ml_model.is_fitted:
            pred = _ml_model.predict(features)
            proba = _ml_model.predict_proba(features)
            result = {"prediction": int(pred) if pred is not None else 0}
            if proba:
                result["confidence"] = float(max(proba))
            return result
        else:
            print("Model not fitted yet — returning default")
            return {"prediction": 0}

    # ---- Batch prediction ----
    batch = state.get("batch") or state.get("samples")
    if batch:
        preds = []
        for sample in batch:
            feat = sample.get("features") or sample.get("x") or sample
            pred = _ml_model.predict(feat) if _ml_model.is_fitted else 0
            preds.append(int(pred) if pred is not None else 0)
        return {"predictions": preds}

    print(f"Unknown state keys: {list(state.keys())}")
    return {"prediction": 0}


async def run(url: str):
    print(f"Connecting to {url}")
    async with websockets.connect(url) as ws:
        async for message in ws:
            state = json.loads(message)
            msg_type = state.get("type", "")

            if msg_type == "game_over":
                print(f"Game over — score: {state.get('score', '?')}")
                break

            action = process_state(state)
            print(f"Round {state.get('round', '?')} → {action}")
            await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="WebSocket URL")
    args = parser.parse_args()
    asyncio.run(run(args.url))
