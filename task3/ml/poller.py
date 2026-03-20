#!/usr/bin/env python3
"""Polls for new active round and runs the R8 pipeline."""
import json, time, urllib.request, urllib.error, subprocess, os, socket, base64, struct

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

seen_rounds = set()
LOG = "/tmp/astar_poller_main.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

log("Poller started. Watching for new active rounds...")

while True:
    try:
        token = get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        req = urllib.request.Request("https://api.ainm.no/astar-island/rounds", headers=headers)
        rounds = json.loads(urllib.request.urlopen(req).read())
        
        for r in rounds:
            if r["status"] == "active" and r["id"] not in seen_rounds:
                rn = r["round_number"]
                log(f"NEW ACTIVE ROUND: R{rn} ({r['id']})")
                
                # Check budget first
                req2 = urllib.request.Request("https://api.ainm.no/astar-island/budget", headers=headers)
                budget = json.loads(urllib.request.urlopen(req2).read())
                used = budget.get("queries_used", 0)
                
                if used >= 45:
                    log(f"Budget nearly exhausted ({used}/50). Skipping pipeline.")
                    seen_rounds.add(r["id"])
                    continue
                
                log(f"Budget fresh ({used}/50). Launching pipeline!")
                # Run pipeline
                proc = subprocess.Popen(
                    ["python3", "/tmp/astar_r9_cnn_pipeline.py"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
                out, _ = proc.communicate(timeout=300)
                log(f"Pipeline finished: exit={proc.returncode}")
                log(out.decode()[-500:] if out else "no output")
                
                seen_rounds.add(r["id"])
                
                # Also save GT for this round when it completes later
    except Exception as e:
        log(f"Error: {e}")
    
    time.sleep(30)
