import { motion } from 'framer-motion'

export default function HeroSection() {
  return (
    <section className="relative min-h-screen flex items-center justify-center px-4 py-20">
      {/* Animated radar background */}
      <div className="absolute inset-0 flex items-center justify-center opacity-20">
        <div className="relative w-96 h-96">
          <div className="absolute inset-0 rounded-full border-2 border-cosmic-cyan animate-ping" />
          <div className="absolute inset-8 rounded-full border border-cosmic-cyan/60 animate-pulse" />
          <div className="absolute inset-16 rounded-full border border-cosmic-cyan/40" />
          <div className="absolute inset-0 rounded-full overflow-hidden">
            <div className="absolute inset-0 bg-gradient-conic from-cosmic-cyan/30 via-transparent to-transparent radar-sweep" />
          </div>
        </div>
      </div>

      <div className="relative z-10 text-center max-w-5xl">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          <div className="inline-block mb-6 px-4 py-2 glass rounded-full border border-cosmic-cyan/30">
            <span className="font-mono text-xs text-cosmic-cyan">
              AWS AGENTS FOR HUMANS HACKATHON 2026
            </span>
          </div>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="font-cosmic text-6xl md:text-8xl font-black mb-6 bg-gradient-to-r from-cosmic-cyan via-white to-cosmic-magenta bg-clip-text text-transparent"
        >
          KiloNOVAScout
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className="font-grotesk text-xl md:text-2xl text-gray-300 mb-8 max-w-3xl mx-auto"
        >
          Autonomous Multi-Messenger Astronomy Targeting Agent
        </motion.p>

        <motion.p
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.6 }}
          className="font-mono text-sm md:text-base text-gray-400 mb-12 max-w-2xl mx-auto"
        >
          An event-driven background daemon that listens for NASA Gravitational Wave alerts, 
          calculates astrometry, checks weather, and autonomously generates telescope slew scripts — 
          only pinging the human when a target is ready for approval.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="flex flex-wrap gap-4 justify-center"
        >
          <a
            href="#dashboard"
            className="px-8 py-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold hover:opacity-90 transition-opacity glow-cyan"
          >
            LAUNCH DEMO
          </a>
          <a
            href="#architecture"
            className="px-8 py-4 border-2 border-cosmic-cyan rounded-lg font-cosmic font-bold hover:bg-cosmic-cyan/10 transition-colors"
          >
            VIEW ARCHITECTURE
          </a>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1, delay: 1.2 }}
          className="mt-16 flex flex-wrap gap-6 justify-center text-xs font-mono text-gray-500"
        >
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <span>LISTENING TO NASA GCN</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-cosmic-cyan" />
            <span>STRANDS AGENTS SDK</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-cosmic-magenta" />
            <span>100% FREE STACK</span>
          </div>
        </motion.div>
      </div>
    </section>
  )
}