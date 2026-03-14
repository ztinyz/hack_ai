"""
Run YOLO .pt inference on one image and print/save detections.

Usage:
  python scripts/predict_image.py \
    --model best.pt \
    --image data/scenes/scene-01.png \
    --conf 0.25 \
    --save
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def resolve_input_path(raw: str) -> Path:
    path = Path(raw)
    if path.exists():
        return path

    root_relative = ROOT / raw
    if root_relative.exists():
        return root_relative

    scenes_relative = ROOT / "data" / "scenes" / raw
    if scenes_relative.exists():
        return scenes_relative

    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YOLO inference on a single image")
    parser.add_argument("--model", default="best.pt", help="Path to YOLO .pt model")
    parser.add_argument("--image", required=True, help="Path to image file")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--save", action="store_true", help="Save annotated image to runs/predict_image")
    args = parser.parse_args()

    model_path = resolve_input_path(args.model)
    image_path = resolve_input_path(args.image)

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    try:
        ultralytics = importlib.import_module("ultralytics")
        yolo_cls = getattr(ultralytics, "YOLO")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: ultralytics. Install with `pip install ultralytics`."
        ) from exc

    model = yolo_cls(str(model_path))
    names = getattr(model, "names", {}) or {}

    results = model.predict(
        source=str(image_path),
        conf=args.conf,
        save=args.save,
        project=str(ROOT / "runs"),
        name="predict_image",
        exist_ok=True,
        verbose=False,
    )

    result = results[0]
    boxes = result.boxes

    output: dict = {
        "model": str(model_path.resolve()),
        "image": str(image_path.resolve()),
        "task": getattr(model, "task", None),
        "classNames": names,
        "detections": [],
    }

    if boxes is not None:
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls_id = int(box.cls[0]) if box.cls is not None else -1
            conf = float(box.conf[0]) if box.conf is not None else None
            class_name = names.get(cls_id, f"class-{cls_id}") if isinstance(names, dict) else f"class-{cls_id}"

            output["detections"].append(
                {
                    "id": i + 1,
                    "classId": cls_id,
                    "className": class_name,
                    "confidence": conf,
                    "xyxy": [x1, y1, x2, y2],
                    "centerXY": [(x1 + x2) / 2, (y1 + y2) / 2],
                }
            )

    print(json.dumps(output, indent=2))

    if args.save:
        print("\nSaved annotated output in runs/predict_image/")


if __name__ == "__main__":
    main()
