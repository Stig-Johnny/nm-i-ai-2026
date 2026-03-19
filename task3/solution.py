"""
Task 3 — Astar Island: Norse World Prediction
==============================================
Observe a 40x40 Norse world through a 15x15 viewport.
50 queries across 5 seeds. Predict H×W×6 terrain probability tensor per seed.

Terrain classes for prediction:
  0: Empty (Ocean=10, Plains=11, Empty=0)
  1: Settlement
  2: Port
  3: Ruin
  4: Forest
  5: Mountain

Run:
    python task3/solution.py --baseline     # Uniform 1/6 for all cells
    python task3/solution.py --explore      # Observe + predict
    python task3/solution.py --poll         # Poll until round is active, then explore
"""

import json
import sys
import time
import numpy as np
import requests

sys.path.insert(0, ".")
from shared.token import get_access_token

BASE = "https://api.ainm.no"
NUM_CLASSES = 6
PROB_FLOOR = 0.01

# Map raw grid values to prediction class indices
TERRAIN_TO_CLASS = {
    0: 0,   # Empty → Empty
    10: 0,  # Ocean → Empty
    11: 0,  # Plains → Empty
    1: 1,   # Settlement
    2: 2,   # Port
    3: 3,   # Ruin
    4: 4,   # Forest
    5: 5,   # Mountain
}


def make_session(token):
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    return s


def get_rounds(s):
    return s.get(f"{BASE}/astar-island/rounds").json()


def get_round_detail(s, round_id):
    return s.get(f"{BASE}/astar-island/rounds/{round_id}").json()


def get_budget(s):
    return s.get(f"{BASE}/astar-island/budget").json()


def simulate(s, round_id, seed_index, vx, vy, vw=15, vh=15):
    return s.post(f"{BASE}/astar-island/simulate", json={
        "round_id": round_id, "seed_index": seed_index,
        "viewport_x": vx, "viewport_y": vy, "viewport_w": vw, "viewport_h": vh
    }).json()


def submit_prediction(s, round_id, seed_index, prediction):
    return s.post(f"{BASE}/astar-island/submit", json={
        "round_id": round_id, "seed_index": seed_index,
        "prediction": prediction
    }).json()


def initial_grid_to_priors(grid):
    """Convert initial grid to probability priors. Static terrain gets high confidence."""
    H, W = len(grid), len(grid[0])
    priors = np.full((H, W, NUM_CLASSES), PROB_FLOOR)

    for y in range(H):
        for x in range(W):
            raw = grid[y][x]
            cls = TERRAIN_TO_CLASS.get(raw, 0)

            if raw == 10:  # Ocean — stays ocean
                priors[y][x][0] = 0.98
            elif raw == 5:  # Mountain — stays mountain
                priors[y][x][5] = 0.95
            elif raw == 4:  # Forest — mostly stays, can become settlement/ruin
                priors[y][x][4] = 0.70
                priors[y][x][0] = 0.10
                priors[y][x][1] = 0.05
                priors[y][x][3] = 0.05
            elif raw == 11:  # Plains — can become anything
                priors[y][x][0] = 0.40
                priors[y][x][1] = 0.15
                priors[y][x][4] = 0.20
                priors[y][x][3] = 0.05
            elif raw == 1:  # Settlement — can grow, die, become ruin/port
                priors[y][x][1] = 0.40
                priors[y][x][2] = 0.10
                priors[y][x][3] = 0.20
                priors[y][x][0] = 0.10
            elif raw == 2:  # Port — somewhat stable
                priors[y][x][2] = 0.45
                priors[y][x][1] = 0.15
                priors[y][x][3] = 0.15
            elif raw == 0:  # Empty
                priors[y][x][0] = 0.70
                priors[y][x][4] = 0.10
            else:
                priors[y][x][cls] = 0.50

    # Normalize
    priors = np.maximum(priors, PROB_FLOOR)
    priors = priors / priors.sum(axis=2, keepdims=True)
    return priors


def observation_to_class(grid_value):
    return TERRAIN_TO_CLASS.get(grid_value, 0)


def solve_baseline(s, round_id, detail):
    """Submit uniform 1/6 for all seeds."""
    H, W = detail["map_height"], detail["map_width"]
    seeds = detail["seeds_count"]
    uniform = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES).tolist()

    for i in range(seeds):
        result = submit_prediction(s, round_id, i, uniform)
        print(f"  Seed {i}: {result}")


def solve_with_priors(s, round_id, detail):
    """Use initial grid to build informed priors, submit without querying."""
    H, W = detail["map_height"], detail["map_width"]
    seeds = detail["seeds_count"]
    initial_states = detail.get("initial_states", [])

    for i in range(seeds):
        if i < len(initial_states):
            grid = initial_states[i]["grid"]
            pred = initial_grid_to_priors(grid)
        else:
            pred = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES)

        # Floor and normalize
        pred = np.maximum(pred, PROB_FLOOR)
        pred = pred / pred.sum(axis=2, keepdims=True)

        result = submit_prediction(s, round_id, i, pred.tolist())
        print(f"  Seed {i}: {result}")


