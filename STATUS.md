# Competition Status — Last Updated 2026-03-21 20:20 CET

## ⚠️ REPO IS PRIVATE — MUST MAKE PUBLIC BEFORE SUNDAY 15:00 CET
```bash
gh repo edit Stig-Johnny/nm-i-ai-2026 --visibility public --accept-visibility-change-consequences
```

## Position: #90 overall, ~76 points (~19 hours remaining)

## Our Scores

| Task | Score | Owner |
|------|-------|-------|
| NorgesGruppen | 0.8987 mAP | Claude-5 |
| Tripletex | 56.0 | Claude-4 |
| Astar Island | 74.9 | iClaw-E (via Claude-3) |

## NorgesGruppen — Current State

### Best Score: 0.8987 (v17a NMS ensemble v17-fulldata + v8x)

### Key Discovery: Full-Data Training
Training on ALL 248 images (no val holdout) improved test score. v17 (full-data YOLOv8l@1280) + v8x ensemble beat previous best by 0.0013.

### Submission History

| Version | mAP | What | Key Learning |
|---------|-----|------|-------------|
| v4 | 0.6724 | YOLOv8m@640 ONNX | First score |
| v5 | 0.8927 | YOLOv8l@1280 ONNX | Cloud GPU + imgsz=1280 = huge gain |
| v8x | 0.8928 | YOLOv8x@1280 ONNX | Bigger model = marginal |
| v6 | 0.8974 | NMS ensemble v5l+v8x | Previous best — ensemble helps |
| v9 | 0.8497 | WBF ensemble + TTA | WBF hurt — bad score averaging |
| v11 | 0.8965 | NMS ensemble v5l+diverse | Diverse model didn't help in ensemble |
| v12 | 0.8943 | Diverse single | Highest val mAP (0.704) but lower test |
| v14 | 0.8929 | Per-class NMS v5l | Per-class NMS didn't help |
| v16 | 0.8944 | Soft-NMS ensemble v5l+v8x | Soft-NMS slightly worse than hard |
| v17a | 0.8987 | **NMS ensemble v17-fulldata+v8x** | **NEW BEST — full-data training works** |

### Available Models (local in task4/)

| File | Model | Training | Size |
|------|-------|----------|------|
| best_v5_1280.onnx | YOLOv8l@1280 | 85/15 split | 168MB |
| best_v8x.onnx | YOLOv8x@1280 FP16 | 85/15 split | 131MB |
| best_diverse_1280.onnx | YOLOv8l@1280 diverse aug | 85/15 split | 168MB |
| best_v17.onnx | YOLOv8l@1280 | **Full 248 images** | 168MB |
| best_v19_fp16.onnx | YOLOv8x@1280 FP16 | **Full 248 images** | 131MB |
| best_v20.onnx | YOLOv8l@1280 alt aug | **Full 248 images** | 168MB |
| best_v20_fp16.onnx | YOLOv8l@1280 alt aug FP16 | **Full 248 images** | 84MB |

### Morning Submissions (3 slots, on Desktop)

**Submit in this order:**

| Priority | File | Size | Models | Rationale |
|----------|------|------|--------|-----------|
| 1st | `sub_3model.zip` | 384MB | v17 + v19_fp16 + v20_fp16 | **3 full-data models**, max diversity, all trained on 248 images |
| 2nd | `sub_v19_v8x.zip` | 262MB | v19_fp16 + v8x | Full-data x + old x — tests if new x model helps |
| 3rd | `sub_v20_v8x.zip` | 299MB | v20 + v8x | Full-data l (alt aug) + old x — tests alt augmentation |

All use hard NMS ensemble (same script as our best v6/v17a).

### Inference Scripts

| Script | Description |
|--------|-------------|
| task4/run.py | Single ONNX, class-agnostic NMS (current main) |
| /tmp/sub_nms_only/run.py | **NMS ensemble** (scored 0.8974 and 0.8987) |
| /tmp/sub_perclass/run.py | Soft-NMS per-class ensemble (scored 0.8944) |

### Key Learnings

1. **Full-data training works** — training on all 248 images (no val holdout) improved test score
2. **Hard NMS ensemble is best** — soft-NMS and per-class NMS both scored worse
3. **WBF scored worse** than NMS — score averaging dilutes good detections
4. **Flip TTA adds noise** on grocery shelves — doesn't help
5. **All models plateau at 0.89-0.90 on test** regardless of architecture/resolution
6. **.pt files crash** in sandbox (torch 2.6 + ultralytics 8.1.0 incompatibility) — must use ONNX
7. **RT-DETR doesn't work** on 248 images — needs more data
8. **Cloud GPU ($0.10/run)** was the single biggest improvement (0.67 → 0.89)
9. **FP16 export must be done on GPU** — CPU export ignores half=True flag

## Infrastructure

- **Vast.ai GPU:** ssh -p 62430 root@212.85.84.41 (RTX 5090). DESTROY when done.
- **Repo:** PRIVATE — make public before Sunday 15:00 CET
- **Mac Mini SSH:** `ssh -i ~/.ssh/mac-executor claude@100.92.170.124`

## Deadline Checklist

- [ ] Submit morning submissions (3 slots available)
- [ ] Make repo public: `gh repo edit Stig-Johnny/nm-i-ai-2026 --visibility public --accept-visibility-change-consequences`
- [ ] Submit repo URL on platform
- [ ] Destroy Vast.ai instance
- [ ] Final leaderboard check
