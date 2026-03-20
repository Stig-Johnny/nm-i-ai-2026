# Competition Status — Last Updated 2026-03-20 14:00 CET

## ⚠️ REPO IS PRIVATE — MUST MAKE PUBLIC BEFORE SUNDAY 15:00 CET
```bash
gh repo edit Stig-Johnny/nm-i-ai-2026 --visibility public --accept-visibility-change-consequences
```

## Position: #46 overall, 60.8 points (~29 hours remaining)

## Our Scores

| Task | Score | Rank on Task | Notes |
|------|-------|-------------|-------|
| NorgesGruppen | 0.8974 mAP | #15 of 148 | Ensemble v5l+v8x, WBF ready for tomorrow |
| Tripletex | 23.6 | ~#50 | Claude-4 working on T2 task types |
| Astar Island | 61.6 | ~#40 | iClaw-E improved priors, poller for Round 6+ |

## Overnight Training (Vast.ai RTX 4090, ~$0.24/hr)

- **YOLOv8x@1920** training. Epoch 32, mAP50=0.629, climbing.
- ETA: ~2-3 AM CET (early stopping ~epoch 100-150)
- Auto-cleanup cron running to prevent disk full
- Download when done: `scp -P 33757 -i ~/.ssh/id_ed25519 root@ssh7.vast.ai:/root/runs/detect/runs/cloud_1920/weights/best.pt task4/best_1920.pt`
- Then destroy instance

## Tomorrow Plan (6 NorgesGruppen slots)

| Slot | What | Files |
|------|------|-------|
| 1 | v8x@1920 single model | run.py + best_1920.onnx |
| 2 | WBF ensemble v5l@1280 + v8x@1280 + v8x@1920 | run_wbf.py + 3 models |
| 3 | WBF ensemble + flip TTA | run_wbf.py (already has TTA) |
| 4-6 | Variants based on results | |

## Key Files

| File | Description |
|------|-------------|
| `task4/run_wbf.py` | WBF ensemble + TTA (best approach) |
| `task4/run_sahi.py` | SAHI tiled inference (needs timeout fix) |
| `task4/best_v5_1280.onnx` | YOLOv8l@1280, scored 0.8927 |
| `task4/best_v8x.onnx` | YOLOv8x@1280 FP16, scored 0.8928 |
| `task4/best_v5_640.onnx` | YOLOv8l@640 (for SAHI tiles) |
| `task4/cloud_train.sh` | Cloud GPU training script |
| `task4/best_1920.pt` | (downloading after training) |

## Task Ownership

| Task | Owner | Status |
|------|-------|--------|
| NorgesGruppen | Claude-5 | Cloud training overnight, WBF ready |
| Tripletex | Claude-4 | Fixing T2 task types, server on Mac Mini |
| Astar Island | iClaw-E | Improved priors, poller for Round 6+ |

## Infrastructure

- **Vast.ai GPU:** host:103274 Ukraine, ssh -p 33757 root@ssh7.vast.ai. DESTROY after downloading weights.
- **Tripletex tunnel:** revenue-gale-lou-manor.trycloudflare.com (Mac Mini port 9001)
- **Mac Mini SSH:** ssh -i ~/.ssh/mac-executor claude@100.92.170.124
- **Repo:** PRIVATE. Make public before Sunday 15:00 CET.
