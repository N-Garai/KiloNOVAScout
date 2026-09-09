# KiloNOVAScout Architecture

## System Overview

KiloNOVAScout is an event-driven autonomous agent that processes NASA Gravitational Wave alerts and generates telescope slew scripts without human intervention until the final approval step.

## Component Architecture

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
- **LLM**: LiteLLM → Google Gemini 1.5 Flash (free tier)
- **Astronomy**: Astropy, Healpy
- **Data**: GLADE+ catalog, Open-Meteo API
- **Messaging**: gcn-kafka client

### Frontend
- **Framework**: React 18 + Vite
- **Styling**: Tailwind CSS v4
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
| LLM | Google Gemini 1.5 Flash | Free tier |
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

## v3 Architecture Additions

v3 adds determinism, data-source authenticity and scientific deliverables on
top of the v2 orchestrator:

- **Authentic-data fallback chain (PRD M4).** Every external data source has a
  documented fallback so the app runs identically with zero network:
  * skymap: live download → bundled `data/bayestar.fits.gz` replay → synthetic
    GW170817 reconstruction;
  * catalog: live CDS VizieR TAP → bundled `data/GW170817_region_glade.json` →
    deterministic mock rows.
  * The winning tier per run is recorded in `run_record.provenance
    = {skymap, catalog, event}` and displayed as a frontend badge.
- **Scoring (PRD M7 + M10).** Full composite formula with Schechter luminosity
  weighting, windowed 2-hour airmass integration, R-band atmospheric
  extinction, lunar-separation penalty, GRB-coincidence boost and a
  distance-based kilonova SNR proxy. Every term and its weights are retained
  per-candidate in a `ScoreBreakdown` for full auditability.
- **Slew scheduling (PRD M7.2).** Targets are ordered with a greedy
  nearest-neighbor TSP heuristic on the local alt/az sphere to minimize total
  slew distance.
- **Writer agent (PRD M6).** Generates the observation report in three formats
  — Markdown, print-optimized HTML (PDF via browser print, Render-safe) and
  LaTeX — with a step-by-step calculation trace for every measurement and a
  GCN Circular draft. Served from `GET /api/runs/{run_id}/report`.
- **Visualization agent (PRD M8).** Produces per-run matplotlib plots (Agg
  backend, in-memory base64): Mollweide skymap with candidates, scoring
  breakdown, observing-conditions radar and distance distribution. Generated
  concurrently with the LLM rationale.
- **Observability & reproducibility (PRD M9).** Strands lifecycle hooks audit
  every tool call; a FITS observation header logs the decision; the
  `SkymapUpdateTracker` detects >10° centroid shifts on skymap updates and
  triggers re-authorization; a mid-sequence dome-safety re-check aborts
  before human approval if humidity > 85% or cloud cover > 40%.

## Future Enhancements

- **Per-observer inboxes.** Today observatory location, webhook/digest
  prefs, and the run history are single-tenant globals (`_RUNTIME_PREFS`
  + `run_registry`). A future authenticated mode would scope them per
  account/API key.
- **A2A inter-agent protocol (PRD M9.3).** The Strands A2A protocol is
  documented as the production inter-agent communication layer and is
  deliberately *not* used in the current release: the orchestrator makes
  direct tool calls within a single agent, which keeps the demo deterministic
  and within the 512 MB Render budget. Adopting A2A would let the writer,
  visualization and validator agents run as independent services and is the
  recommended next step for a multi-instance deployment.
- Real-time GCN Kafka listener (production mode)
- Integration with real telescope control systems (ASCOM/INDI)
- Multi-observatory weather checking
- Historical event database
- Machine learning for host galaxy prioritization