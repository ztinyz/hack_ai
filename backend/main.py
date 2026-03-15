from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import hashlib
import tempfile
import urllib.error
import urllib.request
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import importlib

MANIFEST_PATH = Path(__file__).parents[1] / "data" / "scenes" / "manifest.json"
SCENES_DIR = Path(__file__).parents[1] / "data" / "scenes"
MODEL_PATH = Path(os.getenv("YOLO_MODEL_PATH", Path(__file__).parents[1] / "best.pt"))
DB_PATH = Path(os.getenv("SCENES_DB_PATH", Path(__file__).parent / "scenes.db"))
SCENE_HTTP_CACHE_DIR = Path(
    os.getenv("SCENE_HTTP_CACHE_DIR", Path(tempfile.gettempdir()) / "x-scene-http-cache")
)


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


class SyncScenesRequest(BaseModel):
    forceUpload: bool = False


class ImportManifestUrlsRequest(BaseModel):
    baseUrl: str
    pathPrefix: str = ""
    overwriteExisting: bool = False


_MODEL: Optional[Any] = None


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scenes (
                scene_id TEXT PRIMARY KEY,
                filename TEXT,
                photo_url TEXT NOT NULL,
                captured_at TEXT,
                center_lat REAL,
                center_lng REAL,
                resolution_cm REAL DEFAULT 30,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS scenes_set_updated_at
            AFTER UPDATE ON scenes
            FOR EACH ROW    
            BEGIN
                UPDATE scenes SET updated_at = CURRENT_TIMESTAMP WHERE scene_id = OLD.scene_id;
            END
            """
        )


# Only keep detections whose class name matches one of these (case-insensitive).
# Covers common military vehicle labels from tank/armor YOLO datasets.
MILITARY_VEHICLE_KEYWORDS = frozenset({
    "tank", "armor", "armoured", "armored", "apc", "ifv", "bmp", "btr", "mbt",
    "military", "artillery", "self-propelled", "vehicle", "armoured vehicle",
})


def _is_military_vehicle(class_name: Optional[str]) -> bool:
    if not class_name or not isinstance(class_name, str):
        return False
    lower = class_name.lower().strip()
    return any(kw in lower for kw in MILITARY_VEHICLE_KEYWORDS)

@app.on_event("startup")
def on_startup() -> None:
    init_db()


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


def _normalize_manifest_entry(scene_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    center_lng = meta.get("centerLng")
    if center_lng is None:
        center_lng = meta.get("center Lng")

    return {
        "sceneId": scene_id,
        "filename": meta.get("filename"),
        "capturedAt": meta.get("fakeCapturedAt"),
        "centerLat": meta.get("centerLat"),
        "centerLng": center_lng,
        "resolutionCm": float(meta.get("resolutionCm", 30)),
    }


def _cloudinary_ready() -> bool:
    return bool(
        os.getenv("CLOUDINARY_CLOUD_NAME")
        and os.getenv("CLOUDINARY_API_KEY")
        and os.getenv("CLOUDINARY_API_SECRET")
    )


def _upload_to_cloudinary(local_path: Path, public_id: str) -> str:
    if not local_path.exists():
        raise FileNotFoundError(f"Image not found: {local_path}")

    try:
        cloudinary = importlib.import_module("cloudinary")
        uploader = importlib.import_module("cloudinary.uploader")
    except Exception as exc:
        raise RuntimeError(
            "Cloudinary SDK is missing. Install backend dependencies first."
        ) from exc

    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True,
    )

    result = uploader.upload(
        str(local_path),
        public_id=public_id,
        overwrite=True,
        resource_type="image",
        folder="scenes",
    )
    return str(result["secure_url"])


def upsert_scene(scene: Dict[str, Any]) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO scenes (
                scene_id,
                filename,
                photo_url,
                captured_at,
                center_lat,
                center_lng,
                resolution_cm
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scene_id) DO UPDATE SET
                filename=excluded.filename,
                photo_url=excluded.photo_url,
                captured_at=excluded.captured_at,
                center_lat=excluded.center_lat,
                center_lng=excluded.center_lng,
                resolution_cm=excluded.resolution_cm
            """,
            (
                scene["sceneId"],
                scene.get("filename"),
                scene["photoUrl"],
                scene.get("capturedAt"),
                scene.get("centerLat"),
                scene.get("centerLng"),
                scene.get("resolutionCm", 30),
            ),
        )


