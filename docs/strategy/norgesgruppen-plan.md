# NorgesGruppen Detection — Plan to Win

## Current Position
- Our mAP: 0.6724 (v4 YOLOv8m@640)
- Top team: ~0.77
- v5 ready (YOLOv8l@1280, val mAP50=0.674) — not yet submitted
- 2 submissions remaining today, 3 tomorrow, 3 Sunday

## Gap Analysis: 0.67 → 0.77 = +0.10 mAP

## Plan (priority order)

### Step 1: Submit v5 NOW (expected: 0.73-0.75)
- YOLOv8l@1280, cloud-trained, already downloaded
- This alone should jump us from 0.67 to ~0.75
- **Cost:** 1 submission slot

### Step 2: Ensemble v4+v5 (expected: +0.02-0.04)
- Combine v4 (YOLOv8m@640) + v5 (YOLOv8l@1280)
- Weighted Box Fusion in numpy (no extra libraries)
- Both models under 420MB total (100MB + 168MB = 268MB)
- Different architectures + resolutions = diverse predictions
- **Cost:** code only, ~2 hours work, 1 submission slot

### Step 3: Train YOLOv8x@1280 (expected: +0.01-0.02)
- 68M params vs 43M (YOLOv8l)
- Cloud GPU: ~$0.15, 30-40 min
- Add to ensemble for 3-model fusion
- **Cost:** $0.15 + 1 submission slot

### Step 4: TTA at inference (expected: +0.01-0.02)
- Horizontal flip + original → merge predictions
- Doubles inference time but still within 300s
- Can stack with ensemble
- **Cost:** code change only

### Step 5: Train with pseudo-labels (expected: +0.01-0.02)
- Use v5 to predict on training images
- Add high-confidence predictions as extra labels
- Retrain with enriched dataset
- **Cost:** $0.15 cloud GPU

## Submission Schedule

| When | What | Expected mAP |
|------|------|-------------|
| Today slot 2 | v5 single model | 0.73-0.75 |
| Today slot 3 | v5 + TTA | 0.74-0.76 |
| Tomorrow slot 1 | Ensemble v4+v5+WBF | 0.76-0.78 |
| Tomorrow slot 2 | Ensemble + TTA | 0.77-0.79 |
| Tomorrow slot 3 | 3-model ensemble (add v8x) | 0.77-0.80 |
| Sunday slot 1-3 | Best variant, final tuning | 0.77-0.80 |

## Realistic Target: 0.76-0.78 mAP
## Stretch Target: 0.80+ mAP (would be #1)

## Total Estimated Cloud Cost: $0.30-0.50
