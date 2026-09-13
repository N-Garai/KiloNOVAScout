# KiloNOVAScout Architecture

## System Overview

KiloNOVAScout is an event-driven autonomous agent that processes NASA gravitational-wave, gamma-ray burst, and high-energy neutrino alerts and generates telescope slew scripts without human intervention until the final approval step.

## Component Architecture

> Detailed diagrams are available in [`docs/assets/`](assets/) with source scripts in [`docs/assets-script/`](assets-script/).

```
┌─────────────────────────────────────────────────────────┐
│                    NASA GCN Kafka Stream                 │
│              (gcn-kafka Python client)                   │
└────────────────────┬────────────────────────────────────┘
                     │ GW Alert (VOEvent XML)
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Strands Orchestrator Agent                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Tool 1: parse_healpix_map()                      │  │
│  │ - Downloads LIGO skymap FITS file                │  │
│  │ - Extracts 90% probability volume                │  │
│  │ - Libraries: astropy, healpy                     │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Tool 2: query_glade_catalog()                    │  │
│  │ - Cross-references GLADE+ galaxy catalog         │  │
│  │ - Filters by probability volume                  │  │
│  │ - Returns top 5 candidate hosts                  │  │
│  │ - Libraries: astropy                             │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Tool 3: check_observatory_weather()              │  │
│  │ - Queries Open-Meteo API                         │  │
│  │ - Checks cloud cover, visibility, wind           │  │
│  │ - Determines observability                         │  │
│  │ - API: Open-Meteo (free, no key)                 │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Tool 4: generate_slew_script()                   │  │
│  │ - Creates ASCOM/INDI XML script                  │  │
│  │ - Prioritizes targets by host probability        │  │
│  │ - Includes exposure times, filters               │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                              │
└──────────────────────────┼──────────────────────────────┘
                           │ Target Acquired
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Human Approval Layer                    │
│                                                          │
│  - UI Dashboard with execution trace                    │
│  - SMS/Email notification                               │
│  - 1-click approve/reject                               │
│  - Slew script preview                                  │
└─────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Alert Ingestion**: NASA GCN Kafka stream delivers VOEvent XML
2. **Parsing**: Agent extracts RA, Dec, distance, error radius
3. **Astrometry**: HEALPix skymap processed to get probability volume
4. **Catalog Query**: GLADE+ galaxies filtered by spatial overlap
5. **Weather Check**: Open-Meteo API queried for observatory conditions
6. **Script Generation**: XML slew script created for top candidates
7. **Human Notification**: Alert sent with script preview
8. **Execution**: Upon approval, script sent to telescope control system

## Technology Stack

### Backend
- **Framework**: FastAPI (async, high-performance)
- **Agent SDK**: Strands Agents (orchestration)
- **LLM**: LiteLLM → Google Gemini 2.5 Flash (primary) / Groq gpt-oss-120b (fallback)
- **Astronomy**: Astropy, Healpy
- **Data**: GLADE+ catalog, Open-Meteo API
- **Messaging**: gcn-kafka client

### Frontend
- **Framework**: React 18 + Vite
- **Styling**: Tailwind CSS v3
- **Animation**: Framer Motion, Three.js (starfield)
- **HTTP**: Axios
- **Fonts**: Orbitron (cosmic), Space Grotesk, Space Mono

### Infrastructure
- **Hosting**: Render (free tier)
- **Containerization**: Docker multi-stage build
- **CI/CD**: GitHub Actions (optional)

## Event Replay Harness

For hackathon demos, the backend includes a simulation endpoint:

```python
POST /api/simulate-event
{
  "event_id": "GW170817",
  "observatory_lat": 31.9583,
  "observatory_lon": -111.5967
}
```

This injects the famous GW170817 neutron star merger payload into the agent loop, enabling 100% reproducible 5-minute demos without waiting for real gravitational wave detections.

## Zero-Cost Architecture

All components use free tiers or open-source tools:

| Component | Service | Cost |
|-----------|---------|------|
| LLM | Google Gemini 2.5 Flash (primary) / Groq gpt-oss-120b (fallback) | Free tier |
| Weather | Open-Meteo API | Free, no key |
| Galaxy Data | GLADE+ catalog | Open access |
| Hosting | Render | Free tier |
| GW Alerts | NASA GCN | Open access |
| Agent SDK | Strands Agents | Open source |

**Total Monthly Cost: $0**

## Security Considerations

- API keys stored in environment variables
- CORS configured for frontend-backend communication
- Input validation on all endpoints
- Rate limiting on simulation endpoint
- No persistent storage of sensitive data

## Scalability

- Async FastAPI handles concurrent requests
- Agent tools are stateless and parallelizable
- Frontend is static and CDN-cacheable
- Docker container can scale horizontally

## Advanced Capabilities

Built on top of the core orchestrator:

- **Authentic-data fallback chain.** Every external data source has a documented fallback so the app runs identically with zero network: skymap (live download, bundled replay, synthetic reconstruction), catalog (live VizieR TAP, bundled cache, deterministic mock rows). The winning tier per run is recorded in `run_record.provenance = {skymap, catalog, event}` and displayed as a frontend badge.
- **Scoring.** Full composite formula with Schechter luminosity weighting, windowed 2-hour airmass integration, R-band atmospheric extinction, lunar-separation penalty, GRB-coincidence boost and a distance-based kilonova SNR proxy. Every term and its weights are retained per-candidate in a `ScoreBreakdown` for full auditability.
- **Slew scheduling.** Targets are ordered with a greedy nearest-neighbor TSP heuristic on the local alt/az sphere to minimize total slew distance.
- **Writer agent.** Generates the observation report in three formats — Markdown, print-optimized HTML (PDF via browser print, Render-safe) and LaTeX — with a step-by-step calculation trace for every measurement and a GCN Circular draft. Served from `GET /api/runs/{run_id}/report`.
- **Visualization agent.** Produces per-run matplotlib plots (Agg backend, in-memory base64): Mollweide skymap with candidates, scoring breakdown, observing-conditions radar, distance distribution, score vs airmass, tiling map, and weather gauge. LLM selects 2-4 per run based on event context. Generated concurrently with the LLM rationale.
- **LLM reasoning.** Gemini 2.5 Flash (primary) / Groq gpt-oss-120b (fallback) with 6-field structured JSON output. Class-aware prompt prevents false rejections.
- **Historical analysis.** Live queries to NASA GraceDB for BNS events; curated archive for GRB/neutrino. Batch retrospective analysis through the same pipeline.
- **Observability & reproducibility.** Strands lifecycle hooks audit every tool call; a FITS observation header logs the decision; the `SkymapUpdateTracker` detects >10 degree centroid shifts on skymap updates and triggers re-authorization; a mid-sequence dome-safety re-check aborts before human approval if humidity > 85% or cloud cover > 40%.

## Future Enhancements

- Per-observer inboxes (today single-tenant; a future authenticated mode would scope per account/API key)
- A2A inter-agent protocol for multi-instance deployment
- Real-time GCN Kafka listener (production mode)
- Integration with real telescope control systems (ASCOM/INDI)
- Multi-observatory weather checking
- Machine learning for host galaxy prioritization