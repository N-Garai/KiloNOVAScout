import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

// Pre-hero boot loader: counts 0% -> 100% with a radar sweep, then
// reports done so App can reveal the site.
export default function Loader({ onDone }) {
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const DURATION_MS = 2200
    const started = performance.now()
    let raf = 0
    const tick = (now) => {
      const t = Math.min(1, (now - started) / DURATION_MS)
      // Ease-out so it feels fast at first, settles into 100%.
      const eased = Math.round(100 * (1 - Math.pow(1 - t, 3)))
      setProgress(eased)
      if (t < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        setTimeout(onDone, 350)
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [onDone])

  return (
    <motion.div
      exit={{ opacity: 0, scale: 1.04 }}
      transition={{ duration: 0.5 }}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-void"
    >
      <div className="text-center px-6">
        {/* Radar sweep */}
        <div className="relative w-40 h-40 mx-auto mb-8">
          <div className="absolute inset-0 rounded-full border-2 border-cosmic-cyan/70" />
          <div className="absolute inset-5 rounded-full border border-cosmic-cyan/40" />
          <div className="absolute inset-10 rounded-full border border-cosmic-cyan/25" />
          <div className="absolute inset-0 rounded-full overflow-hidden">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1.6, repeat: Infinity, ease: 'linear' }}
              className="absolute inset-0"
              style={{ background: 'conic-gradient(from 0deg, rgba(0,245,255,0.5), transparent 30%)' }}
            />
          </div>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="font-cosmic text-2xl font-bold text-white tabular-nums">
              {progress}%
            </span>
          </div>
        </div>

        <div className="font-cosmic text-sm tracking-[0.35em] text-cosmic-cyan mb-4">
          KILONOVASCOUT
        </div>

        {/* Progress bar */}
        <div className="w-64 md:w-80 h-1.5 mx-auto rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta transition-[width] duration-100"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="font-mono text-[11px] text-gray-500 mt-3 tracking-widest uppercase">
          {progress < 40 ? 'Acquiring signal' : progress < 75 ? 'Calibrating optics' : progress < 100 ? 'Aligning starfield' : 'Online'}
        </div>
      </div>
    </motion.div>
  )
}
