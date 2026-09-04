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
          <div className="flex flex-wrap gap-6 justify-center mb-8 font-mono text-xs text-gray-500">
            <a href="https://strandsagents.com" target="_blank" rel="noopener noreferrer" className="hover:text-cosmic-cyan transition-colors">
              Strands Agents SDK
            </a>
            <span>•</span>
            <a href="https://github.com" target="_blank" rel="noopener noreferrer" className="hover:text-cosmic-cyan transition-colors">
              GitHub Repository
            </a>
            <span>•</span>
            <span>MIT License</span>
          </div>
          <div className="font-mono text-xs text-gray-600">
            Built for AWS Agents for Humans Hackathon 2026
          </div>
        </motion.div>
      </div>
    </footer>
  )
}

</ARG>