import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import AgentTerminal from './AgentTerminal'

// One-line meaning for every agent status. MONITORING in particular is a
// *finished* state (overcast / dome unsafe — nothing is running), which the
// bare label never conveyed.
const STATUS_INFO = {
  listening: 'Idle — backend connected, no run active.',
  processing: 'Run in progress — agents are working through the pipeline below.',
  target_acquired: 'Target acquired — human approval required to slew.',
  monitoring: 'Run finished — sky overcast or dome unsafe. Not observing; nothing is running.',
  weather_blocked: 'Run finished — sky overcast or dome unsafe. Not observing; nothing is running.',
  error: 'Run failed — see the error panel and backend logs.',
  rejected: 'Trigger rejected by the ingestion filter — no follow-up.',
  skipped: 'Step skipped — see the timeline for the reason.',
}

export default function DashboardSection({ agentStatus, setAgentStatus, onTargetAcquired }) {
  const [loading, setLoading] = useState(false)
  const [executionTraces, setExecutionTraces] = useState([])
  const [candidates, setCandidates] = useState([])
  const [alertData, setAlertData] = useState(null)
  const [source, setSource] = useState('mock')
  const [llmRationale, setLlmRationale] = useState('')
  const [runId, setRunId] = useState('')
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [reportHtml, setReportHtml] = useState('')
  const [provenance, setProvenance] = useState(null)
  const [showReport, setShowReport] = useState(false)
  const [liveFound, setLiveFound] = useState(false)
  const [liveNote, setLiveNote] = useState('')
  const [runError, setRunError] = useState('')
  const [wakingBackend, setWakingBackend] = useState(false)
  const [eventClasses, setEventClasses] = useState([])
  const [enabledClasses, setEnabledClasses] = useState(['bns'])
  const [simClass, setSimClass] = useState('bns')
  const [watchSaving, setWatchSaving] = useState(false)
  const esRef = useRef(null)
  const finishTimerRef = useRef(null)
  const retryTimerRef = useRef(null)
  const finishedRef = useRef(null)
  const loadingRef = useRef(false)
  loadingRef.current = loading
  const runIdRef = useRef('')
  runIdRef.current = runId
  // Stream connection state: idle | live | reconnecting | closed.
  // The LAUNCH button and the terminal footer both read this, so a dead
  // socket can never again look like a finished run (or vice versa).
  const [streamState, setStreamState] = useState('idle')

  // Close EventSource + timers on unmount
  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close()
      if (finishTimerRef.current) clearTimeout(finishTimerRef.current)
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [])

  // Adopt a finished run (usually auto-fired live, discovered via
  // latest-event) into the full dashboard state: terminal, candidates,
  // provenance, rationale, approval modal when warranted.
  const adoptFinishedRun = (data, sourceOverride) => {
    const ev = data.event || {}
    const classMap = {
      bns: 'Binary Neutron Star Merger',
      grb: 'Gamma-Ray Burst',
      neutrino: 'High-Energy Neutrino Track',
    }
    const agentMap = {
      awaiting_approval: 'target_acquired',
      weather_blocked: 'monitoring',
      error: 'error',
      rejected: 'rejected',
      skipped: 'skipped',
    }
    // Adopt ONLY finished records: adopting a still-running run is what
    // produced the stuck PROCESSING-with-empty-candidates state. A run
    // without finished_at is by definition not done.
    if (!data.finished_at) return
    if (data.status !== 'completed' && data.status !== 'failed' && data.status !== 'skipped') return
    const status = data.status === 'failed'
      ? 'error'
      : (agentMap[ev.agent_status] || (data.status === 'completed' ? 'target_acquired' : 'processing'));
    finishedRef.current = data.run_id
    setStreamState('closed')
    setRunId(data.run_id)
    setAlertData({
      alert_id: ev.trigger_id || ev.ivorn || 'GW170817',
      topic: ev.topic || '',
      event_type: classMap[ev.event_class] || 'Binary Neutron Star Merger',
      ivorn: ev.ivorn || 'GW170817',
      observatory: '',
      source: sourceOverride || data.source || 'mock',
      event_class: ev.event_class || 'bns',
      class_label: ev.class_label || '',
      gate_status: ev.gate_status,
      gate_reason: ev.gate_reason,
    })
    setCandidates(data.candidates || [])
    setAgentStatus(status)
    setSource(sourceOverride || data.source || 'mock')
    setLlmRationale(data.llm_rationale || '')
    setProvenance(data.provenance || null)
    setLiveFound((sourceOverride || data.source) === 'live')
    setLiveNote('')
    setReportMarkdown('')
    setReportHtml('')
    if (Array.isArray(data.execution_traces) && data.execution_traces.length > 0) {
      data.execution_traces.forEach(mergeStep)
    }
    if (status === 'target_acquired') {
      setTimeout(() => onTargetAcquired && onTargetAcquired(), 800)
    }
  }

  // 24/7 review: on open — and every 30s while idle — adopt whatever run
  // finished last (often a poller/Kafka-fired live run nobody clicked for).
  // Never clobbers an in-flight user view.
  useEffect(() => {
    let alive = true
    const checkLatest = async () => {
      if (!alive || loadingRef.current) return
      try {
        const { data } = await axios.get('/api/latest-event')
        if (!alive || loadingRef.current) return
        if (data && data.run_id && data.run_id !== runIdRef.current) {
          adoptFinishedRun(data)
        }
      } catch { /* backend asleep or no runs yet */ }
    }
    checkLatest()
    const timer = setInterval(checkLatest, 30000)
    return () => { alive = false; clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [watchTopics, setWatchTopics] = useState([])
  const [poller, setPoller] = useState(null)

  // Load supported trigger families + live-watch selection once; poller
  // status tells the terminal whether background live discovery is armed.
  useEffect(() => {
    axios.get('/api/event-classes')
      .then(({ data }) => {
        if (Array.isArray(data.classes) && data.classes.length) setEventClasses(data.classes)
        if (Array.isArray(data.enabled) && data.enabled.length) {
          setEnabledClasses(data.enabled)
          if (!data.enabled.includes(simClass)) setSimClass(data.enabled[0])
        }
        if (Array.isArray(data.topics)) setWatchTopics(data.topics)
      })
      .catch(() => {})
    axios.get('/api/ping')
      .then(({ data }) => {
        if (data && data.gracedb_poll) setPoller(data.gracedb_poll)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleWatchClass = async (key) => {
    const next = enabledClasses.includes(key)
      ? enabledClasses.filter((k) => k !== key)
      : [...enabledClasses, key]
    if (next.length === 0) return // at least one family must stay watched
    setWatchSaving(true)
    try {
      const { data: cfg } = await axios.get('/agent/config')
      const { data: updated } = await axios.put('/agent/config', { ...cfg, alert_classes: next })
      setEnabledClasses(updated.alert_classes || next)
      if (!next.includes(simClass)) setSimClass(next[0])
    } catch (err) {
      console.error('Watch toggle failed:', err)
      setRunError('Could not update live-watch selection. The backend may be asleep — retry shortly.')
    } finally {
      setWatchSaving(false)
    }
  }

  // Fetch the finished run state (candidates, rationale, provenance) once
  // the SSE stream delivers the terminal run-finished event.
  const finishRun = async (rid) => {
    if (finishedRef.current === rid) return
    finishedRef.current = rid
    setStreamState('closed')
    try {
      const { data } = await axios.get(`/api/runs/${rid}`)
      setAlertData(data.alert)
      setCandidates(data.candidates || [])
      setAgentStatus(data.status)
      setSource(data.alert?.source || 'mock')
      setLlmRationale(data.llm_rationale || '')
      setProvenance(data.provenance || null) // v3 data-source attribution badge (M4.4)
      setLiveFound(!!data.live_trigger_found)
      setLiveNote(data.live_check_note || '')
      setReportMarkdown('')
      setReportHtml('')
      // Merge the full persisted step history: covers anything emitted
      // before the SSE subscription connected.
      if (Array.isArray(data.execution_traces) && data.execution_traces.length > 0) {
        data.execution_traces.forEach(mergeStep)
      }
      if (data.status === 'target_acquired') {
        setTimeout(() => onTargetAcquired && onTargetAcquired(), 800)
      }
    } catch (error) {
      console.error('Run fetch failed:', error)
      setRunError('Run finished but its results could not be fetched. Reload and check the latest event.')
    } finally {
      if (finishTimerRef.current) clearTimeout(finishTimerRef.current)
      setStreamState('closed')
      setLoading(false)
    }
  }

  const simulateEvent = async () => {
    // Double-click guard: the disabled attribute needs a render to take
    // effect, so rapid clicks could otherwise launch overlapping 429s.
    if (loadingRef.current) return
    finishedRef.current = null
    if (esRef.current) esRef.current.close()
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    setStreamState('idle')
    setLoading(true)
    setRunError('')
    setLiveFound(false)
    setLiveNote('')
    setExecutionTraces([])
    setCandidates([])
    setAlertData(null)
    setReportMarkdown('')

    // Wake-then-launch: Render free spins down after ~15 min idle — ping
    // until the backend answers (up to ~90s) BEFORE launching anything.
    setWakingBackend(true)
    const warmDeadline = Date.now() + 90000
    let warm = false
    while (Date.now() < warmDeadline) {
      try {
        await axios.get('/api/ping', { timeout: 10000 })
        warm = true
        break
      } catch {
        await new Promise((r) => setTimeout(r, 5000))
      }
    }
    setWakingBackend(false)
    if (!warm) {
      setRunError('Backend did not wake within 90 seconds — Render may be queuing the free instance. Wait a minute and launch again.')
      setLoading(false)
      return
    }

    // Streaming launch: POST returns instantly with a run id; steps arrive
    // over SSE as each agent finishes, and completion triggers the fetch.
    // Guard: if no finish event arrives in ~5 minutes, stop waiting loudly.
    try {
      const { data } = await axios.post(
        `/api/simulate-event?event_class=${encodeURIComponent(simClass)}`,
        null, { timeout: 30000 })
      const rid = data.run_id
      if (!rid) throw new Error('backend did not return a run id')
      setRunId(rid)
      startEventStream(rid, () => finishRun(rid))
      finishTimerRef.current = setTimeout(() => {
        setRunError('Run is taking unusually long (no finish event in 5 minutes). It may still complete server-side — check back shortly.')
        setLoading(false)
      }, 5 * 60 * 1000)
    } catch (error) {
      console.error('Launch failed:', error)
      const status = error?.response?.status
      const detail = error?.response?.data?.detail
      if (error?.code === 'ECONNABORTED' || /timeout/i.test(error?.message || '')) {
        setRunError('Launch request timed out — the backend may be waking up. Wait ~60 seconds and launch again.')
      } else if (error?.request && !error?.response) {
        setRunError('Could not reach the backend. If it just woke from sleep, wait ~60 seconds and launch again.')
      } else if (status === 429) {
        const d = error?.response?.data?.detail
        const busyRun = d && typeof d === 'object' ? d.run_id : null
        if (busyRun) {
          // A run (live trigger or earlier demo) is already in flight:
          // attach this tab to its live telemetry instead of erroring out.
          setRunId(busyRun)
          setLiveFound(false)
          setLiveNote(`Pipeline busy — attached to the in-progress run ${busyRun}. Watch it stream below.`)
          startEventStream(busyRun, () => finishRun(busyRun))
          finishTimerRef.current = setTimeout(() => {
            setRunError('Run is taking unusually long (no finish event in 5 minutes). It may still complete server-side — check back shortly.')
            setLoading(false)
          }, 5 * 60 * 1000)
        } else {
          setRunError('Pipeline busy — another run is in progress. Wait for it to finish, then launch again.')
          setLoading(false)
        }
      } else if (status === 502 || status === 503 || status === 504) {
        setRunError(`Backend unavailable (HTTP ${status}). It may be restarting — wait a minute and launch again.`)
        setLoading(false)
      } else if (status) {
        setRunError(detail && typeof detail === 'string' ? `Backend error (HTTP ${status}): ${detail}` : `Backend returned HTTP ${status}. Check the service logs and try again.`)
        setLoading(false)
      } else {
        setRunError(`Launch failed: ${error?.message || 'unknown error'}. Try again.`)
        setLoading(false)
      }
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
        started_at: step.started_at || '',
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

  const MAX_SSE_RETRIES = 5

  const startEventStream = (runId, onFinish, attempt = 0) => {
    if (!runId) return
    if (esRef.current) esRef.current.close()
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    let finished = false
    const evtSource = new EventSource(`/api/runs/${runId}/events`)
    evtSource.onmessage = (evt) => {
      try {
        const step = JSON.parse(evt.data)
        setStreamState('live')
        mergeStep(step)
        // Terminal run-finished marker (emitted by finish_run): stop the
        // stream and pull the complete run state.
        const terminal = ['completed', 'failed', 'skipped'].includes(step.status)
        if (!finished && step.tool_name === 'run' && terminal) {
          finished = true
          evtSource.close()
          setStreamState('closed')
          if (onFinish) onFinish()
          else setLoading(false)
        }
      } catch { /* ignore malformed frame */ }
    }
    evtSource.onerror = () => {
      // Do NOT close-and-forget here (that single line caused the stuck
      // "1 event, stream closed" state): verify the run still exists, then
      // reconnect with backoff. Native EventSource auto-retry cannot do the
      // 404 check, so the retry loop is manual.
      evtSource.close()
      if (finished) return
      axios.get(`/api/runs/${runId}`).then(
        () => {
          if (finished) return
          if (attempt >= MAX_SSE_RETRIES) {
            setStreamState('closed')
            if (onFinish) onFinish() // backstop: persisted history still resolves
            return
          }
          setStreamState('reconnecting')
          retryTimerRef.current = setTimeout(() => {
            startEventStream(runId, onFinish, attempt + 1)
          }, 1500 * (attempt + 1))
        },
        () => {
          // Run id unknown to the backend (e.g. restart wiped history):
          // stop retrying and say so instead of hanging.
          setStreamState('closed')
          if (!finished) {
            finished = true
            setRunError('Lost contact with the run (backend restarted or history expired). Reload to check the latest event.')
            setLoading(false)
          }
        }
      )
    }
    esRef.current = evtSource
    setStreamState('live')
  }

  const openReport = async () => {
    if (!runId) return
    try {
      const { data } = await axios.get(`/api/runs/${runId}/report`)
      setReportMarkdown(data.markdown || data.content || '')
      setReportHtml(data.html || '')
      setShowReport(true)
    } catch (e) {
      console.error('report fetch failed', e)
    }
  }

  const printReport = async () => {
    // v3 PRD M6.5 Option C: print the rich HTML report (embeds visualizations
    // and calculation traces + a print-optimized stylesheet).
    if (!runId) return
    let htmlDoc = reportHtml
    let mdDoc = reportMarkdown
    if (!htmlDoc && !mdDoc) {
      try {
        const { data } = await axios.get(`/api/runs/${runId}/report`)
        htmlDoc = data.html || ''
        mdDoc = data.markdown || data.content || ''
        setReportHtml(htmlDoc)
        setReportMarkdown(mdDoc)
      } catch (e) {
        console.error('report fetch failed', e)
        return
      }
    }
    const win = window.open('', '_blank')
    if (!win) return
    if (htmlDoc) {
      win.document.write(htmlDoc)
      win.document.close()
      win.focus()
      win.print()
    } else if (mdDoc) {
      const pre = win.document.createElement('pre')
      pre.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
      pre.style.fontSize = '13px'
      pre.style.padding = '24px'
      pre.style.whiteSpace = 'pre-wrap'
      pre.textContent = mdDoc
      win.document.body.appendChild(pre)
      win.document.close()
      win.print()
    }
  }

  // Rich HTML report (embedded visualizations, calculation traces, print CSS) —
  // PRD M6.6. Falls back to the inline markdown renderer only if no HTML body
  // came back from the server.
  const renderReportBody = () => {
    if (reportHtml) {
      return (
        <iframe
          title="KilonovaScout Observation Report"
          srcDoc={reportHtml}
          className="w-full h-full min-h-[60vh] bg-white rounded-lg border border-white/10"
          sandbox="allow-same-origin"
        />
      )
    }
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
            Listening to the live NASA GCN stream — triage fires on the latest trigger across every watched family.
            When the sky is quiet, the agent replays an archived event as a fallback simulation.
          </p>

          {/* Cosmic events — one panel: pick the demo trigger (radio) and
              toggle live Kafka watch per family (persisted to backend). */}
          <div className="max-w-3xl mx-auto mb-8 glass rounded-2xl border border-white/10 p-5 text-left">
            <div className="font-mono text-[10px] text-gray-500 uppercase tracking-widest mb-1 text-center">
              Cosmic events {watchSaving && <span className="text-yellow-400">· saving…</span>}
            </div>
            <div className="font-mono text-[10px] text-gray-600 mb-4 text-center">
              <span className="text-cosmic-cyan">◉ simulate</span> = demo trigger &nbsp;·&nbsp;
              <span className="text-green-400">● watch</span> = live Kafka subscription
            </div>
            <div className="space-y-2">
              {(eventClasses.length ? eventClasses : [{ key: 'bns', label: 'Neutron-star merger', blurb: '' }]).map((c) => {
                const picked = simClass === c.key
                const watched = enabledClasses.includes(c.key)
                return (
                  <div
                    key={c.key}
                    className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition-all ${
                      picked ? 'border-cosmic-cyan/50 bg-cosmic-cyan/5' : 'border-white/10 hover:border-white/25'
                    }`}
                  >
                    <button
                      onClick={() => setSimClass(c.key)}
                      disabled={loading}
                      title={`Simulate a ${c.label} trigger`}
                      className={`font-mono text-sm w-6 text-center transition-colors disabled:opacity-50 ${
                        picked ? 'text-cosmic-cyan' : 'text-gray-600 hover:text-gray-300'
                      }`}
                    >
                      {picked ? '◉' : '○'}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="font-cosmic text-sm text-white">{c.label}</div>
                      {c.blurb && <div className="font-mono text-[11px] text-gray-500 truncate">{c.blurb}</div>}
                    </div>
                    <button
                      onClick={() => toggleWatchClass(c.key)}
                      disabled={loading || watchSaving}
                      title={watched ? `Watching ${c.label} live — click to mute` : `Muted — click to watch ${c.label} live`}
                      className={`font-mono text-[11px] px-3 py-1.5 rounded-lg border transition-all disabled:opacity-50 ${
                        watched
                          ? 'border-green-400/50 bg-green-500/10 text-green-300'
                          : 'border-white/10 text-gray-600 hover:border-white/25 hover:text-gray-400'
                      }`}
                    >
                      {watched ? '● WATCH' : '○ MUTED'}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          <button
            onClick={simulateEvent}
            disabled={loading}
            className="px-12 py-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-lg hover:opacity-90 transition-opacity glow-cyan disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading
              ? (wakingBackend ? 'WAKING BACKEND…' : (streamState === 'reconnecting' ? 'RECONNECTING…' : 'PROCESSING…'))
              : `LAUNCH ${((eventClasses.find((c) => c.key === simClass) || {}).label || simClass || 'GCN').toUpperCase()} ALERT`}
          </button>

          {wakingBackend && loading && (
            <p className="font-mono text-xs text-yellow-400 mt-4 max-w-xl mx-auto">
              Backend is waking up — Render free-tier cold starts can take ~60s. The pipeline runs automatically once it responds.
            </p>
          )}

          {runError && !loading && (
            <div className="mt-6 max-w-2xl mx-auto glass rounded-xl p-4 border border-red-400/40 text-left">
              <div className="font-cosmic text-sm text-red-400 mb-1">LAUNCH FAILED</div>
              <div className="font-mono text-xs text-gray-300">{runError}</div>
            </div>
          )}

          {(liveFound || liveNote) && !loading && (
            <div className={`mt-6 max-w-2xl mx-auto glass rounded-xl p-4 border text-left ${
              liveFound ? 'border-green-400/40' : 'border-white/10'
            }`}>
              <div className={`font-cosmic text-sm mb-1 ${liveFound ? 'text-green-400' : 'text-gray-400'}`}>
                {liveFound ? 'LIVE TRIGGER' : 'SKY CHECK'}
              </div>
              <div className="font-mono text-xs text-gray-300">
                {liveFound
                  ? liveNote
                  : (liveNote || 'No live trigger pending — fallback simulation (mock packet, live catalog where reachable).')}
              </div>
            </div>
          )}
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
                agentStatus === 'skipped' ? 'text-gray-400' :
                'text-cosmic-cyan'
              }`}>
                {agentStatus.toUpperCase().replace('_', ' ')}
              </div>
              <div className="font-mono text-[11px] text-gray-500 mt-1">
                {STATUS_INFO[agentStatus] || ''}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={`text-[10px] font-mono px-2 py-1 rounded border ${
                source === 'live' ? 'border-green-400/40 text-green-400' : 'border-white/10 text-gray-300'
              }`}>
                {source === 'live' ? '● LIVE GCN' : `MOCK ${(alertData?.class_label || 'GW170817').toUpperCase()}`}
              </span>
              <div className={`w-4 h-4 rounded-full ${
                agentStatus === 'listening' ? 'bg-gray-400' :
                agentStatus === 'processing' ? 'bg-yellow-400 animate-pulse' :
                agentStatus === 'target_acquired' ? 'bg-green-400 animate-pulse' :
                agentStatus === 'weather_blocked' ? 'bg-orange-400 animate-pulse' :
                agentStatus === 'rejected' ? 'bg-red-400' :
                agentStatus === 'skipped' ? 'bg-gray-400' :
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

        {/* Mission-log console: full backend workflow — agent + tool per
            row, indented subagent retries, fallback tiers, in/out payloads */}
        <AgentTerminal
          traces={executionTraces}
          provenance={provenance}
          runId={runId}
          source={source}
          agentStatus={agentStatus}
          loading={loading}
          streamState={streamState}
          eventClass={alertData?.event_class || simClass}
          classLabel={alertData?.class_label || ''}
          topic={alertData?.topic || ''}
          watchTopics={watchTopics}
          poller={poller}
        />

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
              {alertData.gate_reason && (
                <div className="md:col-span-2 mt-1">
                  <span className="text-gray-400">Triage [{alertData.gate_status || 'UNKNOWN'}]:</span>{' '}
                  <span className="text-white">{alertData.gate_reason}</span>
                </div>
              )}
            </div>
            {provenance && (
              <div className="mt-4 pt-3 border-t border-white/10 flex flex-wrap gap-2">
                <span className="text-gray-500 font-mono text-[10px] uppercase tracking-wider self-center">Data provenance:</span>
                {Object.entries(provenance).map(([key, value]) => (
                  <span
                    key={key}
                    className={`font-mono text-[10px] px-2 py-0.5 rounded-full border ${
                      value === 'live'
                        ? 'text-green-400 border-green-500/40 bg-green-500/10'
                        : value === 'replay' || value === 'cached'
                        ? 'text-amber-400 border-amber-500/40 bg-amber-500/10'
                        : 'text-gray-400 border-white/15 bg-white/5'
                    }`}
                  >
                    {key}: {value}
                  </span>
                ))}
              </div>
            )}
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
                        // v3 full formula (PRD M10):
                        // S = α·P + β·w_Sch − γ·X̄ − δ·C + ε·B + ζ·SNR − η·L_moon
                        const t = candidate.score_breakdown.terms || {}
                        const w = candidate.score_breakdown.weights || {}
                        const fmt = (v) => Number(v || 0).toFixed(2)
                        const f = (v) => Number(v).toFixed(3)
                        const alpha = w.alpha
                        const beta = w.beta
                        const gamma = w.gamma
                        const delta = w.delta
                        const zeta = w.zeta
                        const eta = w.eta
                        const hasSg = (t.schechter != null) || (t.lunar != null) || (t.snr != null)
                        if (hasSg) {
                          return `S = ${fmt(alpha)}×${fmt(t.spatial)} + ${fmt(beta)}×${fmt(t.schechter)} − ${fmt(gamma)}×${fmt(t.airmass)} − ${fmt(delta)}×${fmt(t.cloud)} + ${fmt(t.grb_boost ?? 0)} + ${fmt(zeta)}×${fmt(t.snr)} − ${fmt(eta)}×${fmt(t.lunar)} = ${f(candidate.composite_score)}`
                        }
                        return `S = ${fmt(alpha)}×${fmt(t.spatial)} + ${fmt(beta)}×${fmt(t.schechter ?? t.mass)} − ${fmt(gamma)}×${fmt(t.airmass)} − ${fmt(delta)}×${fmt(t.cloud)} = ${f(candidate.composite_score)}`
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
              className="glass rounded-xl border border-cosmic-cyan/30 w-full max-w-5xl max-h-[85vh] flex flex-col"
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