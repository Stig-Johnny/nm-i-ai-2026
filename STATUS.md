# Competition Status — Last Updated 2026-03-20 18:00 CET

## ⚠️ REPO IS PRIVATE — MUST MAKE PUBLIC BEFORE SUNDAY 15:00 CET
```bash
gh repo edit Stig-Johnny/nm-i-ai-2026 --visibility public --accept-visibility-change-consequences
```

## Position: #46 overall, 60.8 points (~21 hours remaining)

## Our Scores

| Task | Score | Rank | Owner |
|------|-------|------|-------|
| NorgesGruppen | 0.8974 mAP | #15/148 | Claude-5 |
| Tripletex | 23.6 | ~#50 | Claude-4 |
| Astar Island | 61.6 | ~#40 | iClaw-E (via Claude-3) |

## Available Models (all downloaded locally)

| Model | File | Size | Val mAP50 | Trained at |
|-------|------|------|-----------|-----------|
| YOLOv8l | best_v5_1280.onnx | 168MB | 0.674 | 1280 |
| YOLOv8l | best_v5_640.onnx | 168MB | 0.674 | 640 export |
| YOLOv8x FP16 | best_v8x.onnx | 131MB | 0.689 | 1280 |
| YOLOv8x | best_1920_full.onnx | 263MB | 0.689 | 1920 |
| YOLOv8x | best_1920_at1280.onnx | 262MB | 0.689 | 1280 export |

## Available Inference Scripts

| Script | Description |
|--------|-------------|
| task4/run.py | Single model ONNX (current on main) |
| task4/run_wbf.py | WBF ensemble + flip TTA (2-3 models) |
| task4/run_sahi.py | SAHI tiled inference (needs 640+1280 models) |

## Tomorrow's Plan (6 NorgesGruppen slots)

| Slot | File | Strategy | Expected |
|------|------|----------|----------|
| 1 | norgesgruppen-v9-wbf-v5l-v8x.zip | WBF ensemble v5l+v8x + flip TTA | 0.91-0.93 |
| 2 | norgesgruppen-v8-1920-single.zip | v8x@1920 single | 0.89-0.91 |
| 3 | TBD | WBF + scale TTA if slot 1 improves | 0.92-0.94 |
| 4-6 | TBD | Iterate on best results | |

## Ready Zips (tested, validated)

| File | Size | Contents |
|------|------|----------|
| norgesgruppen-v9-wbf-v5l-v8x.zip | 259MB | WBF ensemble + flip TTA |
| norgesgruppen-v8-1920-single.zip | 213MB | v8x@1920 single model |

## Submission History

| Date | Version | mAP | Rank |
|------|---------|-----|------|
| Mar 19 | v4 YOLOv8m@640 | 0.6724 | ~#30 |
| Mar 20 | v5 YOLOv8l@1280 | 0.8927 | #4→#15 |
| Mar 20 | v8x YOLOv8x@1280 | 0.8928 | #15 |
| Mar 20 | v6 NMS ensemble v5l+v8x | 0.8974 | #15 |

## Infrastructure

- **Vast.ai GPU:** DESTROY — training done, weights downloaded
- **Tripletex server:** Mac Mini port 9001, tunnel active
- **Mac Mini SSH:** `ssh -i ~/.ssh/mac-executor claude@100.92.170.124`
- **Astar poller:** iClaw-E owns — do NOT restart from Claude-5

## Key Rules

- Repo must be PUBLIC before Sunday 15:00 CET
- NorgesGruppen: 6 submissions/day, resets midnight UTC
- Banned imports: os, sys, subprocess, pickle, shutil (full list in CLAUDE.md)
- Best score kept forever — bad submissions don't hurt
- Max zip: 420MB, max 3 weight files
