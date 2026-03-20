# Tactical Command — Military Vehicle Detection

A full-stack geospatial intelligence application that detects military vehicles in satellite/aerial imagery using YOLOv11. Users draw an Area of Interest (AOI) on an interactive map, and the system runs real-time ML inference on matching satellite scenes to geolocate military assets — with temporal playback to visualize movement over time.

## Architecture

```
┌─────────────────────────────────┐
│  Frontend (React + Leaflet)     │  ← Tactical map UI, AOI drawing, playback
│  http://localhost:5173          │
└──────────────┬──────────────────┘
               │ POST /analyze, /playback
┌──────────────▼──────────────────┐
│  Backend (FastAPI + Uvicorn)    │  ← Scene matching, YOLO inference, geo-conversion
│  http://localhost:8000          │
├─────────────────────────────────┤
│  SQLite DB     │  YOLOv11 Model │
│  (scenes.db)   │  (best.pt)     │
└─────────────────────────────────┘
               │
┌──────────────▼──────────────────┐
│  Image Storage                  │  ← Cloudinary / GCS / local files
└─────────────────────────────────┘
```

## Images
<img width="768" height="432" alt="image" src="https://github.com/user-attachments/assets/a316a7f0-ba84-4c89-a4da-06dea87f74a8" />

<img width="768" height="432" alt="image" src="https://github.com/user-attachments/assets/0da8c179-e16e-431d-b6da-47600267516c" />

## Features

- **Interactive AOI Drawing** — Click-to-place polygon vertices on a satellite map to define a search area
- **ML-Powered Detection** — YOLOv11 inference on satellite scenes, with pixel-to-lat/lng conversion
- **Temporal Playback** — 7-day timeline with 15 frames showing detected vehicle movement over time
- **Scene Management** — SQLite metadata DB with Cloudinary and Google Cloud Storage support
- **Tactical UI** — Dark-themed command interface with telemetry readouts, compass, and status indicators

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in Cloudinary / GCS credentials if using cloud storage
python -m uvicorn main:app --reload
```

The API runs at **http://localhost:8000**.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI runs at **http://localhost:5173**.

### 3. Load Scene Data

Scenes are defined in `data/scenes/manifest.json`. Import them into the database:

```bash
# Option A: Upload local images to Cloudinary + store URLs in DB
curl -X POST http://localhost:8000/scenes/sync-manifest \
  -H "Content-Type: application/json" \
  -d '{"forceUpload": false}'

# Option B: Import URLs directly (images already hosted elsewhere)
curl -X POST http://localhost:8000/scenes/import-manifest-urls \
  -H "Content-Type: application/json" \
  -d '{"baseUrl":"https://your-bucket.example.com","pathPrefix":"scenes","overwriteExisting":true}'
```

Verify scenes are loaded:

```bash
curl http://localhost:8000/scenes
```

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/analyze` | Run YOLO inference on scenes within an AOI polygon, return geolocated detections |
| `POST` | `/playback` | Generate 15 temporal frames (7-day window) with detection movement simulation |
| `GET` | `/scenes` | List all scenes stored in the database |
| `POST` | `/scenes/sync-manifest` | Upload local scene images to Cloudinary and store in DB |
| `POST` | `/scenes/import-manifest-urls` | Import scene image URLs into DB without uploading |
| `GET` | `/model-info` | Return model path, status, task type, and class names |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `YOLO_MODEL_PATH` | `../best.pt` | Path to trained YOLO model weights |
| `SCENES_DB_PATH` | `backend/scenes.db` | SQLite database path |
| `SCENE_HTTP_CACHE_DIR` | `<tempdir>/x-scene-http-cache` | Cache for downloaded scene images |
| `CLOUDINARY_CLOUD_NAME` | — | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | — | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | — | Cloudinary API secret |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | GCP service account JSON path |
| `GCS_SIGNED_URL_TTL_MINUTES` | `60` | TTL for GCS signed URLs |

## Model Training

### Dataset

**MVRSD** — 3,000 remotely sensed images (640×640, 0.3 m/px) from Google Earth with 32,626 annotated military vehicle targets.

Original 5 classes simplified to 2:

| Class | Original MVRSD Classes |
|-------|------------------------|
| Military Vehicle | SMV, LMV, AFV, MCV |
| Civilian Vehicle | CV |

### Training Pipeline

```bash
# 1. Remap 5-class MVRSD labels to 2-class format
python scripts/remap_classes.py

# 2. Verify dataset integrity (image/label counts, class distribution)
python scripts/verify_dataset.py

# 3. Train YOLOv11m (default: 100 epochs, batch 16, 640px)
python scripts/train.py --data /content/data/merged/dataset.yaml

# Custom training
python scripts/train.py --model yolo11l.pt --epochs 150 --batch 8

# Evaluate existing weights only
python scripts/train.py --skip-train --no-export
```

A Google Colab notebook is also available at `notebooks/train_yolov11.ipynb` for GPU training with step-by-step cells (setup, training, validation, export, analysis).

### Single-Image Inference

```bash
python scripts/predict_image.py --image path/to/image.jpg --model best.pt --conf 0.25
```

## Project Structure

```
hack_ai/
├── best.pt                    # Trained YOLOv11 weights
├── yolo11m.pt                 # Pretrained base weights
├── backend/
│   ├── main.py                # FastAPI app (endpoints, YOLO inference, geo-conversion)
│   ├── requirements.txt
│   ├── .env.example
│   └── scenes.db              # SQLite scene metadata (generated)
├── frontend/
│   ├── src/
│   │   ├── App.tsx            # Main UI (map, AOI drawing, playback, detections)
│   │   ├── App.css            # Tactical theme styles
│   │   ├── main.tsx           # Entry point
│   │   └── index.css          # Base styles & CSS variables
│   ├── package.json
│   └── vite.config.ts
├── data/
│   └── scenes/
│       └── manifest.json      # Scene metadata (coordinates, timestamps, filenames)
├── scripts/
│   ├── remap_classes.py       # 5-class → 2-class label remapping
│   ├── verify_dataset.py      # Dataset integrity checker
│   ├── train.py               # YOLOv11 training CLI
│   └── predict_image.py       # Single-image inference CLI
├── notebooks/
│   └── train_yolov11.ipynb    # Colab training notebook
└── readme.md
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Leaflet, Vite |
| Backend | FastAPI, Uvicorn, SQLite |
| ML | YOLOv11 (Ultralytics), PyTorch |
| Storage | Cloudinary, Google Cloud Storage |
| Map Tiles | Esri World Imagery |

## Data Sources

- [MVRSD (SciDB)](https://www.scidb.cn/en/detail?dataSetId=2731ac4153464495b4dfd3caa8a9b0a0) — 3,000 annotated satellite images of military vehicles
