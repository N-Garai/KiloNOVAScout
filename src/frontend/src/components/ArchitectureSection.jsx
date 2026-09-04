import { motion } from 'framer-motion'
import { useInView } from 'framer-motion'
import { useRef } from 'react'

export default function ArchitectureSection() {
  const ref = useRef(null)
  const isInView = useInView(ref, { once: true, margin: "-100px" })

  const tools = [
    {
      name: "parse_healpix_map",
      description: "Extracts 90% probability 3D volume from LIGO skymap",
      library: "astropy + healpy",
      color: "cyan"
    },
    {
      name: "query_glade_catalog",
      description: "Cross-references GLADE+ galaxy catalog for host candidates",
      library: "astropy",
      color: "magenta"
    },
    {
      name: "check_observatory_weather",
      description: "Queries Open-Meteo for cloud cover at telescope coordinates",
      library: "Open-Meteo API",
      color: "purple"
    },
    {
      name: "generate_slew_script",
      description: "Writes ASCOM/INDI XML telescope pointing script",
      library: "Custom XML generator",
      color: "cyan"
    }
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
          <div className="flex flex-col md:flex-row items-center justify-between gap-8">
            <div className="flex-1 text-center">
              <div className="text-4xl mb-2">📡</div>
              <div className="font-cosmic text-sm text-cosmic-cyan">NASA GCN</div>
              <div className="font-mono text-xs text-gray-400">Kafka Stream</div>
            </div>

            <div className="text-2xl text-cosmic-cyan">→</div>

            <div className="flex-1 text-center">
              <div className="text-4xl mb-2">🤖</div>
              <div className="font-cosmic text-sm text-cosmic-magenta">Strands Agent</div>
              <div className="font-mono text-xs text-gray-400">Orchestrator</div>
            </div>

            <div className="text-2xl text-cosmic-cyan">→</div>

            <div className="flex-1 text-center">
              <div className="text-4xl mb-2">🔭</div>
              <div className="font-cosmic text-sm text-cosmic-purple">Slew Script</div>
              <div className="font-mono text-xs text-gray-400">ASCOM/INDI XML</div>
            </div>

            <div className="text-2xl text-cosmic-cyan">→</div>

            <div className="flex-1 text-center">
              <div className="text-4xl mb-2">✅</div>
              <div className="font-cosmic text-sm text-green-400">Human Approval</div>
              <div className="font-mono text-xs text-gray-400">1-Click Execute</div>
            </div>
          </div>
        </motion.div>

        {/* Tools grid */}
        <div className="grid md:grid-cols-2 gap-6">
          {tools.map((tool, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 30 }}
              animate={isInView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.4 + index * 0.1 }}
              className="glass rounded-xl p-6 border border-white/10 hover:border-cosmic-cyan/50 transition-all hover:scale-105"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className={`font-cosmic text-lg font-bold text-cosmic-${tool.color}`}>
                  {tool.name}()
                </h3>
                <span className="font-mono text-xs text-gray-500 bg-black/50 px-2 py-1 rounded">
                  @{tool.library}
                </span>
              </div>
              <p className="font-grotesk text-sm text-gray-300">
                {tool.description}
              </p>
            </motion.div>
          ))}
        </div>

        {/* Tech stack */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8, delay: 1 }}
          className="mt-16 glass rounded-2xl p-8 border border-white/10"
        >
          <h3 className="font-cosmic text-2xl font-bold text-center mb-8 text-cosmic-cyan">
            TECH STACK
          </h3>
          <div className="grid md:grid-cols-3 gap-6 text-center">
            <div>
              <div className="font-cosmic text-sm text-cosmic-magenta mb-2">BACKEND</div>
              <div className="font-mono text-xs text-gray-300 space-y-1">
                <div>FastAPI + Strands SDK</div>
                <div>LiteLLM → Gemini Flash</div>
                <div>Astropy + Healpy</div>
              </div>
            </div>
            <div>
              <div className="font-cosmic text-sm text-cosmic-cyan mb-2">FRONTEND</div>
              <div className="font-mono text-xs text-gray-300 space-y-1">
                <div>React 18 + Vite</div>
                <div>Tailwind CSS v4</div>
                <div>Framer Motion + Three.js</div>
              </div>
            </div>
            <div>
              <div className="font-cosmic text-sm text-cosmic-purple mb-2">HOSTING</div>
              <div className="font-mono text-xs text-gray-300 space-y-1">
                <div>Render (Free Tier)</div>
                <div>Docker Multi-Stage</div>
                <div>100% Zero-Cost</div>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}

</ARG>