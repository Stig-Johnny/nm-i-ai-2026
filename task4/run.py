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


def nms(boxes, scores, iou_thresh=0.5):
    """Non-Maximum Suppression. boxes: Nx4 (x1,y1,x2,y2), scores: N."""
    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0, xx2 - xx1)
        h = np.maximum(0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        mask = iou <= iou_thresh
        order = order[1:][mask]

    return keep


def postprocess(output, orig_w, orig_h, scale, pad_x, pad_y, conf_thresh=0.5, iou_thresh=0.5):
    """Parse YOLOv8 ONNX output [1, 5, 8400] to bounding boxes with NMS."""
    preds = output[0]  # [1, 5, 8400] or [5, 8400]

    if len(preds.shape) == 3:
        preds = preds[0]  # [5, 8400]

    # preds shape: [4+nc, 8400] → transpose to [8400, 4+nc]
    if preds.shape[0] < preds.shape[1]:
        preds = preds.T  # [8400, 5]

    boxes_cxcywh = preds[:, :4]
    scores = preds[:, 4:]
    max_scores = scores.max(axis=1)

    # Filter by confidence
    mask = max_scores >= conf_thresh
    boxes_cxcywh = boxes_cxcywh[mask]
    max_scores = max_scores[mask]
    cls_ids = scores[mask].argmax(axis=1)

    if len(boxes_cxcywh) == 0:
        return []

    # Convert cxcywh to x1y1x2y2 in original image coords
    cx, cy, bw, bh = boxes_cxcywh[:, 0], boxes_cxcywh[:, 1], boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]
    x1 = (cx - bw / 2 - pad_x) / scale
    y1 = (cy - bh / 2 - pad_y) / scale
    x2 = (cx + bw / 2 - pad_x) / scale
    y2 = (cy + bh / 2 - pad_y) / scale

    # Clamp
    x1 = np.clip(x1, 0, orig_w)
    y1 = np.clip(y1, 0, orig_h)
    x2 = np.clip(x2, 0, orig_w)
    y2 = np.clip(y2, 0, orig_h)

    boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

    # NMS
    keep = nms(boxes_xyxy, max_scores, iou_thresh)

    results = []
    for i in keep:
        bx1, by1, bx2, by2 = boxes_xyxy[i]
        w = bx2 - bx1
        h = by2 - by1
        if w > 2 and h > 2:
            results.append({
                "bbox": [round(float(bx1), 1), round(float(by1), 1),
                         round(float(w), 1), round(float(h), 1)],
                "category_id": int(cls_ids[i]),
                "confidence": round(float(max_scores[i]), 4)
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
