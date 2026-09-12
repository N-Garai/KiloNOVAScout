import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

// Maps a backend tool_name to its owning agent. Bare names (no dot) are
// inner retry/fallback attempts emitted by _try_step — rendered indented
// as subagent work under the parent step.
const AGENT_OF = [
  [/^ingestion/, 'Ingestion Agent'],
  [/^healpix/, 'HEALPix Triage'],
  [/^repointing/, 'HEALPix Triage'],
  [/^galaxy/, 'Galaxy Crossmatch'],
  [/^weather/, 'Ephemeris & Weather'],
  [/^ephemeris/, 'Ephemeris & Weather'],
  [/^validator/, 'GRB Validator'],
  [/^scheduler/, 'Scheduler'],
  [/^dome/, 'Dome Safety'],
  [/^llm/, 'LLM Rationale'],
  [/^choose_visualizations/, 'LLM Rationale'],
  [/^generate_run_visualizations/, 'LLM Rationale'],
  [/^viz/, 'LLM Rationale'],
  [/^notify/, 'Notifier'],
  [/^fits/, 'Report Writer'],
  [/^run/, 'Orchestrator'],
]

const AGENT_SKILLS_TOOLS = {
  'Ingestion Agent': { tools: ['ingestion.filter_gcn'], skills: ['event_classes'] },
  'HEALPix Triage': { tools: ['parse_healpix_map','build_point_skymap'], skills: ['astrometry'] },
  'Galaxy Crossmatch': { tools: ['query_glade_catalog','compute_full_score'], skills: ['catalog','scoring'] },
  'Ephemeris & Weather': { tools: ['integrated_airmass','check_observatory_weather'], skills: ['ephemeris','weather'] },
  'GRB Validator': { tools: ['validator.multimessenger'], skills: ['coincidence'] },
  'Scheduler': { tools: ['optimize_slew_order','generate_telescope_slew_script'], skills: ['scheduling','tiling'] },
  'LLM Rationale': { tools: ['llm.rationale','llm.triage_advice','llm.host_explain','choose_visualizations_llm','generate_run_visualizations'], skills: ['reasoning','visualization'] },
  'Report Writer': { tools: ['build_report_markdown','build_report_html'], skills: ['writing','latex'] },
  'Dome Safety': { tools: ['check_dome_safety'], skills: ['safety'] },
  'Notifier': { tools: ['send_sms_alert'], skills: ['safety'] },
}

const agentOf = (toolName = '') => {
  for (const [re, agent] of AGENT_OF) {
    if (re.test(toolName)) return agent
  }
  return 'Orchestrator'
}

const tierOf = (trace, provenance) => {
  const m = /\[tier=([a-z]+)\]/.exec(trace.output_summary || '')
  if (m) return m[1]
  // Family fallback from the run's backend-attached provenance record.
  if (/^healpix/.test(trace.tool_name || '')) return provenance?.skymap || null
  if (/^galaxy/.test(trace.tool_name || '')) return provenance?.catalog || null
  return null
}

const TIER_CLASS = {
  live: 'text-green-400 border-green-500/40 bg-green-500/10',
  replay: 'text-amber-400 border-amber-500/40 bg-amber-500/10',
  cached: 'text-amber-400 border-amber-500/40 bg-amber-500/10',
  // point = map built from the notice's own coordinates (real localization,
  // no FITS download). Sky-tinted: honest data, distinct from live + mock.
  point: 'text-sky-300 border-sky-500/40 bg-sky-500/10',
  synthetic: 'text-gray-400 border-white/15 bg-white/5',
  mock: 'text-gray-400 border-white/15 bg-white/5',
}

const tierChip = (tier) => {
  if (!tier) return null
  return (
    <span className={`font-mono text-[10px] px-1.5 py-px rounded border ${TIER_CLASS[tier] || TIER_CLASS.mock}`}>
      {tier.toUpperCase()}
    </span>
  )
}

const fmtTime = (iso) => {
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return '--:--:--'
    return d.toLocaleTimeString('en-GB', { hour12: false })
  } catch {
    return '--:--:--'
  }
}

const STATUS = {
  running: { glyph: '▸', cls: 'text-yellow-400 animate-pulse' },
  completed: { glyph: '✓', cls: 'text-green-400' },
  failed: { glyph: '✗', cls: 'text-red-400' },
  skipped: { glyph: '○', cls: 'text-gray-400' },
}

