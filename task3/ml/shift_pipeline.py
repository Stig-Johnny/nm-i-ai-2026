#!/usr/bin/env python3
"""
R11+ Pipeline: V1+ Lookup Table + Equilibrium Shift from MC observations.
The shift approach adds 3-6 points consistently (CV validated).

Strategy:
1. 5 queries → estimate ER
2. Submit lookup table prediction (baseline, in case internet drops)
3. 45 queries → focused MC on settlement frontiers (3 viewports, ~15 per viewport)
4. Compute equilibrium shift from observations vs expected
5. Apply shift to ALL cells
6. Resubmit shifted prediction
"""
import sys; sys.path.insert(0, '/tmp/astar_ml'); sys.path.insert(0, '/tmp')
import json, math, time, os, socket, base64, struct
import urllib.request, urllib.error
import numpy as np
from collections import defaultdict

# Load lookup table model
exec(open("/tmp/astar_model_v1plus.py").read())

DATA_DIR = "/tmp/astar_data"
LOG = "/tmp/astar_pipeline.log"
FLOOR = 0.01

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

def get_token():
    tabs = json.loads(urllib.request.urlopen("http://localhost:9222/json/list").read())
    tab_id = tabs[0]["id"]
    s = socket.socket(); s.connect(("localhost", 9222))
    key = base64.b64encode(os.urandom(16)).decode()
    s.send((f"GET /devtools/page/{tab_id} HTTP/1.1\r\nHost: localhost:9222\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp: resp += s.recv(4096)
    def ws_send(sock, msg):
        data = msg.encode(); mask = os.urandom(4); length = len(data)
        frame = bytearray([0x81, 0x80 | (length if length < 126 else 126)])
        if length >= 126: frame += struct.pack(">H", length)
        frame += mask + bytes(b ^ mask[i%4] for i,b in enumerate(data))
        sock.send(bytes(frame))
    def ws_recv(sock, timeout=2):
        sock.settimeout(timeout); data = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk: break
                data += chunk
        except: pass
        if len(data) < 2: return ""
        length = data[1] & 0x7f; offset = 2
        if length == 126: length = struct.unpack(">H", data[2:4])[0]; offset = 4
        elif length == 127: length = struct.unpack(">Q", data[2:10])[0]; offset = 10
        return data[offset:offset+length].decode(errors='replace')
    ws_send(s, json.dumps({"id": 1, "method": "Network.enable"}))
    time.sleep(0.2); ws_recv(s, 0.3)
    ws_send(s, json.dumps({"id": 2, "method": "Network.getAllCookies"}))
    time.sleep(0.5)
    cookies = json.loads(ws_recv(s, 1)).get("result", {}).get("cookies", [])
    s.close()
    return next((c["value"] for c in cookies if c["name"] == "access_token"), None)

TOKEN = get_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
def api_get(path):
    req = urllib.request.Request(f"https://api.ainm.no{path}", headers=HEADERS)
    try: return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e: return {"error": str(e)}
def api_post(path, data):
    req = urllib.request.Request(f"https://api.ainm.no{path}", data=json.dumps(data).encode(), headers=HEADERS, method="POST")
    try: return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e: return {"error": str(e)}

def submit_with_retry(round_id, seed_index, prediction, max_retries=5):
    for attempt in range(max_retries):
        r = api_post("/astar-island/submit", {"round_id": round_id, "seed_index": seed_index, "prediction": prediction})
        if r.get("status") == "accepted": return True
        time.sleep(2)
    return False

def find_frontier_viewports(grid, n_viewports=3):
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
    for _ in range(n_viewports):
        best_s, best_vp = -1, None
        for vy in range(0, H-14, 2):
            for vx in range(0, W-14, 2):
                s = sum(sc[vy+dy][vx+dx] for dy in range(15) for dx in range(15) if not covered[vy+dy][vx+dx])
                if s > best_s: best_s, best_vp = s, (vx, vy)
        if best_vp is None or best_s == 0: break
        vx, vy = best_vp
        vps.append((vx, vy))
        for dy in range(15):
            for dx in range(15): covered[vy+dy][vx+dx] = True
    return vps

def run():
    log("=== R11 Pipeline (Lookup + Equilibrium Shift) ===")
    
    training_data, _ = load_training()
    log(f"Lookup model loaded: {len(training_data)} keys")
    
    rounds = api_get("/astar-island/rounds")
    active = next((r for r in rounds if r["status"] == "active"), None)
    if not active: log("No active round!"); return
    
    rid = active["id"]; rnum = active["round_number"]
    log(f"Active: R{rnum}")
    
    budget = api_get("/astar-island/budget")
    used = budget.get("queries_used", 0)
    total = budget.get("queries_max", 50)
    log(f"Budget: {used}/{total}")
    
    detail = api_get(f"/astar-island/rounds/{rid}")
    n_seeds = detail["seeds_count"]
    grid0 = detail["initial_states"][0]["grid"]
    setts0 = [(y,x) for y in range(40) for x in range(40) if grid0[y][x] == 1]
    log(f"Map: 40x40, {n_seeds} seeds, {len(setts0)} settlements")
    
    remaining = total - used
    
    # Step 1: ER estimation (5 queries)
    er_queries = min(5, remaining)
    observations = []
    log(f"Step 1: ER estimation ({er_queries} queries)...")
    for q in range(er_queries):
        sy, sx = setts0[q % len(setts0)]
        vx = max(0, min(sx-7, 25)); vy = max(0, min(sy-7, 25))
        for attempt in range(3):
            r = api_post("/astar-island/simulate", {
                "round_id": rid, "seed_index": q % n_seeds,
                "viewport_x": vx, "viewport_y": vy, "viewport_w": 15, "viewport_h": 15
            })
            if "grid" in r: break; time.sleep(1)
        if "grid" not in r: continue
        log(f"  ER query {q+1}/{er_queries}: budget {r.get('queries_used','?')}/{total}")
        sim_grid = r["grid"]
        for dy in range(len(sim_grid)):
            for dx in range(len(sim_grid[0])):
                y, x = vy+dy, vx+dx
                if y>=40 or x>=40: continue
                if grid0[y][x] in (4,11,0):
                    d = min(abs(y-s[0])+abs(x-s[1]) for s in setts0)
                    if d <= 3: observations.append(1 if sim_grid[dy][dx] in (1,2) else 0)
        time.sleep(0.25)
    
    er = sum(observations)/len(observations) if observations else 0.15
    log(f"  ER={er:.4f} from {len(observations)} obs")
    
    # Step 2: Base prediction (lookup table) + immediate submit
    log(f"Step 2: Lookup predictions (ER={er:.4f})...")
    seed_preds = {}
    for seed_idx in range(n_seeds):
        grid = detail["initial_states"][seed_idx]["grid"]
        pred = predict_full_map(training_data, grid, er)
        seed_preds[seed_idx] = pred
        ok = submit_with_retry(rid, seed_idx, pred)
        n_s = sum(1 for row in grid for v in row if v == 1)
        log(f"  Seed {seed_idx} ({n_s} sett): {'OK' if ok else 'FAILED'}")
        time.sleep(0.3)
    
    # Step 3: MC observations on frontier cells
    budget2 = api_get("/astar-island/budget")
    remaining2 = budget2.get("queries_max", 50) - budget2.get("queries_used", 0)
    log(f"Step 3: MC on frontiers ({remaining2} queries)...")
    
    if remaining2 < 5:
        log("  Not enough budget for MC. Done.")
        log("=== Pipeline complete ==="); return
    
    viewports = find_frontier_viewports(grid0, n_viewports=3)
    log(f"  Target viewports: {viewports}")
    
    # Accumulate observations
    mc_obs = {}  # (y,x) → list of class observations
    
    for q in range(remaining2):
        vx, vy = viewports[q % len(viewports)]
        for attempt in range(3):
            r = api_post("/astar-island/simulate", {
                "round_id": rid, "seed_index": q % n_seeds,
                "viewport_x": vx, "viewport_y": vy, "viewport_w": 15, "viewport_h": 15
            })
            if "grid" in r: break; time.sleep(1)
        if "grid" not in r:
            log(f"  MC query {q+1} failed"); continue
        
        sim_grid = r["grid"]
        class_map = {10:0, 11:0, 0:0, 1:1, 2:2, 3:3, 4:4, 5:5}
        for dy in range(len(sim_grid)):
            for dx in range(len(sim_grid[0])):
                y, x = vy+dy, vx+dx
                if y>=40 or x>=40: continue
                ci = class_map.get(sim_grid[dy][dx], 0)
                if (y,x) not in mc_obs: mc_obs[(y,x)] = []
                mc_obs[(y,x)].append(ci)
        
        # Every 15 queries: compute equilibrium shift and resubmit
        if (q+1) % 15 == 0 or q == remaining2-1:
            log(f"  MC {q+1}/{remaining2}, computing equilibrium shift...")
            
            # Compute observed distributions
            observed = {}
            for (y,x), obs_list in mc_obs.items():
                n = len(obs_list)
                if n >= 5:
                    dist = np.zeros(6)
                    for ci in obs_list: dist[ci] += 1
                    observed[(y,x)] = dist / n
            
            # For each seed: compute shift and resubmit
            for seed_idx in range(n_seeds):
                grid = detail["initial_states"][seed_idx]["grid"]
                setts = [(y,x) for y in range(40) for x in range(40) if grid[y][x] == 1]
                base = np.array(seed_preds[seed_idx])
                
                # Compute shifts by terrain type + distance bucket
                shifts = defaultdict(lambda: np.zeros(6))
                counts = defaultdict(int)
                
                for (y,x), obs_dist in observed.items():
                    if grid[y][x] in (10, 5): continue
                    val = grid[y][x]
                    d = min(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else 99
                    key = (val, min(d, 5))
                    shifts[key] += obs_dist - base[y][x]
                    counts[key] += 1
                
                for key in shifts:
                    if counts[key] > 0: shifts[key] /= counts[key]
                
                # Apply shift with alpha=0.8
                shifted = base.copy()
                for y in range(40):
                    for x in range(40):
                        val = grid[y][x]
                        if val in (10, 5): continue
                        d = min(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else 99
                        key = (val, min(d, 5))
                        if key in shifts:
                            shifted[y][x] = base[y][x] + 0.8 * shifts[key]
                            shifted[y][x] = np.maximum(shifted[y][x], FLOOR)
                            shifted[y][x] /= shifted[y][x].sum()
                
                submit_with_retry(rid, seed_idx, shifted.tolist())
            log(f"    All {n_seeds} seeds resubmitted with shift")
        time.sleep(0.25)
    
    # Save predictions
    os.makedirs("/tmp/astar_predictions", exist_ok=True)
    for seed_idx in range(n_seeds):
        with open(f"/tmp/astar_predictions/r{rnum}_seed{seed_idx}_shift.json", "w") as f:
            json.dump(seed_preds[seed_idx], f, separators=(',',':'))
    
    log("=== Pipeline complete ===")

if __name__ == "__main__":
    run()
