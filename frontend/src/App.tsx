import { useMemo, useState } from 'react'
import { useEffect } from 'react'
import {
  Circle,
  MapContainer,
  Marker,
  Polygon,
  Popup,
  TileLayer,
  useMapEvents,
} from 'react-leaflet'
import L, { LatLng } from 'leaflet'
import type { LatLngExpression } from 'leaflet'
import './App.css'

type LatLngTuple = [number, number]

type Detection = {
  id: number
  tankId: string
  sceneId?: string
  lat: number
  lng: number
  confidence?: number
  className?: string
}

type HeatCell = {
  id: string
  bounds: LatLngTuple[]
  count: number
  center: LatLngTuple
}

type PlaybackFrame = {
  capturedAt: string
  label: string
  detections: Array<{
    tankId?: string
    sceneId?: string
    lat: number
    lng: number
    confidence?: number
    className?: string
  }>
}

const DEFAULT_CENTER: LatLngExpression = [48.3794, 31.1656] // Example theater coordinates
const DEFAULT_ZOOM = 6

const detectionIcon = L.divIcon({
  className: 'tac-detection-icon',
  html: '<span></span>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
})

type MapInteractionProps = {
  onMapClick: (position: LatLngTuple) => void
  onViewportChange: (center: LatLng, zoom: number) => void
  onCursorMove: (position: LatLngTuple | null) => void
}

function MapInteraction({ onMapClick, onViewportChange, onCursorMove }: MapInteractionProps) {
  useMapEvents({
    click(e) {
      onMapClick([e.latlng.lat, e.latlng.lng])
    },
    mousemove(e) {
      onCursorMove([e.latlng.lat, e.latlng.lng])
    },
    mouseout() {
      onCursorMove(null)
    },
    moveend(e) {
      const map = e.target
      onViewportChange(map.getCenter(), map.getZoom())
    },
    zoomend(e) {
      const map = e.target
      onViewportChange(map.getCenter(), map.getZoom())
    },
  })

  return null
}


