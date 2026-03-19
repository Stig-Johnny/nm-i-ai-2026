# Competition Status — Last Updated 2026-03-19 23:15 CET

## OVERNIGHT: Internet may be down. Training runs locally.

### What's running (no internet needed):
- **v3 YOLOv8m training** at imgsz=1280, 200 epochs, ~15-30 min/epoch
  - Weights saved to: `runs/detect/task4/runs/v3_medium_1280/weights/best.pt`
  - Will copy to `task4/best_v3.pt` when done
  - Script: `task4/train_v3.py`
  - PID check: `ps aux | grep train_v3`

### What needs internet (restart in morning):
- **Astar Island poller:** `source .venv/bin/activate && python3 task3/solution.py --poll`
- **Tripletex tunnel:** check `ssh -i ~/.ssh/mac-executor claude@100.92.170.124 "ps aux | grep cloudflared"`
- **Submissions:** upload when internet returns

## Leaderboard

| # | Team | Tripletex | Detection | Astar | Total |
|---|------|-----------|-----------|-------|-------|
| 1 | Companion | 52.1 | 98.6 | 51.9 | 67.5 |
| 12 | **Dashecorp** | **47.6** | **62.2** | **39.6** | **49.8** |

Gap to #1: 17.7 points. Gap to #10: ~5 points.

## Task Status

### Task 2: Tripletex (Owner: iClaw-E)
- Score: 47.6 (6/30 task types, 6.50 raw)
- Rate limited until midnight CET (00:00)
- Tunnel: `https://revenue-gale-lou-manor.trycloudflare.com/solve`
- Server: Mac Mini port 9001 (`uvicorn task2.solution:app`)
- iClaw-E's git token expired — needs refresh

### Task 3: Astar Island (Owner: iClaw-E taking over)
- Score: 39.6 (Round 1 priors-only)
- Round 2: submitted (mostly priors-only, poller crashed mid-observation)
- Poller: restart with `python3 task3/solution.py --poll`
- Key bugs to fix: observation data persistence, frequency-based predictions
- See docs/strategy/astar-island-mechanics.md for simulation rules

### Task 4: NorgesGruppen Detection (Owner: Claude-5)
- Score: 62.2 (single-class detection only, mAP ~0.684)
- v3 training running overnight: YOLOv8m, imgsz=1280, 200 epochs, 356 classes
- Best weights: `runs/detect/task4/runs/v3_medium_1280/weights/best.pt`
- Submission zip must use ONNX or ultralytics format
- run.py at zip root, flat COCO JSON output: `{image_id, category_id, bbox, score}`
- **BANNED IMPORTS:** os, sys, subprocess, pickle, shutil, etc. See CLAUDE.md
- 3 submissions/day (resets midnight UTC = 01:00 CET)
- Also have single-class ONNX model: `task4/best.onnx` (mAP50=0.82 val, scored 62.2)

## Morning Checklist

1. Check v3 training: `cat runs/detect/task4/runs/v3_medium_1280/weights/best.pt` exists?
2. Check v3 mAP: look at training output for `all ... mAP50` values
3. If v3 mAP50 > 0.15: export ONNX, rebuild zip, submit
4. If v3 still training: let it run, submit current single-class again
5. Restart Astar poller
6. Check Tripletex tunnel alive
7. Read Discord for iClaw-E updates
8. Check leaderboard

## Infrastructure

- **Chrome CDP:** Kill Chrome, relaunch: `pkill -9 "Google Chrome"; sleep 3; /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$(mktemp -d)" "https://app.ainm.no/challenge" &`
- **Mac Mini SSH:** `ssh -i ~/.ssh/mac-executor claude@100.92.170.124`
- **Tunnel check:** `curl https://revenue-gale-lou-manor.trycloudflare.com/health`
- **GCP project:** `invotek-github-infra` (needs `gcloud auth login` for user access)
- **Python venv:** `source .venv/bin/activate` in repo root

## Key Learnings (don't repeat these mistakes)

- NorgesGruppen output: flat COCO array `[{image_id, category_id, bbox, score}]` NOT nested
- `import sys` triggers auto-ban — check CLAUDE.md banned imports list
- ultralytics imports are fine (pre-installed in sandbox)
- .pt pickle files allowed despite `pickle` being banned (scanner only checks .py source)
- Astar Island: second poller overwrote good observations — save data to disk before submitting
- Tripletex: bad runs never lower score — submit aggressively
- Tripletex daily limit: 5 per task type per day, resets midnight CET
- NorgesGruppen: 3 submissions per day, resets midnight UTC (01:00 CET)
