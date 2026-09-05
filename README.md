# 🌌 KiloNOVAScout Autonomous Multi-Messenger Astronomy Targeting Agent

KilonovaScout is an autonomous, event-driven multi-agent system designed to resolve the critical latency bottleneck in multi-messenger time-domain astrophysics.

## 🚀 Key Features

*   **Autonomous Agentic Workflow:** Uses the Strands Agents SDK to chain 8 specialized agents for alert triage, astrometry, crossmatching, observability, meteorology, coincidence validation, scheduling, and human-in-the-loop notification.
*   **Production-Ready:** Built for 24/7 autonomous daemon uptime.
*   **Free-Tier Optimized:** Designed to run on Render Free Tier and utilize free API tiers (Google AI Studio Gemini, Groq, Open-Meteo, VizieR TAP).
*   **Robust & Reproducible:** Includes an integrated `EventSimulator` for end-to-end demo and testing.
*   **Human-in-the-Loop:** Interactive approval workflow via Telegram Bot.

## ⚙️ Setup

### Prerequisites
*   Python 3.11+
*   Node.js 18+ (for frontend)

### Installation
1.  `python -m venv .venv`
2.  `source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows)
3.  `pip install -r src/backend/requirements.txt`
4.  `cd src/frontend && npm install`

### Configuration
1.  Copy `.env.example` to `.env`.
2.  Fill in the required credentials and observatory details.

### Running the System
```bash
# Start the Backend
python -u src/backend/main.py

# Start the Frontend
cd src/frontend && npm run dev
```

## 🧪 Testing and Reproducibility
The system is tested against historical gravitational-wave data (e.g., GW170817). Use the `/simulate-gcn-alert` API endpoint to trigger the end-to-end pipeline during development or hackathon presentations.
