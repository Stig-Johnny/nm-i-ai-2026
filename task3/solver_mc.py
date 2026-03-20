"""
Astar Island solver — Monte Carlo sampling with shared-GT insight.

KEY INSIGHT: Hidden parameters are IDENTICAL for all 5 seeds in a round.
Therefore GT[y][x][k] is the SAME distribution for all seeds at the same cell.
Querying seed 0 and seed 1 at the same viewport are BOTH i.i.d. samples
from the same GT — so we accumulate counts across ALL seeds into one tensor
and submit the SAME prediction for all 5 seeds.

Strategy:
- 9 zero-overlap viewports tile the full 40×40 map
- Cycle 50 queries: pos 0 seed 0, pos 1 seed 1, ..., pos 8 seed 3, pos 0 seed 4, ...
- Accumulate: counts[y][x][k] += 1 for observed class k at cell (y,x)
- Prediction: P[y][x][k] = max(count_k / n_obs, 0.01), renormalized
- Zero-observation cells: fall back to calibrated priors
- Submit same tensor to all 5 seeds
- Intermediate submits every 10 queries to lock in improving predictions
"""

import numpy as np
import json
import time
import http.client
from task3.solution import initial_grid_to_priors, PROB_FLOOR, submit_prediction

# Zero-overlap tiling of 40×40 into 9 viewports
# cols: 0-14 (15w), 15-29 (15w), 30-39 (10w)
# rows: 0-14 (15h), 15-29 (15h), 30-39 (10h)
VIEWPORT_GRID = [
    (0, 0, 15, 15),   (15, 0, 15, 15),   (30, 0, 10, 15),
    (0, 15, 15, 15),  (15, 15, 15, 15),  (30, 15, 10, 15),
    (0, 30, 15, 10),  (15, 30, 15, 10),  (30, 30, 10, 10),
]
# Verified: covers all 1600 cells exactly once per pass


def simulate(token, round_id, seed_index, vx, vy, vw=15, vh=15):
    """One simulate query. Returns response dict."""
    conn = http.client.HTTPSConnection("api.ainm.no")
    body = json.dumps({
        "round_id": round_id, "seed_index": seed_index,
        "viewport_x": vx, "viewport_y": vy, "viewport_w": vw, "viewport_h": vh
    }).encode()
    conn.request("POST", "/astar-island/simulate", body=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    if resp.status == 429:
        print("  429 rate limit — sleeping 3s")
        time.sleep(3)
        return simulate(token, round_id, seed_index, vx, vy, vw, vh)
    return data


TERRAIN_TO_CLASS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 10: 0, 11: 0}


def mc_tensor_from_counts(counts, visits, prior):
    """
    Build prediction tensor from Monte Carlo accumulator.
    - Observed cells: empirical frequency, floored at PROB_FLOOR
    - Unobserved cells: fall back to calibrated prior
    """
    H, W, _ = counts.shape
    pred = prior.copy()
    for y in range(H):
        for x in range(W):
            n = visits[y][x]
            if n >= 1:
                mc_est = counts[y][x] / n
                # Confidence scales with number of samples
                # At n=5: alpha=0.5; n=10: alpha=0.85; n=15+: alpha=0.85 (cap)
                alpha = min(0.85, n / 10)
                pred[y][x] = alpha * mc_est + (1 - alpha) * prior[y][x]
    # Apply floor and renormalize
    pred = np.maximum(pred, PROB_FLOOR)
    pred = pred / pred.sum(axis=2, keepdims=True)
    return pred


