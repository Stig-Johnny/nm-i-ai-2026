"""
Task 4 — NorgesGruppen: Grocery Shelf Object Detection
======================================================
YOLOv8-based object detection on Norwegian grocery shelf images.

Submission: zip this file + weights, upload to platform.

Execution environment:
  - NVIDIA L4 GPU, 24GB VRAM
  - PyTorch 2.6.0, ultralytics 8.1.0, ONNX Runtime GPU
  - No network access, 300s timeout
  - No os/subprocess/socket imports (use pathlib)

Usage (in sandbox):
    python run.py --input /data/images/ --output /tmp/output.json
"""

import json
import sys
from pathlib import Path

# Detect if running in competition sandbox or locally
try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False
    print("ultralytics not installed — using fallback")


def detect_with_yolo(input_dir: Path, weights_path: Path) -> list:
    """Run YOLOv8 detection on all images in input_dir."""
    model = YOLO(str(weights_path))
    results_list = []

    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )

    print(f"Processing {len(image_files)} images...")

    for img_path in image_files:
        results = model(str(img_path), verbose=False)

        predictions = []
        for r in results:
            boxes = r.boxes
            if boxes is not None:
                for i in range(len(boxes)):
                    # YOLO returns xyxy, convert to xywh for COCO format
                    x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                    w = x2 - x1
                    h = y2 - y1
                    conf = float(boxes.conf[i])
                    cls = int(boxes.cls[i])

                    predictions.append({
                        "bbox": [round(x1, 1), round(y1, 1), round(w, 1), round(h, 1)],
                        "category_id": cls,
                        "confidence": round(conf, 4)
                    })

        results_list.append({
            "image_name": img_path.name,
            "predictions": predictions
        })

    return results_list


def detect_fallback(input_dir: Path) -> list:
    """Fallback: return empty predictions for all images."""
    results_list = []
    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )
    for img_path in image_files:
        results_list.append({
            "image_name": img_path.name,
            "predictions": []
        })
    return results_list


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Directory with shelf images")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)

    # Look for weights in same directory as this script
    script_dir = Path(__file__).parent
    weights_path = script_dir / "best.pt"

    if HAS_YOLO and weights_path.exists():
        print(f"Using YOLOv8 weights: {weights_path}")
        results = detect_with_yolo(input_dir, weights_path)
    elif HAS_YOLO:
        # Use pretrained YOLOv8n as fallback (generic COCO detection)
        print("No custom weights found, using YOLOv8n pretrained")
        weights_path = script_dir / "yolov8n.pt"
        if not weights_path.exists():
            # In sandbox, try to use built-in
            model = YOLO("yolov8n.pt")
            results = []
            image_files = sorted(
                [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
            )
            for img_path in image_files:
                res = model(str(img_path), verbose=False)
                preds = []
                for r in res:
                    if r.boxes is not None:
                        for i in range(len(r.boxes)):
                            x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                            preds.append({
                                "bbox": [round(x1,1), round(y1,1), round(x2-x1,1), round(y2-y1,1)],
                                "category_id": 0,  # Generic detection, no classification
                                "confidence": round(float(r.boxes.conf[i]), 4)
                            })
                results.append({"image_name": img_path.name, "predictions": preds})
        else:
            results = detect_with_yolo(input_dir, weights_path)
    else:
        print("No YOLO available, using empty fallback")
        results = detect_fallback(input_dir)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f)

    total_preds = sum(len(r["predictions"]) for r in results)
    print(f"Done: {len(results)} images, {total_preds} detections")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
