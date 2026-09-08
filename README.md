# KiloNOVAScout

Autonomous multi-messenger astronomy targeting agent. Processes NASA GCN gravitational-wave alerts, cross-matches with GLADE+ galaxy catalogs, computes observability with real weather data, and generates telescope slew scripts — all without human intervention until the final approval step.

Built with [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and designed to run on Render Free Tier (512 MB RAM, $0/month).

## Features

### v3 (Current)

- **Authentic data fallback chain** — Live CDS VizieR TAP queries, bundled GW170817 replay data (bayestar.fits.gz + 29 real GLADE+ galaxies), and calibrated synthetic fallbacks. Every data source is labeled with provenance (`live | replay | cached | synthetic | mock`).
- **Advanced astrophysical scoring** — 7-term composite formula with Schechter luminosity function weighting, windowed 2-hour airmass integration, R-band atmospheric extinction, lunar proximity penalty, distance-based kilonova SNR proxy, and GRB coincidence boost. Full per-candidate `ScoreBreakdown` audit trail.
- **TSP-optimized slew scheduling** — Greedy nearest-neighbor heuristic on the local alt/az sphere minimizes total telescope slew distance.
- **Writer agent** — Generates observation reports in Markdown, print-optimized HTML (PDF via browser print), and LaTeX source. Every measurement includes a step-by-step calculation trace. Includes a GCN Circular draft.
- **Visualization agent** — 4 per-run matplotlib plots: Mollweide skymap with candidates, scoring breakdown bars, observing conditions radar chart, and distance distribution histogram. Generated concurrently with LLM rationale.
- **FITS observation header** — Standardized 31-card FITS header for scientific reproducibility.
- **Dynamic re-pointing** — `SkymapUpdateTracker` detects >10° centroid shifts on skymap updates and triggers re-authorization.
- **Mid-sequence dome safety** — Fresh weather check between slew-script generation and human approval with emergency abort thresholds (humidity >85%, cloud cover >40%).
- **Tool-call audit logging** — Strands `AfterToolCallEvent` hook for observability.
- **Scroll-triggered architecture panel** — Real-time agent dispatch log fetched from `/api/latest-event`.

### Multi-event classes (current)

Beyond neutron-star mergers, the agent triages three cosmic trigger families end-to-end — each with its own Kafka topics, ingest gate, scoring profile, and report section:

| Class | Notices | Gate | Ranking math |
|-------|---------|------|--------------|
| Neutron-star merger | LVC INITIAL/PRELIMINARY/UPDATE | HasNS / BNS+NSBH component, FAR < 1/yr | Full 7-term formula incl. Schechter host mass |
| Gamma-ray burst | Fermi-GBM Alert/Fin-Pos, Swift-BAT | T90 duration + fluence/peak-flux triage | Host/SNR terms off; burst-flux proxy (θ) drives priority; point-localized HEALPix built from RA/Dec + error radius |
| High-energy neutrino | IceCube Gold/Bronze tracks | Signalness tiers (gold ≥ 0.5, bronze ≥ 0.3) | Containment + signalness (κ) over degree-scale region; tiling guidance in report |

Users choose what to be alerted on two ways: **Live watch** toggles in the demo section (persisted to backend config, listener resubscribes without restart) and a **demo trigger-class picker** (`POST /api/simulate-event?event_class=grb`). `GET /api/event-classes` lists families, enablement, and subscribed topics.

### v2

- DAG-style orchestration (ingest → skymap → catalog‖weather → GRB validation → scheduler → LLM rationale → human approval)
- Live NASA GCN Kafka listener with mock fallback
- Real-time SSE execution timeline in the frontend
- Observatory configuration picker with d3-geo coordinate inversion

### v1

- Core agent pipeline, HEALPix skymap parsing, GLADE+ crossmatch
- Open-Meteo weather integration
- ASCOM/INDI XML slew script generation
- React frontend with Three.js starfield

## Architecture

```
NASA GCN Kafka → Ingestion → HEALPix Triage → Galaxy Crossmatch →
  ├── Ephemeris & Weather (parallel) ──┤
  └── GRB Validator ──→ Scheduler (TSP) ──→ Dome Safety ──→
      LLM Rationale ‖ Visualization (parallel) ──→ FITS Header ──→
      Writer Agent ──→ Human Approval
```

See [docs/architecture.md](docs/architecture.md) for the full system diagram.

## Stack

| Layer | Technology |
|-------|-----------|
| Agent SDK | Strands Agents 1.26.0 |
| LLM | LiteLLM → Gemini 1.5 Flash (primary) / Groq Llama3-70B (fallback) |
| Backend | FastAPI, Python 3.11 |
| Astronomy | astropy, astropy-healpix, numpy |
| Weather | Open-Meteo API (keyless) |
| Galaxy catalog | CDS VizieR TAP (anonymous ADQL) |
| GW alerts | gcn-kafka client |
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion, Three.js |
| Hosting | Render Free Tier (512 MB RAM) |
| Containerization | Docker multi-stage build |

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)