def solve_with_mc(session, round_id, detail):
    """
    Main solver. Uses all 50 queries to build joint MC estimate.
    Submits same prediction tensor to all 5 seeds.
    """
    from shared.token import get_access_token
    token = get_access_token()

    W, H = detail['map_width'], detail['map_height']
    seeds = detail['seeds_count']

    print(f"MC solver: {W}×{H}, {seeds} seeds, 50 queries")
    print(f"Viewports: {len(VIEWPORT_GRID)}, queries/vp: {50/len(VIEWPORT_GRID):.1f}")

    # Build averaged prior across all seeds (similar initial configs, minor variation)
    initials = [detail['initial_states'][s]['grid'] for s in range(seeds)]
    # Use seed 0 prior as base (representative)
    base_prior = initial_grid_to_priors(initials[0])

    # Submit pure priors immediately as baseline (overwritten as MC accumulates)
    print("\nBaseline submission (pure priors)...")
    for s in range(seeds):
        seed_prior = initial_grid_to_priors(initials[s])
        r = submit_prediction(token, round_id, s, seed_prior)
        print(f"  Seed {s}: {r.get('status', r)}")
        time.sleep(0.55)

    # MC accumulator (shared across all seeds — GT is the same)
    counts = np.zeros((H, W, 6), dtype=np.float64)
    visits = np.zeros((H, W), dtype=np.float64)
    queries_used = 0
    last_submit_q = 0

    # Cache path — persist counts after every observation so we survive crashes
    import os
    cache_path = f"/tmp/astar_cache/{round_id}_mc.json"
    os.makedirs("/tmp/astar_cache", exist_ok=True)

    def save_cache():
        with open(cache_path, "w") as _cf:
            json.dump({"counts": counts.tolist(), "visits": visits.tolist(),
                       "queries_used": queries_used}, _cf)

    print(f"\nRunning 50 queries (cycling viewports × seeds)...")
    for q_idx in range(50):
        vp_idx = q_idx % len(VIEWPORT_GRID)
        seed_idx = (q_idx // len(VIEWPORT_GRID)) % seeds  # cycle seeds per pass
        vx, vy, vw, vh = VIEWPORT_GRID[vp_idx]

        obs = simulate(token, round_id, seed_idx, vx, vy, vw, vh)
        queries_used += 1

        if 'grid' in obs:
            grid = obs['grid']
            for dy, row in enumerate(grid):
                for dx, val in enumerate(row):
                    cy, cx = vy + dy, vx + dx
                    if 0 <= cy < H and 0 <= cx < W:
                        cls = TERRAIN_TO_CLASS.get(val, 0)
                        counts[cy][cx][cls] += 1
                        visits[cy][cx] += 1
        else:
            print(f"  q{q_idx}: unexpected response: {obs}")

        save_cache()  # persist after every observation
        time.sleep(0.22)  # ~4.5 req/sec

        # Resubmit every 10 queries (improve incrementally)
        if queries_used - last_submit_q >= 10:
            pred = mc_tensor_from_counts(counts, visits, base_prior)
            n_obs = (visits >= 1).sum()
            print(f"  q{queries_used}: {n_obs}/{W*H} cells observed, resubmitting all seeds...")
            for s in range(seeds):
                r = submit_prediction(token, round_id, s, pred)
                if r.get('status') != 'accepted':
                    print(f"    Seed {s}: {r}")
                time.sleep(0.55)
            last_submit_q = queries_used

    # Final submission
    pred = mc_tensor_from_counts(counts, visits, base_prior)
    n_obs = (visits >= 1).sum()
    n_gt5 = (visits >= 5).sum()
    print(f"\nFinal: {n_obs}/{W*H} cells observed, {n_gt5} with 5+ samples")
    print(f"Mean samples/cell: {visits.mean():.2f}, min: {visits.min():.0f}")

    print("Final submission...")
    for s in range(seeds):
        r = submit_prediction(token, round_id, s, pred)
        print(f"  Seed {s}: {r.get('status', r)}")
        time.sleep(0.55)

    print(f"\nDone. {queries_used}/50 queries used.")


# Keep old name as alias for solution.py poller compatibility
solve_with_mc_inference = solve_with_mc


if __name__ == "__main__":
    print("MC solver loaded. Call solve_with_mc(session, round_id, detail).")
