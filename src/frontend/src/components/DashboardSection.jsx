import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'

export default function DashboardSection({ agentStatus, setAgentStatus, onTargetAcquired }) {
  const [loading, setLoading] = useState(false)
  const [executionTraces, setExecutionTraces] = useState([])
  const [candidates, setCandidates] = useState([])
  const [alertData, setAlertData] = useState(null)
  const [source, setSource] = useState('mock')
  const [llmRationale, setLlmRationale] = useState('')
  const [runId, setRunId] = useState('')
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [showReport, setShowReport] = useState(false)
  const [expandedTrace, setExpandedTrace] = useState(null)
  const esRef = useRef(null)
  const tracesEndRef = useRef(null)

  // Close EventSource on unmount
  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close()
    }
  }, [])

  // Auto-scroll trace list
  useEffect(() => {
    if (tracesEndRef.current) {
      tracesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [executionTraces.length])

  const simulateEvent = async () => {
    setLoading(true)
    setExecutionTraces([])
    setCandidates([])
    setAlertData(null)
    setReportMarkdown('')

    try {
      const response = await axios.post('/api/simulate-event')
      const data = response.data
      setAlertData(data.alert)
      setCandidates(data.candidates || [])
      setAgentStatus(data.status)
      setSource(data.alert?.source || 'mock')
      setLlmRationale(data.llm_rationale || '')

      // Seed with the measured traces from the response (they may arrive before SSE connects)
      if (Array.isArray(data.execution_traces) && data.execution_traces.length > 0) {
        setExecutionTraces(data.execution_traces.map((t, i) => ({ ...t, _key: `${t.step}-${i}` })))
      }

      if (data.run_id) {
        setRunId(data.run_id)
        startEventStream(data.run_id)
      }

      if (data.status === 'target_acquired') {
        setTimeout(() => onTargetAcquired && onTargetAcquired(), 800)
      }
    } catch (error) {
      console.error('Simulation failed:', error)
    } finally {
      setLoading(false)
    }
  }

  // Merge incoming SSE step events into the timeline: same (step, tool) is one card,
  // updated in place (running -> completed/failed), so spinners become checks.
  const mergeStep = (step) => {
    setExecutionTraces(prev => {
      const existing = [...prev]
      const idx = existing.findIndex(e => e.step === step.step && e.tool_name === step.tool_name)
      const card = {
        step: step.step,
        tool_name: step.tool_name,
        status: step.status,
        attempt: step.attempt,
        duration_ms: step.duration_ms,
        error: step.error || '',
        input_summary: step.input_summary || '',
        output_summary: step.output_summary || '',
      }
      if (idx >= 0) {
        // Never let a stale replayed event regress a finished card:
        // terminal states win, running only fills an unfinished card.
        const prevTerminal = ['completed', 'failed', 'skipped'].includes(existing[idx].status)
        const nextTerminal = ['completed', 'failed', 'skipped'].includes(card.status)
        if (nextTerminal || !prevTerminal) {
          existing[idx] = { ...existing[idx], ...card }
        }
      } else {
        existing.push(card)
      }
      return existing
    })
  }

  const startEventStream = (runId) => {
    if (!runId) return
    if (esRef.current) esRef.current.close()
    const evtSource = new EventSource(`/api/runs/${runId}/events`)
    evtSource.onmessage = (evt) => {
      try {
        const step = JSON.parse(evt.data)
        mergeStep(step)
      } catch { /* ignore malformed frame */ }
    }
    evtSource.onerror = () => {
      evtSource.close()
    }
    esRef.current = evtSource
  }

  const openReport = async () => {
    if (!runId) return
    try {
      const { data } = await axios.get(`/api/report/${runId}`)
      setReportMarkdown(data.content)
      setShowReport(true)
    } catch (e) {
      console.error('report fetch failed', e)
    }
  }

  const printReport = () => {
    const win = window.open('', '_blank')
    if (!win || !reportMarkdown) return
    const pre = win.document.createElement('pre')
    pre.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    pre.style.fontSize = '13px'
    pre.style.padding = '24px'
    pre.style.whiteSpace = 'pre-wrap'
    pre.textContent = reportMarkdown
    win.document.body.appendChild(pre)
    win.document.close()
    win.print()
  }

  // Simple inline markdown-ish renderer for the report body (headings, tables stay pre-like)
  const renderReportBody = () => {
    if (!reportMarkdown) return null
    return reportMarkdown
      .split('\n')
      .map((line, i) => {
        if (line.startsWith('# ')) return <h1 key={i} className="font-cosmic text-2xl text-cosmic-cyan mb-3">{line.slice(2)}</h1>
        if (line.startsWith('## ')) return <h2 key={i} className="font-cosmic text-lg text-cosmic-magenta mt-5 mb-2">{line.slice(3)}</h2>
        if (line.startsWith('### ')) return <h3 key={i} className="font-cosmic text-base text-white mt-3 mb-1">{line.slice(4)}</h3>
        if (line.startsWith('- ')) return <div key={i} className="font-mono text-xs text-gray-300 py-0.5">{line.slice(2)}</div>
        if (line.startsWith('| ')) return <div key={i} className="font-mono text-xs text-gray-300 py-0.5">{line}</div>
        if (line.startsWith('```')) return <div key={i} className="text-gray-500 py-1">{line}</div>
        if (line.trim() === '') return <div key={i} className="h-2" />
        return <div key={i} className="font-mono text-xs text-gray-300 py-0.5 whitespace-pre-wrap">{line}</div>
      })
  }

  return (
    <section id="dashboard" className="relative py-32 px-4">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-cosmic-cyan/5 to-transparent" />

      <div className="relative z-10 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="text-center mb-16"
        >
          <h2 className="font-cosmic text-5xl md:text-6xl font-bold mb-6 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">
            LIVE DEMO
          </h2>
          <p className="font-grotesk text-xl text-gray-400 max-w-3xl mx-auto mb-8">
            Simulate the famous GW170817 neutron star merger event
          </p>

          <button
            onClick={simulateEvent}
            disabled={loading}
            className="px-12 py-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-lg hover:opacity-90 transition-opacity glow-cyan disabled:opacity-50"
          >
            {loading ? 'PROCESSING...' : 'SIMULATE GCN ALERT'}
          </button>
        </motion.div>

        {/* Status indicator + source badge */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          className="glass rounded-xl p-6 mb-8 border border-white/10"
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="font-mono text-xs text-gray-400 mb-1">AGENT STATUS</div>
              <div className={`font-cosmic text-2xl font-bold ${
                agentStatus === 'listening' ? 'text-gray-400' :
                agentStatus === 'processing' ? 'text-yellow-400' :
                agentStatus === 'target_acquired' ? 'text-green-400' :
                agentStatus === 'weather_blocked' ? 'text-orange-400' :
                agentStatus === 'rejected' ? 'text-red-400' :
                'text-cosmic-cyan'
              }`}>
                {agentStatus.toUpperCase().replace('_', ' ')}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={`text-[10px] font-mono px-2 py-1 rounded border ${
                source === 'live' ? 'border-green-400/40 text-green-400' : 'border-white/10 text-gray-300'
              }`}>
                {source === 'live' ? '● LIVE GCN' : 'MOCK GW170817'}
              </span>
              <div className={`w-4 h-4 rounded-full ${
                agentStatus === 'listening' ? 'bg-gray-400' :
                agentStatus === 'processing' ? 'bg-yellow-400 animate-pulse' :
                agentStatus === 'target_acquired' ? 'bg-green-400 animate-pulse' :
                agentStatus === 'weather_blocked' ? 'bg-orange-400 animate-pulse' :
                agentStatus === 'rejected' ? 'bg-red-400' :
                'bg-cosmic-cyan'
              }`} />
            </div>
          </div>
        </motion.div>

        {llmRationale && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 mb-8 border border-cosmic-magenta/30"
          >
            <div className="font-cosmic text-sm text-cosmic-magenta mb-2">LLM RATIONALE</div>
            <div className="font-mono text-xs text-gray-300">{llmRationale}</div>
          </motion.div>
        )}

        {/* Live execution timeline (M3: real-time, spinner -> check, expanders) */}
        {executionTraces.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 mb-8 border border-cosmic-cyan/30"
          >
            <div className="font-cosmic text-sm text-cosmic-cyan mb-4">LIVE AGENT TIMELINE</div>
            <div className="space-y-3 font-mono text-xs max-h-96 overflow-y-auto pr-2">
              {executionTraces.map((trace, index) => {
                const isRunning = trace.status === 'running'
                const isFailed = trace.status === 'failed' || trace.status === 'skipped'
                return (
                  <motion.div
                    key={`${trace.step}-${trace.tool_name}`}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex flex-col gap-2"
                  >
                    <div className="flex items-start gap-3">
                    <span className="text-gray-500">[{trace.step}]</span>
                    <span className="text-cosmic-magenta">{trace.tool_name}()</span>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      isRunning ? 'bg-yellow-500/20 text-yellow-400 animate-pulse' :
                      isFailed ? 'bg-red-500/20 text-red-400' :
                      'bg-green-500/20 text-green-400'
                    }`}>
                      {isRunning ? '⟳ ' : isFailed ? '✗ ' : '✓ '}{trace.status.toUpperCase()}
                    </span>
                    {trace.duration_ms != null && (
                      <span className="text-gray-500">{trace.duration_ms}ms</span>
                    )}
                    {trace.attempt > 1 && (
                      <span className="text-yellow-400">attempt {trace.attempt}</span>
                    )}
                    <button
                      onClick={() => setExpandedTrace(expandedTrace === `${trace.step}-${trace.tool_name}` ? null : `${trace.step}-${trace.tool_name}`)}
                      className="text-gray-500 hover:text-cosmic-cyan transition-colors"
                    >
                      {expandedTrace === `${trace.step}-${trace.tool_name}` ? '▲' : '▼'}
                    </button>
                    </div>
                    {expandedTrace === `${trace.step}-${trace.tool_name}` && (
                      <div className="w-full mt-1 p-3 bg-black/50 rounded border border-white/5">
                        {trace.input_summary && (
                          <div className="mb-2">
                            <span className="text-gray-500">in: </span>
                            <span className="text-gray-300 break-all">{typeof trace.input_summary === 'string' ? trace.input_summary : JSON.stringify(trace.input_summary)}</span>
                          </div>
                        )}
                        {trace.output_summary && (
                          <div className="mb-2">
                            <span className="text-gray-500">out: </span>
                            <span className="text-gray-300 break-all">{typeof trace.output_summary === 'string' ? trace.output_summary : JSON.stringify(trace.output_summary)}</span>
                          </div>
                        )}
                        {trace.error && (
                          <div>
                            <span className="text-red-400">err: </span>
                            <span className="text-red-300 break-all">{trace.error}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </motion.div>
                )
              })}
              <div ref={tracesEndRef} />
            </div>
          </motion.div>
        )}

        {/* Alert data */}
        {alertData && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 mb-8 border border-cosmic-magenta/30"
          >
            <div className="font-cosmic text-sm text-cosmic-magenta mb-4">ALERT DATA</div>
            <div className="grid md:grid-cols-2 gap-4 font-mono text-xs">
              <div>
                <span className="text-gray-400">Event ID:</span>{' '}
                <span className="text-white">{alertData.alert_id}</span>
              </div>
              <div>
                <span className="text-gray-400">Type:</span>{' '}
                <span className="text-white">{alertData.event_type}</span>
              </div>
              <div>
                <span className="text-gray-400">IVORN:</span>{' '}
                <span className="text-white">{alertData.ivorn}</span>
              </div>
              <div>
                <span className="text-gray-400">Observatory:</span>{' '}
                <span className="text-white">{alertData.observatory}</span>
              </div>
            </div>
          </motion.div>
        )}

        {/* Candidates + report buttons */}
        {candidates.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 border border-green-400/30"
          >
            <div className="flex items-center justify-between mb-4">
              <div className="font-cosmic text-sm text-green-400">
                TARGET CANDIDATES ({candidates.length})
              </div>
              <div className="flex gap-2">
                <button onClick={openReport} className="px-3 py-1.5 rounded border border-white/10 text-xs font-mono hover:bg-white/5">
                  View Report
                </button>
                <button onClick={printReport} className="px-3 py-1.5 rounded border border-white/10 text-xs font-mono hover:bg-white/5">
                  Download PDF
                </button>
              </div>
            </div>
            <div className="space-y-3">
              {candidates.map((candidate, index) => (
                <div
                  key={index}
                  className="bg-black/50 rounded-lg p-4 border border-white/5"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-cosmic text-sm text-cosmic-cyan">
                      {candidate.name}
                    </div>
                    <div className="flex items-center gap-2">
                      {candidate.normalized_priority != null && (
                        <div className="font-mono text-xs text-cosmic-magenta">
                          P{candidate.normalized_priority.toFixed(1)}
                        </div>
                      )}
                      <div className="font-mono text-xs text-green-400">
                        S={candidate.composite_score.toFixed(2)}
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 font-mono text-xs text-gray-400">
                    <div>RA: {candidate.ra.toFixed(4)}°</div>
                    <div>Dec: {candidate.dec.toFixed(4)}°</div>
                    <div>Dist: {candidate.distance_mpc} Mpc</div>
                    <div>Prob: {(candidate.probability * 100).toFixed(0)}%</div>
                  </div>
                  {candidate.score_breakdown && (
                    <div className="mt-2 font-mono text-[11px] text-gray-500">
                      {(() => {
                        const t = candidate.score_breakdown.terms || {}
                        const w = candidate.score_breakdown.weights || {}
                        const fmt = (v) => Number(v).toFixed(2)
                        const f = (v) => Number(v).toFixed(3)
                        return `S = ${fmt(w.spatial_prior)}×${fmt(t.spatial)} + ${fmt(w.galaxy_mass_prior)}×${fmt(t.mass)} − ${fmt(w.airmass_penalty)}×${fmt(t.airmass)} − ${fmt(w.cloud_cover_penalty)}×${fmt(t.cloud)} = ${f(candidate.composite_score)}`
                      })()}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </div>

      {/* Report modal (M2) */}
      <AnimatePresence>
        {showReport && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
            onClick={() => setShowReport(false)}
          >
            <motion.div
              initial={{ scale: 0.92, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.92, y: 20 }}
              onClick={e => e.stopPropagation()}
              className="glass rounded-xl border border-cosmic-cyan/30 w-full max-w-3xl max-h-[85vh] flex flex-col"
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
                <div className="font-cosmic text-sm text-cosmic-cyan">OBSERVATION REPORT</div>
                <div className="flex gap-2">
                  <button onClick={printReport} className="px-3 py-1.5 rounded border border-cosmic-cyan/40 text-xs font-mono hover:bg-cosmic-cyan/10">
                    Download PDF
                  </button>
                  <button onClick={() => setShowReport(false)} className="px-3 py-1.5 rounded border border-white/10 text-xs font-mono hover:bg-white/5">
                    ✕ Close
                  </button>
                </div>
              </div>
              <div className="p-6 overflow-y-auto flex-1">
                {renderReportBody()}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}