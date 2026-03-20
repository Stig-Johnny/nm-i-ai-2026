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

# Static terrains that never change — lock them in with high confidence
STATIC_TERRAIN = {10, 5}   # Ocean, Mountain
MOSTLY_STATIC = {4}        # Forest (can change but mostly stable)


CACHE_DIR = "/tmp/astar_cache"


def cache_path(round_id, seed_idx, kind="counts"):
    import pathlib
    pathlib.Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    return f"{CACHE_DIR}/round_{round_id}_seed_{seed_idx}_{kind}.json"


def save_counts(round_id, seed_idx, counts, observed):
    """Persist observation counts to disk so crashes don't lose query data."""
    path = cache_path(round_id, seed_idx)
    with open(path, "w") as f:
        json.dump({
            "counts": counts.tolist(),
            "observed": observed.tolist(),
        }, f)


def load_counts(round_id, seed_idx, H, W):
    """Load saved counts if they exist. Returns (counts, observed) or None."""
    path = cache_path(round_id, seed_idx)
    try:
        with open(path) as f:
            d = json.load(f)
        counts = np.array(d["counts"])
        observed = np.array(d["observed"], dtype=bool)
        if counts.shape == (H, W, NUM_CLASSES):
            total = int(counts.sum())
            print(f"  Loaded cached counts: {total} observations across {observed.sum()} cells")
            return counts, observed
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return None


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
    """Convert initial grid to probability priors using simulation mechanics.

    Key rules:
    - Ocean & Mountain: static (never change)
    - Settlements: can grow, become ports (if coastal), become ruins, change faction
    - Ruins: can be reclaimed by nearby settlements, overgrown by forest, fade to plains
    - Forest: mostly stable, but can be cleared for settlement expansion
    - Plains near settlements: likely to become settlements or forests
    - Adjacency matters: cells near settlements are more dynamic
    """
    H, W = len(grid), len(grid[0])
    priors = np.full((H, W, NUM_CLASSES), PROB_FLOOR)

    # First pass: find settlement and ocean positions for adjacency analysis
    settlement_positions = set()
    ocean_positions = set()
    for y in range(H):
        for x in range(W):
            if grid[y][x] in (1, 2):
                settlement_positions.add((y, x))
            if grid[y][x] == 10:
                ocean_positions.add((y, x))

    def near_settlement(y, x, radius=3):
        for sy, sx in settlement_positions:
            if abs(y - sy) + abs(x - sx) <= radius:
                return True
        return False

    def near_ocean(y, x):
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if (y + dy, x + dx) in ocean_positions:
                    return True
        return False

    # Precompute distance to nearest settlement for each cell
    dist_to_settlement = {}
    for y in range(H):
        for x in range(W):
            d = min((abs(y-sy)+abs(x-sx) for sy, sx in settlement_positions), default=99)
            dist_to_settlement[(y, x)] = d

    for y in range(H):
        for x in range(W):
            raw = grid[y][x]
            dist = dist_to_settlement[(y, x)]
            coastal = near_ocean(y, x)

            if raw == 10:  # Empty/Plains border — static (100% Empty class)
                priors[y][x][0] = 0.98
            elif raw == 5:  # Ruin — static (100% Ruin class=5)
                priors[y][x][5] = 0.98
            elif raw == 4:  # Ocean terrain — calibrated from R1-R6 ground truth (30 seeds)
                # [Empty, Forest, Settlement, Mountain, Ocean, Ruin]
                # Flat global: E=8.4% F=13.9% S=1.0% M=1.5% O=75.3%
                # Distance-based (only Settlement varies meaningfully):
                if dist <= 3:
                    # Adj settlement: S=4.2%, O=71.2%
                    priors[y][x] = [0.088, 0.143, 0.042, 0.015, 0.712, 0.000]
                elif dist <= 8:
                    # Mid: S=1.0%, O=78.7%
                    priors[y][x] = [0.076, 0.114, 0.010, 0.015, 0.787, 0.000]
                else:
                    # Far: S=0.9%, O=75.0% (empirical R1-R6 — NOT 92%+ as earlier versions assumed)
                    priors[y][x] = [0.085, 0.141, 0.009, 0.015, 0.750, 0.000]
            elif raw == 11:  # Fog of war — calibrated from R1-R6 ground truth (30 seeds)
                # [Empty, Forest, Settlement, Mountain, Ocean, Ruin]
                # Global: E=80.3% F=13.4% S=1.1% M=1.4% O=3.8%
                # Settlement IS present near settlements (3.0% dist<=5, 0.9% far)
                if dist <= 5:
                    # Near settlement: E=78.7% F=13.1% S=3.0% M=1.4% O=3.9%
                    priors[y][x] = [0.787, 0.131, 0.030, 0.014, 0.039, 0.000]
                else:
                    # Far from settlement: E=80.4% F=13.5% S=0.9% M=1.4% O=3.8%
                    priors[y][x] = [0.804, 0.135, 0.009, 0.014, 0.038, 0.000]
            elif raw == 1:  # Forest/transition terrain — calibrated from R1-R6 (30 seeds)
                # [Empty, Forest, Settlement, Mountain, Ocean, Ruin]
                # Global: E=45.4% F=30.5% S=0.4% M=2.7% O=21.1%
                # Distance to settlement: near=more Empty, far=more Forest
                if dist <= 5:
                    # Near: E=51.3% F=22.7% S=0.7% M=2.7% O=23.4%
                    priors[y][x] = [0.513, 0.227, 0.007, 0.027, 0.234, 0.000]
                else:
                    # Far: E=45.1% F=30.8% S=0.3% M=2.7% O=21.0%
                    priors[y][x] = [0.451, 0.308, 0.003, 0.027, 0.210, 0.000]
            elif raw == 2:  # Settlement/port terrain — calibrated from R1-R6 (n=53)
                # val=2 empirical: E=46.7% F=9.1% S=19.7% M=2.4% O=22.1%
                priors[y][x] = [0.467, 0.091, 0.197, 0.024, 0.221, 0.000]
            elif raw == 3:  # Unknown — conservative flat prior
                priors[y][x] = [0.25, 0.20, 0.10, 0.20, 0.20, 0.05]
            elif raw == 0:  # Empty
                priors[y][x][0] = 0.90
                priors[y][x][4] = 0.05
            else:
                priors[y][x][TERRAIN_TO_CLASS.get(raw, 0)] = 0.50

    # Normalize
    priors = np.maximum(priors, PROB_FLOOR)
    priors = priors / priors.sum(axis=2, keepdims=True)
    return priors


