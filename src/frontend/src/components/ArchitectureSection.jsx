import { motion, useInView, useScroll, useTransform } from 'framer-motion'
import { useRef, useState, useEffect } from 'react'

export default function ArchitectureSection() {
  const ref = useRef(null)
  const isInView = useInView(ref, { once: true, margin: "-200px" })

  // Pinned horizontal track: vertical scroll progress over the tall
  // wrapper drives the card row horizontally (Chronocut storyboard style).
  // The shift is measured from the real track overflow so the last card
  // lands exactly at the viewport edge on any screen size — scrolling up
  // reverses it automatically since it is scroll-driven.
  const trackWrapRef = useRef(null)
  const trackRef = useRef(null)
  const [trackShift, setTrackShift] = useState(0)
  const { scrollYProgress } = useScroll({ target: trackWrapRef })
  const trackX = useTransform(scrollYProgress, [0, 1], [0, -trackShift])

  useEffect(() => {
    const measure = () => {
      const el = trackRef.current
      if (!el) return
      const overflow = el.scrollWidth - window.innerWidth
      setTrackShift(overflow > 0 ? overflow : 0)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // Static class map (no template interpolation — Tailwind JIT safe).
  const ACCENT = {
    cyan: "border-cosmic-cyan/40 text-cosmic-cyan",
    magenta: "border-cosmic-magenta/40 text-cosmic-magenta",
    purple: "border-cosmic-purple/40 text-cosmic-purple",
    lime: "border-lime-400/40 text-lime-300",
    orange: "border-orange-400/40 text-orange-300",
    pink: "border-pink-400/40 text-pink-300",
    blue: "border-sky-400/40 text-sky-300",
    green: "border-green-400/40 text-green-300",
  }

  const agents = [
    {
      name: "Ingestion Agent",
      purpose: "Filters and normalizes GCN notices — accepts BNS/NSBH mergers, rejects BBH and retractions.",
      tools: ["ingestion.filter_gcn"],
      accent: "cyan",
    },
    {
      name: "HEALPix Triage Agent",
      purpose: "Parses skymap FITS files and calculates the 90% localization volume and distance.",
      tools: ["parse_healpix_map"],
      accent: "magenta",
    },
    {
      name: "Galaxy Crossmatch Agent",
      purpose: "Identifies host galaxy candidates in the GLADE+ catalog with full v3 scoring.",
      tools: ["query_glade_catalog", "compute_full_score"],
      accent: "purple",
    },
    {
      name: "Ephemeris & Weather Agents",
      purpose: "Calculates target observability and fetches live site conditions in parallel.",
      tools: ["integrated_airmass", "check_observatory_weather", "lunar_penalty"],
      accent: "lime",
    },
    {
      name: "GRB Validator Agent",
      purpose: "Performs multi-messenger coincidence checks against the GRB catalog.",
      tools: ["validator.multimessenger"],
      accent: "orange",
    },
    {
      name: "Scheduler Agent",
      purpose: "Optimizes the telescope slew sequence (TSP) and generates the ASCOM/INDI script.",
      tools: ["optimize_slew_order", "generate_telescope_slew_script"],
      accent: "pink",
    },
    {
      name: "LLM Rationale Agent",
      purpose: "Generates the human-readable summary and decision justification, with plots in parallel.",
      tools: ["llm.rationale", "generate_run_visualizations"],
      accent: "blue",
    },
    {
      name: "Human Approval Gate",
      purpose: "Final human verification before execution — dome re-checked, one click to fire.",
      tools: ["check_dome_safety", "approve_slew_script"],
      accent: "green",
    },
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

  // Static flow-chip classes (Tailwind JIT safe — no dynamic construction).
  const FLOW_BG = {
    "cosmic-cyan": "bg-cosmic-cyan/20",
    "cosmic-magenta": "bg-cosmic-magenta/20",
    "cosmic-purple": "bg-cosmic-purple/20",
    "cosmic-lime": "bg-lime-400/20",
    "cosmic-orange": "bg-orange-400/20",
    "cosmic-pink": "bg-pink-400/20",
    "cosmic-blue": "bg-sky-400/20",
    "green": "bg-green-400/20",
  }

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
                  <div className={`p-3 rounded-lg border border-white/10 ${item.type === 'agent-parallel' ? 'bg-gradient-to-r from-lime-400/20 to-cosmic-cyan/20' : (FLOW_BG[item.color] || 'bg-white/5')}`}>
                    <div className="font-cosmic text-sm text-white">{item.label}</div>
                    <div className="font-mono text-xs text-gray-400">{item.description}</div>
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* AGENT DISCOVERY — pinned horizontal scroll.
          Scrolling down slides the agent cards left until the last card,
          then the page continues. Scrolling up slides them back right. */}
      <div ref={trackWrapRef} className="relative h-[320vh]">
        <div className="sticky top-0 h-screen flex flex-col justify-center overflow-hidden">
          <div className="max-w-7xl mx-auto w-full px-4 mb-8">
            <h3 className="font-cosmic text-3xl md:text-4xl font-bold text-white">
              AGENT <span className="bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">DISCOVERY</span>
            </h3>
            <p className="font-mono text-xs text-gray-400 mt-2 tracking-widest uppercase">
              Scroll to travel the pipeline — 8 agents, left to right
            </p>
          </div>

          <motion.div ref={trackRef} style={{ x: trackX }} className="flex gap-6 pl-4 md:pl-[max(1rem,calc((100vw-80rem)/2+1rem))] pr-6 w-max items-stretch">
            {agents.map((agent, index) => (
              <div
                key={agent.name}
                className={`glass rounded-2xl p-7 border ${ACCENT[agent.accent].split(' ')[0]} w-[78vw] sm:w-[52vw] md:w-[30rem] shrink-0 flex flex-col`}
              >
                <div className="font-mono text-xs text-gray-500 mb-3 tracking-widest">
                  {String(index + 1).padStart(2, '0')} / 08
                </div>
                <h4 className={`font-cosmic text-2xl font-bold mb-3 ${ACCENT[agent.accent].split(' ')[1]}`}>
                  {agent.name}
                </h4>
                <p className="font-grotesk text-sm text-gray-300 leading-relaxed mb-6 flex-1">
                  {agent.purpose}
                </p>
                <div className="flex flex-wrap gap-2">
                  {agent.tools.map((tool) => (
                    <span
                      key={tool}
                      className="font-mono text-[11px] text-gray-300 bg-black/60 border border-white/10 px-2.5 py-1 rounded-md"
                    >
                      {tool}()
                    </span>
                  ))}
                </div>
              </div>
            ))}

            {/* End cap card */}
            <div className="w-[78vw] sm:w-[52vw] md:w-[30rem] shrink-0 rounded-2xl p-7 border border-cosmic-cyan/40 bg-gradient-to-br from-cosmic-cyan/10 to-cosmic-magenta/10 flex flex-col justify-center">
              <h4 className="font-cosmic text-2xl font-bold text-white mb-3">
                Then: human approval
              </h4>
              <p className="font-grotesk text-sm text-gray-300 leading-relaxed">
                The slew script waits for one click. Every step above is measured, logged, and traceable in the live demo below.
              </p>
              <a
                href="#dashboard"
                className="mt-6 inline-block px-6 py-3 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-sm text-center hover:opacity-90 transition-opacity"
              >
                GO TO LIVE DEMO
              </a>
            </div>
          </motion.div>

          {/* Scroll progress */}
          <div className="max-w-7xl mx-auto w-full px-4 mt-8">
            <div className="h-1 rounded-full bg-white/10 overflow-hidden">
              <motion.div
                style={{ scaleX: scrollYProgress }}
                className="h-full w-full origin-left bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta"
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
