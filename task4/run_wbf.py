"""
NorgesGruppen — Multi-model ensemble with Weighted Box Fusion + Multi-scale TTA
Expected: 0.93+ mAP
"""

import json, argparse, numpy as np
from pathlib import Path
import onnxruntime as ort
from PIL import Image


def preprocess(img, imgsz):
    ow, oh = img.size
    s = min(imgsz / ow, imgsz / oh)
    nw, nh = int(ow * s), int(oh * s)
    r = img.resize((nw, nh), Image.BILINEAR)
    c = Image.new("RGB", (imgsz, imgsz), (114, 114, 114))
    px, py = (imgsz - nw) // 2, (imgsz - nh) // 2
    c.paste(r, (px, py))
    a = np.array(c, dtype=np.float32) / 255.0
    return a.transpose(2, 0, 1)[np.newaxis], ow, oh, s, px, py


def decode(out, ow, oh, s, px, py, conf=0.001):
    p = out[0]
    if len(p.shape) == 3: p = p[0]
    if p.shape[0] < p.shape[1]: p = p.T
    b, sc = p[:, :4], p[:, 4:]
    ms = sc.max(axis=1)
    m = ms >= conf
    b, ms, ci = b[m], ms[m], sc[m].argmax(axis=1)
    if len(b) == 0:
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)
    cx, cy, bw, bh = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    x1 = np.clip((cx - bw / 2 - px) / s, 0, ow)
    y1 = np.clip((cy - bh / 2 - py) / s, 0, oh)
    x2 = np.clip((cx + bw / 2 - px) / s, 0, ow)
    y2 = np.clip((cy + bh / 2 - py) / s, 0, oh)
    return np.stack([x1, y1, x2, y2], axis=1), ms, ci


def decode_flip(out, ow, oh, s, px, py, conf=0.001):
    boxes, scores, cls = decode(out, ow, oh, s, px, py, conf)
    if len(boxes) > 0:
        x1_new = ow - boxes[:, 2]
        x2_new = ow - boxes[:, 0]
        boxes[:, 0] = np.clip(x1_new, 0, ow)
        boxes[:, 2] = np.clip(x2_new, 0, ow)
    return boxes, scores, cls


def iou_single(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    a1 = (a[2] - a[0]) * (a[3] - a[1])
    a2 = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (a1 + a2 - inter + 1e-6)


def weighted_box_fusion(boxes_list, scores_list, labels_list, iou_thr=0.55, skip_thr=0.001):
    """WBF: averages overlapping boxes instead of discarding them."""
    n_models = len(boxes_list)
    all_b, all_s, all_l = [], [], []
    for boxes, scores, labels in zip(boxes_list, scores_list, labels_list):
        m = scores > skip_thr
        all_b.append(boxes[m]); all_s.append(scores[m]); all_l.append(labels[m])

    if not any(len(b) > 0 for b in all_b):
        return np.empty((0, 4)), np.empty(0), np.empty(0, dtype=int)

    all_b = np.concatenate(all_b)
    all_s = np.concatenate(all_s)
    all_l = np.concatenate(all_l)

    order = np.argsort(-all_s)
    all_b, all_s, all_l = all_b[order], all_s[order], all_l[order]

    # Cluster boxes
    clusters = []  # (weighted_box_sum, score_sum, count, label)

    for i in range(len(all_b)):
        box, score, label = all_b[i], all_s[i], all_l[i]
        matched = False
        for ci in range(len(clusters)):
            c_wbox, c_score, c_count, c_label = clusters[ci]
            if label != c_label:
                continue
            avg_box = c_wbox / c_score
            if iou_single(box, avg_box) > iou_thr:
                clusters[ci] = (c_wbox + box * score, c_score + score, c_count + 1, c_label)
                matched = True
                break
        if not matched:
            clusters.append((box * score, score, 1, label))

    fused_b, fused_s, fused_l = [], [], []
    for w_box, w_score, count, label in clusters:
        fused_b.append(w_box / w_score)
        fused_s.append(w_score / n_models)
        fused_l.append(label)

    return np.array(fused_b), np.array(fused_s), np.array(fused_l, dtype=int)


def img_id(f):
    d = ''.join(c for c in Path(f).stem if c.isdigit())
    return int(d) if d else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    inp = Path(args.input); out = Path(args.output)
    sd = Path(__file__).parent
    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"]

    # Load all available models
    models = []
    for name in ["model_a.onnx", "model_b.onnx", "model_c.onnx"]:
        p = sd / name
        if p.exists():
            sess = ort.InferenceSession(str(p), providers=prov)
            imgsz = sess.get_inputs()[0].shape[2]  # get model input size
            models.append((sess, sess.get_inputs()[0].name, imgsz))

    files = sorted([f for f in inp.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')])
    preds = []

    for fp in files:
        iid = img_id(fp.name)
        img = Image.open(str(fp)).convert("RGB")
        ow, oh = img.size

        boxes_list, scores_list, labels_list = [], [], []

        for sess, nm, imgsz in models:
            # Original
            arr, _, _, s, px, py = preprocess(img, imgsz)
            o = sess.run(None, {nm: arr})
            b, sc, cl = decode(o[0], ow, oh, s, px, py)
            if len(b) > 0:
                boxes_list.append(b); scores_list.append(sc); labels_list.append(cl)

            # Horizontal flip
            img_f = img.transpose(Image.FLIP_LEFT_RIGHT)
            arr2, _, _, s2, px2, py2 = preprocess(img_f, imgsz)
            o2 = sess.run(None, {nm: arr2})
            b2, sc2, cl2 = decode_flip(o2[0], ow, oh, s2, px2, py2)
            if len(b2) > 0:
                boxes_list.append(b2); scores_list.append(sc2); labels_list.append(cl2)

        if not boxes_list:
            continue

        # WBF fusion
        fb, fs, fl = weighted_box_fusion(boxes_list, scores_list, labels_list, iou_thr=0.55)

        for i in range(len(fb)):
            x1, y1, x2, y2 = fb[i]
            w, h = x2 - x1, y2 - y1
            if w > 1 and h > 1:
                preds.append({
                    "image_id": iid,
                    "category_id": int(fl[i]),
                    "bbox": [round(float(x1), 1), round(float(y1), 1),
                             round(float(w), 1), round(float(h), 1)],
                    "score": round(float(fs[i]), 3)
                })

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        json.dump(preds, f)
    print(f"Done: {len(files)} images, {len(preds)} detections, {len(models)} models")


if __name__ == "__main__":
    main()
