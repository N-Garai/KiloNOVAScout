import { useEffect, useRef } from 'react'
import axios from 'axios'

// Keep-alive for Render free tier (see version-docs/QnA.md "Cold-Start
// Problem"): while this tab is visible, ping the cheap /api/ping endpoint
// every 9 minutes so an open demo/judging tab holds the instance warm.
// This never runs in background tabs and never spins a sleeping instance
// on its own — it only preserves warmth during active viewing.
const PING_INTERVAL_MS = 9 * 60 * 1000

export default function useKeepAlive(enabled = true) {
  const timerRef = useRef(null)

  useEffect(() => {
    if (!enabled) return

    const ping = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        await axios.get('/api/ping', { timeout: 15000 })
      } catch {
        /* offline or asleep — next tick retries */
      }
    }

    // First ping shortly after load (also warms a cold instance while
    // the user reads the hero), then on the interval.
    const warmup = setTimeout(ping, 5000)
    timerRef.current = setInterval(ping, PING_INTERVAL_MS)

    return () => {
      clearTimeout(warmup)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [enabled])
}
