# Task 4: NorgesGruppen Data — Object Detection

**Status:** Training in progress, submit at midnight UTC
**Owner:** Claude-5
**Submission:** Code upload (ZIP), 3 submissions/day (resets midnight UTC)

## Overview

Object detection on 248 Norwegian grocery shelf images with ~22.7k COCO annotations and 356 product categories across 4 store sections: Egg, Frokost, Knekkebrod, Varmedrikker.

## Key Details

- Train locally, upload `.zip` with `run.py` + weights (max 420MB)
- Runs in sandboxed Docker: NVIDIA L4 GPU, 24GB VRAM, 300s timeout
- Score: **70% detection** + 30% classification (mAP@0.5)
- No network access in sandbox
- No `os`, `subprocess`, `socket` imports — use `pathlib`
- Pre-installed: PyTorch 2.6.0, ultralytics 8.1.0, ONNX Runtime GPU
- 3 submissions per day (burned today on network errors, resets midnight UTC)

## Architecture

```mermaid
flowchart TD
    A[COCO dataset: 248 images, 22.7k annotations] --> B{Training strategy}
    B -->|Phase 1| C[Single-class detection]
    B -->|Phase 2| D[356-class classification]

    C --> E[YOLOv8n trained on 'product' class]
    E --> F[Scores up to 70% detection weight]

    D --> G[YOLOv8m with all categories]
    G --> H[Scores up to 100%]

    F --> I[Package run.py + best.pt]
    H --> I
    I --> J[Upload ZIP at midnight UTC]
    J --> K[Platform: Docker + L4 GPU + 300s]
    K --> L[mAP@0.5 score]
```

## Training Strategy

### Phase 1: Detection-only (current)

356 categories with only 248 images is too sparse for classification. Training **single-class "product" detector** first:

- All 22.7k bounding boxes mapped to class 0 ("product")
- YOLOv8n, 80 epochs, imgsz=640, batch=16
- Detection-only can score up to **70%** of total
- Training on Apple Silicon MPS

**Results so far:** Epoch 2/80, mAP50=0.113 (rising fast)

### Phase 2: Classification (later)

Once detection is solid, train multi-class:
- YOLOv8m or YOLOv8l for more capacity
- 356 classes, longer training
- FP16 quantization to fit under 420MB weight limit

## Submission Format

```
zip structure:
├── run.py          # Entry point (MUST be at root)
├── best.pt         # YOLOv8 weights
```

run.py contract:
```bash
python run.py --input /data/images/ --output /tmp/output.json
```

Output JSON:
```json
[
  {
    "image_name": "img_00042.jpg",
    "predictions": [
      {"bbox": [x, y, w, h], "category_id": 0, "confidence": 0.85}
    ]
  }
]
```

## Rate Limits

- 3 submissions per day (resets midnight UTC)
- Today's 3 submissions burned on network upload errors
- Next submission window: **midnight UTC (01:00 CET)**

## Scores

| Submission | Model | Detection mAP | Classification mAP | Total |
|-----------|-------|--------------|-------------------|-------|
| — | Training... | — | — | — |

## Blocked

- ~~Need training data~~ Downloaded (854MB COCO + 60MB product images)
- ~~Need submission slot~~ Resets midnight UTC
