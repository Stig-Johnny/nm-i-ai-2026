"""
Monte Carlo + Parameter Inference solver for Astar Island.

Strategy:
1. Query 9 systematic viewports (full map coverage) on seed 0 × 3 reps = 27 queries
2. From observations: count terrain transitions (Plains→Settlement, Forest→Settlement)
   to infer expansion rate; count ruins to infer conflict rate; observe settlement stats
3. Adjust priors for ALL 5 seeds based on inferred parameters
4. Use remaining 23 queries for MC refinement on high-entropy cells across seeds 1-4

Hidden params we can infer from observations:
- expansion_rate: fraction of initial Plains/Forest near settlements that became Settlement
- conflict_rate: fraction of initial settlements that are ruins
- food_multiplier: avg food level of alive settlements (predicts stability)
"""

import numpy as np
import json
import time
import http.client
from task3.solution import initial_grid_to_priors, PROB_FLOOR

VIEWPORT_GRID = [
    # Zero-overlap tiling of 40×40 map into 9 viewports (3 cols × 3 rows)
    # Cols: 0-14 (15w), 15-29 (15w), 30-39 (10w)
    # Rows: 0-14 (15h), 15-29 (15h), 30-39 (10h)
    # Each cell covered exactly once per pass. 50 queries = 5 full passes + 5 extra.
    # Avg = 5.55 samples/cell vs old tiling's mean 5.55 but variance was higher.
    (0, 0, 15, 15),
    (15, 0, 15, 15),
    (30, 0, 10, 15),
    (0, 15, 15, 15),
    (15, 15, 15, 15),
    (30, 15, 10, 15),
    (0, 30, 15, 10),
    (15, 30, 15, 10),
    (30, 30, 10, 10),
]


