"""
Train YOLOv8 for detection-only (single class) on NorgesGruppen data.

Detection is 70% of the score. With 248 images and 356 categories,
classification is too hard for YOLOv8n. Train single-class "product"
detection first to maximize the 70% detection score.

Usage:
    python task4/train_detection.py
"""

import json
import shutil
from pathlib import Path

COCO_DIR = Path("data/coco/train")
YOLO_DIR = Path("data/yolo_detection")
ANNOTATIONS = COCO_DIR / "annotations.json"
IMAGES_DIR = COCO_DIR / "images"


def coco_to_yolo_single_class():
    """Convert COCO annotations to YOLO format with single class (0 = product)."""
    with open(ANNOTATIONS) as f:
        coco = json.load(f)

    img_info = {img["id"]: img for img in coco["images"]}
    img_anns = {}
    for ann in coco["annotations"]:
        img_id = ann["image_id"]
        if img_id not in img_anns:
            img_anns[img_id] = []
        img_anns[img_id].append(ann)

    for split in ["train", "val"]:
        (YOLO_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    images = list(coco["images"])
    split_idx = int(len(images) * 0.9)
    train_imgs = images[:split_idx]
    val_imgs = images[split_idx:]

    for split_name, split_images in [("train", train_imgs), ("val", val_imgs)]:
        for img in split_images:
            img_id = img["id"]
            fname = img["file_name"]
            w, h = img["width"], img["height"]

            src = IMAGES_DIR / fname
            dst = YOLO_DIR / split_name / "images" / fname
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

            anns = img_anns.get(img_id, [])
            label_file = YOLO_DIR / split_name / "labels" / (Path(fname).stem + ".txt")
            with open(label_file, "w") as lf:
                for ann in anns:
                    bx, by, bw, bh = ann["bbox"]
                    cx = (bx + bw / 2) / w
                    cy = (by + bh / 2) / h
                    nw = bw / w
                    nh = bh / h
                    # All products are class 0
                    lf.write(f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n")

    print(f"Converted: {len(train_imgs)} train, {len(val_imgs)} val (single class)")
    return 1  # single class


def train():
    from ultralytics import YOLO

    num_classes = coco_to_yolo_single_class()

    yaml_content = f"""path: {YOLO_DIR.resolve()}
train: train/images
val: val/images

nc: {num_classes}
names: ['product']
"""
    yaml_path = YOLO_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(yaml_content)

    model = YOLO("yolov8n.pt")
    model.train(
        data=str(yaml_path),
        epochs=80,
        imgsz=640,
        batch=16,
        device="mps",
        workers=4,
        patience=15,
        save=True,
        project="task4/runs",
        name="detection",
        exist_ok=True,
    )

    best = Path("task4/runs/detection/weights/best.pt")
    if best.exists():
        shutil.copy2(best, "task4/best_detection.pt")
        print(f"Best weights: task4/best_detection.pt ({best.stat().st_size / 1e6:.1f}MB)")


if __name__ == "__main__":
    train()
