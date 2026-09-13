# KilonovaScout Deployment Guide for Render

This document outlines the steps and environment variables required to deploy KilonovaScout to Render.

## 1. Project Structure

```
KiloNOVAScout/
├── .env.example
├── Dockerfile
├── LICENSE                    # Apache 2.0
├── README.md
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   ├── assets/                # Generated diagrams (PNG)
├── config/
│   └── scoring_weights.json   # Scoring formula weights
├── scripts/                   # Validation scripts
│   ├── check_event_classes.py
│   ├── check_llm_parse.py
│   ├── check_notifier.py
│   ├── check_gracedb_poller.py
│   ├── check_live_path.py
│   └── generate_diagrams.py
├── src/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app
│   │   ├── models.py          # Pydantic models
│   │   ├── event_classes.py   # BNS/GRB/neutrino gates
│   │   ├── gcn_listener.py    # Kafka consumer
│   │   ├── gracedb_poller.py  # GraceDB REST poller
│   │   ├── historical.py      # Historical event corpus
│   │   ├── llm_reasoner.py    # LLM reasoning + fallback
│   │   ├── llm_advisors.py    # Per-stage LLM advisors
│   │   ├── notifier.py        # Webhook + email alerts
│   │   ├── run_registry.py    # In-memory run history
│   │   ├── agents/
│   │   │   ├── agent.py       # Master orchestrator
│   │   │   ├── healpix_agent.py
│   │   │   ├── galaxy_agent.py
│   │   │   ├── weather_agent.py
│   │   │   ├── ephemeris_agent.py
│   │   │   ├── scheduler_agent.py
│   │   │   ├── validator_agent.py
│   │   │   ├── visualization_agent.py
│   │   │   ├── writer_agent.py
│   │   │   ├── notification_agent.py
│   │   │   └── subagents/     # Hook-gated specialists
│   │   ├── tools/             # 18 Strands @tool functions
│   │   ├── data/              # Bundled replay data
│   │   ├── simulator/         # EventSimulator
│   │   └── requirements.txt
│   └── frontend/
│       ├── index.html
│       ├── package.json
│       ├── tailwind.config.js
│       ├── vite.config.js
│       └── src/
│           ├── App.jsx
│           └── components/
│               ├── DashboardSection.jsx
│               ├── HistoricalSection.jsx
│               ├── ObservatorySection.jsx
│               ├── EventClassesSection.jsx
│               ├── ArchitectureSection.jsx
│               ├── AgentTerminal.jsx
│               ├── HeroSection.jsx
│               └── Footer.jsx
```

## 2. Backend Setup (FastAPI)

- **Requirements:** `requirements.txt` lists all necessary Python packages.
- **Web Server:** The application uses Uvicorn, launched via `main.py`.

## 3. Frontend Setup (React/Vite)

- **Build Tool:** Vite is used for efficient development and building.
- **Dependencies:** `package.json` lists frontend dependencies.
- **Styling:** Tailwind CSS and Framer Motion are used for styling and animations.

## 4. Dockerfile

- The `Dockerfile` is configured to build and run the Python backend.
- It installs dependencies and exposes port 8000 for the FastAPI application.

## 5. Environment Variables for Render

Render requires certain environment variables to be set for your application to run correctly. These can be configured in your Render service settings under "Environment Variables".

### Required Environment Variables:

- **`PRIMARY_LLM`**: Primary LLM model ID. Default: `gemini/gemini-2.5-flash`
- **`FALLBACK_LLM`**: Fallback LLM model ID. Default: `groq/openai/gpt-oss-120b`
- **`GEMINI_API_KEY`**: Google AI Studio API key (free) — required for LLM reasoning.
- **`GROQ_API_KEY`**: Groq Cloud API key (free) — required for LLM fallback.
- **`OBSERVATORY_NAME`**: Observatory name. Default: `Palomar`
- **`OBSERVATORY_LAT`**: Latitude in decimal degrees. Default: `33.356`
- **`OBSERVATORY_LON`**: Longitude in decimal degrees. Default: `-116.865`
- **`OBSERVATORY_ALT`**: Altitude in meters. Default: `1706`

### Optional Environment Variables:

- **`GCN_KAFKA_CLIENT_ID` / `GCN_KAFKA_CLIENT_SECRET`**: NASA GCN Kafka credentials (free at gcn.nasa.gov/quickstart) — required for live alerts.
- **`GRACEDB_POLL`**: Set `true` for live BNS polling via GraceDB REST (no Kafka needed).
- **`ALERT_WEBHOOK_URL`**: HTTPS endpoint for per-run alerts (Discord/Slack/ntfy.sh).
- **`ALERT_EMAIL_ENABLED`**: Set `true` to mail reports on live triggers.
- **`DIGEST_ENABLED`**: Set `true` for daily digest mail.

### Example Render Configuration:

| Variable Name       | Value                                        |
| :------------------ | :------------------------------------------- |
| `PRIMARY_LLM`       | `gemini/gemini-2.5-flash`                    |
| `FALLBACK_LLM`      | `groq/openai/gpt-oss-120b`                   |
| `GEMINI_API_KEY`    | `YOUR_GOOGLE_AI_STUDIO_KEY`                  |
| `GROQ_API_KEY`      | `YOUR_GROQ_API_KEY`                          |
| `OBSERVATORY_NAME`  | `Palomar`                                    |
| `OBSERVATORY_LAT`   | `33.356`                                     |
| `OBSERVATORY_LON`   | `-116.865`                                   |
| `OBSERVATORY_ALT`   | `1706`                                       |


## 6. Hosting on Render

1.  **Create a new Web Service** on Render.
2.  **Connect your GitHub repository** (after pushing the code).
3.  **Configure Build Settings:**
    *   Build Command: `pip install -r src/backend/requirements.txt && npm install --prefix src/frontend && npm run build --prefix src/frontend`
4.  **Configure Start Command:** `python src/backend/main.py`
5.  **Set Environment Variables:** Enter the variables listed in Section 5.
6.  **Deploy.**

## 7. Database Considerations

For this hackathon submission, **no database is required**. The agent's state is managed in memory. For a production system requiring state persistence across restarts or distributed operation, consider adding a simple key-value store or a database.

## 8. Final Checks

- Ensure all Python syntax errors are resolved (especially f-strings).
- Verify `package.json` syntax and dependencies.
- Test the `/simulate-gcn-alert` endpoint locally to confirm the agent flow.
