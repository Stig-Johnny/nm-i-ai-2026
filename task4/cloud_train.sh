#!/bin/bash
# NorgesGruppen Cloud Training Script
# Run this on a cloud GPU (Vast.ai RTX 4090 / A100)
#
# Step 1: Upload this script + training data to the GPU instance
# Step 2: Run: bash cloud_train.sh
# Step 3: Download best.pt and best.onnx when done

set -e

echo "=== NorgesGruppen Cloud Training ==="
echo "GPU:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "No GPU detected"

# Install dependencies
pip install ultralytics==8.1.0 2>/dev/null || pip install ultralytics
pip install onnx onnxruntime-gpu

# Create dataset structure
mkdir -p data/train/images data/train/labels data/val/images data/val/labels

# Check if data is already extracted
if [ ! -f "annotations.json" ]; then
    echo "ERROR: annotations.json not found. Upload NM_NGD_coco_dataset.zip and extract first:"
    echo "  unzip NM_NGD_coco_dataset.zip"
    echo "  mv train/annotations.json ."
    echo "  mv train/images/* images/"
    exit 1
fi

# Convert COCO to YOLO format
python3 << 'PYEOF'
import json, shutil
from pathlib import Path

with open("annotations.json") as f:
    coco = json.load(f)

img_anns = {}
for ann in coco["annotations"]:
    img_anns.setdefault(ann["image_id"], []).append(ann)

images = list(coco["images"])
split_idx = int(len(images) * 0.85)

for split, imgs in [("train", images[:split_idx]), ("val", images[split_idx:])]:
    for img in imgs:
        fname = img["file_name"]
        w, h = img["width"], img["height"]
        src = Path("images") / fname
        if src.exists():
            shutil.copy2(src, f"data/{split}/images/{fname}")
        with open(f"data/{split}/labels/{Path(fname).stem}.txt", "w") as lf:
            for ann in img_anns.get(img["id"], []):
                cat_id = ann["category_id"]
                bx, by, bw, bh = ann["bbox"]
                cx = (bx + bw / 2) / w
                cy = (by + bh / 2) / h
                lf.write(f"{cat_id} {cx:.6f} {cy:.6f} {bw/w:.6f} {bh/h:.6f}\n")

nc = len(coco["categories"])
with open("data/dataset.yaml", "w") as f:
    f.write(f"path: {Path('data').resolve()}\ntrain: train/images\nval: val/images\nnc: {nc}\nnames: {list(range(nc))}\n")

print(f"Data ready: {split_idx} train, {len(images)-split_idx} val, {nc} classes")
PYEOF

echo ""
echo "=== Starting Training ==="
echo "Model: YOLOv8l, imgsz=1280, 400 epochs"
echo ""

# Train YOLOv8l at 1280
python3 << 'PYEOF'
from ultralytics import YOLO

model = YOLO("yolov8l.pt")
model.train(
    data="data/dataset.yaml",
    imgsz=1280,
    epochs=400,
    patience=50,
    batch=4,
    device=0,
    workers=4,
    save=True,
    project="runs",
    name="cloud_v5",
    exist_ok=True,
    cos_lr=True,
    close_mosaic=15,
    mixup=0.15,
    copy_paste=0.1,
    scale=0.5,
    label_smoothing=0.05,
    degrees=0.0,
    flipud=0.0,
    fliplr=0.5,
    hsv_h=0.015,
    hsv_s=0.4,
    hsv_v=0.3,
)

# Export to ONNX
import shutil
from pathlib import Path

best = Path("runs/cloud_v5/weights/best.pt")
if best.exists():
    shutil.copy2(best, "best.pt")
    print(f"Weights saved: best.pt ({best.stat().st_size/1e6:.1f}MB)")

    m = YOLO(str(best))
    m.export(format="onnx", imgsz=1280)
    onnx = best.with_suffix(".onnx")
    if onnx.exists():
        shutil.copy2(onnx, "best.onnx")
        print(f"ONNX saved: best.onnx ({onnx.stat().st_size/1e6:.1f}MB)")

print("\n=== TRAINING COMPLETE ===")
print("Download: best.pt and best.onnx")
PYEOF
