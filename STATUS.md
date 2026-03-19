# Competition Status — Last Updated 2026-03-19 23:30 CET

## OVERNIGHT TRAINING RUNNING (no internet needed)

**v4 YOLOv8m** at imgsz=640, 200 epochs, ~90s/epoch, **ETA ~4 AM CET**
- Weights: `runs/detect/task4/runs/v4_medium_640/weights/best.pt`
- Script: `task4/train_v4.py`
- Check: `ps aux | grep train_v4`
- v3 (imgsz=1280) was killed — too slow on MPS

**Morning checklist:**
1. `ps aux | grep train_v4` — still running?
2. Check mAP: grep for `all.*mAP50` in training output
3. If done: `cp runs/detect/task4/runs/v4_medium_640/weights/best.pt task4/best_v4.pt`
4. Export ONNX or use ultralytics .pt directly
5. Rebuild zip, have Stig upload
6. Restart Astar Island poller: `python3 task3/solution.py --poll`
7. Check Tripletex tunnel: `curl https://revenue-gale-lou-manor.trycloudflare.com/health`

## Leaderboard (19:45 CET)

| # | Team | Tripletex | Detection | Astar | Total |
|---|------|-----------|-----------|-------|-------|
| 1 | Make No Mistakes | 100.0 | --- | --- | 25.0 |
| 2 | Prompt Injection | 63.3 | --- | --- | 15.8 |
| 1 | Slop Overflow | 100.0 | --- | --- | 33.3 |
| 1 | 000110 000111 | --- | 100.0 | --- | 33.3 |
| 12 | **Dashecorp (us)** | **47.6** | **62.2** | **39.6** | **49.8** |

#1 Companion at 67.5. Gap to top 10: ~5 points. Improvement paths: Detection (multi-class), Tripletex (more tasks), Astar (better observations).

NorgesGruppen Detection NOW SCORING — 4 teams have mAP scores. We submit at midnight UTC.
Astar Island leaderboard still says "hasn't started".

## Active Tasks

### Task 1: Grocery Bot (WebSocket)
- **Owner:** Shared
- **Scores:** Easy 110, Medium 117, Hard 113, Expert 13
- **Code:** `warmup/grocery_bot.py`, `warmup/run_game.py`
- **Token automation:** Chrome CDP on port 9222 → `shared/token.py`
- **Map UUIDs:** easy=3c7e90e6, medium=0aba093f, hard=9bb9b3de, expert=c6acd676, nightmare=8e5eeedd

### Task 2: Tripletex (HTTPS endpoint)
- **Owner:** iClaw-E
- **Score:** Rank #1, 0.29 (2/7 checks pass from format alone)
- **Endpoint:** Cloudflare tunnel (DNS proxy issue — tx-proxy.ainm.no doesn't resolve outside GCP)
- **Blocker:** Need GCP Cloud Run deploy for full proxy access. @gcplab.me account button inactive. Trying our `invotek-github-infra` GCP project.
- **LLM approach:** Gemini via Vertex AI in Cloud Run (claude CLI doesn't work in containers)
- **Sandbox:** `https://kkpqfuj-amager.tripletex.dev/v2` (works from anywhere)

### Task 3: Astar Island (REST API)
- **Owner:** Claude-5
- **Code:** `task3/solution.py`
- **Round 1:** Submitted all 5 seeds, 100% coverage, 45/50 queries. BUT second poller overwrote with priors-only. Awaiting score.
- **Round closes:** ~21:42 CET
- **Poller running:** Background task polls every 30s, skips rounds with existing queries
- **API:** `https://api.ainm.no/astar-island/`
- **Auth:** Bearer JWT from Chrome CDP cookie
- **Terrain classes:** 0=Empty, 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain. Raw grid: 10=Ocean, 11=Plains

### Task 4: NorgesGruppen (ZIP upload)
- **Owner:** Claude-5
- **Code:** `task4/run.py` (submission), `task4/train_detection.py` (training)
- **Training:** YOLOv8n single-class detection, epoch 31/80, best mAP50=0.82 (saved)
- **Submission zip ready:** `norgesgruppen-submission.zip` (11MB) with trained best.pt
- **Data:** `data/coco/train/` (248 images, 22.7k annotations, 356 categories)
- **Submission limit:** 0/3 remaining today (burned on network errors). Resets midnight UTC (01:00 CET)
- **Submit at 01:00 CET:** Package `task4/run.py` + `task4/best_detection.pt` as ZIP, Stig uploads

## Infrastructure

- **Chrome CDP:** Port 9222, logged into app.ainm.no (kill all Chrome, relaunch with `--remote-debugging-port=9222` using copied profile dir)
- **Python venv:** `.venv/` in repo root
- **MCP docs:** `https://mcp-docs.ainm.no/mcp` (SSE-based, needs session init)
- **GCP:** `gcloud` installed, project `invotek-github-infra`, only service accounts authed (need `gcloud auth login` for user access)
- **Discord channels:** #iclaw-e=1482354822492455065, #human=1477261394666590328

## Key Learnings

- Astar Island rounds are admin-created on a schedule, not continuous
- tx-proxy.ainm.no is GCP-internal DNS only
- NorgesGruppen: 3 submissions/day, resets midnight UTC
- 356 classes too sparse for 248 images — train single-class detection first (70% of score)
- Grocery Bot: fleet coordination helps multi-bot but hurts single-bot Easy (126→110 regression)
- Tripletex: returning correct format gets 2/7 checks free