function App() {
  const [detections, setDetections] = useState<Detection[]>([])
  const [playbackFrames, setPlaybackFrames] = useState<PlaybackFrame[] | null>(null)
  const [playbackIndex, setPlaybackIndex] = useState<number>(0)
  const [center, setCenter] = useState<LatLngExpression>(DEFAULT_CENTER)
  const [zoom, setZoom] = useState<number>(DEFAULT_ZOOM)
  const [isDrawing, setIsDrawing] = useState(false)
  const [drawPoints, setDrawPoints] = useState<LatLngTuple[]>([])
  const [isPlaying, setIsPlaying] = useState(false)
  const [cursorLatLng, setCursorLatLng] = useState<LatLngTuple | null>(null)


  useEffect(() => {
    if (!isPlaying || !playbackFrames) return
  
    const interval = setInterval(() => {
      setPlaybackIndex((prev) => {
        const next = prev + 1
  
        if (next >= playbackFrames.length) {
          setIsPlaying(false)
          return prev
        }
  
        setDetections(mapFrameDetections(playbackFrames[next].detections))
        return next
      })
    }, 800) // speed of animation
  
    return () => clearInterval(interval)
  }, [isPlaying, playbackFrames])

  const cellSizeDeg = useMemo(() => {
    if (zoom <= 8) return 0.24
    if (zoom <= 11) return 0.12
    if (zoom <= 13) return 0.06
    return 0.03
  }, [zoom])

  const orderedDrawPoints = useMemo(() => {
    if (drawPoints.length < 3) return drawPoints

    const [sumLat, sumLng] = drawPoints.reduce(
      (acc, [lat, lng]) => [acc[0] + lat, acc[1] + lng],
      [0, 0],
    )
    const centerLat = sumLat / drawPoints.length
    const centerLng = sumLng / drawPoints.length

    return [...drawPoints].sort((a, b) => {
      const angleA = Math.atan2(a[0] - centerLat, a[1] - centerLng)
      const angleB = Math.atan2(b[0] - centerLat, b[1] - centerLng)
      return angleA - angleB
    })
  }, [drawPoints])

  const heatCells = useMemo<HeatCell[]>(() => {

    if (!detections.length) return []

    const grid = new Map<string, { count: number; minLat: number; minLng: number }>()

    detections.forEach((d) => {
      const lat = d.lat
      const lng = d.lng
      const cellLatIndex = Math.floor(lat / cellSizeDeg)
      const cellLngIndex = Math.floor(lng / cellSizeDeg)
      const key = `${cellLatIndex}:${cellLngIndex}`

      if (!grid.has(key)) {
        const minLat = cellLatIndex * cellSizeDeg
        const minLng = cellLngIndex * cellSizeDeg
        grid.set(key, { count: 1, minLat, minLng })
      } else {
        const cell = grid.get(key)!
        cell.count += 1
      }
    })

    const result: HeatCell[] = []

    grid.forEach((value, key) => {
      const { count, minLat, minLng } = value
      const maxLat = minLat + cellSizeDeg
      const maxLng = minLng + cellSizeDeg

      const bounds: LatLngTuple[] = [
        [minLat, minLng],
        [minLat, maxLng],
        [maxLat, maxLng],
        [maxLat, minLng],
      ]

      result.push({
        id: key,
        bounds,
        count,
        center: [minLat + cellSizeDeg / 2, minLng + cellSizeDeg / 2],
      })
    })

    return result
  }, [detections, cellSizeDeg])

  const maxHeatCount = useMemo(
    () => heatCells.reduce((max, cell) => Math.max(max, cell.count), 0),
    [heatCells],
  )

  const markerLayerOpacity = useMemo(() => {
    if (zoom <= 11) return 0
    if (zoom >= 14) return 1
    return (zoom - 11) / 3
  }, [zoom])

  // Circle radius in meters derived from the current cell size in degrees.
  // 1 deg latitude ≈ 111 320 m; divide by 2 for radius (cell center to edge).
  const cellRadiusMeters = useMemo(
    () => (cellSizeDeg / 2) * 111_320,
    [cellSizeDeg],
  )

  const formattedCenter = useMemo(() => {
    const [lat, lng] = center as [number, number]
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`
  }, [center])

  const handleMapClick = (position: LatLngTuple) => {
    if (isDrawing) {
      setDrawPoints((prev) => [...prev, position])
    }
  }

  const handleViewportChange = (nextCenter: LatLng, nextZoom: number) => {
    setCenter([nextCenter.lat, nextCenter.lng])
    setZoom(nextZoom)
  }

  const mapFrameDetections = (raw: PlaybackFrame['detections']): Detection[] =>
    raw.map((d, index) => ({
      id: index + 1,
      tankId: d.tankId ?? `T-${(index + 1).toString().padStart(3, '0')}`,
      sceneId: d.sceneId,
      lat: d.lat,
      lng: d.lng,
      confidence: d.confidence,
      className: d.className,
    }))

  const startDrawing = () => {
    setDrawPoints([])
    setIsDrawing(true)
  }

  const cancelDrawing = () => {
    setIsDrawing(false)
    setDrawPoints([])
  }

  const finishDrawing = async () => {
    if (orderedDrawPoints.length < 3) {
      alert('Define at least three points to create an area.')
      return
    }

    setIsDrawing(false)

    const coords = orderedDrawPoints.map(([lat, lng]) => [lng, lat])
    //console.log("Polygon points:", orderedDrawPoints)
    coords.push(coords[0])

    try {
      const res = await fetch('http://localhost:8000/playback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          aoi: {
            type: 'Polygon',
            coordinates: [coords],
          },
        }),
      })

      if (!res.ok) {
        // eslint-disable-next-line no-console
        console.error('Playback request failed', res.status)
        return
      }

      const data = await res.json()
      const frames: PlaybackFrame[] = data.frames ?? []
      if (frames.length === 0) {
        setDetections([])
        setPlaybackFrames(null)
        setPlaybackIndex(0)
        setDetections([])
        return
      }
      setPlaybackFrames(frames)
      const latestWithDetections = [...frames]
        .map((frame, index) => ({ frame, index }))
        .reverse()
        .find(({ frame }) => (frame.detections?.length ?? 0) > 0)

      const selectedIndex = latestWithDetections ? latestWithDetections.index : frames.length - 1
      setPlaybackIndex(selectedIndex)
      setDetections(mapFrameDetections(frames[selectedIndex].detections))
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Playback request error', err)
    }
  }

  const handlePlaybackSliderChange = (index: number) => {
    if (!playbackFrames || index < 0 || index >= playbackFrames.length) return
    setPlaybackIndex(index)
    setDetections(mapFrameDetections(playbackFrames[index].detections))
  }

  return (
    <div className="tac-root">
      <header className="tac-topbar">
        <div className="tac-topbar-left">
          <span className="tac-logo">Tactical Command</span>
          <span className="tac-badge tac-badge-live">Live Theater: Active</span>
        </div>
        <div className="tac-search">
          <input placeholder="Search coordinates or unit ID…" />
        </div>
        <div className="tac-topbar-right">
          <span className="tac-status-dot" />
          <span className="tac-status-label">SAT-LINK: STABLE</span>
        </div>
      </header>

      <main className="tac-main">
        <section className="tac-map-layer" aria-label="Tactical theater map">
          <MapContainer
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            scrollWheelZoom
            className="tac-map"
          >
            <TileLayer
              attribution='Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />

            <MapInteraction
              onMapClick={handleMapClick}
              onViewportChange={handleViewportChange}
              onCursorMove={setCursorLatLng}
            />

            {drawPoints.map((p, idx) => (
              <Marker
                key={idx}
                position={p}
                draggable
                icon={L.divIcon({
                  className: 'tac-aoi-vertex',
                  html: '<span></span>',
                  iconSize: [10, 10],
                  iconAnchor: [5, 5],
                })}
                eventHandlers={{
                  dragend: (e) => {
                    const { lat, lng } = e.target.getLatLng()
                    setDrawPoints((prev) => {
                      const next = [...prev]
                      next[idx] = [lat, lng]
                      return next
                    })
                  },
                }}
              />
            ))}

            {orderedDrawPoints.length > 1 && (
              <Polygon
                positions={orderedDrawPoints}
                pathOptions={{ color: '#ffffff', weight: 2, fillOpacity: 0.1 }}
              />
            )}

            {detections.map((d) => (
              <Marker
                key={d.id}
                position={[d.lat, d.lng]}
                icon={detectionIcon}
                opacity={markerLayerOpacity}
              >
                <Popup>
                  <span>
                    {d.tankId}
                    <br />
                    COORDS {d.lat.toFixed(6)}, {d.lng.toFixed(6)}
                    {d.className ? (
                      <>
                        <br />
                        CLASS {d.className}
                      </>
                    ) : null}
                    {typeof d.confidence === 'number' ? (
                      <>
                        <br />
                        CONF {(d.confidence * 100).toFixed(1)}%
                      </>
                    ) : null}
                  </span>
                </Popup>
              </Marker>
            ))}

            {heatCells.map((cell) => {
              const intensity =
                maxHeatCount > 0
                  ? Math.log1p(cell.count) / Math.log1p(maxHeatCount)
                  : 0
              const [centerLat, centerLng] = cell.center

              let fillColor = '#00ff88'
              if (intensity >= 0.75) {
                fillColor = '#ff0000'
              } else if (intensity >= 0.5) {
                fillColor = '#ff7f00'
              } else if (intensity >= 0.25) {
                fillColor = '#ffff00'
              }

              const fillOpacity = Math.min(0.2 + intensity * 0.55, 0.3)

              return (
                <Circle
                  key={cell.id}
                  center={cell.center}
                  radius={cellRadiusMeters}
                  pathOptions={{
                    color: 'transparent',
                    fillColor,
                    weight: 0,
                    fillOpacity,
                  }}
                >
                  <Popup>
                    <span>
                      {cell.count.toString().padStart(3, '0')} TANKS
                      <br />
                      COORDS {centerLat.toFixed(6)}, {centerLng.toFixed(6)}
                      <br />
                      INTENSITY {(intensity * 100).toFixed(0)}%
                    </span>
                  </Popup>
                </Circle>
              )
            })}
          </MapContainer>

          <div className="tac-telemetry-card">
            <h2>Theater Telemetry</h2>
            <dl>
              <div className="tac-telemetry-row">
                <dt>Cursor Lat</dt>
                <dd>{cursorLatLng ? cursorLatLng[0].toFixed(6) : '—'}</dd>
              </div>
              <div className="tac-telemetry-row">
                <dt>Cursor Lng</dt>
                <dd>{cursorLatLng ? cursorLatLng[1].toFixed(6) : '—'}</dd>
              </div>
              <div className="tac-telemetry-row">
                <dt>View Center Lat</dt>
                <dd>{formattedCenter.split(',')[0]}°N</dd>
              </div>
              <div className="tac-telemetry-row">
                <dt>View Center Lng</dt>
                <dd>{formattedCenter.split(',')[1]}°E</dd>
              </div>
              <div className="tac-telemetry-row tac-telemetry-row-strong">
                <dt>Detected Units</dt>
                <dd>{detections.length.toString().padStart(2, '0')} Heavy Armor</dd>
              </div>
            </dl>
          </div>

          <div className="tac-aoi-card">
            <h2>Area of Interest</h2>
            <p>{isDrawing ? 'Click on the map to add vertices. Finish when done.' : 'Define a custom area on the map.'}</p>
            <div className="tac-aoi-actions">
              <button type="button" onClick={startDrawing} disabled={isDrawing}>
                Start Draw
              </button>
              <button type="button" onClick={finishDrawing} disabled={!isDrawing || drawPoints.length < 3}>
                Finish
              </button>
              <button type="button" onClick={cancelDrawing} disabled={!isDrawing && drawPoints.length === 0}>
                Clear
              </button>
            </div>
            <div className="tac-aoi-meta">
              <span>Vertices: {drawPoints.length}</span>
            </div>
          </div>

          <div className="tac-timeline">
            <button
              type="button"
              className="tac-play-button"
              onClick={() => setIsPlaying((p) => !p)}
              disabled={!playbackFrames}
              title="Clear playback"
            >
              {isPlaying ? '⏸' : '▶'}
            </button>

            <div className="tac-timeline-content">
              <div className="tac-timeline-label">Playback History</div>
              <div className="tac-timeline-title">7 days, 2 timestamps/day</div>
              <div className="tac-timeline-slider-row">
                <span>7d ago</span>
                <input
                  type="range"
                  min={0}
                  max={playbackFrames ? playbackFrames.length - 1 : 0}
                  value={playbackIndex}
                  onChange={(e) => handlePlaybackSliderChange(Number(e.target.value))}
                  disabled={!playbackFrames || playbackFrames.length === 0}
                />
                <span>Now</span>
              </div>
            </div>

            <div className="tac-timeline-meta">
              <div className="tac-timeline-meta-label">Timeframe</div>
              <div className="tac-timeline-meta-value">
                {playbackFrames ? 'Last 7 days' : 'Draw AOI & Finish to load'}
              </div>
              <div className="tac-timeline-meta-current">
                {playbackFrames && playbackFrames[playbackIndex]
                  ? `Current: ${playbackFrames[playbackIndex].label}`
                  : 'Current: —'}
              </div>
            </div>
          </div>

          <div className="tac-compass">
            <div className="tac-compass-n">N</div>
            <div className="tac-compass-arrow" />
          </div>

          <div className="tac-scale">
            <span>0.3 M/PIX</span>
            <div className="tac-scale-bar" />
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
