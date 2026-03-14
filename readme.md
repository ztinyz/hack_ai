# Military Vehicle Detection — YOLOv11

Aerial/satellite image detection of military and civilian vehicles using YOLOv11 (Ultralytics).

## Dataset

**MVRSD** — 3,000 remotely sensed images (640×640, 0.3m) from Google Earth with 32,626 annotated military vehicle targets.

Original 5 classes simplified to 2:

| Class              | Original MVRSD Classes         |
|--------------------|--------------------------------|
| Military Vehicle   | SMV, LMV, AFV, MCV             |
| Civilian Vehicle   | CV                             |

## Quick Start

### 1. Prepare Data (local)

```bash
# Remap classes and create data/merged/ with dataset.yaml
python scripts/remap_classes.py

# Verify dataset integrity
python scripts/verify_dataset.py
```

### 2. Train (Google Colab or any GPU)

```bash
# Default: trains YOLOv11m, 100 epochs, batch 16, imgsz 640
python scripts/train.py --data /content/data/merged/dataset.yaml

# Custom options
python scripts/train.py --model yolo11l.pt --epochs 150 --batch 8

# Evaluate existing weights without retraining
python scripts/train.py --skip-train --no-export
```

### 3. Inference

```python
from ultralytics import YOLO
model = YOLO("runs/military_v1/weights/best.pt")
results = model.predict("path/to/image.jpg")
```

## Project Structure

```
hack_ai/
├── data/
│   ├── mvrsd/          # Raw MVRSD dataset
│   ├── roboflow/       # (reserved for Roboflow data)
│   └── merged/         # Remapped 2-class dataset (generated)
├── notebooks/
├── scripts/
│   ├── remap_classes.py
│   ├── verify_dataset.py
│   └── train.py
├── runs/               # Training outputs
└── readme.md
```

## Data Sources

- [MVRSD (SciDB)](https://www.scidb.cn/en/detail?dataSetId=2731ac4153464495b4dfd3caa8a9b0a0)
- [Roboflow Military Vehicle Detection](https://universe.roboflow.com/odec/military-vehicle-detection-5mb9k) *(planned)*