#!/usr/bin/env python3
"""
Simple pipeline. Matches R8 (81.3) and R10 (81.5) approach exactly.
1. Estimate ER from 10 queries
2. V1+ lookup prediction per-seed
3. Submit. Done. No shift, no MC, no fancy stuff.
"""
import sys; sys.path.insert(0, '/tmp')
import json, math, time, os, fcntl
import urllib.request, urllib.error

exec(open("/tmp/astar_model_v1plus.py").read())
exec(open("/tmp/astar_auth.py").read())

LOG = "/tmp/astar_pipeline.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

TOKEN = get_token()
if not TOKEN: log("NO TOKEN"); sys.exit(1)
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api_get(path):
    req = urllib.request.Request(f"https://api.ainm.no{path}", headers=HEADERS)
    try: return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e: return {"error": str(e)}

def api_post(path, data):
    req = urllib.request.Request(f"https://api.ainm.no{path}", data=json.dumps(data).encode(), headers=HEADERS, method="POST")
    try: return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e: return {"error": str(e)}

def run():
    lock_file = open("/tmp/astar_pipeline.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid())); lock_file.flush()
    except BlockingIOError:
        log("Pipeline locked. Exiting."); return

    log("=== Simple Pipeline (R8/R10 approach) ===")
    
    training, _ = load_training()
    log(f"Model: {len(training)} keys")
    
    rounds = api_get("/astar-island/rounds")
    active = next((r for r in rounds if r["status"] == "active"), None)
    if not active: log("No active round"); return
    
    rid = active["id"]; rnum = active["round_number"]
    log(f"Active: R{rnum}")
    
    detail = api_get(f"/astar-island/rounds/{rid}")
    n_seeds = detail["seeds_count"]
    grid0 = detail["initial_states"][0]["grid"]
    setts = [(y,x) for y in range(40) for x in range(40) if grid0[y][x] == 1]
    log(f"Map: {len(setts)} settlements")
    
    budget = api_get("/astar-island/budget")
    used = budget.get("queries_used", 0)
    log(f"Budget: {used}/50")

    # Step 0: Safety submit with average ER (in case internet drops during ER estimation)
    log("Step 0: Safety submit (ER=0.20)...")
    for seed_idx in range(n_seeds):
        grid = detail["initial_states"][seed_idx]["grid"]
        pred = predict_full_map(training, grid, 0.20)
        api_post("/astar-island/submit", {"round_id": rid, "seed_index": seed_idx, "prediction": pred})
    log("  Safety predictions submitted")

    # Step 1: Estimate ER from 10 queries (same as R8/R10)
    remaining = 50 - used
    n_er = min(10, remaining)
    log(f"Step 1: ER estimation ({n_er} queries)...")
    
    observations = []
    for q in range(n_er):
        sy, sx = setts[q % len(setts)]
        vx = max(0, min(sx-7, 25)); vy = max(0, min(sy-7, 25))
        for attempt in range(3):
            r = api_post("/astar-island/simulate", {
                "round_id": rid, "seed_index": q % n_seeds,
                "viewport_x": vx, "viewport_y": vy, "viewport_w": 15, "viewport_h": 15
            })
            if "grid" in r: break
            time.sleep(1)
        if "grid" not in r: continue
        
        log(f"  Query {q+1}/{n_er}: budget {r.get('queries_used','?')}/50")
        sim_grid = r["grid"]
        for dy in range(len(sim_grid)):
            for dx in range(len(sim_grid[0])):
                y, x = vy+dy, vx+dx
                if y>=40 or x>=40: continue
                if grid0[y][x] in (4, 11, 0):
                    d = min(abs(y-s[0])+abs(x-s[1]) for s in setts)
                    if d <= 3:
                        observations.append(1 if sim_grid[dy][dx] in (1,2) else 0)
        time.sleep(0.25)
    
    er = sum(observations)/len(observations) if observations else 0.15
    log(f"  ER={er:.4f} from {len(observations)} obs")
    
    # Step 2: Per-seed V1+ prediction + submit with retry
    log(f"Step 2: Per-seed predictions (ER={er:.4f})...")
    for seed_idx in range(n_seeds):
        grid = detail["initial_states"][seed_idx]["grid"]
        pred = predict_full_map(training, grid, er)
        for attempt in range(5):
            r = api_post("/astar-island/submit", {
                "round_id": rid, "seed_index": seed_idx, "prediction": pred
            })
            if r.get("status") == "accepted": break
            time.sleep(2)
        n_s = sum(1 for row in grid for v in row if v == 1)
        log(f"  Seed {seed_idx} ({n_s} sett): {r.get('status', r.get('error', '?'))}")
        time.sleep(0.3)
    
    log("=== Done ===")

if __name__ == "__main__":
    run()
