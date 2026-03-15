from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import importlib

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

def _playback_timestamps(days: int = 7) -> List[datetime]:
    """
    Generate timestamps for the last `days` days at 08:00 and 18:00 UTC.
    The last timestamp is 'now'.
    """
    now = datetime.now(timezone.utc)

    start_day = (now - timedelta(days=days)).date()

    stamps: List[datetime] = []

    for d in range(days):
        day = start_day + timedelta(days=d)

        morning = datetime(day.year, day.month, day.day, 8, 0, 0, tzinfo=timezone.utc)
        evening = datetime(day.year, day.month, day.day, 18, 0, 0, tzinfo=timezone.utc)

        stamps.append(morning)
        stamps.append(evening)

    stamps.append(now)  # final frame = current moment
    return stamps


def _parse_captured_at(meta: Dict) -> Optional[datetime]:
    raw = meta.get("fakeCapturedAt")
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except Exception:
        return None


# Only show detections for a frame if we have a scene captured within this window of the frame time.
MAX_SCENE_TIME_DIFF_SECONDS = 12 * 3600  # 12 hours


def _pick_scene_for_timestamp(manifest: Dict, ts: datetime) -> Optional[tuple[str, Dict]]:
    """Return (scene_id, meta) whose fakeCapturedAt is nearest to ts, or None if none within window."""
    best = None
    best_diff = None
    for scene_id, meta in manifest.items():
        t = _parse_captured_at(meta)
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        diff = abs((t - ts).total_seconds())
        if diff <= MAX_SCENE_TIME_DIFF_SECONDS and (best_diff is None or diff < best_diff):
            best_diff = diff
            best = (scene_id, meta)
    return best


def _drift_for_frame(tank_id: str, frame_index: int, scale: float = 0.00015) -> tuple[float, float]:
    """Deterministic small offset so tanks appear to move across playback frames."""
    h = int(hashlib.sha256(f"{tank_id}-{frame_index}".encode()).hexdigest()[:8], 16)
    h2 = int(hashlib.sha256(f"{tank_id}-{frame_index}-lng".encode()).hexdigest()[:8], 16)
    lat_d = (h % 1000) / 1000.0 - 0.5
    lng_d = (h2 % 1000) / 1000.0 - 0.5
    return lat_d * scale, lng_d * scale


@app.post("/playback")
def playback(req: AnalyzeRequest):
    """
    Returns 14 frames (7 days, 2 timestamps per day): from 7 days ago 00:00 UTC to now.
    Each frame has capturedAt (ISO) and detections in the AOI, with slight per-frame drift
    so tank positions appear to move over time.
    """
    manifest = load_manifest()
    ring = req.aoi.coordinates[0]
    timestamps = _playback_timestamps(days=7)
    frames: List[Dict] = []

    for frame_index, ts in enumerate(timestamps):
        scene_pair = _pick_scene_for_timestamp(manifest, ts)
        if not scene_pair:
            frames.append({
                "capturedAt": ts.isoformat(),
                "label": ts.strftime("%Y-%m-%d %H:%M UTC"),
                "detections": [],
            })
            continue

        scene_id, meta = scene_pair
        raw_dets = mock_ml_detections(scene_id, meta)
        dets: List[Dict] = []

        for det_index, d in enumerate(raw_dets, start=1):
            lat, lng = pixel_to_latlng(meta, d["x"], d["y"], d.get("imgW", 1024), d.get("imgH", 1024))
            if not point_in_polygon(lng, lat, ring):
                continue
            dlat, dlng = _drift_for_frame(d.get("tankId", f"T-{det_index:03d}"), frame_index)
            lat += dlat
            lng += dlng
            dets.append({
                "tankId": d.get("tankId", f"{scene_id}-T-{det_index:03d}"),
                "sceneId": scene_id,
                "lat": lat,
                "lng": lng,
                "confidence": d.get("confidence"),
                "classId": d.get("classId"),
                "className": d.get("className"),
            })

        frames.append({
            "capturedAt": ts.isoformat(),
            "label": ts.strftime("%Y-%m-%d %H:%M UTC"),
            "detections": dets,
        })

    return {
        "timeRange": {
            "from": timestamps[0].isoformat(),
            "to": timestamps[-1].isoformat(),
        },
        "frames": frames,
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