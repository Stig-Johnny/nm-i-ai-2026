"""
Train YOLOv8s (small) with full 356 classes on NorgesGruppen data.
Better augmentation, larger model, more epochs.

v1 was single-class YOLOv8n — detection only, mAP50=0.82 (val)
v2 aims for detection + classification with a bigger model
"""

import json
import shutil
from pathlib import Path
from ultralytics import YOLO

COCO_DIR = Path("data/coco/train")
YOLO_DIR = Path("data/yolo_v2")


def coco_to_yolo_multiclass():
    """Convert COCO to YOLO format with all 356 classes."""
    with open(COCO_DIR / "annotations.json") as f:
        coco = json.load(f)

    img_anns = {}
    for ann in coco["annotations"]:
        img_anns.setdefault(ann["image_id"], []).append(ann)

    for split in ["train", "val"]:
        (YOLO_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    images = list(coco["images"])
    split_idx = int(len(images) * 0.9)

    for split_name, split_images in [("train", images[:split_idx]), ("val", images[split_idx:])]:
        for img in split_images:
            fname = img["file_name"]
            w, h = img["width"], img["height"]

            src = COCO_DIR / "images" / fname
            dst = YOLO_DIR / split_name / "images" / fname
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

            label_file = YOLO_DIR / split_name / "labels" / (Path(fname).stem + ".txt")
            with open(label_file, "w") as lf:
                for ann in img_anns.get(img["id"], []):
                    cat_id = ann["category_id"]
                    bx, by, bw, bh = ann["bbox"]
                    cx = (bx + bw / 2) / w
                    cy = (by + bh / 2) / h
                    lf.write(f"{cat_id} {cx:.6f} {cy:.6f} {bw/w:.6f} {bh/h:.6f}\n")

    print(f"Train: {split_idx}, Val: {len(images)-split_idx}")
    return len(coco["categories"])


def train():
    nc = coco_to_yolo_multiclass()

    yaml_path = YOLO_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {YOLO_DIR.resolve()}\ntrain: train/images\nval: val/images\nnc: {nc}\nnames: {list(range(nc))}\n")

    # YOLOv8s — 2x bigger than nano, much better accuracy
    model = YOLO("yolov8s.pt")
    model.train(
        data=str(yaml_path),
        epochs=100,
        imgsz=640,
        batch=8,       # smaller batch for larger model
        device="mps",
        workers=4,
        patience=20,
        save=True,
        project="task4/runs",
        name="v2_multiclass",
        exist_ok=True,
        # Better augmentation
        mosaic=1.0,
        mixup=0.1,
        copy_paste=0.1,
        degrees=5.0,
        scale=0.5,
        fliplr=0.5,
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.3,
    )

    best = Path("task4/runs/v2_multiclass/weights/best.pt")
    if best.exists():
        # Export to ONNX
        best_model = YOLO(str(best))
        best_model.export(format="onnx")
        onnx_path = best.with_suffix(".onnx")
        if onnx_path.exists():
            shutil.copy2(onnx_path, "task4/best_v2.onnx")
            print(f"ONNX exported: task4/best_v2.onnx ({onnx_path.stat().st_size/1e6:.1f}MB)")
        shutil.copy2(best, "task4/best_v2.pt")
        print(f"Weights: task4/best_v2.pt ({best.stat().st_size/1e6:.1f}MB)")


if __name__ == "__main__":
    train()
