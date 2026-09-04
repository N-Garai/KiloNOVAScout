import { useState, useCallback, useEffect, useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup
} from 'react-simple-maps'
import axios from 'axios'

const GEO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json'

// Palomar Observatory coordinates as default
const DEFAULT_OBS = {
  name: 'Palomar Observatory',
  lat: 33.356,
  lon: -116.865,
  alt: 1706,
}

// Reverse geocode to get a rough location name from coordinates
const reverseGeocode = async (lat, lon) => {
  try {
    const res = await axios.get(
      `https://geocoding-api.open-meteo.com/v1/search?name=&latitude=${lat}&longitude=${lon}&count=1&language=en&format=json`,
      { timeout: 3000 }
    )
    // Open-Meteo geocoding doesn't do reverse, so we just format coords
    return null
  } catch {
    return null
  }
}

export default function ObservatorySection() {
  const [config, setConfig] = useState(DEFAULT_OBS)
  const [pickedPos, setPickedPos] = useState({ lat: DEFAULT_OBS.lat, lon: DEFAULT_OBS.lon })
  const [obsName, setObsName] = useState(DEFAULT_OBS.name)
  const [obsAlt, setObsAlt] = useState(DEFAULT_OBS.alt.toString())
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const [mapZoom, setMapZoom] = useState(1)
  const ref = useRef(null)
  const isInView = useInView(ref, { once: true, margin: '-100px' })

  // Fetch current config on mount
  useEffect(() => {
    axios.get('/agent/config')
      .then(res => {
        const c = res.data
        setConfig(c)
        setPickedPos({ lat: c.lat, lon: c.lon })
        setObsName(c.name)
        setObsAlt(c.alt?.toString() || '1706')
      })
      .catch(() => {})
  }, [])

  const handleMapClick = useCallback((geo, projection) => (evt) => {
    const [x, y] = projection.invert([evt.clientX, evt.clientY])
    if (x !== undefined && y !== undefined && !isNaN(x) && !isNaN(y)) {
      const lon = Math.round(x * 1000) / 1000
      const lat = Math.round(y * 1000) / 1000
      setPickedPos({ lat, lon })
      setSaved(false)
    }
  }, [])

  const handleSave = async () => {
    setLoading(true)
    try {
      const payload = {
        name: obsName || 'Palomar Observatory',
        lat: pickedPos.lat,
        lon: pickedPos.lon,
        alt: parseFloat(obsAlt) || 1706,
      }
      const res = await axios.put('/agent/config', payload)
      setConfig(res.data)
      setObsName(res.data.name)
      setPickedPos({ lat: res.data.lat, lon: res.data.lon })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      console.error('Failed to update observatory:', err)
    }
    setLoading(false)
  }

  return (
    <section
      ref={ref}
      className="relative min-h-screen py-24 px-6 overflow-hidden"
    >
      {/* Section background — subtle grid mesh */}
      <div className="absolute inset-0 opacity-10">
        <div
          className="w-full h-full"
          style={{
            backgroundImage:
              'linear-gradient(rgba(0,245,255,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(0,245,255,0.15) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto">
        {/* Title */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8 }}
          className="text-center mb-16"
        >
          <h2 className="font-cosmic text-4xl md:text-5xl font-bold text-white mb-4">
            <span className="text-cosmic-cyan">OBSERVATORY</span>{' '}
            <span className="text-cosmic-magenta">COORDINATES</span>
          </h2>
          <p className="text-gray-400 font-grotesk text-lg max-w-2xl mx-auto">
            Click anywhere on the world map to pin your observatory location.
            Lat/Lon is calculated automatically from your selection.
            Falls back to <span className="text-cosmic-cyan font-bold">Palomar</span> if no custom location is set.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          {/* World Map — 2 columns */}
          <motion.div
            initial={{ opacity: 0, x: -60 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.9, delay: 0.2 }}
            className="lg:col-span-2 glass rounded-2xl p-4 border border-cosmic-cyan/20 overflow-hidden"
          >
            <div className="relative" style={{ aspectRatio: '2/1' }}>
              <ComposableMap
                projection="geoMercator"
                projectionConfig={{
                  scale: 140,
                  center: [pickedPos.lon, pickedPos.lat],
                }}
                style={{ width: '100%', height: '100%' }}
              >
                <ZoomableGroup
                  zoom={mapZoom}
                  center={[pickedPos.lon, pickedPos.lat]}
                >
                  <Geographies geography={GEO_URL}>
                    {({ geographies }) =>
                      geographies.map((geo) => (
                        <Geography
                          key={geo.rsmKey}
                          geography={geo}
                          onClick={handleMapClick(geo, null)}
                          style={{
                            default: {
                              fill: 'rgba(0, 245, 255, 0.05)',
                              stroke: 'rgba(0, 245, 255, 0.2)',
                              strokeWidth: 0.5,
                              outline: 'none',
                              cursor: 'crosshair',
                            },
                            hover: {
                              fill: 'rgba(0, 245, 255, 0.15)',
                              stroke: 'rgba(0, 245, 255, 0.5)',
                              strokeWidth: 1,
                              outline: 'none',
                            },
                            pressed: {
                              fill: 'rgba(255, 0, 255, 0.2)',
                              stroke: '#ff00ff',
                              strokeWidth: 1,
                              outline: 'none',
                            },
                          }}
                        />
                      ))
                    }
                  </Geographies>

                  {/* Picked location marker */}
                  <Marker coordinates={[pickedPos.lon, pickedPos.lat]}>
                    {/* Pulse ring */}
                    <motion.circle
                      r={12}
                      fill="none"
                      stroke="#00f5ff"
                      strokeWidth={1.5}
                      initial={{ r: 4, opacity: 1 }}
                      animate={{ r: [4, 14, 4], opacity: [1, 0.3, 1] }}
                      transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                    />
                    {/* Inner glow */}
                    <motion.circle
                      r={5}
                      fill="#00f5ff"
                      initial={{ scale: 1 }}
                      animate={{ scale: [1, 1.3, 1] }}
                      transition={{ duration: 1.5, repeat: Infinity }}
                      style={{ filter: 'drop-shadow(0 0 6px #00f5ff)' }}
                    />
                    {/* Center dot */}
                    <circle r={2} fill="#ffffff" />
                  </Marker>
                </ZoomableGroup>
              </ComposableMap>

              {/* Coordinate readout overlay */}
              <div className="absolute bottom-3 left-3 glass rounded-lg px-4 py-2 border border-cosmic-cyan/30">
                <div className="font-mono text-xs text-cosmic-cyan">
                  LAT: <span className="text-white font-bold">{pickedPos.lat.toFixed(4)}°</span>
                </div>
                <div className="font-mono text-xs text-cosmic-magenta">
                  LON: <span className="text-white font-bold">{pickedPos.lon.toFixed(4)}°</span>
                </div>
              </div>

              {/* Crosshair overlay */}
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center opacity-20">
                <div className="w-px h-full bg-cosmic-cyan" />
              </div>
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center opacity-20">
                <div className="h-px w-full bg-cosmic-cyan" />
              </div>
            </div>
          </motion.div>

          {/* Config Panel — 1 column */}
          <motion.div
            initial={{ opacity: 0, x: 60 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.9, delay: 0.4 }}
            className="glass rounded-2xl p-6 border border-cosmic-magenta/20"
          >
            <h3 className="font-cosmic text-xl font-bold text-white mb-6 flex items-center gap-2">
              <span className="text-cosmic-cyan">🛰</span> Station Config
            </h3>

            {/* Observatory Name */}
            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Observatory Name
              </label>
              <input
                type="text"
                value={obsName}
                onChange={(e) => {
                  setObsName(e.target.value)
                  setSaved(false)
                }}
                placeholder="e.g. Palomar Observatory"
                className="w-full bg-black/60 border border-cosmic-cyan/20 rounded-lg px-4 py-2.5
                           text-white font-grotesk text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-cyan/60 focus:ring-1 focus:ring-cosmic-cyan/30
                           transition-all"
              />
            </div>

            {/* Latitude (read-only, auto-calculated) */}
            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Latitude <span className="text-cosmic-cyan">(auto-calculated)</span>
              </label>
              <div className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm font-mono">
                <span className="text-cosmic-cyan">{pickedPos.lat.toFixed(6)}°</span>
              </div>
            </div>

            {/* Longitude (read-only, auto-calculated) */}
            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Longitude <span className="text-cosmic-magenta">(auto-calculated)</span>
              </label>
              <div className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm font-mono">
                <span className="text-cosmic-magenta">{pickedPos.lon.toFixed(6)}°</span>
              </div>
            </div>

            {/* Altitude */}
            <div className="mb-6">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Altitude (meters)
              </label>
              <input
                type="number"
                value={obsAlt}
                onChange={(e) => {
                  setObsAlt(e.target.value)
                  setSaved(false)
                }}
                placeholder="e.g. 1706"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            {/* Status indicator */}
            <div className="flex items-center gap-2 mb-5 text-xs font-mono">
              <div className={`w-2 h-2 rounded-full ${saved ? 'bg-green-400' : 'bg-yellow-400'} animate-pulse`} />
              <span className={saved ? 'text-green-400' : 'text-gray-400'}>
                {saved ? 'Configuration saved — ready for GCN alerts' : 'Modified — not yet saved'}
              </span>
            </div>

            {/* Save button */}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleSave}
              disabled={loading}
              className={`w-full py-3 rounded-lg font-cosmic font-bold text-sm tracking-wider
                         transition-all duration-300 ${
                           saved
                             ? 'bg-green-500/20 border border-green-400/40 text-green-400'
                             : 'bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta text-black hover:opacity-90'
                         } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {loading ? 'CONFIGURING...' : saved ? '✓ CONFIGURED' : 'SAVE CONFIGURATION'}
            </motion.button>

            {/* Fallback note */}
            <p className="mt-4 text-[10px] text-gray-500 font-mono leading-relaxed">
              If no custom location is set, the agent falls back to{' '}
              <span className="text-cosmic-cyan">Palomar Observatory</span> (33.356°N, 116.865°W, 1706m).
            </p>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
