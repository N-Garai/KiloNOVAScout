import { Fragment, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'

// Historical Event Analysis (v4 M17) — retrospective entry point into the
// SAME pipeline, rendered INSIDE the live-demo dashboard (not a separate
// page section). The corpus holds metadata + official links only; heavy
// skymap FITS is fetched at analysis time by the existing DAG stage.
// Each analyzed run attaches to the SHARED AgentTerminal trace via
// onHistoricalRun(runId), and full per-event reports reuse the SAME
// GET /api/runs/{run_id}/report flow as the LAUNCH button — only the
// provenance label differs (historical:<ID>).
const CLASSES = [
  { id: 'bns', label: 'BNS mergers' },
  { id: 'grb', label: 'Gamma-ray bursts' },
  { id: 'neutrino', label: 'Neutrinos' },
]
// Year window: Fermi-GBM era (2008) through the O5 horizon (2030).
// The backend filter accepts any integers — widening the corpus never needs
// a frontend change. Current corpus spans 2013 (GRB130427A) to 2022.
const YEARS = []
for (let y = 2008; y <= 2030; y++) YEARS.push(y)

const YEAR_SELECT = 'bg-black/40 border border-white/10 rounded px-2 py-1.5 text-white [&>option]:bg-[#0b0b16] [&>option]:text-gray-200'

export function useHistoricalBatch({ onHistoricalRun } = {}) {
  const [classes, setClasses] = useState(['bns', 'grb', 'neutrino'])
  const [startYear, setStartYear] = useState(2008)
  const [endYear, setEndYear] = useState(2030)
  const [events, setEvents] = useState([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState({})
  const [searching, setSearching] = useState(false)
  const [batchId, setBatchId] = useState(null)
  const [batchStatus, setBatchStatus] = useState('')
  const [results, setResults] = useState([])
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const attachedRef = useRef({})
  const onRunRef = useRef(null)
  onRunRef.current = onHistoricalRun || null

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
      // Attach every new run to the SHARED AgentTerminal trace, exactly as
      // if it had been launched — same SSE stream, same finish flow. The
      // event id travels along so the terminal prints an event divider
      // before the next workflow's steps.
      ;(data.results || []).forEach((r) => {
        if (r.run_id && !attachedRef.current[r.run_id] && onRunRef.current) {
          attachedRef.current[r.run_id] = true
          onRunRef.current(r.run_id, r.event_id)
        }
      })
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
    attachedRef.current = {}
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

  const clear = () => {
    setResults([])
    setBatchId(null)
    setBatchStatus('')
    setAnalyzing(false)
    setError('')
    attachedRef.current = {}
  }

  return {
    classes, toggleClass, startYear, setStartYear, endYear, setEndYear,
    events, total, selected, toggleEvent, searching, search,
    batchId, batchStatus, results, analyzing, analyze, error, clear,
  }
}

export function HistoricalSelector({ h, disabled }) {
  const picked = h.events.filter((e) => h.selected[e.event_id]).length
  return (
    <div id="historical" className="glass rounded-2xl border border-white/10 p-5 text-left h-full">
      <div className="font-mono text-[10px] text-gray-500 uppercase tracking-widest mb-1 text-center">
        Historical events
      </div>
      <div className="font-mono text-[10px] text-gray-600 mb-4 text-center">
        <span className="text-cosmic-magenta">◉ archive</span> = curated past trigger, re-analyzed live
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {CLASSES.map((c) => (
          <button
            key={c.id}
            onClick={() => h.toggleClass(c.id)}
            disabled={disabled}
            className={`px-2.5 py-1.5 rounded-lg border font-mono text-[11px] transition-all disabled:opacity-50 ${h.classes.includes(c.id) ? 'border-cosmic-magenta/60 bg-cosmic-magenta/10 text-cosmic-magenta' : 'border-white/10 text-gray-400'}`}
          >
            {h.classes.includes(c.id) ? '✓ ' : ''}{c.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 font-mono text-[11px] text-gray-400 mb-3">
        <span>Year</span>
        <select value={h.startYear} onChange={(e) => h.setStartYear(Number(e.target.value))} disabled={disabled} className={YEAR_SELECT}>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <span>—</span>
        <select value={h.endYear} onChange={(e) => h.setEndYear(Number(e.target.value))} disabled={disabled} className={YEAR_SELECT}>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <button
          onClick={h.search}
          disabled={disabled || h.searching}
          className="ml-auto px-4 py-1.5 rounded-lg border border-cosmic-cyan/40 text-cosmic-cyan font-mono text-[11px] hover:bg-cosmic-cyan/10 disabled:opacity-50"
        >
          {h.searching ? 'SEARCHING…' : 'SEARCH EVENTS'}
        </button>
      </div>
      {h.error && (
        <div className="mb-3 font-mono text-[11px] text-red-400 border border-red-400/40 rounded-lg p-2">{h.error}</div>
      )}
      {h.events.length > 0 && (
        <>
          <div className="font-mono text-[10px] text-gray-500 mb-2">{h.total} events found</div>
          <div className="max-h-56 overflow-y-auto border border-white/10 rounded-lg mb-4">
            {h.events.map((e) => (
              <label key={e.event_id} className="flex items-center gap-2 px-3 py-2 border-b border-white/5 hover:bg-white/5 cursor-pointer">
                <input type="checkbox" checked={!!h.selected[e.event_id]} onChange={() => h.toggleEvent(e.event_id)} disabled={disabled} className="accent-fuchsia-400" />
                <span className="font-mono text-xs text-white">{e.event_id}</span>
                <span className="font-mono text-[10px] px-1.5 py-px rounded border border-white/15 text-gray-300">{e.event_class}</span>
                <span className="font-mono text-[11px] text-gray-400">{e.year}{e.distance_mpc ? ` · ${e.distance_mpc} Mpc` : ''}</span>
                <a href={e.official_ref} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()} className="ml-auto font-mono text-[10px] text-cosmic-cyan hover:underline">official ↗</a>
              </label>
            ))}
          </div>
          <button
            onClick={h.analyze}
            disabled={disabled || h.analyzing}
            className="w-full px-6 py-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-base hover:opacity-90 transition-opacity glow-cyan disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {h.analyzing ? `ANALYZING… (${h.batchStatus || 'starting'})` : `LAUNCH HISTORICAL ANALYSIS (${picked})`}
          </button>
        </>
      )}
    </div>
  )
}

export function HistoricalBatchResults({ h, onViewReport, onDownloadReport }) {
  const [busyId, setBusyId] = useState(null)
  const [rowError, setRowError] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  // Each row opens that event's OWN report in the STANDARD preview modal
  // (same window as normal mode) — never shared content across rows.
  const viewRow = async (runId) => {
    if (!runId || busyId || !onViewReport) return
    setBusyId(runId)
    setRowError('')
    try {
      await onViewReport(runId)
    } catch {
      setRowError('Report not ready yet — wait a moment and try again.')
    } finally {
      setBusyId(null)
    }
  }
  const downloadRow = async (runId) => {
    if (!runId || busyId || !onDownloadReport) return
    setBusyId(runId)
    setRowError('')
    try {
      await onDownloadReport(runId)
    } catch {
      setRowError('PDF fetch failed — try again.')
    } finally {
      setBusyId(null)
    }
  }
  if (!h.results.length) return null
  const exportCSV = () => {
    const rows = [['event_id', 'status', 'top_host', 'score', 'airmass', 'cloud', 'tiling', 'run_id']]
    h.results.forEach((r) => {
      rows.push([r.event_id, r.status, r.top_host || '', r.score ?? '', r.airmass ?? '', r.weather_cloud ?? '', r.tiling || '', r.run_id || ''])
    })
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `historical-batch-${h.batchId || 'export'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }
  const exportLatex = () => {
    const lines = ['\\begin{tabular}{@{}llrrrr@{}}', '\\toprule',
      'Event & Top host & Score & Airmass & Cloud\\% & Tiling \\\\ \\midrule']
    h.results.forEach((r) => {
      const score = r.score === null || r.score === undefined ? '--' : Number(r.score).toFixed(3)
      const air = r.airmass === null || r.airmass === undefined ? '--' : Number(r.airmass).toFixed(2)
      lines.push(`${r.event_id} & ${(r.top_host || '--').replace(/_/g, '\\_')} & ${score} & ${air} & ${r.weather_cloud ?? '--'} & ${(r.tiling || '--').replace(/_/g, '\\_')} \\\\`)
    })
    lines.push('\\bottomrule', '\\end{tabular}')
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `historical-batch-${h.batchId || 'export'}.tex`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-xl p-6 mb-8 border border-white/10"
    >
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="font-cosmic text-sm text-white">
          HISTORICAL BATCH RESULTS {h.batchId && <span className="font-mono text-[11px] text-gray-400">· {h.batchId} · {h.batchStatus}</span>}
        </div>
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
            {h.results.map((r) => (
              <Fragment key={r.event_id}>
                <tr className="border-b border-white/5 text-gray-300">
                  <td className="py-2 pr-3 text-white">
                    <button
                      onClick={() => setExpandedId(expandedId === r.event_id ? null : r.event_id)}
                      className="hover:text-cosmic-cyan transition-colors"
                      title="Show this event's LLM rationale"
                    >
                      <span className="text-gray-600 mr-1">{expandedId === r.event_id ? '▲' : '▼'}</span>
                      {r.event_id}
                    </button>
                  </td>
                  <td className="py-2 pr-3">{r.status}</td>
                  <td className="py-2 pr-3">{r.top_host || '—'}</td>
                  <td className="py-2 pr-3 text-right">{r.score === null || r.score === undefined ? '—' : Number(r.score).toFixed(3)}</td>
                  <td className="py-2 pr-3 text-right">{r.airmass === null || r.airmass === undefined ? '—' : Number(r.airmass).toFixed(2)}</td>
                  <td className="py-2 pr-3 text-right">{r.weather_cloud ?? '—'}</td>
                  <td className="py-2 pr-3">{r.tiling || '—'}</td>
                  <td className="py-2">
                    {r.run_id ? (
                      <span className="inline-flex gap-1.5">
                        <button onClick={() => viewRow(r.run_id)} disabled={busyId === r.run_id} className="px-2 py-1 rounded border border-cosmic-cyan/40 text-cosmic-cyan hover:bg-cosmic-cyan/10 disabled:opacity-50">
                          {busyId === r.run_id ? '…' : 'View report'}
                        </button>
                        <button onClick={() => downloadRow(r.run_id)} disabled={busyId === r.run_id} className="px-2 py-1 rounded border border-white/10 text-gray-300 hover:bg-white/5 disabled:opacity-50">
                          PDF
                        </button>
                      </span>
                    ) : (
                      <span className="text-gray-500">{r.error ? 'failed' : '…'}</span>
                    )}
                  </td>
                </tr>
                {expandedId === r.event_id && (
                  <tr key={`${r.event_id}-rationale`} className="border-b border-white/5">
                    <td colSpan={8} className="py-2 pr-3">
                      <div className="rounded-lg bg-black/40 border border-cosmic-magenta/20 p-3">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="font-mono text-[10px] uppercase tracking-widest text-cosmic-magenta">LLM rationale — {r.event_id}</span>
                          {typeof r.confidence === 'number' && (
                            <span className="font-mono text-[10px] px-1.5 py-px rounded-full border border-white/15 text-gray-300">
                              confidence {Math.round(r.confidence * 100)}%
                            </span>
                          )}
                          {r.decision && (
                            <span className={`font-mono text-[10px] px-1.5 py-px rounded-full border ${r.decision === 'ACCEPT' ? 'text-green-400 border-green-500/40' : 'text-red-400 border-red-500/40'}`}>
                              {r.decision}
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-[11px] text-gray-300 whitespace-pre-wrap">
                          {r.rationale || 'No rationale recorded for this run yet.'}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {rowError && (
        <div className="mt-3 font-mono text-[11px] text-red-400">{rowError}</div>
      )}
      <div className="mt-3 font-mono text-[10px] text-gray-500">
        Same pipeline, same report as the LAUNCH button — only the provenance label differs (historical:event_id). Each View report opens that event's own report in the standard preview window. Each run streams live into the Agent Observatory above.
      </div>
    </motion.div>
  )
}
