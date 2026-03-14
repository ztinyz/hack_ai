"""
YOLOv11 — Military Vehicle Detection Training Script

Designed for Google Colab (or any GPU environment).
Trains YOLOv11m to detect Military Vehicles and Civilian Vehicles in aerial imagery.

Usage:
    python scripts/train.py [--data PATH] [--epochs N] [--batch N] [--model MODEL] [--imgsz N]
"""

import argparse
import glob
from pathlib import Path

import torch
from ultralytics import YOLO


def check_gpu():
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("WARNING: No GPU detected — training will be very slow")


def train(args):
    print("\n=== Training ===")
    model = YOLO(args.model)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=20,
        project=args.project,
        name=args.name,
        exist_ok=True,
    )
    return model


def validate(model):
    print("\n=== Validation ===")
    metrics = model.val()
    print(f"mAP50:    {metrics.box.map50:.4f}")
    print(f"mAP50-95: {metrics.box.map:.4f}")
    print("\nPer-class AP50:")
    for i, name in enumerate(["Military Vehicle", "Civilian Vehicle"]):
        print(f"  {name}: {metrics.box.ap50[i]:.4f}")
    return metrics


def predict_demo(model, data_path, project, name):
    print("\n=== Inference Demo ===")
    val_dir = Path(data_path).parent / "images" / "val"
    val_images = sorted(glob.glob(str(val_dir / "*.jpg")))[:6]
    if not val_images:
        print("No val images found for demo, skipping")
        return
    model.predict(val_images, save=True, project=project, name=f"{name}_predict", exist_ok=True)
    print(f"Saved predictions for {len(val_images)} images")


def export_model(model):
    print("\n=== Export ===")
    model.export(format="onnx")
    print("ONNX export complete")


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv11 for military vehicle detection")
    parser.add_argument("--data", default="/content/data/merged/dataset.yaml",
                        help="Path to dataset.yaml")
    parser.add_argument("--model", default="yolo11m.pt",
                        help="Pretrained model (yolo11n/s/m/l/x.pt)")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16,
                        help="Batch size (use 8 if OOM on free Colab)")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--project", default="/content/runs")
    parser.add_argument("--name", default="military_v1")
    parser.add_argument("--skip-train", action="store_true",
                        help="Skip training, load existing weights for eval/export")
    parser.add_argument("--no-export", action="store_true",
                        help="Skip ONNX export")
    args = parser.parse_args()

    check_gpu()

    if args.skip_train:
        weights = Path(args.project) / args.name / "weights" / "best.pt"
        print(f"\nLoading existing weights: {weights}")
        model = YOLO(str(weights))
    else:
        model = train(args)

    validate(model)
    predict_demo(model, args.data, args.project, args.name)

    if not args.no_export:
        export_model(model)

    print("\n✓ Done")


if __name__ == "__main__":
    main()
