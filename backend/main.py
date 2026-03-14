from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
from pathlib import Path
import math
import importlib
import os
from typing import Any, Dict, Optional

MANIFEST_PATH = Path(__file__).parents[1] / "data" / "scenes" / "manifest.json"
SCENES_DIR = Path(__file__).parents[1] / "data" / "scenes"
MODEL_PATH = Path(os.getenv("YOLO_MODEL_PATH", Path(__file__).parents[1] / "best.pt"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Polygon(BaseModel):
    type: str
    coordinates: list[list[tuple[float, float]]]


class AnalyzeRequest(BaseModel):
    aoi: Polygon


_MODEL: Optional[Any] = None


def _get_model_names(model: Any) -> Dict[int, str]:
    names = getattr(model, "names", {}) or {}
    if isinstance(names, dict):
        return {int(key): str(value) for key, value in names.items()}
    if isinstance(names, list):
        return {idx: str(value) for idx, value in enumerate(names)}
    return {}


def load_manifest() -> Dict:
    with MANIFEST_PATH.open() as f:
        return json.load(f)


def polygon_centroid(aoi: Polygon) -> tuple[float, float]:
    # Very simple centroid: average of all vertices (sufficient for this demo).
    ring = aoi.coordinates[0]
    sum_lat = 0.0
    sum_lng = 0.0
    for lng, lat in ring:
        sum_lat += lat
        sum_lng += lng
    n = len(ring)
    return sum_lat / n, sum_lng / n


def pick_nearest_scene(aoi: Polygon, manifest: Dict) -> str:
    centroid_lat, centroid_lng = polygon_centroid(aoi)
    best_id = None
    best_dist = float("inf")
    for scene_id, meta in manifest.items():
        d = math.hypot(meta["centerLat"] - centroid_lat, meta["centerLng"] - centroid_lng)
        if d < best_dist:
            best_dist = d
            best_id = scene_id
    if best_id is None:
        raise ValueError("No scenes found in manifest.json")
    return best_id


def _load_model() -> Optional[Any]:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if not MODEL_PATH.exists():
        return None

    try:
        ultralytics = importlib.import_module("ultralytics")
        yolo_cls = getattr(ultralytics, "YOLO")
    except Exception:
        return None

    _MODEL = yolo_cls(str(MODEL_PATH))
    return _MODEL


def mock_ml_detections(scene_id: str, scene_meta: Dict):
    """
    Uses YOLO inference if model + scene image are available.
    Falls back to static detections so frontend integration keeps working.
    """
    model = _load_model()
    scene_image = SCENES_DIR / scene_meta.get("filename", "")

    if model is not None and scene_image.exists():
        results = model.predict(source=str(scene_image), conf=0.25, verbose=False)
        detections = []
        class_names = _get_model_names(model)

        if results:
            boxes = results[0].boxes
            for idx, box in enumerate(boxes):
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                class_id = int(box.cls[0]) if box.cls is not None else -1
                detections.append(
                    {
                        "tankId": f"T-{idx + 1:03d}",
                        "x": (x1 + x2) / 2,
                        "y": (y1 + y2) / 2,
                        "confidence": float(box.conf[0]),
                        "classId": class_id,
                        "className": class_names.get(class_id, f"class-{class_id}"),
                    }
                )

        return detections

    # Fallback mock detections
    return [
        {"tankId": "T-001", "x": 100, "y": 120, "confidence": 0.95, "classId": 0, "className": "mock-target"},
        {"tankId": "T-002", "x": 300, "y": 220, "confidence": 0.90, "classId": 0, "className": "mock-target"},
    ]


def pixel_to_latlng(meta: Dict, x: float, y: float, img_w: int = 1024, img_h: int = 1024):
    # simple fake mapping: +/- 0.01 deg around center
    dx = (x / img_w - 0.5) * 0.02
    dy = (y / img_h - 0.5) * 0.02
    return meta["centerLat"] + dy, meta["centerLng"] + dx


def point_in_polygon(lng: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """
    Ray casting algorithm for point-in-polygon on a single ring.
    """
    inside = False
    n = len(ring)
    if n < 3:
        return False

    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]

        intersects = ((y1 > lat) != (y2 > lat)) and (
            lng < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-12) + x1
        )
        if intersects:
            inside = not inside

    return inside


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    manifest = load_manifest()
    scene_id = pick_nearest_scene(req.aoi, manifest)
    meta = manifest[scene_id]

    raw_dets = mock_ml_detections(scene_id, meta)
    dets = []
    ring = req.aoi.coordinates[0]

    for d in raw_dets:
        lat, lng = pixel_to_latlng(meta, d["x"], d["y"])
        if point_in_polygon(lng, lat, ring):
            dets.append(
                {
                    "tankId": d["tankId"],
                    "lat": lat,
                    "lng": lng,
                    "confidence": d["confidence"],
                    "classId": d.get("classId"),
                    "className": d.get("className"),
                }
            )

    return {
        "sceneId": scene_id,
        "capturedAt": meta["fakeCapturedAt"],
        "summary": {"totalTanks": len(dets)},
        "detections": dets,
    }


@app.get("/model-info")
def model_info():
    if not MODEL_PATH.exists():
        return {
            "modelPath": str(MODEL_PATH),
            "exists": False,
            "loaded": False,
            "error": "Model file not found",
        }

    model = _load_model()
    if model is None:
        return {
            "modelPath": str(MODEL_PATH),
            "exists": True,
            "loaded": False,
            "error": "Could not import/load Ultralytics YOLO. Install the 'ultralytics' package in the backend environment.",
        }

    return {
        "modelPath": str(MODEL_PATH),
        "exists": True,
        "loaded": True,
        "task": getattr(model, "task", None),
        "classNames": _get_model_names(model),
    }