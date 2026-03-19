"""
NorgesGruppen v5 — learned from competitor analysis.
Key changes: conf=0.001, torch.load monkey-patch, max_det=500, flat COCO output.
"""

import json
import argparse
import torch
from pathlib import Path

# CRITICAL: torch 2.6 + ultralytics 8.1.0 compatibility fix
# Sandbox uses torch 2.6.0+cu124 which defaults weights_only=True
# ultralytics .pt files need weights_only=False
_original_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs.setdefault('weights_only', False)
    return _original_load(*args, **kwargs)
torch.load = _patched_load

from ultralytics import YOLO


def image_id_from_filename(fname):
    digits = ''.join(c for c in Path(fname).stem if c.isdigit())
    return int(digits) if digits else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)
    script_dir = Path(__file__).parent
    weights_path = script_dir / "best.pt"

    model = YOLO(str(weights_path))
    all_predictions = []

    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )

    print(f"Processing {len(image_files)} images...")

    for img_path in image_files:
        img_id = image_id_from_filename(img_path.name)
        results = model(str(img_path), verbose=False, conf=0.001, iou=0.5, max_det=500)

        for r in results:
            if r.boxes is not None:
                for i in range(len(r.boxes)):
                    x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                    w = x2 - x1
                    h = y2 - y1
                    if w > 1 and h > 1:
                        all_predictions.append({
                            "image_id": img_id,
                            "category_id": int(r.boxes.cls[i]),
                            "bbox": [round(x1, 1), round(y1, 1), round(w, 1), round(h, 1)],
                            "score": round(float(r.boxes.conf[i]), 3)
                        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(all_predictions, f)

    print(f"Done: {len(image_files)} images, {len(all_predictions)} detections")


if __name__ == "__main__":
    main()
