import { useState, useEffect, useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup
} from 'react-simple-maps'
import { geoMercator } from 'd3-geo'
import axios from 'axios'

const GEO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json'

// ComposableMap renders into an 800x600 viewBox by default; mirror its
// projection here so map clicks can be converted back to lon/lat.
const MAP_VIEWBOX = { width: 800, height: 600 }
const MAP_SCALE = 140

// Palomar Observatory coordinates as default
const DEFAULT_OBS = {
  name: 'Palomar Observatory',
  lat: 33.356,
  lon: -116.865,
  alt: 1706,
}

export default function ObservatorySection() {
  const [config, setConfig] = useState(DEFAULT_OBS)
  const [pickedPos, setPickedPos] = useState({ lat: DEFAULT_OBS.lat, lon: DEFAULT_OBS.lon })
  const [obsName, setObsName] = useState(DEFAULT_OBS.name)
  const [obsAlt, setObsAlt] = useState(DEFAULT_OBS.alt.toString())
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saveError, setSaveError] = useState('')
  // Notification preferences (mirrors ObservatoryConfig; secrets stay blank
  // unless being set — the backend never echoes them back).
  const [notify, setNotify] = useState({
    alert_webhook_url: '', alert_webhook_secret: '', alert_live_only: false,
    digest_enabled: false, digest_hour_utc: '6',
    digest_smtp_host: '', digest_smtp_port: '465', digest_smtp_user: '',
    digest_smtp_pass: '', digest_from: '', digest_to: '',
  })
  const [notifySaved, setNotifySaved] = useState(false)
  const [notifyLoading, setNotifyLoading] = useState(false)
  const [notifyError, setNotifyError] = useState('')
  const [digestTest, setDigestTest] = useState('')
  const [mapZoom, setMapZoom] = useState(1)
  const ref = useRef(null)
  const mapWrapRef = useRef(null)
  const isInView = useInView(ref, { once: true, margin: '-100px' })

  const applyNotifyFromConfig = (c) => {
    if (!c) return
    setNotify((prev) => ({
      ...prev,
      alert_webhook_url: c.alert_webhook_url ?? prev.alert_webhook_url,
      alert_live_only: !!c.alert_live_only,
      digest_enabled: !!c.digest_enabled,
      digest_hour_utc: c.digest_hour_utc ?? prev.digest_hour_utc,
      digest_smtp_host: c.digest_smtp_host ?? prev.digest_smtp_host,
      digest_smtp_port: c.digest_smtp_port ?? prev.digest_smtp_port,
      digest_smtp_user: c.digest_smtp_user ?? prev.digest_smtp_user,
      digest_from: c.digest_from ?? prev.digest_from,
      digest_to: c.digest_to ?? prev.digest_to,
      // Secrets intentionally never populated (backend always blanks them).
      alert_webhook_secret: '',
      digest_smtp_pass: '',
    }))
  }

  // Fetch current config on mount
  useEffect(() => {
    axios.get('/agent/config')
      .then(res => {
        const c = res.data
        setConfig(c)
        setPickedPos({ lat: c.lat, lon: c.lon })
        setObsName(c.name)
        setObsAlt(c.alt?.toString() || '1706')
        applyNotifyFromConfig(c)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Click anywhere on the map to move the observatory marker there.
  // Inverts the same Mercator projection ComposableMap uses internally.
  // NOTE: the SVG letterboxes (preserveAspectRatio meet) inside the 2:1
  // wrapper, so client pixels must be mapped through the SVG's own
  // viewBox — mapping across the wrapper rect shifts the marker sideways.
  const handleMapSelect = (evt) => {
    const node = mapWrapRef.current
    if (!node) return
    const svg = node.querySelector('svg')
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return

    let x, y
    const vb = svg.viewBox && svg.viewBox.baseVal
    if (vb && vb.width && vb.height) {
      // xMidYMid meet (SVG default): content centered, possible side bands.
      const scale = Math.min(rect.width / vb.width, rect.height / vb.height)
      if (!scale) return
      const offsetX = (rect.width - vb.width * scale) / 2
      const offsetY = (rect.height - vb.height * scale) / 2
      x = vb.x + (evt.clientX - rect.left - offsetX) / scale
      y = vb.y + (evt.clientY - rect.top - offsetY) / scale
      // Clicks landing in the letterbox bands are outside the map.
      if (x < vb.x || y < vb.y || x > vb.x + vb.width || y > vb.y + vb.height) return
    } else {
      // No viewBox: fall back to stretching across the rendered box.
      const w = parseFloat(svg.getAttribute('width')) || rect.width
      const h = parseFloat(svg.getAttribute('height')) || rect.height
      x = ((evt.clientX - rect.left) / rect.width) * w
      y = ((evt.clientY - rect.top) / rect.height) * h
    }

    const projection = geoMercator()
      .scale(MAP_SCALE)
      .translate([MAP_VIEWBOX.width / 2, MAP_VIEWBOX.height / 2])
      .center([pickedPos.lon, pickedPos.lat])
    const coords = projection.invert([x, y])
    if (!coords || coords.some((v) => v === undefined || isNaN(v))) return
    const lon = Math.round(Math.max(-180, Math.min(180, coords[0])) * 1000) / 1000
    const lat = Math.round(Math.max(-90, Math.min(90, coords[1])) * 1000) / 1000
    setPickedPos({ lat, lon })
    setSaved(false)
  }

  const handleCoordChange = (key, rawValue) => {
    const v = parseFloat(rawValue)
    if (isNaN(v)) return
    const clamped = key === 'lat'
      ? Math.max(-90, Math.min(90, v))
      : Math.max(-180, Math.min(180, v))
    setPickedPos((prev) => ({ ...prev, [key]: Math.round(clamped * 1000) / 1000 }))
    setSaved(false)
  }

  const handleSave = async () => {
    setLoading(true)
    setSaveError('')
    try {
      const payload = {
        name: obsName || 'Palomar Observatory',
        lat: pickedPos.lat,
        lon: pickedPos.lon,
        alt: parseFloat(obsAlt) || 1706,
      }
      // 60s timeout: first request after idle may hit a Render cold start.
      const res = await axios.put('/agent/config', payload, { timeout: 60000 })
      setConfig(res.data)
      setObsName(res.data.name)
      setPickedPos({ lat: res.data.lat, lon: res.data.lon })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      console.error('Failed to update observatory:', err)
      if (err?.request && !err?.response) {
        setSaveError('Backend unreachable — it may be waking from sleep. Wait ~60s and retry.')
      } else {
        setSaveError(`Save failed (HTTP ${err?.response?.status || 'unknown'}). Retry.`)
      }
    }
    setLoading(false)
  }

  const setNotifyField = (key, value) => {
    setNotify((prev) => ({ ...prev, [key]: value }))
    setNotifySaved(false)
  }

  const handleNotifySave = async () => {
    setNotifyLoading(true)
    setNotifyError('')
    setDigestTest('')
    try {
      const numOrUndef = (v) => (v === '' || v == null ? undefined : parseInt(v, 10));
      const payload = {
        name: obsName || 'Palomar Observatory',
        lat: pickedPos.lat,
        lon: pickedPos.lon,
        alt: parseFloat(obsAlt) || 1706,
        alert_webhook_url: notify.alert_webhook_url,
        alert_webhook_secret: notify.alert_webhook_secret || undefined,
        alert_live_only: !!notify.alert_live_only,
        digest_enabled: !!notify.digest_enabled,
        digest_hour_utc: numOrUndef(notify.digest_hour_utc),
        digest_smtp_host: notify.digest_smtp_host,
        digest_smtp_port: numOrUndef(notify.digest_smtp_port),
        digest_smtp_user: notify.digest_smtp_user,
        digest_smtp_pass: notify.digest_smtp_pass || undefined,
        digest_from: notify.digest_from,
        digest_to: notify.digest_to,
      }
      const res = await axios.put('/agent/config', payload, { timeout: 60000 })
      setConfig(res.data)
      applyNotifyFromConfig(res.data)
      setNotifySaved(true)
      setTimeout(() => setNotifySaved(false), 3000)
    } catch (err) {
      console.error('Failed to update notifications:', err)
      setNotifyError(`Save failed (HTTP ${err?.response?.status || 'unknown'}). Retry.`)
    }
    setNotifyLoading(false)
  }

  const handleDigestTest = async () => {
    setDigestTest('Sending test digest…')
    try {
      const { data } = await axios.post('/api/digest/send-now', null, { timeout: 45000 })
      setDigestTest(data?.sent ? `Sent: ${data.message || ''}` : `Not sent: ${data?.message || 'check SMTP settings'}`)
    } catch (err) {
      setDigestTest(`Failed (HTTP ${err?.response?.status || 'unknown'}). Check backend logs.`)
    }
  }

  return (
    <section
      id="observatory"
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
            Click anywhere on the world map to pin your observatory location,
            or type the coordinates directly — both stay in sync.
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
            <div
              ref={mapWrapRef}
              onClick={handleMapSelect}
              className="relative cursor-crosshair"
              style={{ aspectRatio: '2/1' }}
            >
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
              <span className="text-cosmic-cyan">
                <svg viewBox="0 0 24 24" className="w-5 h-5 inline-block" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="12" cy="12" r="3.2" />
                  <path d="M12 2v4m0 12v4M2 12h4m12 0h4" />
                  <circle cx="12" cy="12" r="9" strokeDasharray="3 3" />
                </svg>
              </span> Station Config
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

            {/* Latitude (editable — stays in sync with the map marker) */}
            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Latitude
              </label>
              <input
                type="number"
                step="0.001"
                min="-90"
                max="90"
                value={pickedPos.lat}
                onChange={(e) => handleCoordChange('lat', e.target.value)}
                placeholder="e.g. 33.356"
                className="w-full bg-black/60 border border-cosmic-cyan/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-cyan/60 focus:ring-1 focus:ring-cosmic-cyan/30
                           transition-all"
              />
            </div>

            {/* Longitude (editable — stays in sync with the map marker) */}
            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Longitude
              </label>
              <input
                type="number"
                step="0.001"
                min="-180"
                max="180"
                value={pickedPos.lon}
                onChange={(e) => handleCoordChange('lon', e.target.value)}
                placeholder="e.g. -116.865"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
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

            {saveError && (
              <div className="mb-4 rounded-lg border border-red-400/40 bg-red-500/10 px-4 py-2.5 font-mono text-xs text-red-300">
                {saveError}
              </div>
            )}

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

        {/* Notifications — who gets woken, and how. Secrets are never
            echoed back: blank means "keep the saved value". */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.9, delay: 0.6 }}
          className="glass rounded-2xl p-6 border border-cosmic-cyan/20 mt-8"
        >
          <h3 className="font-cosmic text-xl font-bold text-white mb-2">
            Notification Settings
          </h3>
          <p className="font-mono text-[11px] text-gray-500 mb-6 leading-relaxed">
            Per-run alerts fire on every finished pipeline; the daily digest
            mails the last 24 h of runs with report links. Secrets are stored
            server-side and never displayed back.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <div className="mb-5 md:col-span-2">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Webhook URL (Discord / Slack / ntfy.sh topic)
              </label>
              <input
                type="text"
                value={notify.alert_webhook_url}
                onChange={(e) => setNotifyField('alert_webhook_url', e.target.value)}
                placeholder="https://ntfy.sh/my-unique-topic"
                className="w-full bg-black/60 border border-cosmic-cyan/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-cyan/60 focus:ring-1 focus:ring-cosmic-cyan/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Webhook Secret (leave blank to keep)
              </label>
              <input
                type="password"
                value={notify.alert_webhook_secret}
                onChange={(e) => setNotifyField('alert_webhook_secret', e.target.value)}
                placeholder="saved — blank keeps current"
                autoComplete="new-password"
                className="w-full bg-black/60 border border-cosmic-cyan/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-cyan/60 focus:ring-1 focus:ring-cosmic-cyan/30
                           transition-all"
              />
            </div>

            <div className="mb-5 flex items-end pb-1">
              <label className="flex items-center gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!!notify.alert_live_only}
                  onChange={(e) => setNotifyField('alert_live_only', e.target.checked)}
                  className="w-4 h-4 accent-cyan-400"
                />
                <span className="font-mono text-xs text-gray-300">
                  Alert only on genuine triggers <span className="text-gray-500">(skip mock/demo runs)</span>
                </span>
              </label>
            </div>

            <div className="md:col-span-2 border-t border-white/10 my-1" />

            <div className="mb-5 flex items-end pb-1">
              <label className="flex items-center gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!!notify.digest_enabled}
                  onChange={(e) => setNotifyField('digest_enabled', e.target.checked)}
                  className="w-4 h-4 accent-fuchsia-400"
                />
                <span className="font-mono text-xs text-gray-300">
                  Daily digest mail <span className="text-gray-500">(runs + report links, once per day)</span>
                </span>
              </label>
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Digest Hour (UTC, 0–23)
              </label>
              <input
                type="number" min="0" max="23"
                value={notify.digest_hour_utc}
                onChange={(e) => setNotifyField('digest_hour_utc', e.target.value)}
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                SMTP Host
              </label>
              <input
                type="text"
                value={notify.digest_smtp_host}
                onChange={(e) => setNotifyField('digest_smtp_host', e.target.value)}
                placeholder="smtp.gmail.com"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                SMTP Port
              </label>
              <input
                type="number"
                value={notify.digest_smtp_port}
                onChange={(e) => setNotifyField('digest_smtp_port', e.target.value)}
                placeholder="465"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                SMTP Username
              </label>
              <input
                type="text"
                value={notify.digest_smtp_user}
                onChange={(e) => setNotifyField('digest_smtp_user', e.target.value)}
                placeholder="you@gmail.com"
                autoComplete="username"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                SMTP Password <span className="text-gray-600">(leave blank to keep)</span>
              </label>
              <input
                type="password"
                value={notify.digest_smtp_pass}
                onChange={(e) => setNotifyField('digest_smtp_pass', e.target.value)}
                placeholder="saved — use an App Password for Gmail"
                autoComplete="new-password"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                From Display
              </label>
              <input
                type="text"
                value={notify.digest_from}
                onChange={(e) => setNotifyField('digest_from', e.target.value)}
                placeholder="KilonovaScout"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>

            <div className="mb-5 md:col-span-2">
              <label className="block text-xs font-mono text-gray-400 mb-1.5 uppercase tracking-wider">
                Mail To (comma-separated for several observers)
              </label>
              <input
                type="text"
                value={notify.digest_to}
                onChange={(e) => setNotifyField('digest_to', e.target.value)}
                placeholder="observer@observatory.org"
                className="w-full bg-black/60 border border-cosmic-magenta/20 rounded-lg px-4 py-2.5
                           text-white font-mono text-sm placeholder-gray-600
                           focus:outline-none focus:border-cosmic-magenta/60 focus:ring-1 focus:ring-cosmic-magenta/30
                           transition-all"
              />
            </div>
          </div>

          {notifyError && (
            <div className="mb-4 rounded-lg border border-red-400/40 bg-red-500/10 px-4 py-2.5 font-mono text-xs text-red-300">
              {notifyError}
            </div>
          )}
          {digestTest && (
            <div className="mb-4 rounded-lg border border-white/10 bg-black/40 px-4 py-2.5 font-mono text-xs text-gray-300">
              {digestTest}
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-3">
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleNotifySave}
              disabled={notifyLoading}
              className={`flex-1 py-3 rounded-lg font-cosmic font-bold text-sm tracking-wider
                         transition-all duration-300 ${
                           notifySaved
                             ? 'bg-green-500/20 border border-green-400/40 text-green-400'
                             : 'bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta text-black hover:opacity-90'
                         } ${notifyLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {notifyLoading ? 'SAVING...' : notifySaved ? '✓ NOTIFICATIONS SAVED' : 'SAVE NOTIFICATIONS'}
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleDigestTest}
              disabled={notifyLoading}
              className="flex-1 py-3 rounded-lg font-cosmic font-bold text-sm tracking-wider
                         border-2 border-cosmic-magenta/50 text-cosmic-magenta hover:bg-cosmic-magenta/10
                         transition-all disabled:opacity-50"
            >
              SEND TEST DIGEST NOW
            </motion.button>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
