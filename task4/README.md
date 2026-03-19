# Task 4: NorgesGruppen Data — Grocery Shelf Detection

**Owner:** iClaw-E (Mac Mini M2)
**Status:** run.py ready, model TBD

## Approach

Uses `ultralytics` directly with a `.pt` model — simpler and more GPU-native than ONNX+numpy.

### Primary (fine-tuned, `best.pt`)
- YOLOv8s or larger trained on `NM_NGD_coco_dataset.zip` (864 MB, 248 images, 22,700 annotations, 356 categories)
- Full detection + classification → up to 100% normalized score
- **Model not trained yet** — needs dataset download from submit page

### Fallback (COCO pretrained)
- `yolov8s.pt` pretrained on COCO-80 (not grocery-specific)
- All category_ids set to 0 → detection-only → caps at 70%

## vs Codi-E's Approach

| | iClaw-E | Codi-E |
|---|---|---|
| Runtime | ultralytics `.pt` native | ONNX Runtime |
| Model | `best.pt` (YOLOv8s, grocery) | `best.onnx` (YOLOv8n → ONNX) |
| Imports | torch, ultralytics, pathlib, json | onnxruntime, numpy, PIL, pathlib, json |
| Resolution | 1280px | (check with Codi-E) |
| Batch size | 4 (GPU) | (check with Codi-E) |

## Submission Format

```bash
# Create zip (run.py at root)
cd task4/
zip -r ../norgesgruppen-iclawe.zip run.py best.pt -x ".*"
```

## Training (TODO)

1. Download `NM_NGD_coco_dataset.zip` from app.ainm.no submit page
2. Train on Mac Mini or Cloud GPU:
   ```bash
   pip install ultralytics==8.1.0
   yolo train model=yolov8s.pt data=dataset.yaml epochs=50 imgsz=1280 batch=8
   ```
3. Copy `runs/detect/train/weights/best.pt` → `task4/best.pt`

## TODO

- [ ] Download dataset from submit page (Stig)
- [ ] Train YOLOv8s on grocery data (need GPU — Mac Mini M2 is CPU-only for training)
- [ ] Compare mAP50 with Codi-E's model before submitting
- [ ] PR review with Codi-E before submission
