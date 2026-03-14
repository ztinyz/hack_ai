import { useMemo, useState } from 'react'
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
}

function MapInteraction({ onMapClick, onViewportChange }: MapInteractionProps) {
  useMapEvents({
    click(e) {
      onMapClick([e.latlng.lat, e.latlng.lng])
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
  const [center, setCenter] = useState<LatLngExpression>(DEFAULT_CENTER)
  const [zoom, setZoom] = useState<number>(DEFAULT_ZOOM)
  const [isDrawing, setIsDrawing] = useState(false)
  const [drawPoints, setDrawPoints] = useState<LatLngTuple[]>([])

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

  const clearDetections = () => setDetections([])

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
      const res = await fetch('http://localhost:8000/analyze', {
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
        console.error('Analyze request failed', res.status)
        return
      }

      const data = await res.json()
      const nextDetections: Detection[] = (data.detections ?? []).map(
        (
          d: {
            tankId?: string
            sceneId?: string
            lat: number
            lng: number
            confidence?: number
            className?: string
          },
          index: number,
        ) => ({
          id: index + 1,
          tankId: d.tankId ?? `T-${(index + 1).toString().padStart(3, '0')}`,
          sceneId: d.sceneId,
          lat: d.lat,
          lng: d.lng,
          confidence: d.confidence,
          className: d.className,
        }),
      )
      setDetections(nextDetections)
      console.log('Detections:', nextDetections.length)
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Analyze request error', err)
    }
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

              const fillOpacity = Math.min(0.2 + intensity * 0.55, 0.75)

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
                <dt>Latitude</dt>
                <dd>{formattedCenter.split(',')[0]}°N</dd>
              </div>
              <div className="tac-telemetry-row">
                <dt>Longitude</dt>
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
              onClick={clearDetections}
              disabled={detections.length === 0}
            >
              ▶
            </button>

            <div className="tac-timeline-content">
              <div className="tac-timeline-label">Playback History (T-hours)</div>
              <div className="tac-timeline-title">Enemy Displacement Timeline</div>
              <div className="tac-timeline-slider-row">
                <span>-24h</span>
                <input type="range" min={0} max={24} defaultValue={24} />
                <span>Now</span>
              </div>
            </div>

            <div className="tac-timeline-meta">
              <div className="tac-timeline-meta-label">Timeframe</div>
              <div className="tac-timeline-meta-value">Last 24 Hours</div>
              <div className="tac-timeline-meta-current">Current View: Now</div>
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
