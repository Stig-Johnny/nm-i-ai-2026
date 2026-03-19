"""
NorgesGruppen Grocery Shelf Object Detection
NM i AI 2026 — Task 4

Contract:
  python run.py --input /data/images --output /output/predictions.json

Output: JSON array of {image_id, category_id, bbox: [x,y,w,h], score}

Safe imports only — no os, sys, subprocess, pickle, etc.
Uses pathlib for file ops, json for output.
"""

import argparse
import json
from pathlib import Path

# All allowed: torch, ultralytics, numpy, PIL are pre-installed and not banned
import torch
from ultralytics import YOLO


# ── Config ─────────────────────────────────────────────────────────────────────
MODEL_FILE = "best.pt"          # Fine-tuned grocery model (primary)
FALLBACK_MODEL = "yolov8s.pt"   # COCO pretrained fallback (detection-only)
CONF_THRESH = 0.20              # Lower threshold → more recall for mAP
IOU_THRESH = 0.50               # NMS IoU threshold
IMG_SIZE = 1280                 # Higher res → better small product detection
MAX_DET = 500                   # Max detections per image (shelves are dense)
BATCH_SIZE = 4                  # Process 4 images at once on L4 GPU
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
# ──────────────────────────────────────────────────────────────────────────────


def load_model():
    """Load fine-tuned model if available, else COCO pretrained fallback."""
    model_path = Path(MODEL_FILE)
    if model_path.exists():
        print(f"Loading fine-tuned model: {MODEL_FILE} on {DEVICE}")
        model = YOLO(str(model_path))
        model.to(DEVICE)
        return model, False  # (model, is_fallback)
    else:
        print(f"Fine-tuned model not found. Using COCO pretrained fallback: {FALLBACK_MODEL}")
        print("WARNING: Fallback will score 0 on classification (detection-only, category_id=0 for all)")
        model = YOLO(FALLBACK_MODEL)
        model.to(DEVICE)
        return model, True


def image_id_from_path(img_path: Path) -> int:
    """Extract numeric ID: img_00042.jpg → 42"""
    stem = img_path.stem  # e.g. "img_00042"
    parts = stem.split("_")
    return int(parts[-1])


def predict_batch(model, image_paths: list, is_fallback: bool) -> list:
    """Run inference on a batch of images, return flat list of predictions."""
    predictions = []

    # Run ultralytics inference (handles batching internally when given a list)
    results = model.predict(
        source=[str(p) for p in image_paths],
        conf=CONF_THRESH,
        iou=IOU_THRESH,
        imgsz=IMG_SIZE,
        max_det=MAX_DET,
        verbose=False,
        device=DEVICE,
    )

    for img_path, result in zip(image_paths, results):
        img_id = image_id_from_path(img_path)
        boxes = result.boxes

        if boxes is None or len(boxes) == 0:
            continue

        # xyxy → convert to COCO xywh
        xyxy = boxes.xyxy.cpu().tolist()
        confs = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()

        for (x1, y1, x2, y2), conf, cls in zip(xyxy, confs, classes):
            category_id = 0 if is_fallback else int(cls)
            predictions.append({
                "image_id": img_id,
                "category_id": category_id,
                "bbox": [round(x1, 2), round(y1, 2), round(x2 - x1, 2), round(y2 - y1, 2)],
                "score": round(conf, 6),
            })

    return predictions


def main():
    parser = argparse.ArgumentParser(description="NorgesGruppen grocery detection")
    parser.add_argument("--input", required=True, help="Path to directory of shelf images")
    parser.add_argument("--output", required=True, help="Path to write predictions.json")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Gather and sort images
    images = sorted(input_path.glob("img_*.jpg"))
    print(f"Found {len(images)} images in {input_path}")

    if not images:
        print("No images found — writing empty predictions")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump([], f)
        return

    # Load model
    model, is_fallback = load_model()

    # Inference in batches
    all_predictions = []
    for i in range(0, len(images), BATCH_SIZE):
        batch = images[i : i + BATCH_SIZE]
        batch_preds = predict_batch(model, batch, is_fallback)
        all_predictions.extend(batch_preds)
        print(f"  Processed {min(i + BATCH_SIZE, len(images))}/{len(images)} images "
              f"({len(batch_preds)} detections in batch)")

    print(f"Total predictions: {len(all_predictions)}")

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_predictions, f)

    print(f"Predictions written to {output_path}")


if __name__ == "__main__":
    main()
