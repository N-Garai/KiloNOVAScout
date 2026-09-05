import { motion } from 'framer-motion'

export default function Footer() {
  return (
    <footer className="relative py-16 px-4 border-t border-white/10">
      <div className="relative z-10 max-w-7xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
        >
          <div className="font-cosmic text-3xl font-bold mb-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">
            KiloNOVAScout
          </div>
          <p className="font-grotesk text-gray-400 mb-6">
            Autonomous Multi-Messenger Astronomy Targeting Agent
          </p>
          <div className="font-mono text-xs text-gray-600">
            © 2026 KiloNOVAScout · All rights reserved
          </div>
        </motion.div>
      </div>
    </footer>
  )
}