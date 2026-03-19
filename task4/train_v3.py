"""
Train YOLOv8m at imgsz=1280 for maximum NorgesGruppen score.
Target: detection + classification to beat top teams.
"""

import json
import shutil
from pathlib import Path
from ultralytics import YOLO

COCO_DIR = Path("data/coco/train")
YOLO_DIR = Path("data/yolo_v3")


def coco_to_yolo():
    with open(COCO_DIR / "annotations.json") as f:
        coco = json.load(f)

    img_anns = {}
    for ann in coco["annotations"]:
        img_anns.setdefault(ann["image_id"], []).append(ann)

    for split in ["train", "val"]:
        (YOLO_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    images = list(coco["images"])
    # Use 85/15 split for more training data
    split_idx = int(len(images) * 0.85)

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
    nc = coco_to_yolo()

    yaml_path = YOLO_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {YOLO_DIR.resolve()}\ntrain: train/images\nval: val/images\nnc: {nc}\nnames: {list(range(nc))}\n")

    # YOLOv8m — 25.9M params, much more capacity
    model = YOLO("yolov8m.pt")
    model.train(
        data=str(yaml_path),
        epochs=200,
        imgsz=1280,        # Large images for small product detection
        batch=4,            # Smaller batch for larger images + model
        device="mps",
        workers=4,
        patience=30,        # More patience for slow convergence
        save=True,
        project="task4/runs",
        name="v3_medium_1280",
        exist_ok=True,
        # Augmentation tuned for grocery shelves
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.15,
        degrees=3.0,        # Slight rotation only
        scale=0.5,
        fliplr=0.5,
        flipud=0.0,         # No vertical flip (shelves don't flip)
        hsv_h=0.01,
        hsv_s=0.4,
        hsv_v=0.3,
        translate=0.1,
        perspective=0.0001,
        close_mosaic=20,     # Disable mosaic last 20 epochs for fine-tuning
    )

    best = Path("task4/runs/v3_medium_1280/weights/best.pt")
    if best.exists():
        shutil.copy2(best, "task4/best_v3.pt")
        size_mb = best.stat().st_size / 1e6
        print(f"Best weights: task4/best_v3.pt ({size_mb:.1f}MB)")

        # Export to ONNX
        best_model = YOLO(str(best))
        best_model.export(format="onnx", imgsz=1280)
        onnx = best.with_suffix(".onnx")
        if onnx.exists():
            shutil.copy2(onnx, "task4/best_v3.onnx")
            print(f"ONNX: task4/best_v3.onnx ({onnx.stat().st_size/1e6:.1f}MB)")


if __name__ == "__main__":
    train()
