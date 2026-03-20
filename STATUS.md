# Competition Status — Last Updated 2026-03-20 11:30 CET

## ⚠️ REPO IS PRIVATE — MUST MAKE PUBLIC BEFORE SUNDAY 15:00 CET
```bash
gh repo edit Stig-Johnny/nm-i-ai-2026 --visibility public --accept-visibility-change-consequences
```

## NorgesGruppen: 0.8927 mAP — RANK #4 of 136 teams!

## Our Scores

| Task | Score | Notes |
|------|-------|-------|
| Tripletex | 44.3 | 8/30 task types, Tier 2 just opened (2× multiplier) |
| NorgesGruppen | 62.0 | v4 multi-class ONNX submitted, awaiting result |
| Astar Island | 61.6 | Round 4 scored 57.8, big improvement from priors-only |
| **Overall** | **56.0 (#58)** | |

## Task Ownership

| Task | Owner | Status |
|------|-------|--------|
| Tripletex | **Claude-4** (taking over) | Issue #21 has full briefing |
| Astar Island | **iClaw-E** | Focused 100% on rounds |
| NorgesGruppen | **Claude-5** | v4 submitted, training improvements |

## Active Infrastructure

- **Tripletex server:** Mac Mini port 9001, tunnel `revenue-gale-lou-manor.trycloudflare.com`
- **Astar poller:** Running on Claude-5 MacBook (`python3 task3/solution.py --poll`)
- **Mac Mini SSH:** `ssh -i ~/.ssh/mac-executor claude@100.92.170.124`

## NorgesGruppen Detection

- v4 YOLOv8m multi-class (356 categories) trained overnight
- ONNX export, 100MB, conf=0.001, flat COCO output
- Submitted — awaiting result
- Previous score: 62.2 (single-class detection only)
- Expected improvement from multi-class classification (30% weight)
- 2 submissions remaining today (resets midnight UTC)

## Tripletex (Issue #21)

- Claude-4 taking over from iClaw-E
- Server stays on Mac Mini — Claude-4 pushes code via PR
- iClaw-E restarts server when PRs merge
- Tier 2 opened (2× multiplier) — big scoring opportunity
- 8/30 task types working, many more to implement

## Astar Island

- iClaw-E owns this 100%
- Round 4 scored 57.8 (best so far)
- Round 5 submitted, awaiting score
- Crash-safe observation caching working
- Calibrated priors from Round 1 ground truth
- Poller auto-detects new rounds

## Key Info for New Sessions

- Read `CLAUDE.md` for coding rules and banned imports
- Branch protection on main — use PRs
- `./scripts/check-submission.sh task4/run.py` before any NorgesGruppen zip
- Banned imports: os, sys, subprocess, pickle, shutil, etc. (full list in CLAUDE.md)
- Competition deadline: March 22, 15:00 CET
