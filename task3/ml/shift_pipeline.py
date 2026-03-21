#!/usr/bin/env python3
"""
V2 Shift Pipeline: Skip ER estimation. Use default ER + full 50 MC queries for shift.
CV shows this scores 85+ consistently regardless of actual ER.
"""
import sys; sys.path.insert(0, '/tmp/astar_ml'); sys.path.insert(0, '/tmp')
import json, math, time, os, fcntl
import numpy as np
from collections import defaultdict
import urllib.request, urllib.error

exec(open("/tmp/astar_model_v1plus.py").read())
exec(open("/tmp/astar_auth.py").read())

LOG = "/tmp/astar_pipeline.log"
DEFAULT_ER = 0.20  # Average across all historical rounds

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

TOKEN = get_token()
if not TOKEN:
    log("FATAL: No token"); sys.exit(1)
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api_get(path):
    req = urllib.request.Request(f"https://api.ainm.no{path}", headers=HEADERS)
    try: return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e: return {"error": str(e)}

def api_post(path, data):
    req = urllib.request.Request(f"https://api.ainm.no{path}", data=json.dumps(data).encode(), headers=HEADERS, method="POST")
    try: return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e: return {"error": str(e)}

def submit_retry(round_id, seed_index, prediction, retries=5):
    for i in range(retries):
        r = api_post("/astar-island/submit", {"round_id": round_id, "seed_index": seed_index, "prediction": prediction})
        if r.get("status") == "accepted": return True
        time.sleep(2)
    return False

