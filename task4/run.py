"""
NorgesGruppen Grocery Shelf Object Detection
"""

import json
import argparse
from pathlib import Path
from ultralytics import YOLO


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
    results_list = []

    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )

    for img_path in image_files:
        results = model(str(img_path), verbose=False)
        predictions = []
        for r in results:
            if r.boxes is not None:
                for i in range(len(r.boxes)):
                    x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                    predictions.append({
                        "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                        "category_id": int(r.boxes.cls[i]),
                        "confidence": round(float(r.boxes.conf[i]), 4)
                    })
        results_list.append({
            "image_name": img_path.name,
            "predictions": predictions
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results_list, f)

    print(f"Done: {len(results_list)} images, {sum(len(r['predictions']) for r in results_list)} detections")


if __name__ == "__main__":
    main()