### Local Development

```bash
# Backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r src/backend/requirements.txt

# Frontend
cd src/frontend && npm install
```

### Running

```bash
# Backend (from repo root)
PYTHONPATH=src python -u src/backend/main.py

# Frontend (separate terminal)
cd src/frontend && npm run dev
```

### Docker

```bash
docker build -t kilonovascout .
docker run -p 8000:8000 kilonovascout
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/simulate-event` | Run the GW170817 demo pipeline |
| POST | `/simulate-gcn-alert` | Legacy alias |
| GET | `/api/latest-event` | Latest run record with provenance |
| GET | `/api/runs/{run_id}/events` | SSE stream of step events |
| GET | `/api/runs/{run_id}/report` | Writer-agent report (Markdown + HTML + LaTeX) |
| GET | `/api/report/{run_id}` | Legacy Markdown report |
| GET | `/agent/config` | Observatory configuration |
| PUT | `/agent/config` | Update observatory location |
| GET | `/agent/state` | Current agent state |
| GET | `/agent/status` | Status summary |
| POST | `/agent/approve-slew-script` | Approve the slew script |
| GET | `/health` | Health check |

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | For LLM reasoning | — | Google AI Studio API key ([free](https://aistudio.google.com/app/apikey)) |
| `GROQ_API_KEY` | For LLM failover | — | Groq Cloud API key ([free](https://console.groq.com/keys)) |
| `GCN_KAFKA_CLIENT_ID` | For live alerts | — | NASA GCN Kafka client ID ([free](https://gcn.nasa.gov/quickstart)) |
| `GCN_KAFKA_CLIENT_SECRET` | For live alerts | — | NASA GCN Kafka client secret |
| `PRIMARY_LLM` | No | `gemini/gemini-1.5-flash` | Primary LLM model ID |
| `FALLBACK_LLM` | No | `groq/llama3-70b-8192` | Fallback LLM model ID |
| `OBSERVATORY_NAME` | No | `Palomar` | Observatory name |
| `OBSERVATORY_LAT` | No | `33.356` | Observatory latitude (degrees) |
| `OBSERVATORY_LON` | No | `-116.865` | Observatory longitude (degrees) |
| `OBSERVATORY_ALT` | No | `1706` | Observatory altitude (meters) |
| `ALERT_CLASSES` | No | `bns,grb,neutrino` | Live-watch event classes (comma-separated; also changeable in UI) |
| `PORT` | Do not set | `8000` | Render injects this automatically |

**No keys needed for:** VizieR TAP (anonymous), Open-Meteo (keyless), bundled replay data (in repo), matplotlib (local Agg backend).

### Render Deployment

1. Create a new Web Service on Render
2. Connect your GitHub repo
3. Set environment variables above in the Render dashboard
4. Render will auto-detect the Dockerfile and build

The Dockerfile uses a multi-stage build: Python builder → Node.js frontend build → Python runtime. The compiled frontend is copied into the backend's static serving path.

## Data Files

| File | Description |
|------|-------------|
| `src/backend/data/bayestar.fits.gz` | GW170817 BAYESTAR skymap (flat HEALPix, PROB/DISTMU/DISTSIGMA) |
| `src/backend/data/GW170817_initial.json` | Faithful VOEvent replay packet (real IVORN, trigger time) |
| `src/backend/data/GW170817_region_glade.json` | 29 real GLADE+ galaxies from live VizieR TAP (NGC 4993 verified) |
| `config/scoring_weights.json` | Full v3 scoring formula weights |

## Scoring Formula

```
S_i = α·P_spatial + β·w_Schechter − γ·X̄ − δ·C + ε·B_GRB + ζ·SNR − η·L_moon
```

| Term | Weight | Description |
|------|--------|-------------|
| `α` | 1.0 | Spatial containment probability |
| `β` | 0.5 | Schechter luminosity function weight |
| `γ` | 0.3 | Windowed airmass (2-hour integration) |
| `δ` | 0.2 | Cloud cover penalty |
| `ε` | 3.0 | GRB coincidence boost |
| `ζ` | 0.15 | Distance-based SNR proxy |
| `η` | 0.1 | Lunar proximity penalty |

See `config/scoring_weights.json` for all parameters including Schechter L★, α, zenith extinction, and peak kilonova magnitude.

## Testing

```bash
# Run the demo pipeline
curl -X POST http://localhost:8000/api/simulate-event

# Check health
curl http://localhost:8000/health
```

The system includes an integrated `EventSimulator` that loads a faithful GW170817 replay packet for reproducible end-to-end testing without waiting for real gravitational-wave detections.

## License

© 2026 KiloNOVAScout. All rights reserved.
