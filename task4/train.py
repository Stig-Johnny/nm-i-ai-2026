"""
Train YOLOv8 on NorgesGruppen grocery shelf data.

Converts COCO annotations to YOLO format, splits into train/val, trains YOLOv8n.

Usage:
    python task4/train.py
"""

import json
import shutil
from pathlib import Path

# Paths
COCO_DIR = Path("data/coco/train")
YOLO_DIR = Path("data/yolo")
ANNOTATIONS = COCO_DIR / "annotations.json"
IMAGES_DIR = COCO_DIR / "images"


def coco_to_yolo():
    """Convert COCO annotations to YOLO format."""
    with open(ANNOTATIONS) as f:
        coco = json.load(f)

    # Image dimensions lookup
    img_info = {img["id"]: img for img in coco["images"]}

    # Group annotations by image
    img_anns = {}
    for ann in coco["annotations"]:
        img_id = ann["image_id"]
        if img_id not in img_anns:
            img_anns[img_id] = []
        img_anns[img_id].append(ann)

    # Create YOLO directories
    for split in ["train", "val"]:
        (YOLO_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    # Split: 90% train, 10% val
    images = list(coco["images"])
    split_idx = int(len(images) * 0.9)
    train_imgs = images[:split_idx]
    val_imgs = images[split_idx:]

    for split_name, split_images in [("train", train_imgs), ("val", val_imgs)]:
        for img in split_images:
            img_id = img["id"]
            fname = img["file_name"]
            w, h = img["width"], img["height"]

            # Copy image
            src = IMAGES_DIR / fname
            dst = YOLO_DIR / split_name / "images" / fname
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

            # Convert annotations to YOLO format
            anns = img_anns.get(img_id, [])
            label_file = YOLO_DIR / split_name / "labels" / (Path(fname).stem + ".txt")
            with open(label_file, "w") as lf:
                for ann in anns:
                    cat_id = ann["category_id"]
                    bx, by, bw, bh = ann["bbox"]  # COCO: x,y,w,h (top-left)
                    # Convert to YOLO: cx, cy, w, h (center, normalized)
                    cx = (bx + bw / 2) / w
                    cy = (by + bh / 2) / h
                    nw = bw / w
                    nh = bh / h
                    lf.write(f"{cat_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n")

    print(f"Converted: {len(train_imgs)} train, {len(val_imgs)} val")
    return len(coco["categories"])


def create_dataset_yaml(num_classes):
    """Create YOLO dataset config."""
    yaml_content = f"""path: {YOLO_DIR.resolve()}
train: train/images
val: val/images

nc: {num_classes}
names: {list(range(num_classes))}
"""
    yaml_path = YOLO_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(yaml_content)
    print(f"Dataset YAML: {yaml_path}")
    return yaml_path


def train():
    from ultralytics import YOLO

    # Convert COCO to YOLO format
    num_classes = coco_to_yolo()
    yaml_path = create_dataset_yaml(num_classes)

    # Train YOLOv8n (smallest, fastest)
    model = YOLO("yolov8n.pt")
    results = model.train(
        data=str(yaml_path),
        epochs=50,
        imgsz=640,
        batch=8,
        device="mps",  # Apple Silicon GPU
        workers=4,
        patience=10,
        save=True,
        project="task4/runs",
        name="grocery",
        exist_ok=True,
    )

    # Copy best weights
    best = Path("task4/runs/grocery/weights/best.pt")
    if best.exists():
        shutil.copy2(best, "task4/best.pt")
        print(f"Best weights: task4/best.pt ({best.stat().st_size / 1e6:.1f}MB)")
    else:
        print("No best.pt found — check training logs")


if __name__ == "__main__":
    train()