def solve_explore(s, round_id, detail):
    """Use queries to observe + initial grid priors."""
    H, W = detail["map_height"], detail["map_width"]
    seeds = detail["seeds_count"]
    initial_states = detail.get("initial_states", [])

    budget = get_budget(s)
    queries_left = budget["queries_max"] - budget["queries_used"]
    queries_per_seed = queries_left // seeds
    print(f"Budget: {queries_left} queries, {queries_per_seed} per seed")

    # Coverage positions for 40x40 with 15x15 viewport
    positions = []
    for gy in range(0, H, 15):
        for gx in range(0, W, 15):
            positions.append((min(gx, W - 15), min(gy, H - 15)))

    for seed_idx in range(seeds):
        print(f"\n=== Seed {seed_idx} ===")

        # Start with initial grid priors
        if seed_idx < len(initial_states):
            pred = initial_grid_to_priors(initial_states[seed_idx]["grid"])
        else:
            pred = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES)

        observed = np.zeros((H, W), dtype=bool)

        # Query the simulator
        for qi, (vx, vy) in enumerate(positions[:queries_per_seed]):
            try:
                result = simulate(s, round_id, seed_idx, vx, vy)
            except Exception as e:
                print(f"  Q{qi} error: {e}")
                break

            if "error" in result or "detail" in result:
                print(f"  Q{qi}: {result}")
                break

            grid = result.get("grid", [])
            vp = result.get("viewport", {"x": vx, "y": vy, "w": 15, "h": 15})

            for dy, row in enumerate(grid):
                for dx, cell in enumerate(row):
                    mx = vp["x"] + dx
                    my = vp["y"] + dy
                    if 0 <= mx < W and 0 <= my < H:
                        observed[my][mx] = True
                        cls = observation_to_class(cell)
                        # High confidence on observed cell
                        pred[my][mx] = np.full(NUM_CLASSES, PROB_FLOOR)
                        pred[my][mx][cls] = 0.90

            coverage = observed.mean() * 100
            ql = result.get("queries_used", "?")
            print(f"  Q{qi}: ({vx},{vy}) coverage={coverage:.0f}% used={ql}/{result.get('queries_max','?')}")

        # For unobserved cells, blend initial priors with nearest observed
        if observed.any():
            from scipy.ndimage import distance_transform_edt
            dist, indices = distance_transform_edt(~observed, return_indices=True)
            for y in range(H):
                for x in range(W):
                    if not observed[y][x]:
                        ny, nx = indices[0][y][x], indices[1][y][x]
                        alpha = min(dist[y][x] / 10.0, 0.7)
                        pred[y][x] = (1 - alpha) * pred[ny][nx] + alpha * pred[y][x]

        # Floor and normalize
        pred = np.maximum(pred, PROB_FLOOR)
        pred = pred / pred.sum(axis=2, keepdims=True)

        result = submit_prediction(s, round_id, seed_idx, pred.tolist())
        obs_pct = observed.mean() * 100
        print(f"  Submitted (coverage={obs_pct:.0f}%): {result}")


def find_active_round(s):
    rounds = get_rounds(s)
    for r in rounds:
        if r.get("status") == "active":
            return r
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--priors", action="store_true", help="Submit using initial grid priors only (no queries)")
    parser.add_argument("--explore", action="store_true")
    parser.add_argument("--poll", action="store_true", help="Poll until round active, then explore")
    args = parser.parse_args()

    token = get_access_token()
    s = make_session(token)
    print("Authenticated")

    if args.poll:
        print("Polling for active round...")
        while True:
            r = find_active_round(s)
            if r:
                print(f"Round {r['round_number']} is active!")
                detail = get_round_detail(s, r["id"])
                solve_explore(s, r["id"], detail)
                return
            time.sleep(30)
            print(".", end="", flush=True)

    active = find_active_round(s)
    if not active:
        print("No active round. Use --poll to wait.")
        rounds = get_rounds(s)
        print(f"Rounds: {json.dumps(rounds)[:300]}")
        return

    round_id = active["id"]
    detail = get_round_detail(s, round_id)
    print(f"Round {active['round_number']}: {detail['map_width']}x{detail['map_height']}, {detail['seeds_count']} seeds")

    if args.baseline:
        solve_baseline(s, round_id, detail)
    elif args.priors:
        solve_with_priors(s, round_id, detail)
    elif args.explore:
        solve_explore(s, round_id, detail)
    else:
        # Default: priors first (free), then explore if budget available
        print("Submitting priors-based prediction...")
        solve_with_priors(s, round_id, detail)
        budget = get_budget(s)
        if budget.get("queries_used", 0) < budget.get("queries_max", 50):
            print("\nNow exploring with remaining budget...")
            solve_explore(s, round_id, detail)


if __name__ == "__main__":
    main()
