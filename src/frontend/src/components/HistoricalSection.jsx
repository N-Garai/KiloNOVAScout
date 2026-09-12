import { useState } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'

// Historical Event Analysis (v4 M17) — retrospective entry point into the
// SAME pipeline. The corpus holds metadata + official links only; heavy
// skymap FITS is fetched at analysis time by the existing DAG stage.
// Full per-event reports reuse GET /api/runs/{run_id}/report — no new
// report code.
const CLASSES = [
  { id: 'bns', label: 'BNS mergers' },
  { id: 'grb', label: 'Gamma-ray bursts' },
  { id: 'neutrino', label: 'Neutrinos' },
]
const YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]

export default function HistoricalSection() {
  const [classes, setClasses] = useState(['bns', 'grb', 'neutrino'])
  const [startYear, setStartYear] = useState(2017)
  const [endYear, setEndYear] = useState(2024)
  const [events, setEvents] = useState([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState({})
  const [searching, setSearching] = useState(false)
  const [batchId, setBatchId] = useState(null)
  const [batchStatus, setBatchStatus] = useState('')
  const [results, setResults] = useState([])
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const [reportLoading, setReportLoading] = useState(null)

  const toggleClass = (id) => {
    setClasses((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))
  }

  const search = async () => {
    setSearching(true)
    setError('')
    try {
      const { data } = await axios.get('/api/historical/events', {
        params: {
          event_class: classes.join(','),
          start_year: startYear,
          end_year: endYear,
          t: Date.now(),
        },
      })
      setEvents(data.events || [])
      setTotal(data.total || 0)
      const all = {}
      ;(data.events || []).forEach((e) => { all[e.event_id] = true })
      setSelected(all)
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load historical events.')
    } finally {
      setSearching(false)
    }
  }

  const toggleEvent = (id) => {
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const pollBatch = async (bid) => {
    try {
      const { data } = await axios.get(`/api/historical/batch/${bid}`, { params: { t: Date.now() } })
      setBatchStatus(data.status || '')
      setResults(data.results || [])
      if (data.status !== 'completed') {
        setTimeout(() => pollBatch(bid), 2000)
      } else {
        setAnalyzing(false)
      }
    } catch {
      setTimeout(() => pollBatch(bid), 3000)
    }
  }

  const analyze = async () => {
    const ids = events.filter((e) => selected[e.event_id]).map((e) => e.event_id)
    if (!ids.length) {
      setError('Select at least one event to analyze.')
      return
    }
    setAnalyzing(true)
    setError('')
    setResults([])
    try {
      const { data } = await axios.post('/api/historical/analyze', { event_ids: ids }, { timeout: 30000 })
      setBatchId(data.batch_id)
      setBatchStatus('running')
      pollBatch(data.batch_id)
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not start historical analysis.')
      setAnalyzing(false)
    }
  }

  const openReport = async (runId) => {
    if (!runId || reportLoading) return
    setReportLoading(runId)
    try {
      const { data } = await axios.get(`/api/runs/${runId}/report`, {
        headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
        params: { t: Date.now() },
      })
      const html = data.html || ''
      const win = window.open('', '_blank')
      if (!win) return
      if (html) {
        win.document.write(html)
        win.document.close()
      } else if (data.markdown) {
        win.document.write(`<pre>${data.markdown.replace(/</g, '&lt;')}</pre>`)
        win.document.close()
      }
    } catch {
      setError('Report not ready yet — wait a moment and try again.')
    } finally {
      setReportLoading(null)
    }
  }

  const exportCSV = () => {
    const rows = [['event_id', 'status', 'top_host', 'score', 'airmass', 'cloud', 'tiling', 'run_id']]
    results.forEach((r) => {
      rows.push([r.event_id, r.status, r.top_host || '', r.score ?? '', r.airmass ?? '', r.weather_cloud ?? '', r.tiling || '', r.run_id || ''])
    })
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `historical-batch-${batchId || 'export'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportLatex = () => {
    const lines = ['\\begin{tabular}{@{}llrrrr@{}}', '\\toprule',
      'Event & Top host & Score & Airmass & Cloud\\% & Tiling \\\\ \\midrule']
    results.forEach((r) => {
      const score = r.score === null || r.score === undefined ? '--' : Number(r.score).toFixed(3)
      const air = r.airmass === null || r.airmass === undefined ? '--' : Number(r.airmass).toFixed(2)
      lines.push(`${r.event_id} & ${(r.top_host || '--').replace(/_/g, '\\_')} & ${score} & ${air} & ${r.weather_cloud ?? '--'} & ${(r.tiling || '--').replace(/_/g, '\\_')} \\\\`)
    })
    lines.push('\\bottomrule', '\\end{tabular}')
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `historical-batch-${batchId || 'export'}.tex`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section id="historical" className="relative py-32 px-4">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-cosmic-purple/5 to-transparent" />
      <div className="relative z-10 max-w-7xl mx-auto">
        <motion.div initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.8 }} className="text-center mb-12">
          <h2 className="font-cosmic text-5xl md:text-6xl font-bold mb-6 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">
            HISTORICAL ANALYSIS
          </h2>
          <p className="font-grotesk text-xl text-gray-400 max-w-3xl mx-auto">
            Retrospective runs on real past events — same pipeline, same report, no fallback needed
          </p>
        </motion.div>

        <div className="glass rounded-2xl p-8 border border-white/10 mb-8">
          <div className="flex flex-wrap items-center gap-4 mb-6">
            <div className="flex gap-2">
              {CLASSES.map((c) => (
                <button
                  key={c.id}
                  onClick={() => toggleClass(c.id)}
                  className={`px-3 py-1.5 rounded-lg border font-mono text-xs ${classes.includes(c.id) ? 'border-cosmic-cyan/60 bg-cosmic-cyan/10 text-cosmic-cyan' : 'border-white/10 text-gray-400'}`}
                >
                  {classes.includes(c.id) ? '✓ ' : ''}{c.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 font-mono text-xs text-gray-400">
              <span>Year</span>
              <select value={startYear} onChange={(e) => setStartYear(Number(e.target.value))} className="bg-black/40 border border-white/10 rounded px-2 py-1.5">
                {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <span>—</span>
              <select value={endYear} onChange={(e) => setEndYear(Number(e.target.value))} className="bg-black/40 border border-white/10 rounded px-2 py-1.5">
                {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            <button
              onClick={search}
              disabled={searching}
              className="px-6 py-2 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-sm hover:opacity-90 disabled:opacity-50"
            >
              {searching ? 'SEARCHING…' : 'SEARCH EVENTS'}
            </button>
          </div>

          {error && (
            <div className="mb-4 font-mono text-xs text-red-400 border border-red-400/40 rounded-lg p-3">{error}</div>
          )}

          {events.length > 0 && (
            <>
              <div className="font-mono text-xs text-gray-400 mb-3">{total} events found — official links included, skymap FITS fetched at analysis time</div>
              <div className="max-h-64 overflow-y-auto border border-white/10 rounded-lg mb-4">
                {events.map((e) => (
                  <label key={e.event_id} className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 hover:bg-white/5 cursor-pointer">
                    <input type="checkbox" checked={!!selected[e.event_id]} onChange={() => toggleEvent(e.event_id)} className="accent-cyan-400" />
                    <span className="font-mono text-sm text-white w-28">{e.event_id}</span>
                    <span className="font-mono text-[10px] px-1.5 py-px rounded border border-white/15 text-gray-300">{e.event_class}</span>
                    <span className="font-mono text-xs text-gray-400">{e.year} · {e.distance_mpc ? `${e.distance_mpc} Mpc` : 'no distance'}</span>
                    <a href={e.official_ref} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()} className="ml-auto font-mono text-[10px] text-cosmic-cyan hover:underline">official ↗</a>
                  </label>
                ))}
              </div>
              <button
                onClick={analyze}
                disabled={analyzing}
                className="px-6 py-2 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-sm hover:opacity-90 disabled:opacity-50"
              >
                {analyzing ? `ANALYZING… (${batchStatus})` : `ANALYZE SELECTED (${events.filter((e) => selected[e.event_id]).length})`}
              </button>
            </>
          )}
        </div>

        {results.length > 0 && (
          <div className="glass rounded-2xl p-8 border border-white/10">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-cosmic text-xl text-white">BATCH RESULTS {batchId && <span className="font-mono text-xs text-gray-400">· {batchId} · {batchStatus}</span>}</h3>
              <div className="flex gap-2">
                <button onClick={exportCSV} className="px-3 py-1.5 rounded border border-white/10 text-xs font-mono hover:bg-white/5">Export CSV</button>
                <button onClick={exportLatex} className="px-3 py-1.5 rounded border border-white/10 text-xs font-mono hover:bg-white/5">Export LaTeX</button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full font-mono text-xs">
                <thead>
                  <tr className="text-gray-400 border-b border-white/10">
                    <th className="text-left py-2 pr-3">Event</th>
                    <th className="text-left py-2 pr-3">Status</th>
                    <th className="text-left py-2 pr-3">Top host</th>
                    <th className="text-right py-2 pr-3">Score</th>
                    <th className="text-right py-2 pr-3">Airmass</th>
                    <th className="text-right py-2 pr-3">Cloud%</th>
                    <th className="text-left py-2 pr-3">Tiling</th>
                    <th className="text-left py-2">Report</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.event_id} className="border-b border-white/5 text-gray-300">
                      <td className="py-2 pr-3 text-white">{r.event_id}</td>
                      <td className="py-2 pr-3">{r.status}</td>
                      <td className="py-2 pr-3">{r.top_host || '—'}</td>
                      <td className="py-2 pr-3 text-right">{r.score === null || r.score === undefined ? '—' : Number(r.score).toFixed(3)}</td>
                      <td className="py-2 pr-3 text-right">{r.airmass === null || r.airmass === undefined ? '—' : Number(r.airmass).toFixed(2)}</td>
                      <td className="py-2 pr-3 text-right">{r.weather_cloud ?? '—'}</td>
                      <td className="py-2 pr-3">{r.tiling || '—'}</td>
                      <td className="py-2">
                        {r.run_id ? (
                          <button onClick={() => openReport(r.run_id)} disabled={reportLoading === r.run_id} className="px-2 py-1 rounded border border-cosmic-cyan/40 text-cosmic-cyan hover:bg-cosmic-cyan/10 disabled:opacity-50">
                            {reportLoading === r.run_id ? '…' : 'View report'}
                          </button>
                        ) : (
                          <span className="text-gray-500">{r.error ? 'failed' : '…'}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
