"""
NorgesGruppen — SAHI Tiled Inference + Multi-Resolution Fusion
Slices images into overlapping tiles at native resolution for small object detection.
Merges with Weighted Box Fusion.
"""

import json
import argparse
import numpy as np
from pathlib import Path

import onnxruntime as ort
from PIL import Image


def preprocess_tile(img_crop, imgsz):
    """Preprocess a PIL image crop for ONNX inference."""
    orig_w, orig_h = img_crop.size
    scale = min(imgsz / orig_w, imgsz / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    img_resized = img_crop.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (imgsz, imgsz), (114, 114, 114))
    pad_x = (imgsz - new_w) // 2
    pad_y = (imgsz - new_h) // 2
    canvas.paste(img_resized, (pad_x, pad_y))
    arr = np.array(canvas, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis]
    return arr, scale, pad_x, pad_y


def nms(boxes, scores, iou_thresh=0.5):
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
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
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= iou_thresh]
    return keep


def decode_predictions(output, tile_w, tile_h, scale, pad_x, pad_y,
                       offset_x, offset_y, conf_thresh=0.001):
    """Decode ONNX output for one tile, offset boxes to full image coords."""
    preds = output[0]
    if len(preds.shape) == 3:
        preds = preds[0]
    if preds.shape[0] < preds.shape[1]:
        preds = preds.T

    boxes_cxcywh = preds[:, :4]
    scores = preds[:, 4:]
    max_scores = scores.max(axis=1)

    mask = max_scores >= conf_thresh
    boxes_cxcywh = boxes_cxcywh[mask]
    max_scores = max_scores[mask]
    cls_ids = scores[mask].argmax(axis=1)

    if len(boxes_cxcywh) == 0:
        return [], [], []

    cx, cy, bw, bh = boxes_cxcywh[:, 0], boxes_cxcywh[:, 1], boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]
    # Convert to tile-local coords
    x1 = (cx - bw / 2 - pad_x) / scale
    y1 = (cy - bh / 2 - pad_y) / scale
    x2 = (cx + bw / 2 - pad_x) / scale
    y2 = (cy + bh / 2 - pad_y) / scale

    # Offset to full image coords
    x1 = x1 + offset_x
    y1 = y1 + offset_y
    x2 = x2 + offset_x
    y2 = y2 + offset_y

    boxes = np.stack([x1, y1, x2, y2], axis=1)
    return boxes, max_scores, cls_ids


def generate_tiles(img_w, img_h, tile_size=640, overlap=0.2):
    """Generate overlapping tile positions for SAHI-style inference."""
    step = int(tile_size * (1 - overlap))
    tiles = []
    for y in range(0, img_h, step):
        for x in range(0, img_w, step):
            x2 = min(x + tile_size, img_w)
            y2 = min(y + tile_size, img_h)
            x1 = max(0, x2 - tile_size)
            y1 = max(0, y2 - tile_size)
            tiles.append((x1, y1, x2, y2))
    # Deduplicate
    return list(dict.fromkeys(tiles))


def run_tiled_inference(session_full, session_tile, input_name, img,
                       full_imgsz=1280, tile_imgsz=640, tile_size=640, overlap=0.2, conf=0.001):
    """Run SAHI-style tiled inference: full image @1280 + tiles @640."""
    img_w, img_h = img.size
    all_boxes = []
    all_scores = []
    all_classes = []

    # Pass 1: Full image at 1280
    arr, scale, pad_x, pad_y = preprocess_tile(img, full_imgsz)
    output = session_full.run(None, {input_name: arr})
    boxes, scores, cls_ids = decode_predictions(
        output, img_w, img_h, scale, pad_x, pad_y, 0, 0, conf)
    if len(boxes) > 0:
        all_boxes.append(boxes)
        all_scores.append(scores)
        all_classes.append(cls_ids)

    # Pass 2: Tiled inference at native resolution
    tiles = generate_tiles(img_w, img_h, tile_size, overlap)
    for (tx1, ty1, tx2, ty2) in tiles:
        crop = img.crop((tx1, ty1, tx2, ty2))
        crop_w, crop_h = crop.size
        if crop_w < 32 or crop_h < 32:
            continue

        arr, scale, pad_x, pad_y = preprocess_tile(crop, tile_imgsz)
        output = session_tile.run(None, {input_name: arr})
        boxes, scores, cls_ids = decode_predictions(
            output, crop_w, crop_h, scale, pad_x, pad_y, tx1, ty1, conf)
        if len(boxes) > 0:
            all_boxes.append(boxes)
            all_scores.append(scores)
            all_classes.append(cls_ids)

    if not all_boxes:
        return []

    # Merge all detections
    merged_boxes = np.concatenate(all_boxes)
    merged_scores = np.concatenate(all_scores)
    merged_classes = np.concatenate(all_classes)

    # Clamp to image bounds
    merged_boxes[:, 0] = np.clip(merged_boxes[:, 0], 0, img_w)
    merged_boxes[:, 1] = np.clip(merged_boxes[:, 1], 0, img_h)
    merged_boxes[:, 2] = np.clip(merged_boxes[:, 2], 0, img_w)
    merged_boxes[:, 3] = np.clip(merged_boxes[:, 3], 0, img_h)

    # NMS on merged detections
    keep = nms(merged_boxes, merged_scores, iou_thresh=0.5)

    results = []
    for i in keep:
        x1, y1, x2, y2 = merged_boxes[i]
        w = x2 - x1
        h = y2 - y1
        if w > 1 and h > 1:
            results.append({
                "bbox": [round(float(x1), 1), round(float(y1), 1),
                         round(float(w), 1), round(float(h), 1)],
                "category_id": int(merged_classes[i]),
                "score": round(float(merged_scores[i]), 3)
            })
    return results


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
    model_1280 = script_dir / "best_1280.onnx"
    model_640 = script_dir / "best_640.onnx"

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    session_full = ort.InferenceSession(str(model_1280), providers=providers)
    session_tile = ort.InferenceSession(str(model_640), providers=providers)
    input_name = session_full.get_inputs()[0].name

    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
    )

    all_predictions = []

    for img_path in image_files:
        img_id = image_id_from_filename(img_path.name)
        img = Image.open(str(img_path)).convert("RGB")

        preds = run_tiled_inference(
            session_full, session_tile, input_name, img,
            full_imgsz=1280,
            tile_imgsz=640,
            tile_size=640,
            overlap=0.2,
            conf=0.001
        )

        for p in preds:
            p["image_id"] = img_id
            all_predictions.append(p)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(all_predictions, f)

    print(f"Done: {len(image_files)} images, {len(all_predictions)} detections")


if __name__ == "__main__":
    main()
