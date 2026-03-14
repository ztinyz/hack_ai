"""
Verify the merged dataset: check image/label counts, class distribution, mismatches.

Usage:
    python scripts/verify_dataset.py
"""

from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "data" / "merged"

CLASS_NAMES = {0: "Military Vehicle", 1: "Civilian Vehicle"}


def verify_split(split: str):
    img_dir = DST / "images" / split
    lbl_dir = DST / "labels" / split

    imgs = {p.stem for p in img_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tif")} if img_dir.exists() else set()
    lbls = {p.stem for p in lbl_dir.glob("*.txt")} if lbl_dir.exists() else set()

    missing_labels = imgs - lbls
    missing_images = lbls - imgs

    class_counts: Counter = Counter()
    box_total = 0
    for txt in sorted(lbl_dir.glob("*.txt")):
        for line in txt.read_text().strip().splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                class_counts[int(parts[0])] += 1
                box_total += 1

    print(f"\n=== {split.upper()} ===")
    print(f"  Images: {len(imgs)}")
    print(f"  Labels: {len(lbls)}")
    print(f"  Total boxes: {box_total}")
    for cls_id in sorted(class_counts):
        name = CLASS_NAMES.get(cls_id, f"Unknown({cls_id})")
        print(f"    {name} (id={cls_id}): {class_counts[cls_id]}")

    if missing_labels:
        print(f"  ⚠ Images without labels ({len(missing_labels)}): {list(missing_labels)[:5]}...")
    if missing_images:
        print(f"  ⚠ Labels without images ({len(missing_images)}): {list(missing_images)[:5]}...")
    if not missing_labels and not missing_images:
        print("  ✓ All images have matching labels")


def main():
    print(f"Dataset root: {DST}")
    for split in ("train", "val"):
        verify_split(split)
    print()


if __name__ == "__main__":
    main()
