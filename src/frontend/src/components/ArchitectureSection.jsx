import { motion, useInView, AnimatePresence, useScroll } from 'framer-motion'
import { useRef, useState, useEffect } from 'react'

export default function ArchitectureSection() {
  const ref = useRef(null)
  const isInView = useInView(ref, { once: true, margin: "-200px" })

  const { scrollYProgress, scrollY } = useScroll();
  const [isScrollingDown, setIsScrollingDown] = useState(false);
  const lastScrollY = useRef(0);
  const [workingTraces, setWorkingTraces] = useState([]);
  const tracesFetchedRef = useRef(false);

  useEffect(() => {
    // framer-motion v11: MotionValue uses .on("change", ...) (v10's .onChange was removed)
    const unsubscribe = scrollY.on("change", (latest) => {
      if (latest > lastScrollY.current) {
        setIsScrollingDown(true);
      } else {
        setIsScrollingDown(false);
      }
      lastScrollY.current = latest;
    });
    return () => unsubscribe();
  }, [scrollY]);

  // When the working-details panel becomes visible, load the last run's real
  // measured dispatch log so the user sees actual step names / statuses /
  // durations (M5.2), not placeholder text.
  const panelVisible = isInView && isScrollingDown
  useEffect(() => {
    if (!panelVisible || tracesFetchedRef.current) return
    fetch('/api/latest-event')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        tracesFetchedRef.current = true
        if (data && Array.isArray(data.execution_traces) && data.execution_traces.length) {
          setWorkingTraces(data.execution_traces)
        }
      })
      .catch(() => {})
  }, [panelVisible])

  const agents = [
    {
      name: "Ingestion Agent",
      purpose: "Filters and normalizes GCN notices",
      toolCount: 1,
      color: "cyan"
    },
    {
      name: "HEALPix Triage Agent",
      purpose: "Parses skymap FITS files and calculates localization",
      toolCount: 1,
      color: "magenta"
    },
    {
      name: "Galaxy Crossmatch Agent",
      purpose: "Identifies host galaxy candidates in GLADE+ catalog",
      toolCount: 2,
      color: "purple"
    },
    {
      name: "Ephemeris & Weather Agents",
      purpose: "Calculates target observability and fetches conditions",
      toolCount: 3,
      color: "lime"
    },
    {
      name: "GRB Validator Agent",
      purpose: "Performs multi-messenger coincidence checks",
      toolCount: 1,
      color: "orange"
    },
    {
      name: "Scheduler Agent",
      purpose: "Optimizes telescope slew sequence and generates script",
      toolCount: 2,
      color: "pink"
    },
    {
      name: "LLM Rationale Agent",
      purpose: "Generates human-readable summary and decision justification",
      toolCount: 1,
      color: "blue"
    },
    {
      name: "Human Approval Gate",
      purpose: "Final human verification before execution",
      toolCount: 0,
      color: "green"
    }
  ]

  const agentFlow = [
    { label: "NASA GCN", description: "Kafka Stream", type: "data", color: "cosmic-cyan" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "Ingestion", description: "Filter GCN Notices", type: "agent", color: "cosmic-cyan" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "HEALPix Triage", description: "Parse Skymap FITS", type: "agent", color: "cosmic-magenta" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "Galaxy Crossmatch", description: "Identify Host Candidates", type: "agent", color: "cosmic-purple" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "Ephemeris & Weather (Parallel)", description: "Observability & Conditions", type: "agent-parallel", color: "cosmic-lime" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "GRB Validator", description: "Multi-Messenger Coincidence", type: "agent", color: "cosmic-orange" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "Scheduler", description: "Generate Slew Script", type: "agent", color: "cosmic-pink" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "LLM Rationale", description: "Human-Readable Justification", type: "agent", color: "cosmic-blue" },
    { label: "→", type: "arrow", color: "cosmic-cyan" },
    { label: "Human Approval", description: "1-Click Execute", type: "agent", color: "green" },
  ]

  return (
    <section id="architecture" ref={ref} className="relative py-32 px-4">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-cosmic-magenta/5 to-transparent" />

      <div className="relative z-10 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8 }}
          className="text-center mb-20"
        >
          <h2 className="font-cosmic text-5xl md:text-6xl font-bold mb-6 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">
            ARCHITECTURE
          </h2>
          <p className="font-grotesk text-xl text-gray-400 max-w-3xl mx-auto">
            Event-driven autonomous agent built with Strands Agents SDK
          </p>
        </motion.div>

        {/* Flow diagram */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={isInView ? { opacity: 1, scale: 1 } : {}}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="glass rounded-2xl p-8 mb-16 border border-white/10"
        >
          <div className="flex flex-wrap items-center justify-center gap-2 md:gap-4">
            {agentFlow.map((item, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 20 }}
                animate={isInView ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 0.5, delay: 0.2 + index * 0.1 }}
                className={`flex-shrink-0 text-center ${
                  item.type === 'arrow' ? 'text-2xl text-cosmic-cyan' : 'flex-1 p-2'
                }`}
              >
                {item.type === 'arrow' ? (
                  item.label
                ) : (
                  <div className={`p-3 rounded-lg border border-white/10 ${item.type === 'agent-parallel' ? 'bg-gradient-to-r from-cosmic-lime/20 to-cosmic-cyan/20' : `bg-cosmic-${item.color}/20`}`}>
                    <div className="font-cosmic text-sm text-white">{item.label}</div>
                    <div className="font-mono text-xs text-gray-400">{item.description}</div>
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Agent Details Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
          {agents.map((agent, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={isInView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.4 + index * 0.1 }}
              className="glass rounded-xl p-6 border border-white/10 hover:border-cosmic-cyan/50 transition-all hover:scale-105"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className={`font-cosmic text-lg font-bold text-${agent.color}-400`}>
                  {agent.name}
                </h3>
                {agent.toolCount > 0 && (
                  <span className="font-mono text-xs text-gray-500 bg-black/50 px-2 py-1 rounded">
                    {agent.toolCount} Tools
                  </span>
                )}
              </div>
              <p className="font-grotesk text-sm text-gray-300">
                {agent.purpose}
              </p>
            </motion.div>
          ))}
        </div>

        {/* Scroll-triggered Working Details Panel */}
        <AnimatePresence>
          {scrollYProgress.get() > 0.3 && isScrollingDown && (
            <motion.div
              initial={{ opacity: 0, y: 50 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 50 }}
              transition={{ duration: 0.5 }}
              className="fixed bottom-8 right-8 w-80 p-6 glass rounded-xl border border-white/10 shadow-lg z-50"
            >
              <h3 className="font-cosmic text-xl text-white mb-4">Agent Working Details</h3>
              <div className="font-mono text-sm text-gray-400 max-h-60 overflow-y-auto custom-scrollbar">
                {workingTraces.length > 0 ? (
                  workingTraces.map((trace, i) => (
                    <p key={i} className="mb-2 flex items-start gap-2">
                      <span className={trace.status === 'completed' ? 'text-green-400' : trace.status === 'failed' ? 'text-red-400' : 'text-cosmic-cyan'}>
                        {trace.status === 'completed' ? '✓' : trace.status === 'failed' ? '✕' : '○'}
                      </span>
                      <span>
                        [{String(trace.step).padStart(2, '0')}] {trace.tool_name}
                        {trace.duration_ms != null && <span className="text-gray-500"> · {trace.duration_ms}ms</span>}
                        {trace.error && <span className="text-red-400"> · {String(trace.error).slice(0, 60)}</span>}
                      </span>
                    </p>
                  ))
                ) : (
                  <>
                    <p className="mb-2 opacity-70">Waiting for a pipeline run to display live step telemetry.</p>
                    <p className="mb-2 opacity-50">Run the demo in the section below, then return here to see the measured agent dispatch log.</p>
                  </>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  )
}
