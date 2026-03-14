import { useMemo, useState } from 'react'
import { MapContainer, Marker, Popup, TileLayer, useMapEvents } from 'react-leaflet'
import L, { LatLng } from 'leaflet'
import type { LatLngExpression } from 'leaflet'
import './App.css'

type Detection = {
  id: number
  position: LatLngExpression
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
  onMapClick: (position: LatLngExpression) => void
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

  const lastDetection = detections[detections.length - 1]

  const formattedCenter = useMemo(() => {
    const [lat, lng] = center as [number, number]
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`
  }, [center])

  const handleMapClick = (position: LatLngExpression) => {
    setDetections((prev) => [
      ...prev,
      {
        id: prev.length ? prev[prev.length - 1]!.id + 1 : 1,
        position,
      },
    ])
  }

  const handleViewportChange = (nextCenter: LatLng, nextZoom: number) => {
    setCenter([nextCenter.lat, nextCenter.lng])
    setZoom(nextZoom)
  }

  const clearDetections = () => setDetections([])

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

            {detections.map((det) => (
              <Marker key={det.id} position={det.position} icon={detectionIcon}>
                <Popup>
                  <span>
                    UNIT #{det.id.toString().padStart(3, '0')}
                    <br />
                    HEAVY ARMOR
                    <br />
                    {(det.position as [number, number])[0].toFixed(4)},{' '}
                    {(det.position as [number, number])[1].toFixed(4)}
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

          {lastDetection && (
            <div className="tac-unit-tooltip">
              <div className="tac-unit-id">UNIT ID: {lastDetection.id.toString().padStart(3, '0')}</div>
              <div className="tac-unit-meta">
                HDG: 142° · VEL: 12 KM/H
              </div>
            </div>
          )}

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