// In-flow mission-log console: every backend step event rendered
// chronologically — agent + tool, indented subagent retries, durations,
// errors, and the live→fallback tier won by each data stage.
export default function AgentTerminal({ traces = [], provenance = null, runId = '', source = 'mock', agentStatus = 'listening', loading = false, eventClass = 'bns', classLabel = '', topic = '', watchTopics = [], poller = null, streamState = 'idle' }) {
  const pollOn = !!(poller && poller.enabled)
  const isRunning = agentStatus === 'processing'
  const [expanded, setExpanded] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [traces.length])

  const keyOf = (t) => `${t.step}-${t.tool_name}-${t.attempt}-${t.status}`

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-8 rounded-2xl border border-white/15 bg-[#0a0d13] overflow-hidden"
    >
      {/* Title bar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10 bg-black/40">
        <span className="w-3 h-3 rounded-full bg-red-500/80" />
        <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
        <span className="w-3 h-3 rounded-full bg-green-500/80" />
        <span className="ml-2 font-mono text-xs text-gray-300 tracking-wider">
          KiloNovaScout - Agent Observatory
        </span>
        <div className="ml-auto flex items-center gap-2">
          {runId && (
            <span className="font-mono text-[10px] text-gray-500 hidden sm:inline">
              {runId}
            </span>
          )}
          <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-cosmic-magenta/40 text-cosmic-magenta">
            {(classLabel || eventClass || 'bns').toUpperCase()}
          </span>
          <span className={`font-mono text-[10px] px-2 py-0.5 rounded border ${
            source === 'live' ? 'border-green-400/40 text-green-400' : 'border-white/10 text-gray-400'
          }`}>
            {source === 'live' ? '● LIVE GCN' : 'MOCK REPLAY'}
          </span>
          <span className={`font-mono text-[10px] px-2 py-0.5 rounded border ${
            agentStatus === 'target_acquired' ? 'border-green-400/40 text-green-400' :
            agentStatus === 'processing' ? 'border-yellow-400/40 text-yellow-400 animate-pulse' :
            'border-white/10 text-gray-400'
          }`}>
            {agentStatus.toUpperCase().replace('_', ' ')}
          </span>
        </div>
      </div>

      {/* Signal path: which stream this trigger arrived on */}
      {topic !== '' && (
        <div className="px-4 py-2 border-b border-white/10 bg-black/20 font-mono text-[10px]">
          <span className="text-gray-500 uppercase tracking-widest mr-2">signal:</span>
          <span className="text-cosmic-cyan break-all">{topic}</span>
        </div>
      )}

      {/* Data-source strip (backend-attached provenance) */}
      {provenance && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-white/10 bg-black/20 font-mono text-[10px]">
          <span className="text-gray-500 uppercase tracking-widest">data sources:</span>
          {Object.entries(provenance).map(([k, v]) => (
            <span key={k}>
              <span className="text-gray-500 mr-1">{k}:</span>
              {tierChip(v) || <span className="text-gray-400">{String(v)}</span>}
            </span>
          ))}
        </div>
      )}

      {/* Watch state: what the backend is listening to right now */}
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 border-b border-white/10 bg-black/20 font-mono text-[10px]"
        title={watchTopics.length ? watchTopics.join('\n') : 'no topic list loaded yet'}
      >
        <span className="text-gray-500 uppercase tracking-widest">watching:</span>
        <span className="text-gray-300">
          kafka · {watchTopics.length ? `${watchTopics.length} classic topics` : 'topics unknown'}
        </span>
        <span className={pollOn ? 'text-green-400' : 'text-gray-500'}>
          {pollOn ? '●' : '○'} gracedb poll{pollOn ? '' : ' off'}
        </span>
        {pollOn && poller.last_result && (
          <span className="text-gray-500 truncate">last: {String(poller.last_result).slice(0, 80)}</span>
        )}
      </div>

      {/* Log body — deep-space backdrop (nebula wash + starfield + drift) */}
      <div className="relative font-mono text-xs max-h-[28rem] overflow-y-auto">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(600px 220px at 15% 0%, rgba(0,245,255,0.09), transparent 60%),' +
              'radial-gradient(700px 260px at 85% 100%, rgba(255,0,255,0.08), transparent 60%),' +
              'radial-gradient(400px 200px at 70% 20%, rgba(139,92,246,0.10), transparent 60%)',
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{
            backgroundImage:
              'radial-gradient(1px 1px at 12% 22%, rgba(255,255,255,0.8), transparent),' +
              'radial-gradient(1px 1px at 32% 68%, rgba(255,255,255,0.5), transparent),' +
              'radial-gradient(1.5px 1.5px at 54% 12%, rgba(0,245,255,0.7), transparent),' +
              'radial-gradient(1px 1px at 71% 44%, rgba(255,255,255,0.6), transparent),' +
              'radial-gradient(1px 1px at 84% 78%, rgba(255,0,255,0.6), transparent),' +
              'radial-gradient(1.5px 1.5px at 92% 28%, rgba(255,255,255,0.7), transparent),' +
              'radial-gradient(1px 1px at 44% 88%, rgba(255,255,255,0.5), transparent),' +
              'radial-gradient(1px 1px at 5% 82%, rgba(0,245,255,0.6), transparent)',
          }}
        />
        <div className="relative px-4 py-3 space-y-1.5">
        {traces.length === 0 && !loading && (
          <div className="py-8 text-center">
            <div className="text-gray-500 mb-1">$ awaiting launch_</div>
            <div className="text-gray-600 text-[11px]">press LAUNCH GCN ALERT above — every agent call streams here</div>
          </div>
        )}

        {traces.map((trace) => {
          const isSystem = trace.tool_name === 'run'
          const isChild = !isSystem && !(trace.tool_name || '').includes('.')
          const st = STATUS[trace.status] || STATUS.running
          const agent = agentOf(trace.tool_name)
          const tier = tierOf(trace, provenance)
          const id = keyOf(trace)
          const isOpen = expanded === id

          if (isSystem) {
            return (
              <div key={id} className="text-gray-600 text-[11px] py-0.5">
                <span className="text-gray-700">[{fmtTime(trace.started_at)}]</span>{' '}
                <span className="text-cosmic-cyan/70">●</span>{' '}
                {trace.output_summary || trace.input_summary || 'run event'}
              </div>
            )
          }

          return (
            <motion.div
              key={id}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              className={isChild ? 'ml-6 border-l-2 border-cosmic-magenta/30 pl-3' : ''}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-gray-600">{fmtTime(trace.started_at)}</span>
                {isChild && <span className="text-cosmic-magenta">↳</span>}
                <span className={st.cls}>{st.glyph}</span>
                <span className="text-sky-300">[{agent}]</span>
                <span className="text-gray-200">{trace.tool_name}()</span>
                {tierChip(tier)}
                {trace.duration_ms != null && (
                  <span className="text-gray-600">{trace.duration_ms}ms</span>
                )}
                {trace.attempt > 1 && (
                  <span className="text-yellow-400">attempt {trace.attempt}</span>
                )}
                {/* Skill/tool tags once tick appears — not just in dropdown */}
                {st.glyph === '✓' || st.glyph === '○' ? (
                  <span className="flex flex-wrap gap-1 items-center">
                    {(AGENT_SKILLS_TOOLS[agent]?.tools || []).slice(0,2).map(t => (
                      <span key={t} className="font-mono text-[9px] text-cosmic-cyan bg-cosmic-cyan/10 border border-cosmic-cyan/20 px-1.5 py-px rounded">
                        {t}
                      </span>
                    ))}
                    {(AGENT_SKILLS_TOOLS[agent]?.skills || []).slice(0,2).map(s => (
                      <span key={s} className="font-mono text-[9px] text-gray-400 bg-white/5 border border-white/10 px-1.5 py-px rounded">
                        {s}
                      </span>
                    ))}
                  </span>
                ) : null}
                {trace.status === 'skipped' && trace.output_summary && (
                  <span className="text-gray-500 text-[10px] truncate max-w-[260px]">{trace.output_summary}</span>
                )}
                <button
                  onClick={() => setExpanded(isOpen ? null : id)}
                  className="text-gray-600 hover:text-cosmic-cyan transition-colors"
                  aria-label="toggle step detail"
                >
                  {isOpen ? '▲' : '▼'}
                </button>
              </div>

              {trace.status === 'failed' && trace.error && (
                <div className="text-red-400/90 text-[11px] mt-0.5 break-all">
                  err: {trace.error}
                </div>
              )}

              {isOpen && (
                <div className="mt-1.5 mb-1 p-2.5 rounded bg-black/60 border border-white/10 text-[11px] space-y-1.5">
                  {trace.input_summary && (
                    <div className="break-all">
                      <span className="text-gray-600">in&gt; </span>
                      <span className="text-gray-300">{String(trace.input_summary).slice(0, 600)}</span>
                    </div>
                  )}
                  {trace.output_summary && (
                    <div className="break-all">
                      <span className="text-gray-600">out&gt; </span>
                      <span className="text-gray-300">{String(trace.output_summary).slice(0, 600)}</span>
                    </div>
                  )}
                  {!trace.input_summary && !trace.output_summary && (
                    <div className="text-gray-600">no payload captured</div>
                  )}
                </div>
              )}
            </motion.div>
          )
        })}
        <div ref={bottomRef} />
        </div>
      </div>

      {/* Status bar — never say "closed" while the pipeline is still running;
          that single line is what made PROCESSING look finished. */}
      <div className="px-4 py-2 border-t border-white/10 bg-black/40 font-mono text-[10px] text-gray-600 flex items-center gap-3">
        <span>{traces.length} events</span>
        {isRunning && <span className="text-yellow-400 animate-pulse">● live — agents working…</span>}
        {!isRunning && streamState === 'live' && <span className="text-yellow-400 animate-pulse">● streaming…</span>}
        {!isRunning && streamState === 'reconnecting' && <span className="text-orange-400 animate-pulse">● reconnecting…</span>}
        {!isRunning && streamState === 'closed' && traces.length > 0 && <span className="text-green-500">● stream closed — run finished</span>}
        {!isRunning && streamState === 'idle' && traces.length === 0 && <span>awaiting launch — press LAUNCH above</span>}
        {isRunning && streamState === 'closed' && traces.length <= 1 && <span className="text-orange-400 animate-pulse">● polling for live steps…</span>}
        <span className="ml-auto hidden sm:inline">backend: /api/runs/:id/events (SSE) + polling</span>
      </div>
    </motion.div>
  )
}
