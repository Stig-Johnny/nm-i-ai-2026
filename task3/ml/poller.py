#!/usr/bin/env python3
"""Polls for new active rounds. Single pipeline instance enforced."""
import json, time, urllib.request, urllib.error, subprocess, os, fcntl

exec(open("/tmp/astar_auth.py").read())

PIPELINE_LOCK = "/tmp/astar_pipeline.lock"
seen_rounds = set()
LOG = "/tmp/astar_poller_main.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

def is_pipeline_running():
    """Check if pipeline lock exists and process is alive."""
    if os.path.exists(PIPELINE_LOCK):
        try:
            with open(PIPELINE_LOCK) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # Check if process exists
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            os.remove(PIPELINE_LOCK)
    return False

log("Poller started (resilient auth, pipeline lock)")

while True:
    try:
        token = get_token()
        if not token:
            log("No token"); time.sleep(30); continue
        
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        req = urllib.request.Request("https://api.ainm.no/astar-island/rounds", headers=headers)
        rounds = json.loads(urllib.request.urlopen(req, timeout=10).read())
        
        for r in rounds:
            if r["status"] == "active" and r["id"] not in seen_rounds:
                rn = r["round_number"]
                log(f"NEW ACTIVE ROUND: R{rn} ({r['id']})")
                
                if is_pipeline_running():
                    log("Pipeline already running. Skipping.")
                    seen_rounds.add(r["id"])
                    continue
                
                req2 = urllib.request.Request("https://api.ainm.no/astar-island/budget", headers=headers)
                budget = json.loads(urllib.request.urlopen(req2, timeout=10).read())
                used = budget.get("queries_used", 0)
                
                if used >= 45:
                    log(f"Budget exhausted ({used}/50). Skipping.")
                    seen_rounds.add(r["id"])
                    continue
                
                log(f"Budget: {used}/50. Launching pipeline!")
                
                proc = subprocess.Popen(
                    ["/tmp/astar_venv/bin/python3", "/tmp/astar_shift_v2_pipeline.py"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
                # Write lock
                with open(PIPELINE_LOCK, "w") as f:
                    f.write(str(proc.pid))
                
                out, _ = proc.communicate(timeout=300)
                
                # Remove lock
                try: os.remove(PIPELINE_LOCK)
                except: pass
                
                log(f"Pipeline finished: exit={proc.returncode}")
                if out: log(out.decode()[-300:])
                seen_rounds.add(r["id"])
                
    except Exception as e:
        log(f"Error: {e}")
    
    time.sleep(30)
