from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
from pathlib import Path
import importlib
import math
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
    Uses YOLO inference when both the model and the scene image are available.
    Returns no detections when the scene cannot be analyzed.
    """
    model = _load_model()
    scene_image = SCENES_DIR / scene_meta.get("filename", "")

    if model is not None and scene_image.exists():
        results = model.predict(source=str(scene_image), conf=0.25, verbose=False)
        detections = []
        class_names = _get_model_names(model)

        if results:
            result = results[0]
            boxes = result.boxes
            orig_h, orig_w = result.orig_shape
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
                        "imgW": float(orig_w),
                        "imgH": float(orig_h),
                    }
                )
        return detections

    return []


def pixel_to_latlng(meta: Dict, x: float, y: float, img_w: float = 1024, img_h: float = 1024):
    center_lat = meta["centerLat"]
    center_lng = meta["centerLng"]
    resolution_cm = float(meta.get("resolutionCm", 30))
    meters_per_pixel = resolution_cm / 100.0

    offset_x_m = (x - img_w / 2.0) * meters_per_pixel
    offset_y_m = (y - img_h / 2.0) * meters_per_pixel

    meters_per_degree_lat = 111_320.0
    meters_per_degree_lng = 111_320.0 * math.cos(math.radians(center_lat))
    if abs(meters_per_degree_lng) < 1e-9:
        meters_per_degree_lng = 1e-9

    # Image Y grows downward; latitude grows northward.
    lat = center_lat - offset_y_m / meters_per_degree_lat
    lng = center_lng + offset_x_m / meters_per_degree_lng
    return lat, lng


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


def get_scenes_in_aoi(aoi: Polygon, manifest: Dict[str, Dict[str, Any]]) -> list[tuple[str, Dict[str, Any]]]:
    ring = aoi.coordinates[0]
    matching_scenes = []

    for scene_id, meta in manifest.items():
        center_lat = meta.get("centerLat")
        center_lng = meta.get("centerLng")
        if center_lat is None or center_lng is None:
            continue

        if point_in_polygon(center_lng, center_lat, ring):
            matching_scenes.append((scene_id, meta))

    return matching_scenes


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    manifest = load_manifest()
    ring = req.aoi.coordinates[0]
    scenes_in_aoi = get_scenes_in_aoi(req.aoi, manifest)

    if not scenes_in_aoi:
        return {
            "sceneId": None,
            "sceneIds": [],
            "capturedAt": None,
            "summary": {"totalTanks": 0, "sceneCount": 0},
            "detections": [],
        }

    dets = []
    scene_ids = []
    captured_at = []

    for scene_id, meta in scenes_in_aoi:
        scene_ids.append(scene_id)
        captured_at.append(meta.get("fakeCapturedAt"))

        raw_dets = mock_ml_detections(scene_id, meta)

        for detection_index, d in enumerate(raw_dets, start=1):
            lat, lng = pixel_to_latlng(meta, d["x"], d["y"], d.get("imgW", 1024), d.get("imgH", 1024))
            if point_in_polygon(lng, lat, ring):
                dets.append(
                    {
                        "tankId": d.get("tankId", f"{scene_id}-T-{detection_index:03d}"),
                        "sceneId": scene_id,
                        "lat": lat,
                        "lng": lng,
                        "confidence": d["confidence"],
                        "classId": d.get("classId"),
                        "className": d.get("className"),
                    }
                )

    return {
        "sceneId": scene_ids[0] if len(scene_ids) == 1 else None,
        "sceneIds": scene_ids,
        "capturedAt": captured_at[0] if len(captured_at) == 1 else captured_at,
        "summary": {"totalTanks": len(dets), "sceneCount": len(scene_ids)},
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