def load_scenes_from_db() -> list[Dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                scene_id,
                filename,
                photo_url,
                captured_at,
                center_lat,
                center_lng,
                resolution_cm
            FROM scenes
            ORDER BY scene_id
            """
        ).fetchall()

    return [
        {
            "sceneId": row["scene_id"],
            "filename": row["filename"],
            "photoUrl": row["photo_url"],
            "capturedAt": row["captured_at"],
            "centerLat": row["center_lat"],
            "centerLng": row["center_lng"],
            "resolutionCm": row["resolution_cm"],
        }
        for row in rows
    ]


def load_runtime_scenes() -> list[Dict[str, Any]]:
    scenes = load_scenes_from_db()
    if scenes:
        return scenes
    manifest = load_manifest()
    return [_normalize_manifest_entry(scene_id, meta) for scene_id, meta in manifest.items()]


def _build_image_url(base_url: str, filename: str, path_prefix: str = "") -> str:
    clean_base = base_url.rstrip("/")
    clean_prefix = path_prefix.strip("/")
    clean_file = filename.lstrip("/")
    if clean_prefix:
        return f"{clean_base}/{clean_prefix}/{clean_file}"
    return f"{clean_base}/{clean_file}"


def _parse_gs_url(url: str) -> Optional[tuple[str, str]]:
    if not url.startswith("gs://"):
        return None
    rest = url[len("gs://") :]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    bucket_name, object_path = parts
    if not bucket_name or not object_path:
        return None
    return bucket_name, object_path


def _generate_gcs_signed_url(gs_url: str) -> str:
    parsed = _parse_gs_url(gs_url)
    if parsed is None:
        raise ValueError("Invalid gs:// URL")

    try:
        storage = importlib.import_module("google.cloud.storage")
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency: google-cloud-storage. Install backend requirements."
        ) from exc

    bucket_name, object_path = parsed
    ttl_minutes = int(os.getenv("GCS_SIGNED_URL_TTL_MINUTES", "60"))

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    return str(
        blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=ttl_minutes),
            method="GET",
        )
    )


def _resolve_scene_source(scene_meta: Dict[str, Any]) -> Optional[str]:
    source = scene_meta.get("photoUrl")
    if isinstance(source, str) and source.startswith("gs://"):
        try:
            return _generate_gcs_signed_url(source)
        except Exception:
            source = None

    if source:
        source_str = str(source)
        if source_str.startswith("http://") or source_str.startswith("https://"):
            if _is_http_url_reachable(source_str):
                cached_local = _download_http_image_to_cache(source_str)
                if cached_local:
                    return cached_local
            source = None
        else:
            return source_str

    local_scene_image = SCENES_DIR / scene_meta.get("filename", "")
    if local_scene_image.exists():
        return str(local_scene_image)

    return None


def _is_http_url_reachable(url: str, timeout_seconds: int = 10) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= int(getattr(response, "status", 0)) < 400
    except urllib.error.HTTPError as exc:
        # Some storage/CDN layers may reject HEAD but allow GET.
        if exc.code in (403, 405):
            try:
                get_request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(get_request, timeout=timeout_seconds) as response:
                    return 200 <= int(getattr(response, "status", 0)) < 400
            except Exception:
                return False
        return False
    except Exception:
        return False


def _download_http_image_to_cache(url: str) -> Optional[str]:
    try:
        SCENE_HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        extension = Path(url.split("?", 1)[0]).suffix or ".img"
        file_name = f"{hashlib.sha256(url.encode()).hexdigest()}{extension}"
        target = SCENE_HTTP_CACHE_DIR / file_name

        if target.exists() and target.stat().st_size > 0:
            return str(target)

        with urllib.request.urlopen(url, timeout=20) as response:
            content = response.read()
        if not content:
            return None

        target.write_bytes(content)
        return str(target)
    except Exception:
        return None


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
    Returns only detections classified as military vehicles.
    """
    model = _load_model()
    scene_source = _resolve_scene_source(scene_meta)

    if model is not None and scene_source:
        results = model.predict(source=scene_source, conf=0.25, verbose=False)
        detections = []
        class_names = _get_model_names(model)

        if results:
            result = results[0]
            boxes = result.boxes
            orig_h, orig_w = result.orig_shape
            for idx, box in enumerate(boxes):
                class_id = int(box.cls[0]) if box.cls is not None else -1
                class_name = class_names.get(class_id, f"class-{class_id}")
                if not _is_military_vehicle(class_name):
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(
                    {
                        "tankId": f"T-{len(detections) + 1:03d}",
                        "x": (x1 + x2) / 2,
                        "y": (y1 + y2) / 2,
                        "confidence": float(box.conf[0]),
                        "classId": class_id,
                        "className": class_name,
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


def get_scenes_in_aoi(aoi: Polygon, scenes: List[Dict[str, Any]]) -> list[tuple[str, Dict[str, Any]]]:
    ring = aoi.coordinates[0]
    matching_scenes = []

    for meta in scenes:
        scene_id = meta.get("sceneId")
        center_lat = meta.get("centerLat")
        center_lng = meta.get("centerLng")
        if scene_id is None or center_lat is None or center_lng is None:
            continue

        if point_in_polygon(center_lng, center_lat, ring):
            matching_scenes.append((scene_id, meta))

    return matching_scenes


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    scenes = load_runtime_scenes()
    ring = req.aoi.coordinates[0]
    scenes_in_aoi = get_scenes_in_aoi(req.aoi, scenes)

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
        captured_at.append(meta.get("capturedAt"))

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
    
def _scenes_for_timestamp(scenes: List[Dict[str, Any]], ts: datetime) -> List[tuple[str, Dict[str, Any]]]:
    matching_scenes: List[tuple[str, Dict[str, Any]]] = []
    for meta in scenes:
        scene_id = meta.get("sceneId")
        if scene_id is None:
            continue
        t = _parse_captured_at(meta)
        if not t:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        diff = abs((t - ts).total_seconds())
        if diff <= MAX_SCENE_TIME_DIFF_SECONDS:
            matching_scenes.append((scene_id, meta))
    return matching_scenes

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
    raw = meta.get("capturedAt")
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


def _pick_scene_for_timestamp(scenes: List[Dict[str, Any]], ts: datetime) -> Optional[tuple[str, Dict]]:
    """Return (scene_id, meta) whose capturedAt is nearest to ts, or None if none within window."""
    best = None
    best_diff = None
    for meta in scenes:
        scene_id = meta.get("sceneId")
        if scene_id is None:
            continue
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
    scenes = load_runtime_scenes()
    ring = req.aoi.coordinates[0]
    timestamps = _playback_timestamps(days=7)
    frames: List[Dict] = []

    for frame_index, ts in enumerate(timestamps):
        scene_pairs = [
            (scene_id, meta)
            for scene_id, meta in _scenes_for_timestamp(scenes, ts)
            if "centerLat" in meta and "centerLng" in meta
        ]

        dets: List[Dict] = []

        if scene_pairs:
            for scene_index, (scene_id, meta) in enumerate(scene_pairs):
                raw_dets = mock_ml_detections(scene_id, meta)

                for det_index, d in enumerate(raw_dets, start=1):
                    lat, lng = pixel_to_latlng(meta, d["x"], d["y"], d.get("imgW", 1024), d.get("imgH", 1024))
                    if not point_in_polygon(lng, lat, ring):
                        continue

                    tank_id = f"{scene_id}-T-{det_index:03d}"
                    dlat, dlng = _drift_for_frame(tank_id, frame_index)
                    lat += dlat
                    lng += dlng

                    dets.append({
                        "tankId": tank_id,
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

@app.get("/scenes")
def list_scenes():
    scenes = load_scenes_from_db()
    return {"count": len(scenes), "scenes": scenes}


@app.post("/scenes/import-manifest-urls")
def import_manifest_urls(req: ImportManifestUrlsRequest):
    if not req.baseUrl.strip():
        raise HTTPException(status_code=400, detail="baseUrl is required")

    manifest = load_manifest()
    imported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []

    existing = {scene["sceneId"]: scene for scene in load_scenes_from_db()}

    for scene_id, raw_meta in manifest.items():
        meta = _normalize_manifest_entry(scene_id, raw_meta)
        filename = meta.get("filename")
        if not filename:
            errors.append({"sceneId": scene_id, "error": "Missing filename in manifest"})
            continue

        if scene_id in existing and not req.overwriteExisting:
            skipped.append({"sceneId": scene_id, "reason": "Exists in DB"})
            continue

        photo_url = _build_image_url(req.baseUrl, filename, req.pathPrefix)
        db_scene = {**meta, "photoUrl": photo_url}
        upsert_scene(db_scene)
        imported.append(db_scene)

    return {
        "imported": len(imported),
        "skipped": len(skipped),
        "failed": len(errors),
        "scenes": imported,
        "skips": skipped,
        "errors": errors,
    }


@app.post("/scenes/sync-manifest")
def sync_scenes_from_manifest(req: SyncScenesRequest):
    if not _cloudinary_ready():
        raise HTTPException(
            status_code=400,
            detail=(
                "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
            ),
        )

    manifest = load_manifest()
    synced: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    existing = {scene["sceneId"]: scene for scene in load_scenes_from_db()}

    for scene_id, raw_meta in manifest.items():
        meta = _normalize_manifest_entry(scene_id, raw_meta)
        filename = meta.get("filename")
        if not filename:
            errors.append({"sceneId": scene_id, "error": "Missing filename in manifest"})
            continue

        local_path = SCENES_DIR / filename
        if not local_path.exists():
            errors.append({"sceneId": scene_id, "error": f"Missing local file: {local_path.name}"})
            continue

        try:
            should_upload = req.forceUpload or scene_id not in existing
            if should_upload:
                photo_url = _upload_to_cloudinary(local_path, public_id=scene_id)
            else:
                photo_url = existing[scene_id]["photoUrl"]

            db_scene = {**meta, "photoUrl": photo_url}
            upsert_scene(db_scene)
            synced.append(db_scene)
        except Exception as exc:
            errors.append({"sceneId": scene_id, "error": str(exc)})

    return {
        "synced": len(synced),
        "failed": len(errors),
        "scenes": synced,
        "errors": errors,
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