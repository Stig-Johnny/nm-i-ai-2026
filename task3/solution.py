"""
Task 3 — Astar Island: Norse World Prediction
==============================================
Observe a 40x40 Norse world through a 15x15 viewport.
50 queries across 5 seeds. Predict W×H×6 terrain probability tensor.

API: https://api.ainm.no/astar-island/
Auth: Bearer JWT from app.ainm.no cookie

Run:
    python task3/solution.py --baseline    # Submit uniform 1/6 baseline
    python task3/solution.py --explore     # Explore and predict
"""

import json
import sys
import numpy as np
import http.client

sys.path.insert(0, ".")
from shared.token import get_access_token

BASE_URL = "api.ainm.no"
MAP_SIZE = 40
VIEWPORT = 15
NUM_CLASSES = 6
TOTAL_QUERIES = 50


def api_call(method, path, token, body=None):
    conn = http.client.HTTPSConnection(BASE_URL)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    conn.request(method, f"/astar-island{path}",
                 body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    if resp.status == 200:
        return json.loads(data)
    print(f"{method} /astar-island{path}: {resp.status} {data[:200]}")
    return None


def submit_baseline(token):
    """Submit uniform 1/6 for all cells — any score > 0."""
    rounds = api_call("GET", "/rounds", token)
    budget = api_call("GET", "/budget", token)
    print(f"Rounds: {json.dumps(rounds)[:300]}")
    print(f"Budget: {json.dumps(budget)[:200]}")

    # Build uniform prediction
    uniform = np.full((MAP_SIZE, MAP_SIZE, NUM_CLASSES), 1.0 / NUM_CLASSES).tolist()

    # Parse seeds from rounds response
    predictions = {}
    if isinstance(rounds, list):
        for r in rounds:
            sid = r if isinstance(r, str) else str(r.get("id", r.get("seed_id", r)))
            predictions[sid] = uniform
    elif isinstance(rounds, dict):
        for key in rounds:
            predictions[key] = uniform

    if not predictions:
        print(f"Could not parse seeds from: {json.dumps(rounds)[:500]}")
        return

    print(f"Submitting uniform baseline for {len(predictions)} seeds...")
    result = api_call("POST", "/submit", token, predictions)
    print(f"Result: {json.dumps(result, indent=2)[:500] if result else 'None'}")


def explore_and_predict(token):
    """Use queries to observe map, then predict."""
    rounds = api_call("GET", "/rounds", token)
    budget = api_call("GET", "/budget", token)
    print(f"Rounds: {json.dumps(rounds)[:300]}")
    print(f"Budget: {json.dumps(budget)[:200]}")

    # Parse seeds
    seeds = []
    if isinstance(rounds, list):
        for r in rounds:
            seeds.append(r if isinstance(r, str) else str(r.get("id", r.get("seed_id", r))))
    elif isinstance(rounds, dict):
        seeds = list(rounds.keys())

    if not seeds:
        print("No seeds found")
        return

    queries_per_seed = TOTAL_QUERIES // len(seeds)
    print(f"{len(seeds)} seeds, {queries_per_seed} queries each")

    predictions = {}

    for seed_id in seeds:
        print(f"\n=== Seed: {seed_id} ===")

        # Map: uniform prior
        terrain_map = np.full((MAP_SIZE, MAP_SIZE, NUM_CLASSES), 1.0 / NUM_CLASSES)
        observed = np.zeros((MAP_SIZE, MAP_SIZE), dtype=bool)

        # Grid coverage positions (no overlap)
        positions = []
        for gy in range(0, MAP_SIZE, VIEWPORT):
            for gx in range(0, MAP_SIZE, VIEWPORT):
                positions.append((min(gx, MAP_SIZE - VIEWPORT), min(gy, MAP_SIZE - VIEWPORT)))

        for i, (qx, qy) in enumerate(positions[:queries_per_seed]):
            result = simulate_query(token, seed_id, qx, qy)
            if not result:
                continue

            # Parse viewport — try common keys
            grid = (result.get("grid") or result.get("viewport") or
                    result.get("terrain") or result.get("data") or result.get("cells"))

            if grid is None:
                print(f"  Q{i}: unknown keys: {list(result.keys())}")
                continue

            # Update terrain map
            for dy, row in enumerate(grid if isinstance(grid, list) else []):
                for dx, cell in enumerate(row if isinstance(row, list) else []):
                    mx, my = qx + dx, qy + dy
                    if 0 <= mx < MAP_SIZE and 0 <= my < MAP_SIZE:
                        observed[my][mx] = True
                        terrain_map[my][mx] = np.full(NUM_CLASSES, 0.01)
                        if isinstance(cell, (int, float)) and 0 <= int(cell) < NUM_CLASSES:
                            terrain_map[my][mx][int(cell)] = 0.95
                        elif isinstance(cell, dict):
                            # Maybe it's already a distribution
                            for k, v in cell.items():
                                try:
                                    idx = int(k)
                                    if 0 <= idx < NUM_CLASSES:
                                        terrain_map[my][mx][idx] = max(float(v), 0.01)
                                except (ValueError, TypeError):
                                    pass

            coverage = observed.sum() / (MAP_SIZE * MAP_SIZE) * 100
            print(f"  Q{i}: pos=({qx},{qy}) coverage={coverage:.1f}%")

        # Interpolate unobserved cells from nearest observed
        if observed.any():
            from scipy.ndimage import distance_transform_edt
            # Use distance transform for efficient nearest-neighbor
            dist, indices = distance_transform_edt(~observed, return_indices=True)
            for y in range(MAP_SIZE):
                for x in range(MAP_SIZE):
                    if not observed[y][x]:
                        ny, nx = indices[0][y][x], indices[1][y][x]
                        alpha = min(dist[y][x] / 15.0, 0.8)
                        uniform = np.full(NUM_CLASSES, 1.0 / NUM_CLASSES)
                        terrain_map[y][x] = (1 - alpha) * terrain_map[ny][nx] + alpha * uniform

        # Floor and normalize
        terrain_map = np.maximum(terrain_map, 0.01)
        terrain_map = terrain_map / terrain_map.sum(axis=2, keepdims=True)

        predictions[seed_id] = terrain_map.tolist()
        print(f"  Coverage: {observed.sum()}/{MAP_SIZE*MAP_SIZE} ({observed.mean()*100:.1f}%)")

    print(f"\nSubmitting for {len(predictions)} seeds...")
    result = api_call("POST", "/submit", token, predictions)
    print(f"Result: {json.dumps(result, indent=2)[:500] if result else 'None'}")


def simulate_query(token, seed_id, x, y):
    return api_call("POST", "/simulate", token, {"seed_id": seed_id, "x": x, "y": y})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--explore", action="store_true")
    args = parser.parse_args()

    token = get_access_token()
    print("Got access token")

    if args.baseline:
        submit_baseline(token)
    elif args.explore:
        explore_and_predict(token)
    else:
        print("Usage: --baseline or --explore")