def simulate(token, round_id, seed_index, vx, vy, vw=15, vh=15):
    """One simulate query."""
    conn = http.client.HTTPSConnection("api.ainm.no")
    body = json.dumps({
        "round_id": round_id, "seed_index": seed_index,
        "viewport_x": vx, "viewport_y": vy, "viewport_w": vw, "viewport_h": vh
    }).encode()
    conn.request("POST", "/astar-island/simulate", body=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    r = conn.getresponse()
    data = json.loads(r.read())
    if r.status == 429:
        print("  Rate limited — sleeping 2s")
        time.sleep(2)
        return simulate(token, round_id, seed_index, vx, vy, vw, vh)
    return data


def infer_expansion_rate(observations, initial_grids, W, H):
    """
    Estimate expansion_rate from observed terrain transitions.
    
    expansion_rate = fraction of initial-Plains cells near settlements that transitioned to Settlement/Port
    Baseline empirical: ~13.5% (from R1-R6 avg).
    Round multiplier = observed_rate / baseline_rate.
    """
    BASELINE_EXPANSION = 0.135
    
    n_plains_near = 0
    n_became_settlement = 0
    
    for obs, initial in zip(observations, initial_grids):
        grid = obs['grid']
        vp = obs.get('viewport', {})
        vx, vy = vp.get('x', 0), vp.get('y', 0)
        
        # Find settlement positions in initial grid
        settlement_cells = set()
        for y in range(H):
            for x in range(W):
                if initial[y][x] in (1, 2):  # Settlement or Port
                    settlement_cells.add((y, x))
        
        # For each cell in viewport: if initial=Plains (11) near settlement
        for dy, row in enumerate(grid):
            for dx, val in enumerate(row):
                y, x = vy + dy, vx + dx
                if 0 <= y < H and 0 <= x < W:
                    if initial[y][x] == 11:  # was Plains
                        min_d = min((abs(y-sy)+abs(x-sx) for sy, sx in settlement_cells), default=99)
                        if min_d <= 5:
                            n_plains_near += 1
                            if val in (1, 2):  # became Settlement or Port
                                n_became_settlement += 1
    
    if n_plains_near < 10:
        return 1.0  # not enough data — use baseline
    
    observed_rate = n_became_settlement / n_plains_near
    # Smooth toward baseline with prior weight of 50 observations
    prior_weight = 50
    smoothed_rate = (n_became_settlement + BASELINE_EXPANSION * prior_weight) / (n_plains_near + prior_weight)
    multiplier = smoothed_rate / BASELINE_EXPANSION
    print(f"  Expansion: {n_became_settlement}/{n_plains_near} = {observed_rate:.3f} (baseline {BASELINE_EXPANSION:.3f}) → mult={multiplier:.2f}")
    return multiplier


def infer_conflict_rate(observations, initial_grids, W, H):
    """
    Estimate conflict_rate from fraction of initial settlements that became ruins.
    Baseline: ~2.7% of settlement cells become ruins (from R1-R6).
    """
    BASELINE_RUIN = 0.027
    
    n_settlements_obs = 0
    n_became_ruin = 0
    
    for obs, initial in zip(observations, initial_grids):
        grid = obs['grid']
        vp = obs.get('viewport', {})
        vx, vy = vp.get('x', 0), vp.get('y', 0)
        
        for dy, row in enumerate(grid):
            for dx, val in enumerate(row):
                y, x = vy + dy, vx + dx
                if 0 <= y < H and 0 <= x < W:
                    if initial[y][x] in (1, 2):
                        n_settlements_obs += 1
                        if val == 3:  # Ruin
                            n_became_ruin += 1
    
    if n_settlements_obs < 5:
        return 1.0
    
    observed_rate = n_became_ruin / n_settlements_obs
    prior_weight = 20
    smoothed_rate = (n_became_ruin + BASELINE_RUIN * prior_weight) / (n_settlements_obs + prior_weight)
    multiplier = smoothed_rate / BASELINE_RUIN
    print(f"  Conflict: {n_became_ruin}/{n_settlements_obs} = {observed_rate:.3f} (baseline {BASELINE_RUIN:.3f}) → mult={multiplier:.2f}")
    return multiplier


def adjust_priors_for_params(prior, initial_grid, W, H, expansion_mult, conflict_mult):
    """
    Adjust prediction tensor based on inferred round parameters.
    
    expansion_mult > 1: Plains/Forest near settlements → more Settlement
    conflict_mult > 1: Settlement cells → more Ruin
    """
    SETTLEMENT_VALS = {1, 2}
    settlement_cells = [(y, x) for y in range(H) for x in range(W)
                       if initial_grid[y][x] in SETTLEMENT_VALS]
    
    for y in range(H):
        for x in range(W):
            raw = initial_grid[y][x]
            if len(settlement_cells) > 0:
                dist = min(abs(y-sy)+abs(x-sx) for sy,sx in settlement_cells)
            else:
                dist = 99
            
            if raw == 11:  # Plains — affected by expansion
                # Class 1 = Settlement, Class 0 = Empty, Class 4 = Forest
                base_settlement = prior[y][x][1]
                if expansion_mult > 1 and dist <= 8:
                    # Boost Settlement probability
                    boost = base_settlement * (expansion_mult - 1) * max(0, (8 - dist) / 8)
                    boost = min(boost, 0.20)  # cap at 20% additional
                    prior[y][x][1] += boost
                    prior[y][x][0] -= boost * 0.7
                    prior[y][x][4] -= boost * 0.3
                elif expansion_mult < 1 and dist <= 8:
                    # Reduce Settlement probability
                    reduce = base_settlement * (1 - expansion_mult) * max(0, (8 - dist) / 8)
                    reduce = min(reduce, base_settlement * 0.5)
                    prior[y][x][1] -= reduce
                    prior[y][x][0] += reduce
            
            elif raw in (1, 2):  # Settlement/Port — affected by conflict
                base_ruin = prior[y][x][3]
                if conflict_mult > 1:
                    boost = base_ruin * (conflict_mult - 1)
                    boost = min(boost, 0.15)
                    prior[y][x][3] += boost
                    prior[y][x][1] -= boost * 0.5
                    prior[y][x][0] -= boost * 0.5
                elif conflict_mult < 1:
                    reduce = base_ruin * (1 - conflict_mult)
                    prior[y][x][3] -= reduce
                    prior[y][x][1] += reduce * 0.5
                    prior[y][x][0] += reduce * 0.5
    
    # Re-normalize and apply floor
    prior = np.maximum(prior, PROB_FLOOR)
    prior = prior / prior.sum(axis=2, keepdims=True)
    return prior


def build_mc_accumulator(W, H):
    """Create empty MC accumulator."""
    return {
        'counts': np.zeros((H, W, 6)),
        'visits': np.zeros((H, W)),
    }


TERRAIN_TO_CLASS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 10: 0, 11: 0}


def update_mc(mc, obs, W, H):
    """Add one observation to MC accumulator."""
    grid = obs['grid']
    vp = obs.get('viewport', {})
    vx, vy = vp.get('x', 0), vp.get('y', 0)
    for dy, row in enumerate(grid):
        for dx, val in enumerate(row):
            y, x = vy + dy, vx + dx
            if 0 <= y < H and 0 <= x < W:
                cls = TERRAIN_TO_CLASS.get(val, 0)
                mc['counts'][y][x][cls] += 1
                mc['visits'][y][x] += 1


def blend_mc_with_prior(mc, prior, min_samples=3, max_alpha=0.85):
    """Blend MC estimates with prior based on confidence."""
    pred = prior.copy()
    H, W = mc['visits'].shape
    for y in range(H):
        for x in range(W):
            n = mc['visits'][y][x]
            if n >= min_samples:
                mc_est = mc['counts'][y][x] / n
                alpha = min(max_alpha, n / 15)  # full confidence at 15+ samples
                pred[y][x] = alpha * mc_est + (1 - alpha) * prior[y][x]
    pred = np.maximum(pred, PROB_FLOOR)
    pred = pred / pred.sum(axis=2, keepdims=True)
    return pred