def observation_to_class(grid_value):
    return TERRAIN_TO_CLASS.get(grid_value, 0)


def is_static_raw(grid_value):
    """Return True if this terrain type never changes."""
    return grid_value in STATIC_TERRAIN


def cell_entropy(probs):
    """Shannon entropy of a probability vector (nats)."""
    p = np.clip(probs, 1e-9, 1.0)
    return -np.sum(p * np.log(p))


def coverage_grid_positions(H, W, step=15):
    """Tile H×W map with step×step viewports. Returns list of (vx, vy)."""
    positions = []
    for gy in range(0, H, step):
        for gx in range(0, W, step):
            positions.append((min(gx, W - step), min(gy, H - step)))
    # Deduplicate (can happen when map dims < step)
    return list(dict.fromkeys(positions))


def highest_entropy_viewport(pred, H, W, step=15):
    """Find the step×step viewport position with highest average cell entropy."""
    best_vx, best_vy, best_score = 0, 0, -1.0
    for vy in range(0, H - step + 1, 5):
        for vx in range(0, W - step + 1, 5):
            region = pred[vy:vy + step, vx:vx + step]
            # avg entropy per cell in this viewport
            score = np.mean([-np.sum(np.clip(region[y, x], 1e-9, 1) *
                                     np.log(np.clip(region[y, x], 1e-9, 1)))
                             for y in range(region.shape[0])
                             for x in range(region.shape[1])])
            if score > best_score:
                best_score, best_vx, best_vy = score, vx, vy
    return best_vx, best_vy


