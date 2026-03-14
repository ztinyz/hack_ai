"""
Remap MVRSD 5-class labels to 2-class (Military Vehicle / Civilian Vehicle).

Mapping:
  0 (SMV) → 0 (Military Vehicle)
  1 (LMV) → 0 (Military Vehicle)
  2 (AFV) → 0 (Military Vehicle)
  3 (CV)  → 1 (Civilian Vehicle)
  4 (MCV) → 0 (Military Vehicle)

Usage:
    python scripts/remap_classes.py
"""

import shutil
from pathlib import Path

CLASS_MAP = {0: 0, 1: 0, 2: 0, 3: 1, 4: 0}

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "mvrsd" / "MVRSD_dataset" / "data"
DST = ROOT / "data" / "merged"


def remap_labels(src_dir: Path, dst_dir: Path) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for txt in sorted(src_dir.glob("*.txt")):
        lines_out = []
        for line in txt.read_text().strip().splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            cls_id = int(parts[0])
            new_cls = CLASS_MAP.get(cls_id, cls_id)
            lines_out.append(f"{new_cls} {' '.join(parts[1:])}")
        (dst_dir / txt.name).write_text("\n".join(lines_out) + "\n")
        count += 1
    return count


def copy_images(src_dir: Path, dst_dir: Path) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for img in sorted(src_dir.iterdir()):
        if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tif"):
            shutil.copy2(img, dst_dir / img.name)
            count += 1
    return count


def write_dataset_yaml():
    yaml_content = (
        "# YOLO dataset config — update 'path' for your environment\n"
        "# Colab: /content/data/merged\n"
        "# Local: adjust to absolute path of data/merged/\n\n"
        "path: /content/data/merged\n"
        "train: images/train\n"
        "val: images/val\n\n"
        "names:\n"
        "  0: Military Vehicle\n"
        "  1: Civilian Vehicle\n"
    )
    DST.mkdir(parents=True, exist_ok=True)
    yaml_path = DST / "dataset.yaml"
    yaml_path.write_text(yaml_content)
    print(f"Created {yaml_path}")


def main():
    for split in ("train", "val"):
        lbl_count = remap_labels(SRC / "labels" / split, DST / "labels" / split)
        img_count = copy_images(SRC / "images" / split, DST / "images" / split)
        print(f"[{split}] labels: {lbl_count}, images: {img_count}")

    write_dataset_yaml()
    print(f"\nOutput written to: {DST}")
    print("Done.")


if __name__ == "__main__":
    main()