def solve_with_mc_inference(session, round_id, detail):
    """
    Full solver: all 50 queries on seed 0 for best MC estimate,
    then apply inferred parameters to all 5 seeds.

    Strategy (revised based on analysis):
    - 50 queries × 9 zero-overlap viewports = 5.5 full-map passes on seed 0
    - Each cell gets ~5-6 Monte Carlo samples → reliable empirical frequency estimate
    - Infer expansion_rate + conflict_rate from observed transitions
    - Apply parameter adjustments to seeds 1-4 (shared hidden params)
    - Submit parameter-adjusted priors for seeds 1-4 + MC blend for seed 0

    Expected score: ~64 (vs ~58 pure prior, +6 pts per round)
    Theoretical ceiling with 50 samples/cell: ~87
    """
    from shared.token import get_access_token
    from task3.solution import submit_prediction

    token = get_access_token()
    W, H = detail['map_width'], detail['map_height']
    seeds = detail['seeds_count']

    print(f"MC+Inference solver: {W}×{H}, {seeds} seeds, 50 queries all on seed 0")

    # Build initial priors for all seeds
    initials = [detail['initial_states'][s]['grid'] for s in range(seeds)]
    priors = [initial_grid_to_priors(initials[s]) for s in range(seeds)]

    # Submit pure priors immediately as fallback (resubmit later with MC)
    print("\nSubmitting pure priors as initial fallback...")
    for s in range(seeds):
        result = submit_prediction(token, round_id, s, priors[s].copy())
        print(f"  Seed {s}: {result.get('status', result)}")
        time.sleep(0.6)

    # Run all 50 queries on seed 0 (5+ full map passes)
    print(f"\nRunning 50 queries on seed 0 ({len(VIEWPORT_GRID)} viewports, 5-6 reps)...")
    obs_seed0 = []
    mc_seed0 = build_mc_accumulator(W, H)
    queries_used = 0

    for q_idx in range(50):
        vp_idx = q_idx % len(VIEWPORT_GRID)
        vx, vy, vw, vh = VIEWPORT_GRID[vp_idx]
        obs = simulate(token, round_id, 0, vx, vy, vw, vh)
        queries_used += 1
        if 'grid' in obs:
            obs['viewport'] = obs.get('viewport', {'x': vx, 'y': vy, 'w': vw, 'h': vh})
            obs_seed0.append(obs)
            update_mc(mc_seed0, obs, W, H)
        else:
            print(f"  q{q_idx}: {obs}")
        time.sleep(0.22)  # ~4.5 req/sec (limit is 5/sec)

        # Resubmit seed 0 after each full pass (every 9 queries)
        if queries_used % 9 == 0 and queries_used >= 9:
            mc_est = blend_mc_with_prior(mc_seed0, priors[0])
            submit_prediction(token, round_id, 0, mc_est)
            print(f"  q{queries_used}: resubmitted seed 0 ({queries_used//9} passes done)")
            time.sleep(0.6)

    print(f"\n50 queries complete. Inferring hidden parameters...")

    # Infer round parameters from seed 0 observations
    expansion_mult = infer_expansion_rate(obs_seed0, [initials[0]] * len(obs_seed0), W, H)
    conflict_mult = infer_conflict_rate(obs_seed0, [initials[0]] * len(obs_seed0), W, H)
    print(f"  expansion_mult={expansion_mult:.2f}  conflict_mult={conflict_mult:.2f}")

    # Final seed 0 prediction: MC blend
    mc_visits_min = mc_seed0['visits'].min()
    mc_visits_mean = mc_seed0['visits'].mean()
    print(f"  Seed 0 MC coverage: min={mc_visits_min:.0f} mean={mc_visits_mean:.1f} samples/cell")
    final_pred_0 = blend_mc_with_prior(mc_seed0, priors[0], min_samples=3, max_alpha=0.85)
    result0 = submit_prediction(token, round_id, 0, final_pred_0)
    print(f"  Seed 0 final: {result0.get('status', result0)}")
    time.sleep(0.6)

    # Seeds 1-4: parameter-adjusted priors (no observations, but shared hidden params)
    print(f"\nApplying parameter adjustments to seeds 1-{seeds-1}...")
    for s in range(1, seeds):
        adj = adjust_priors_for_params(
            priors[s].copy(), initials[s], W, H, expansion_mult, conflict_mult
        )
        result = submit_prediction(token, round_id, s, adj)
        print(f"  Seed {s}: {result.get('status', result)}")
        time.sleep(0.6)

    print(f"\nDone. Queries: {queries_used}/50")


if __name__ == "__main__":
    print("MC+Inference solver loaded. Import and call solve_with_mc_inference().")
