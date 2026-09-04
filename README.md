# 🌌 KiloNOVAScout

**Autonomous Multi-Messenger Astronomy Targeting Agent**

> An event-driven background daemon that listens for NASA Gravitational Wave alerts, calculates astrometry, checks weather, and autonomously generates telescope slew scripts — only pinging the human when a target is ready for approval.

## 🏆 Hackathon Submission

**AWS Agents for Humans Hackathon** — Professional Agents Track

Built with [Strands Agents SDK](https://strandsagents.com) — 100% free stack, zero paid AWS services.

## 🚀 The Problem

Multi-messenger astronomy is a race against time. When LIGO/Virgo detects a gravitational wave (e.g., neutron star merger), NASA blasts a GCN alert with a HEALPix skymap — a massive, imprecise blob where the merger occurred. Optical telescopes have minutes to hours to find the resulting kilonova before it fades.

Currently, astronomers manually:
- Download the skymap
- Cross-reference millions of galaxies
- Check local cloud cover
- Calculate telescope visibility
- Write pointing scripts

By the time humans finish, the transient flash is gone.

## ⚡ The Solution

KiloNOVAScout automates this entire pipeline:

```
[NASA GCN Kafka Stream] → [Strands Agent] → [Telescope Slew Script]
         │                      │
         ▼                      ▼
   GW Alert Detected     Tools: parse_healpix_map()
                         query_glade_catalog()
                         check_observatory_weather()
```

## 🛠️ Tech Stack

### Backend
- **Framework:** FastAPI + Strands Agents SDK
- **LLM:** LiteLLM → Google Gemini 1.5 Flash (free tier) / Groq Llama 3
- **Astronomy:** Astropy, Healpy, gcn-kafka
- **Data:** GLADE+ galaxy catalog, Open-Meteo weather API
- **Hosting:** Render (free tier)

### Frontend
- **Framework:** React 18 + Vite
- **Styling:** Tailwind CSS v4
- **Animation:** Framer Motion, GSAP
- **Fonts:** Orbitron (cosmic/galactic), Space Grotesk, Space Mono
- **3D:** Three.js + React Three Fiber (starfield background)

## 📁 Project Structure

```
KiloNOVAScout/
├── src/
│   ├── backend/          # FastAPI + Strands agent
│   │   ├── main.py       # API server
│   │   ├── agent.py      # Strands orchestrator
│   │   ├── tools.py      # Astronomy tools
│   │   ├── simulator.py  # GW170817 event replay
│   │   └── models.py     # Data schemas
│   └── frontend/         # React + Vite UI
│       ├── src/
│       │   ├── components/
│       │   └── App.jsx
│       └── package.json
├── docs/                 # Documentation
├── Dockerfile            # Multi-stage build
├── .gitignore
└── README.md
```

## 🎮 Event Replay Harness (Demo)

Since gravitational waves are unpredictable, the backend includes an **Event Simulator** endpoint:

```bash
POST /api/simulate-event
{
  "event_id": "GW170817"
}
```

This injects the famous neutron star merger payload into the Strands Agent loop, allowing 100% reproducible 5-minute demos.

## 🚀 Quick Start

### Local Development

**Backend:**
```bash
cd src/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd src/frontend
npm install
npm run dev
```

### Docker

```bash
docker build -t kilonovascout .
docker run -p 8000:8000 -p 5173:5173 kilonovascout
```

### Render Deployment

1. Push to GitHub
2. Connect repo to Render
3. Set build command: `cd src/frontend && npm install && npm run build`
4. Set start command: `cd src/backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables: `GEMINI_API_KEY`, `GROQ_API_KEY`

## 🎯 Key Features

- **Event-Driven Daemon:** Listens to NASA GCN Kafka stream 24/7
- **Autonomous Astrometry:** Parses HEALPix skymaps, cross-references galaxies
- **Weather Integration:** Checks observatory cloud cover via Open-Meteo
- **Human-in-the-Loop:** Only surfaces when telescope script needs approval
- **Cinematic UI:** Cosmic command center with glassmorphism, animations, radar viz
- **100% Free:** No paid AWS services, uses free API tiers

## 📊 Architecture

```
┌─────────────────┐
│  NASA GCN Kafka │
│   (gcn-kafka)   │
└────────┬────────┘
         │ GW Alert
         ▼
┌─────────────────────────────────┐
│   Strands Orchestrator Agent    │
│                                 │
│  ┌──────────┐  ┌─────────────┐ │
│  │ Tool 1:  │  │ Tool 2:     │ │
│  │ HEALPix  │  │ GLADE+      │ │
│  │ Parser   │  │ Catalog     │ │
│  └──────────┘  └─────────────┘ │
│                                 │
│  ┌──────────┐  ┌─────────────┐ │
│  │ Tool 3:  │  │ Tool 4:     │ │
│  │ Weather  │  │ Slew Script │ │
│  │ Check    │  │ Generator   │ │
│  └──────────┘  └─────────────┘ │
└────────┬────────────────────────┘
         │ Target Acquired
         ▼
┌─────────────────┐
│  Human Approval │
│  (SMS/UI Alert) │
└─────────────────┘
```

## 📝 License

MIT

## 👥 Team

Built for the AWS Agents for Humans Hackathon 2026.

</ARG>