def find_frontier_viewports(grid, n=3):
    H, W = len(grid), len(grid[0])
    setts = [(y,x) for y in range(H) for x in range(W) if grid[y][x] in (1,2)]
    sc = [[0]*W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if grid[y][x] in (10,5): continue
            d = min(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else 99
            if 1 <= d <= 4: sc[y][x] = 4 - d + 1
    covered = [[False]*W for _ in range(H)]
    vps = []
    for _ in range(n):
        best_s, best_vp = -1, None
        for vy in range(0, H-14, 2):
            for vx in range(0, W-14, 2):
                s = sum(sc[vy+dy][vx+dx] for dy in range(15) for dx in range(15) if not covered[vy+dy][vx+dx])
                if s > best_s: best_s, best_vp = s, (vx, vy)
        if not best_vp or best_s == 0: break
        vx, vy = best_vp; vps.append((vx, vy))
        for dy in range(15):
            for dx in range(15): covered[vy+dy][vx+dx] = True
    return vps

def run():
    # Pipeline lock
    lock_file = open("/tmp/astar_pipeline.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid())); lock_file.flush()
    except BlockingIOError:
        log("Pipeline already running. Exiting."); return

    log("=== V2 Shift Pipeline (no ER estimation) ===")
    
    training, _ = load_training()
    log(f"Model: {len(training)} keys, default ER={DEFAULT_ER}")
    
    rounds = api_get("/astar-island/rounds")
    active = next((r for r in rounds if r["status"] == "active"), None)
    if not active: log("No active round!"); return
    
    rid = active["id"]; rnum = active["round_number"]
    log(f"Active: R{rnum}")
    
    budget = api_get("/astar-island/budget")
    used = budget.get("queries_used", 0)
    total = budget.get("queries_max", 50)
    remaining = total - used
    log(f"Budget: {used}/{total}")
    
    detail = api_get(f"/astar-island/rounds/{rid}")
    n_seeds = detail["seeds_count"]
    
    # Step 1: Base prediction with DEFAULT ER + immediate submit
    log(f"Step 1: Base predictions (default ER={DEFAULT_ER})...")
    seed_preds = {}
    for seed_idx in range(n_seeds):
        grid = detail["initial_states"][seed_idx]["grid"]
        pred = predict_full_map(training, grid, DEFAULT_ER)
        seed_preds[seed_idx] = np.array(pred)
        ok = submit_retry(rid, seed_idx, pred)
        n_s = sum(1 for row in grid for v in row if v == 1)
        log(f"  Seed {seed_idx} ({n_s} sett): {'OK' if ok else 'FAILED'}")
        time.sleep(0.3)
    
    # Step 2: ALL remaining queries for MC on frontiers
    budget2 = api_get("/astar-island/budget")
    remaining2 = budget2.get("queries_max", 50) - budget2.get("queries_used", 0)
    log(f"Step 2: MC shift with {remaining2} queries...")
    
    if remaining2 < 5:
        log("Not enough budget. Done."); return
    
    grid0 = detail["initial_states"][0]["grid"]
    setts0 = [(y,x) for y in range(40) for x in range(40) if grid0[y][x] in (1,2)]
    viewports = find_frontier_viewports(grid0, n=3)
    log(f"  Viewports: {viewports}")
    
    mc_obs = {}  # (y,x) → list of class observations
    
    for q in range(remaining2):
        vx, vy = viewports[q % len(viewports)]
        for attempt in range(3):
            r = api_post("/astar-island/simulate", {
                "round_id": rid, "seed_index": q % n_seeds,
                "viewport_x": vx, "viewport_y": vy, "viewport_w": 15, "viewport_h": 15
            })
            if "grid" in r: break
            time.sleep(1)
        
        if "grid" not in r:
            log(f"  MC {q+1} failed: {r}"); continue
        
        sim_grid = r["grid"]
        class_map = {10:0, 11:0, 0:0, 1:1, 2:2, 3:3, 4:4, 5:5}
        for dy in range(len(sim_grid)):
            for dx in range(len(sim_grid[0])):
                y, x = vy+dy, vx+dx
                if y>=40 or x>=40: continue
                ci = class_map.get(sim_grid[dy][dx], 0)
                if (y,x) not in mc_obs: mc_obs[(y,x)] = []
                mc_obs[(y,x)].append(ci)
        
        # Resubmit with shift every 15 queries
        if (q+1) % 15 == 0 or q == remaining2-1:
            log(f"  MC {q+1}/{remaining2}, applying shift...")
            
            # Compute observed distributions
            observed = {}
            for (y,x), obs_list in mc_obs.items():
                n = len(obs_list)
                if n >= 5:
                    dist = np.zeros(6)
                    for ci in obs_list: dist[ci] += 1
                    observed[(y,x)] = dist / n
            
            log(f"    {len(observed)} cells with 5+ observations")
            
            for seed_idx in range(n_seeds):
                grid = detail["initial_states"][seed_idx]["grid"]
                setts = [(y,x) for y in range(40) for x in range(40) if grid[y][x] in (1,2)]
                base = seed_preds[seed_idx]
                
                # Compute shifts by (terrain_type, distance_bucket)
                shifts = defaultdict(lambda: np.zeros(6))
                counts = defaultdict(int)
                for (y,x), obs_dist in observed.items():
                    if grid[y][x] in (10,5): continue
                    val = grid[y][x]
                    d = min(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else 99
                    key = (val, min(d, 5))
                    shifts[key] += obs_dist - base[y][x]
                    counts[key] += 1
                for key in shifts:
                    if counts[key] > 0: shifts[key] /= counts[key]
                
                # Apply shift alpha=0.8
                shifted = base.copy()
                for y in range(40):
                    for x in range(40):
                        val = grid[y][x]
                        if val in (10,5): continue
                        d = min(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else 99
                        key = (val, min(d, 5))
                        if key in shifts:
                            shifted[y][x] = base[y][x] + 0.9 * shifts[key]
                            shifted[y][x] = np.maximum(shifted[y][x], 0.01)
                            shifted[y][x] /= shifted[y][x].sum()
                
                submit_retry(rid, seed_idx, shifted.tolist())
            log(f"    All {n_seeds} seeds resubmitted with shift")
        time.sleep(0.25)
    
    # Save predictions
    os.makedirs("/tmp/astar_predictions", exist_ok=True)
    for seed_idx in range(n_seeds):
        with open(f"/tmp/astar_predictions/r{rnum}_seed{seed_idx}.json", "w") as f:
            json.dump(seed_preds[seed_idx].tolist(), f, separators=(',',':'))
    
    log("=== Pipeline complete ===")

if __name__ == "__main__":
    run()
