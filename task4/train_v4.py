"""
Train YOLOv8m at imgsz=640 — overnight run on MPS.
v3 at 1280 was 93s/batch = 266 hours. This should be ~5-10 hours.
"""

import json
import shutil
from pathlib import Path
from ultralytics import YOLO

COCO_DIR = Path("data/coco/train")
YOLO_DIR = Path("data/yolo_v3")  # reuse v3 data dir


def setup_data():
    if (YOLO_DIR / "train" / "images").exists():
        print("Data already prepared")
        return

    with open(COCO_DIR / "annotations.json") as f:
        coco = json.load(f)

    img_anns = {}
    for ann in coco["annotations"]:
        img_anns.setdefault(ann["image_id"], []).append(ann)

    for split in ["train", "val"]:
        (YOLO_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    images = list(coco["images"])
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

    nc = len(coco["categories"])
    yaml_path = YOLO_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {YOLO_DIR.resolve()}\ntrain: train/images\nval: val/images\nnc: {nc}\nnames: {list(range(nc))}\n")
    print(f"Data ready: {split_idx} train, {len(images)-split_idx} val, {nc} classes")


def train():
    setup_data()

    model = YOLO("yolov8m.pt")
    model.train(
        data=str(YOLO_DIR / "dataset.yaml"),
        epochs=200,
        imgsz=640,
        batch=8,
        device="mps",
        workers=4,
        patience=30,
        save=True,
        project="task4/runs",
        name="v4_medium_640",
        exist_ok=True,
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.15,
        degrees=3.0,
        scale=0.5,
        fliplr=0.5,
        flipud=0.0,
        hsv_h=0.01,
        hsv_s=0.4,
        hsv_v=0.3,
        close_mosaic=20,
    )

    best = Path("task4/runs/v4_medium_640/weights/best.pt")
    if best.exists():
        shutil.copy2(best, "task4/best_v4.pt")
        print(f"Best: task4/best_v4.pt ({best.stat().st_size/1e6:.1f}MB)")

        m = YOLO(str(best))
        m.export(format="onnx")
        onnx = best.with_suffix(".onnx")
        if onnx.exists():
            shutil.copy2(onnx, "task4/best_v4.onnx")
            print(f"ONNX: task4/best_v4.onnx ({onnx.stat().st_size/1e6:.1f}MB)")


if __name__ == "__main__":
    train()
