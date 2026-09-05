import { motion } from 'framer-motion'
import { useInView } from 'framer-motion'
import { useRef } from 'react'

export default function MissionSection() {
  const ref = useRef(null)
  const isInView = useInView(ref, { once: true, margin: "-100px" })

  const problems = [
    {
      icon: "🌌",
      title: "The Race Against Time",
      description: "When LIGO/Virgo detects a gravitational wave, NASA blasts a GCN alert with a HEALPix skymap — a massive, imprecise blob where the merger occurred."
    },
    {
      icon: "⏱️",
      title: "Minutes to Hours",
      description: "Optical telescopes have a tiny window to find the resulting kilonova explosion before it fades. Every second counts."
    },
    {
      icon: "🧮",
      title: "Manual Bottleneck",
      description: "Astronomers must manually download maps, cross-reference millions of galaxies, check weather, calculate visibility, and write pointing scripts."
    },
    {
      icon: "💨",
      title: "The Flash is Gone",
      description: "By the time humans finish the math, the transient optical flash may already be gone. The moment is lost forever."
    }
  ]

  return (
    <section ref={ref} className="relative py-32 px-4">
      {/* Background gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-cosmic-purple/5 to-transparent" />

      <div className="relative z-10 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8 }}
          className="text-center mb-20"
        >
          <h2 className="font-cosmic text-5xl md:text-6xl font-bold mb-6 bg-gradient-to-r from-cosmic-magenta to-cosmic-cyan bg-clip-text text-transparent">
            THE PROBLEM
          </h2>
          <p className="font-grotesk text-xl text-gray-400 max-w-3xl mx-auto">
            Multi-messenger astronomy is a race against the speed of light. 
            Current workflows are too slow for the transient universe.
          </p>
        </motion.div>

        <div className="grid md:grid-cols-2 gap-8">
          {problems.map((problem, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, x: index % 2 === 0 ? -50 : 50 }}
              animate={isInView ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.8, delay: index * 0.2 }}
              className="glass rounded-xl p-8 border border-white/10 hover:border-cosmic-cyan/50 transition-colors"
            >
              <div className="text-5xl mb-4">{problem.icon}</div>
              <h3 className="font-cosmic text-2xl font-bold text-cosmic-cyan mb-3">
                {problem.title}
              </h3>
              <p className="font-grotesk text-gray-300 leading-relaxed">
                {problem.description}
              </p>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8, delay: 1 }}
          className="mt-20 text-center"
        >
          <div className="inline-block glass rounded-2xl p-8 border-2 border-cosmic-cyan/30">
            <p className="font-mono text-sm text-cosmic-cyan mb-2">THE SOLUTION</p>
            <p className="font-grotesk text-2xl text-white font-semibold">
              KiloNOVAScout automates this entire pipeline
            </p>
            <p className="font-mono text-sm text-gray-400 mt-2">
              From alert detection to telescope slew script in under 5 minutes
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  )
}