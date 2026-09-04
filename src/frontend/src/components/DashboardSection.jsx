import { useState } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'

export default function DashboardSection({ agentStatus, setAgentStatus, onTargetAcquired }) {
  const [loading, setLoading] = useState(false)
  const [executionTraces, setExecutionTraces] = useState([])
  const [candidates, setCandidates] = useState([])
  const [alertData, setAlertData] = useState(null)

  const simulateEvent = async () => {
    setLoading(true)
    setExecutionTraces([])
    setCandidates([])
    setAlertData(null)

    try {
      const response = await axios.post('/api/simulate-event', {
        event_id: 'GW170817',
        observatory_lat: 31.9583,
        observatory_lon: -111.5967
      })

      const data = response.data
      setAlertData(data.alert)
      setCandidates(data.candidates)
      setAgentStatus(data.status)

      // Animate execution traces
      for (let i = 0; i < data.execution_traces.length; i++) {
        await new Promise(resolve => setTimeout(resolve, 500))
        setExecutionTraces(prev => [...prev, data.execution_traces[i]])
      }

      if (data.status === 'target_acquired') {
        setTimeout(() => onTargetAcquired(), 1000)
      }
    } catch (error) {
      console.error('Simulation failed:', error)
    } finally {
      setLoading(false)
    }
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
            Simulate the famous GW170817 neutron star merger event
          </p>

          <button
            onClick={simulateEvent}
            disabled={loading}
            className="px-12 py-4 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta rounded-lg font-cosmic font-bold text-lg hover:opacity-90 transition-opacity glow-cyan disabled:opacity-50"
          >
            {loading ? 'PROCESSING...' : 'SIMULATE GCN ALERT'}
          </button>
        </motion.div>

        {/* Status indicator */}
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
                'text-cosmic-cyan'
              }`}>
                {agentStatus.toUpperCase().replace('_', ' ')}
              </div>
            </div>
            <div className={`w-4 h-4 rounded-full ${
              agentStatus === 'listening' ? 'bg-gray-400' :
              agentStatus === 'processing' ? 'bg-yellow-400 animate-pulse' :
              agentStatus === 'target_acquired' ? 'bg-green-400 animate-pulse' :
              'bg-cosmic-cyan'
            }`} />
          </div>
        </motion.div>

        {/* Execution traces */}
        {executionTraces.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 mb-8 border border-cosmic-cyan/30"
          >
            <div className="font-cosmic text-sm text-cosmic-cyan mb-4">EXECUTION TRACE</div>
            <div className="space-y-3 font-mono text-xs">
              {executionTraces.map((trace, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-start gap-3"
                >
                  <span className="text-gray-500">[{trace.step}]</span>
                  <span className="text-cosmic-magenta">{trace.tool_name}()</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    trace.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                    trace.status === 'running' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-red-500/20 text-red-400'
                  }`}>
                    {trace.status.toUpperCase()}
                  </span>
                  {trace.duration_ms && (
                    <span className="text-gray-500">{trace.duration_ms}ms</span>
                  )}
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}

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
            </div>
          </motion.div>
        )}

        {/* Candidates */}
        {candidates.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-6 border border-green-400/30"
          >
            <div className="font-cosmic text-sm text-green-400 mb-4">
              TARGET CANDIDATES ({candidates.length})
            </div>
            <div className="space-y-3">
              {candidates.map((candidate, index) => (
                <div
                  key={index}
                  className="bg-black/50 rounded-lg p-4 border border-white/5"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-cosmic text-sm text-cosmic-cyan">
                      {candidate.galaxy.name}
                    </div>
                    <div className="font-mono text-xs text-green-400">
                      Priority: {candidate.priority_score.toFixed(2)}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 font-mono text-xs text-gray-400">
                    <div>RA: {candidate.galaxy.ra.toFixed(4)}°</div>
                    <div>Dec: {candidate.galaxy.dec.toFixed(4)}°</div>
                    <div>Dist: {candidate.galaxy.distance_mpc} Mpc</div>
                    <div>Prob: {(candidate.galaxy.probability * 100).toFixed(0)}%</div>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </div>
    </section>
  )
}

</ARG>