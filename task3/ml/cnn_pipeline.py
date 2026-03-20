#!/usr/bin/env python3
"""R9 Pipeline with CNN model."""
import sys
sys.path.insert(0, '/tmp/astar_ml')

import json, math, time, os, socket, base64, struct
import urllib.request, urllib.error

DATA_DIR = "/tmp/astar_data"
LOG = "/tmp/astar_r9.log"
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
    try: return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e: return {"error": e.code}

def api_post(path, data):
    req = urllib.request.Request(f"https://api.ainm.no{path}", data=json.dumps(data).encode(), headers=HEADERS, method="POST")
    try: return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e: return {"error": e.code}

# Load CNN model
from predict_local import predict_cnn, load_model
log("Loading CNN model...")
load_model()
log("CNN loaded")

def estimate_er(round_id, grid, n_seeds, n_queries=5):
    """Estimate expansion rate from observations."""
    H, W = len(grid), len(grid[0])
    setts = [(y,x) for y in range(H) for x in range(W) if grid[y][x] == 1]
    observations = []
    
    for q in range(n_queries):
        sy, sx = setts[q % len(setts)]
        vx = max(0, min(sx-7, W-15))
        vy = max(0, min(sy-7, H-15))
        
        r = api_post("/astar-island/simulate", {
            "round_id": round_id, "seed_index": q % n_seeds,
            "viewport_x": vx, "viewport_y": vy, "viewport_w": 15, "viewport_h": 15
        })
        if "error" in r: continue
        
        sim_grid = r["grid"]
        log(f"  ER query {q+1}/{n_queries}: budget {r.get('queries_used','?')}/50")
        
        for dy in range(len(sim_grid)):
            for dx in range(len(sim_grid[0])):
                y, x = vy+dy, vx+dx
                if y>=H or x>=W: continue
                if grid[y][x] in (4, 11, 0):
                    d = min(abs(y-s[0])+abs(x-s[1]) for s in setts)
                    if d <= 3:
                        observations.append(1 if sim_grid[dy][dx] in (1,2) else 0)
        time.sleep(0.15)
    
    er = sum(observations)/len(observations) if observations else 0.15
    log(f"  ER={er:.4f} from {len(observations)} obs")
    return er

def run():
    log("=== R9 CNN Pipeline ===")
    
    rounds = api_get("/astar-island/rounds")
    active = next((r for r in rounds if r["status"] == "active"), None)
    if not active:
        log("No active round!"); return
    
    rid = active["id"]; rnum = active["round_number"]
    log(f"Active: R{rnum}")
    
    budget = api_get("/astar-island/budget")
    used = budget.get("queries_used", 0)
    log(f"Budget: {used}/50")
    
    if used > 5:
        log(f"WARNING: {used} queries pre-consumed!")
    
    detail = api_get(f"/astar-island/rounds/{rid}")
    n_seeds = detail["seeds_count"]
    
    # Step 1: Quick ER estimate (5 queries)
    grid0 = detail["initial_states"][0]["grid"]
    setts = [(y,x) for y in range(40) for x in range(40) if grid0[y][x] == 1]
    log(f"Map: 40x40, {n_seeds} seeds, {len(setts)} settlements")
    
    remaining = 50 - used
    er_queries = min(5, remaining)
    log(f"Step 1: ER estimation ({er_queries} queries)...")
    er = estimate_er(rid, grid0, n_seeds, er_queries)
    
    # Step 2: Per-seed CNN predictions + submit
    log(f"Step 2: CNN predictions (ER={er:.4f})...")
    for seed_idx in range(n_seeds):
        grid = detail["initial_states"][seed_idx]["grid"]
        pred = predict_cnn(grid, er)
        r = api_post("/astar-island/submit", {"round_id": rid, "seed_index": seed_idx, "prediction": pred})
        n_s = sum(1 for row in grid for v in row if v == 1)
        log(f"  Seed {seed_idx} ({n_s} sett): {r.get('status', r.get('error', '?'))}")
        time.sleep(0.3)
    
    log("=== Pipeline complete ===")

if __name__ == "__main__":
    run()
