"""
NorgesGruppen Grocery Shelf Object Detection — ONNX Runtime
No banned imports (no os, sys, subprocess, pickle, shutil, etc.)
"""

import json
import argparse
import numpy as np
from pathlib import Path

import onnxruntime as ort
from PIL import Image


def preprocess(img_path, imgsz=640):
    """Load and preprocess image for YOLOv8 ONNX model."""
    img = Image.open(str(img_path)).convert("RGB")
    orig_w, orig_h = img.size

    # Resize with letterbox
    scale = min(imgsz / orig_w, imgsz / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    img_resized = img.resize((new_w, new_h), Image.BILINEAR)

    # Pad to imgsz x imgsz
    canvas = Image.new("RGB", (imgsz, imgsz), (114, 114, 114))
    pad_x = (imgsz - new_w) // 2
    pad_y = (imgsz - new_h) // 2
    canvas.paste(img_resized, (pad_x, pad_y))

    # Convert to float32 NCHW tensor [0, 1]
    arr = np.array(canvas, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)  # HWC → CHW
    arr = np.expand_dims(arr, 0)  # add batch dim

    return arr, orig_w, orig_h, scale, pad_x, pad_y


def postprocess(output, orig_w, orig_h, scale, pad_x, pad_y, conf_thresh=0.25):
    """Parse YOLOv8 ONNX output to bounding boxes.

    YOLOv8 ONNX output shape: [1, num_classes+4, num_detections]
    First 4 rows: cx, cy, w, h (in input image coords)
    Remaining rows: class confidences
    """
    predictions = output[0]  # [num_classes+4, num_detections]

    if predictions.shape[0] > predictions.shape[1]:
        predictions = predictions.T  # transpose if needed

    num_detections = predictions.shape[1] if len(predictions.shape) == 2 else predictions.shape[0]

    # Handle different output formats
    if len(predictions.shape) == 3:
        predictions = predictions[0]  # remove batch dim

    # predictions shape: [4+nc, num_boxes] or [num_boxes, 4+nc]
    if predictions.shape[0] < predictions.shape[1]:
        predictions = predictions.T  # → [num_boxes, 4+nc]

    boxes = predictions[:, :4]  # cx, cy, w, h
    scores = predictions[:, 4:]  # class scores

    results = []
    for i in range(len(boxes)):
        max_score = float(scores[i].max())
        if max_score < conf_thresh:
            continue

        cls_id = int(scores[i].argmax())
        cx, cy, bw, bh = boxes[i]

        # Convert from model coords to original image coords
        x1 = (cx - bw / 2 - pad_x) / scale
        y1 = (cy - bh / 2 - pad_y) / scale
        w = bw / scale
        h = bh / scale

        # Clamp to image bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        w = min(w, orig_w - x1)
        h = min(h, orig_h - y1)

        if w > 2 and h > 2:
            results.append({
                "bbox": [round(float(x1), 1), round(float(y1), 1),
                         round(float(w), 1), round(float(h), 1)],
                "category_id": cls_id,
                "confidence": round(max_score, 4)
            })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)
    script_dir = Path(__file__).parent
    model_path = script_dir / "best.onnx"

    # Load ONNX model
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession(str(model_path), providers=providers)
    input_name = session.get_inputs()[0].name

    results_list = []
    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )

    print(f"Processing {len(image_files)} images with ONNX Runtime...")

    for img_path in image_files:
        tensor, orig_w, orig_h, scale, pad_x, pad_y = preprocess(img_path)
        output = session.run(None, {input_name: tensor})
        preds = postprocess(output[0], orig_w, orig_h, scale, pad_x, pad_y)

        results_list.append({
            "image_name": img_path.name,
            "predictions": preds
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results_list, f)

    total = sum(len(r["predictions"]) for r in results_list)
    print(f"Done: {len(results_list)} images, {total} detections")


if __name__ == "__main__":
    main()