def apply_observation(counts, observed, grid_rows, vp, W, H, initial_grid=None):
    """Update counts + observed arrays from one viewport result."""
    for dy, row in enumerate(grid_rows):
        for dx, cell in enumerate(row):
            mx = vp["x"] + dx
            my = vp["y"] + dy
            if 0 <= mx < W and 0 <= my < H:
                observed[my][mx] = True
                cls = observation_to_class(cell)
                counts[my][mx][cls] += 1
                # Lock static terrain from the RAW cell value
                if is_static_raw(cell):
                    # Override: static cells get very high count in their correct class
                    counts[my][mx] = np.zeros(NUM_CLASSES)
                    counts[my][mx][cls] = 10  # equivalent to 10 observations → alpha ≈ 0.9


def blend_observation_prior(counts, pred, H, W, initial_raw_grid=None):
    """Update prediction tensor in-place by blending observation frequencies with prior."""
    for y in range(H):
        for x in range(W):
            total = counts[y][x].sum()
            if total <= 0:
                continue

            obs_dist = (counts[y][x] + PROB_FLOOR) / (total + PROB_FLOOR * NUM_CLASSES)

            # Higher alpha for more observations, scaled per terrain type
            raw_val = initial_raw_grid[y][x] if initial_raw_grid else -1
            if raw_val in STATIC_TERRAIN:
                # Static terrain — trust observation heavily
                alpha = 0.98
            elif raw_val in MOSTLY_STATIC:
                # Forest — fairly stable but can change
                alpha = min(total / 2.0, 0.85)
            else:
                # Dynamic cells — be more conservative; ground truth is stochastic
                # 1 obs → 0.60, 2 obs → 0.75, 3+ obs → 0.85
                alpha = min(0.40 + total * 0.15, 0.85)

            pred[y][x] = alpha * obs_dist + (1 - alpha) * pred[y][x]


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
    """Use queries to observe + build frequency-based predictions.

    Phase 1: Full coverage — tile the map once per seed (9 queries/seed × 5 = 45 total)
    Phase 2: Re-observe highest-entropy viewport per seed (1 query/seed × 5 = 5 total)

    Key improvements vs. v1:
    - Static cells (Ocean, Mountain) are locked in with high confidence (alpha=0.98)
    - Dynamic cells use alpha=0.60 for 1 obs, 0.75 for 2, 0.85 for 3+
    - Phase 2 re-queries the highest-entropy area for each seed
    - No more accidental overwrite with priors when queries exhausted
    """
    H, W = detail["map_height"], detail["map_width"]
    seeds = detail["seeds_count"]
    initial_states = detail.get("initial_states", [])

    budget = get_budget(s)
    queries_left = budget["queries_max"] - budget["queries_used"]
    print(f"Budget: {queries_left} queries remaining of {budget['queries_max']}")

    if queries_left == 0:
        # No new queries — but check if we have cached observations from a crashed run
        print("No queries left — checking for cached observation data...")
        recovered = False
        for seed_idx in range(seeds):
            cached = load_counts(round_id, seed_idx, H, W)
            if cached and cached[0].sum() > 0:
                counts, observed = cached
                initial_raw = initial_states[seed_idx]["grid"] if seed_idx < len(initial_states) else None
                if seed_idx < len(initial_states):
                    pred = initial_grid_to_priors(initial_states[seed_idx]["grid"])
                else:
                    pred = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES)
                blend_observation_prior(counts, pred, H, W, initial_raw)
                pred = np.maximum(pred, PROB_FLOOR)
                pred = pred / pred.sum(axis=2, keepdims=True)
                result = submit_prediction(s, round_id, seed_idx, pred.tolist())
                print(f"  Seed {seed_idx}: recovered {int(counts.sum())} observations → {result}")
                recovered = True
        if not recovered:
            print("  No cache found — priors already submitted, nothing to do.")
        return

    # Phase 1: full coverage positions (tiles 40×40 in 9 positions with 15×15 viewports)
    coverage_positions = coverage_grid_positions(H, W, step=15)
    # Allocate: keep at least 1 query/seed for phase 2, rest for phase 1
    phase1_per_seed = min(len(coverage_positions), (queries_left - seeds) // seeds)
    phase1_per_seed = max(1, phase1_per_seed)  # At least 1 phase-1 query per seed
    phase2_budget = max(0, queries_left - phase1_per_seed * seeds)
    print(f"Phase 1: {phase1_per_seed} queries/seed | Phase 2: {phase2_budget} remaining")

    all_preds = {}  # seed_idx → final prediction array

    # ── Phase 1: full coverage ──────────────────────────────────────────────
    for seed_idx in range(seeds):
        print(f"\n=== Seed {seed_idx} — Phase 1 ===")

        # Get initial raw grid for this seed (used for alpha selection)
        initial_raw = None
        if seed_idx < len(initial_states):
            initial_raw = initial_states[seed_idx]["grid"]

        # Load cached counts from previous run if available (crash recovery)
        cached = load_counts(round_id, seed_idx, H, W)
        if cached:
            counts, observed = cached
        else:
            counts = np.zeros((H, W, NUM_CLASSES))
            observed = np.zeros((H, W), dtype=bool)

        for qi, (vx, vy) in enumerate(coverage_positions[:phase1_per_seed]):
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
            apply_observation(counts, observed, grid, vp, W, H, initial_raw)
            # Save after every observation — crash-safe
            save_counts(round_id, seed_idx, counts, observed)

            coverage = observed.mean() * 100
            ql = result.get("queries_used", "?")
            print(f"  Q{qi}: ({vx},{vy}) coverage={coverage:.0f}% used={ql}/{result.get('queries_max','?')}")

        # Build prediction: prior → observation blend
        if seed_idx < len(initial_states):
            pred = initial_grid_to_priors(initial_states[seed_idx]["grid"])
        else:
            pred = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES)

        blend_observation_prior(counts, pred, H, W, initial_raw)

        # Spatial interpolation: propagate nearby observations to unobserved cells
        if observed.any() and not observed.all():
            try:
                from scipy.ndimage import distance_transform_edt
                dist, indices = distance_transform_edt(~observed, return_indices=True)
                for y in range(H):
                    for x in range(W):
                        if not observed[y][x]:
                            ny, nx = indices[0][y][x], indices[1][y][x]
                            # Further from nearest observation = rely more on prior
                            alpha = max(0.0, 1.0 - dist[y][x] / 8.0)
                            pred[y][x] = alpha * pred[ny][nx] + (1 - alpha) * pred[y][x]
            except ImportError:
                pass  # scipy not available — skip interpolation

        # Floor and normalize
        pred = np.maximum(pred, PROB_FLOOR)
        pred = pred / pred.sum(axis=2, keepdims=True)

        all_preds[seed_idx] = (pred, counts, observed)

        # Submit phase 1 prediction (will be improved in phase 2)
        result = submit_prediction(s, round_id, seed_idx, pred.tolist())
        obs_pct = observed.mean() * 100
        print(f"  Phase 1 submitted (coverage={obs_pct:.0f}%): {result}")

    # ── Phase 2: re-observe highest-entropy viewports ───────────────────────
    if phase2_budget > 0:
        print(f"\n=== Phase 2: {phase2_budget} refinement queries ===")

        # Assign phase 2 queries across seeds (1 per seed if budget allows)
        phase2_per_seed = min(1, phase2_budget // seeds)
        extra = phase2_budget - phase2_per_seed * seeds

        for seed_idx in range(seeds):
            n_queries = phase2_per_seed + (1 if seed_idx < extra else 0)
            if n_queries == 0:
                continue

            pred, counts, observed = all_preds[seed_idx]
            initial_raw = initial_states[seed_idx]["grid"] if seed_idx < len(initial_states) else None

            for q in range(n_queries):
                # Find viewport with highest average prediction entropy
                vx, vy = highest_entropy_viewport(pred, H, W, step=15)
                print(f"  Seed {seed_idx} Q{q}: re-observe ({vx},{vy}) — highest entropy viewport")

                try:
                    result = simulate(s, round_id, seed_idx, vx, vy)
                except Exception as e:
                    print(f"  Error: {e}")
                    break

                if "error" in result or "detail" in result:
                    print(f"  Result: {result}")
                    break

                grid = result.get("grid", [])
                vp = result.get("viewport", {"x": vx, "y": vy, "w": 15, "h": 15})
                apply_observation(counts, observed, grid, vp, W, H, initial_raw)
                save_counts(round_id, seed_idx, counts, observed)

                # Reblend with updated counts
                if seed_idx < len(initial_states):
                    pred = initial_grid_to_priors(initial_states[seed_idx]["grid"])
                else:
                    pred = np.full((H, W, NUM_CLASSES), 1.0 / NUM_CLASSES)

                blend_observation_prior(counts, pred, H, W, initial_raw)
                pred = np.maximum(pred, PROB_FLOOR)
                pred = pred / pred.sum(axis=2, keepdims=True)
                all_preds[seed_idx] = (pred, counts, observed)

            # Resubmit improved prediction
            final_pred = all_preds[seed_idx][0]
            result = submit_prediction(s, round_id, seed_idx, final_pred.tolist())
            print(f"  Seed {seed_idx} Phase 2 submitted: {result}")


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
        seen_rounds = set()
        while True:
            try:
                rounds = get_rounds(s)
            except Exception as e:
                print(f"Error fetching rounds: {e}")
                time.sleep(30)
                continue

            for r in rounds:
                if r.get("status") == "active" and r["id"] not in seen_rounds:
                    # With pure-prior strategy, we always submit (no query budget dependency).
                    # Queries may have been used by external processes — we still overwrite
                    # with our calibrated priors which are empirically better.
                    seen_rounds.add(r["id"])
                    print(f"\nRound {r['round_number']} is active!")

                    try:
                        detail = get_round_detail(s, r["id"])
                    except Exception as e:
                        print(f"Error fetching round detail: {e}")
                        continue

                    # STRATEGY (R8+): MC + Parameter Inference
                    # - 27 queries on seed 0 (3 full-map passes) → infer expansion/conflict params
                    # - Apply inferred params to adjust priors for ALL 5 seeds
                    # - 23 remaining queries for MC refinement on seeds 1-4
                    # Empirically: MC+inference beats pure priors by ~6+ pts per round
                    # Pure prior is fallback if MC solver fails
                    budget = get_budget(s)
                    queries_used = budget.get("queries_used", 0)
                    if queries_used < 5:  # Fresh round — use MC+inference
                        print("Running MC+inference solver (parameter estimation)...")
                        try:
                            from task3.solver_mc import solve_with_mc_inference
                            solve_with_mc_inference(s, r["id"], detail)
                        except Exception as e:
                            print(f"MC solver error: {e} — falling back to pure priors")
                            try:
                                solve_with_priors(s, r["id"], detail)
                            except Exception as e2:
                                print(f"solve_with_priors fallback error: {e2}")
                    else:
                        print(f"Round already has {queries_used} queries — submitting calibrated priors only...")
                        try:
                            solve_with_priors(s, r["id"], detail)
                        except Exception as e:
                            print(f"solve_with_priors error: {e}")

            time.sleep(30)
            print(".", end="", flush=True)
        return

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
        # Default: priors first, then explore
        print("Submitting informed priors...")
        solve_with_priors(s, round_id, detail)
        print("Exploring with queries...")
        solve_explore(s, round_id, detail)


if __name__ == "__main__":
    main()
