import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import HeroSection from './components/HeroSection'
import MissionSection from './components/MissionSection'
import ArchitectureSection from './components/ArchitectureSection'
import ObservatorySection from './components/ObservatorySection'
import DashboardSection from './components/DashboardSection'
import Footer from './components/Footer'
import StarfieldBackground from './components/StarfieldBackground'

function App() {
  const [agentStatus, setAgentStatus] = useState('listening')
  const [showApprovalModal, setShowApprovalModal] = useState(false)

  return (
    <div className="relative min-h-screen bg-void text-white overflow-x-hidden">
      <StarfieldBackground />
      
      <main className="relative z-10">
        <HeroSection />
        <MissionSection />
        <ArchitectureSection />
        <ObservatorySection />
        <DashboardSection 
          agentStatus={agentStatus}
          setAgentStatus={setAgentStatus}
          onTargetAcquired={() => setShowApprovalModal(true)}
        />
        <Footer />
      </main>

      <AnimatePresence>
        {showApprovalModal && (
          <ApprovalModal onClose={() => setShowApprovalModal(false)} />
        )}
      </AnimatePresence>
    </div>
  )
}

function ApprovalModal({ onClose }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
    >
      <motion.div
        initial={{ scale: 0.8, y: 50 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.8, y: 50 }}
        className="glass rounded-2xl p-8 max-w-2xl w-full mx-4 border-2 border-cosmic-cyan glow-cyan"
      >
        <div className="text-center mb-6">
          <motion.div
            animate={{ scale: [1, 1.1, 1] }}
            transition={{ repeat: Infinity, duration: 2 }}
            className="text-6xl mb-4"
          >
            🎯
          </motion.div>
          <h2 className="font-cosmic text-3xl font-bold text-cosmic-cyan mb-2">
            TARGET ACQUIRED
          </h2>
          <p className="text-gray-300 font-mono text-sm">
            HUMAN APPROVAL REQUIRED
          </p>
        </div>

        <div className="bg-black/50 rounded-lg p-4 mb-6 font-mono text-xs">
          <div className="text-cosmic-cyan mb-2">[ALERT] GW170817 — Binary Neutron Star Merger</div>
          <div className="text-gray-400 mb-2">Distance: 40.8 Mpc | Confidence: 90%</div>
          <div className="text-white mb-2">Top Target: NGC 4993 (S0 Galaxy)</div>
          <div className="text-green-400">Weather: Clear skies at Kitt Peak Observatory</div>
        </div>

        <div className="bg-black/50 rounded-lg p-4 mb-6">
          <div className="text-xs font-mono text-gray-400 mb-2">SLEW SCRIPT PREVIEW:</div>
          <pre className="text-xs font-mono text-cosmic-cyan overflow-x-auto">
{`<?xml version="1.0" encoding="UTF-8"?>
<TelescopeControl>
  <TargetSequence>
    <Target id="1" priority="0.85">
      <Name>NGC 4993</Name>
      <Coordinates>
        <RA>130.6208</RA>
        <Dec>-25.0708</Dec>
      </Coordinates>
      <Exposure time="300" filter="R"/>
    </Target>
  </TargetSequence>
</TelescopeControl>`}
          </pre>
        </div>

        <div className="flex gap-4">
          <button
            onClick={onClose}
            className="flex-1 px-6 py-3 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold hover:opacity-90 transition-opacity"
          >
            APPROVE & EXECUTE
          </button>
          <button
            onClick={onClose}
            className="flex-1 px-6 py-3 border-2 border-gray-600 rounded-lg font-cosmic font-bold hover:border-gray-400 transition-colors"
          >
            REJECT
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

export default App