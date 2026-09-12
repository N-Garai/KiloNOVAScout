import { motion } from 'framer-motion'

const NAV = [
  { label: 'Problem', href: '#problem' },
  { label: 'Architecture', href: '#architecture' },
  { label: 'Observatory', href: '#observatory' },
  { label: 'Live Demo', href: '#dashboard' },
  { label: 'Historical Analysis', href: '#historical' },
]

const SOURCES = [
  { label: 'NASA GCN', href: 'https://gcn.nasa.gov' },
  { label: 'GraceDB', href: 'https://gracedb.ligo.org' },
  { label: 'GLADE+ / VizieR CDS', href: 'https://vizier.cds.unistra.fr' },
  { label: 'Open-Meteo', href: 'https://open-meteo.com' },
]

export default function Footer() {
  return (
    <footer className="relative py-16 px-4 border-t border-white/10">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-cosmic-purple/5 to-transparent pointer-events-none" />

      <div className="relative z-10 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="grid gap-10 md:grid-cols-3 text-left"
        >
          {/* Brand */}
          <div>
            <div className="font-cosmic text-2xl font-bold mb-2 bg-gradient-to-r from-cosmic-cyan to-cosmic-magenta bg-clip-text text-transparent">
              KiloNovaScout
            </div>
            <p className="font-grotesk text-sm text-gray-400 leading-relaxed">
              Autonomous multi-messenger astronomy targeting agent — from
              gravitational-wave alert to telescope slew script, with a human
              holding the final approval.
            </p>
          </div>

          {/* Site nav */}
          <nav aria-label="Site sections">
            <div className="font-mono text-[11px] uppercase tracking-widest text-gray-500 mb-3">
              Explore
            </div>
            <ul className="space-y-2">
              {NAV.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    className="font-grotesk text-sm text-gray-300 hover:text-cosmic-cyan transition-colors"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          {/* Data provenance */}
          <div>
            <div className="font-mono text-[11px] uppercase tracking-widest text-gray-500 mb-3">
              Data sources
            </div>
            <ul className="space-y-2">
              {SOURCES.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noreferrer"
                    className="font-grotesk text-sm text-gray-300 hover:text-cosmic-cyan transition-colors"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </motion.div>

        <div className="mt-12 pt-6 border-t border-white/10 flex flex-col md:flex-row items-center justify-between gap-3">
          <div className="font-mono text-xs text-gray-600">
            © 2026 KiloNovaScout · All rights reserved
          </div>
          <div className="font-mono text-[11px] text-gray-600 text-center md:text-right max-w-xl">
            Research demonstration. Every run labels its data tiers
            (live / replay / cached / point / synthetic / mock) — trust the
            badges, not the demo.
          </div>
        </div>
      </div>
    </footer>
  )
}
