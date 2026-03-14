import { useMemo, useState } from 'react'
import {
  CircleMarker,
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
  position: LatLngExpression
}

type Cluster = {
  id: number
  center: LatLngTuple
  count: number
}

const DEFAULT_CENTER: LatLngExpression = [48.3794, 31.1656] // Example theater coordinates
const DEFAULT_ZOOM = 6

const detectionIcon = L.divIcon({
  className: 'tac-detection-icon',
  html: '<span></span>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
})

const makeGroupIcon = (count: number) =>
  L.divIcon({
    className: 'tac-group-icon',
    html: `<span>${count}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
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
  const [, setZoom] = useState<number>(DEFAULT_ZOOM)
  const [isDrawing, setIsDrawing] = useState(false)
  const [drawPoints, setDrawPoints] = useState<LatLngTuple[]>([])

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

  const clusters = useMemo<Cluster[]>(() => {
    if (!detections.length) return []

    const THRESHOLD_DEG = 0.03
    const pts = detections.map((d) => d.position as LatLngTuple)
    const result: Cluster[] = []

    pts.forEach(([lat, lng]) => {
      let found: Cluster | undefined
      for (const c of result) {
        const [clat, clng] = c.center
        const dist = Math.hypot(clat - lat, clng - lng)
        if (dist < THRESHOLD_DEG) {
          found = c
          break
        }
      }

      if (!found) {
        result.push({ id: result.length + 1, center: [lat, lng], count: 1 })
      } else {
        const [clat, clng] = found.center
        const newCount = found.count + 1
        found.center = [(clat * found.count + lat) / newCount, (clng * found.count + lng) / newCount]
        found.count = newCount
      }
    })

    return result
  }, [detections])

  const lastDetection = detections[detections.length - 1]

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
        (d: { lat: number; lng: number }, index: number) => ({
          id: index + 1,
          position: [d.lat, d.lng],
        }),
      )
      setDetections(nextDetections)
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
                pathOptions={{ color: '#00f5ff', weight: 2, fillOpacity: 0.15 }}
              />
            )}
            {clusters.map((cluster) => (
              <Marker
                key={cluster.id}
                position={cluster.center}
                icon={cluster.count > 1 ? makeGroupIcon(cluster.count) : detectionIcon}
              >
                <Popup>
                  <span>
                    {cluster.count > 1
                      ? `${cluster.count.toString().padStart(2, '0')} UNITS`
                      : '1 UNIT'}
                    <br />
                    HEAVY ARMOR GROUP
                    <br />
                    {cluster.center[0].toFixed(4)}, {cluster.center[1].toFixed(4)}
                  </span>
                </Popup>
              </Marker>
            ))}
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
            <span>5 KM</span>
            <div className="tac-scale-bar" />
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
