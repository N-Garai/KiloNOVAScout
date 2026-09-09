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
| LLM | LiteLLM → Gemini 2.5 Flash (primary) / Groq gpt-oss-120b (fallback) |
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
# Backend (from repo root — package mode is required for relative imports)
PYTHONPATH=src python -u -m backend.main

# Frontend (separate terminal)
cd src/frontend && npm run dev
```

Windows PowerShell equivalents:

```powershell
$env:PYTHONPATH = 'src'; python -u -m backend.main
cd src/frontend; npm run dev
```

Then open http://localhost:5173 (Vite proxies `/api` and `/agent` to the
backend on :8000). Copy `.env.example` to `.env` first — the backend loads
it automatically for keys, credentials, and observatory defaults.

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
| `PRIMARY_LLM` | No | `gemini/gemini-2.5-flash` | Primary LLM model ID (1.5/2.0-flash are retired) |
| `FALLBACK_LLM` | No | `groq/openai/gpt-oss-120b` | Fallback LLM model ID (llama-3.3-70b retired Aug 2026) |
| `OBSERVATORY_NAME` | No | `Palomar` | Observatory name |
| `OBSERVATORY_LAT` | No | `33.356` | Observatory latitude (degrees) |
| `OBSERVATORY_LON` | No | `-116.865` | Observatory longitude (degrees) |
| `OBSERVATORY_ALT` | No | `1706` | Observatory altitude (meters) |
| `ALERT_CLASSES` | No | `bns,grb,neutrino` | Live-watch event classes (comma-separated; also changeable in UI) |
| `GRACEDB_POLL` | No | `false` | Opt-in live BNS polling via public GraceDB REST (works without Kafka/IPv6) |
| `GRACEDB_POLL_MINUTES` | No | `15` | Poll interval in minutes (minimum 5) |
| `ALERT_WEBHOOK_URL` | No | — | HTTPS endpoint receiving a JSON POST on every finished run (Discord/Slack webhook, ntfy.sh topic, PagerDuty) |
| `ALERT_WEBHOOK_SECRET` | No | — | Optional Bearer token sent with webhook alerts (skipped for ntfy.sh) |
| `ALERT_LIVE_ONLY` | No | `false` | Set `true` to notify only on genuine triggers (mock/demo runs skipped) |
| `DIGEST_ENABLED` | No | `false` | Set `true` for the daily digest mail |
| `DIGEST_HOUR_UTC` | No | `6` | Hour of day (UTC, 0–23) the digest is sent |
| `DIGEST_SMTP_HOST` / `DIGEST_SMTP_PORT` | With digest | — | SMTP server, e.g. `smtp.gmail.com` / `465` (SSL) |
| `DIGEST_SMTP_USER` / `DIGEST_SMTP_PASS` | With digest | — | SMTP credentials (Gmail: App Password, not login password) |
| `DIGEST_FROM` / `DIGEST_TO` | With digest | — | Sender display and recipient address(es, comma-separated) |
| `PORT` | Do not set | `8000` | Render injects this automatically |

**No keys needed for:** VizieR TAP (anonymous), Open-Meteo (keyless), bundled replay data (in repo), matplotlib (local Agg backend).

### Render Deployment

1. Create a new Web Service on Render
2. Connect your GitHub repo
3. Set environment variables above in the Render dashboard
4. Render will auto-detect the Dockerfile and build

The Dockerfile uses a multi-stage build: Python builder → Node.js frontend build → Python runtime. The compiled frontend is copied into the backend's static serving path.

## Observatory Operations (24/7)

This section is for astronomers and observatory staff who want KilonovaScout
watching the sky unattended and waking a human on every cosmic event.

### What "live" means here (read first)

"Live" is tracked **per input**, never as a single claim. Every run carries
provenance `{skymap, catalog, event, weather}` with values `live | replay |
cached | point | synthetic | mock`, shown in the dashboard badge, the
telemetry console, and the report header (`point` = map built from the
notice's own coordinates, e.g. GRB/neutrino error circles — real
localization, not a FITS download). A run can legitimately be a mock
trigger with a live catalog and live weather — the UI always says which
is which.
The telemetry console additionally shows the exact signal path (the Kafka
topic or poll source the trigger arrived on) and a watching strip with the
currently subscribed topics and poller state, so there is never ambiguity
about what the backend is listening to.

| Input | Live source | Fallback chain | Needs |
|-------|-------------|----------------|-------|
| Trigger | NASA GCN Kafka (push) or GraceDB REST poller | Per-class replay packets (GW170817 / GBM_170817529 / IC170922A-like) | Kafka: credentials + IPv6 egress. Poller: plain HTTPS only |
| Skymap | FITS download from the notice URL | Bundled `bayestar.fits.gz` → calibrated synthetic | HTTPS (or nothing) |
| Catalog | CDS VizieR TAP (anonymous ADQL) | Bundled GLADE+ cache → deterministic mock rows | HTTPS (or nothing) |
| Weather | Open-Meteo API (keyless) | Safe-default snapshot, labeled `fallback` | HTTPS (or nothing) |
| Rationale | Gemini → Groq | Deterministic summary (always works, zero keys) | API keys (or nothing) |

### Choosing a host

Minimum: Python 3.11, ~1 GB RAM recommended (512 MB proven workable —
watch the `[MEM] stage=… peak_rss=…MB` log lines; sustained readings above
~450 MB mean the host is too small), negligible disk, outbound HTTPS.
Kafka push additionally needs IPv6 egress to `kafka*.gcn.nasa.gov:9092`.

- **Render Free**: fine for demos and opportunistic live coverage. Not true
  24/7 — the platform sleeps idle services after ~15 minutes, one always-on
  service consumes ~720 of the 750 monthly instance-hours, and Kafka is
  unreachable (IPv6). Use it as a public dashboard, not a sentinel.
- **Laptop / lab server / VPS with IPv6**: full operation, including Kafka
  push. This is the recommended sentinel host. Same repo, same `.env` keys,
  `python -u -m backend.main` (see Local Development). A minimal systemd
  unit is provided below.

### Kafka consumer setup

1. Sign in at <https://gcn.nasa.gov/quickstart> and create a credential
   with scope `gcn.nasa.gov/kafka-public-consumer` (selected by default).
2. Format: **VOEvent** (the pipeline parses VOEvent XML only; JSON/Text/
   Binary notices are dropped with a log line).
3. Notice types: tick **Fermi**, **Swift**, **IceCube** (+AMON). Skip
   Heartbeat (1 msg/sec flood), Circulars, and families without a pipeline
   class (CHIME/DSA/EP/MAXI/SuperK/BOOM) — unknown topics default to the BNS
   path, which would mislabel them. There is no LVK entry: LVK discontinued
   VOEvent distribution in July 2026, so BNS live coverage comes from the
   GraceDB poller instead.
4. Set `GCN_KAFKA_CLIENT_ID` / `GCN_KAFKA_CLIENT_SECRET` in the environment
   and (re)start. Healthy signs in the log: `Listening on N topics (...)`
   with no follow-up `Subscribed topic not available` lines. `role="test"`
   drill notices are deliberately ignored — they never spend telescope time.

### GraceDB poller (Kafka-free live BNS coverage)

Set `GRACEDB_POLL=true` (optionally `GRACEDB_POLL_MINUTES`, minimum 5).
Every interval the poller asks public GraceDB — plain IPv4 HTTPS, no
credentials — for new significant Production superevents (SIGNIF_LOCKED,
FAR below threshold) and runs each through the full live pipeline. Guards:
seen-set seeding (boot never replays history), retraction skipping, a
central once-only claim registry (a superevent can never produce two live
runs, whichever entrypoint fires first), and a pipeline busy-lock (a second
concurrent run gets HTTP 429 instead of doubling peak memory into an OOM
kill). Confirm via boot log (`GraceDB poller on …`) and
`GET /api/ping` → `gracedb_poll.last_check` / `last_result`.

### Getting woken up (alerting)

The dashboard approval modal only works when a human is looking at it. For
unattended operation, set `ALERT_WEBHOOK_URL` to any HTTPS endpoint that
accepts a JSON POST. It fires on **every finished run, completed and
failed** — a dead pipeline at 3am is exactly what must wake someone — with
event class, gate verdict, top candidate + score, provenance, observatory
and dome status, and the report path. Optional `ALERT_WEBHOOK_SECRET` is
sent as a Bearer token. Delivery is best-effort (10 s timeout, failures
logged, pipeline never blocked). Fastest zero-setup path: pick an unguessable topic name (it doubles as the
password — no account exists) and point the URL at
`https://ntfy.sh/<your-topic>`; install the phone app, subscribe to the same
topic, and it buzzes on every run. ntfy targets automatically get a native
message (title header, urgent priority when candidates exist) instead of a
JSON blob, and no Bearer token is sent to public topics. Set
`ALERT_LIVE_ONLY=true` to wake the on-call human **only on genuine
triggers** — mock/demo runs are then skipped silently (logged, not sent).
Be explicit about what is *not*
included: there is no built-in SMS/Telegram dispatch — `send_sms_alert`
only logs. Wire your own relay behind the webhook for those channels.

#### Daily digest mail (opt-in)

For a once-a-day summary instead of (or in addition to) per-run buzzes,
set `DIGEST_ENABLED=true` plus the `DIGEST_SMTP_*` / `DIGEST_TO` settings
(any SMTP account works; Gmail needs an App Password, not the login
password). Once per day at `DIGEST_HOUR_UTC` (default 06:00 UTC) the agent
mails every retained run from the last 24 hours with statuses, top
candidates, and clickable report links (`RENDER_EXTERNAL_URL` is prepended
when set, so phone taps land on the report). A quiet sky still sends —
saying so explicitly — so an empty inbox day reads as "all quiet," never
as "mailer broken." The scheduler is a single daemon thread that only
wakes every 10 minutes to check the clock; SMTP failures are logged and
retried the next day, never raised into the pipeline. Turn the whole thing
off with `DIGEST_ENABLED=false` (the default).

##### Getting the Gmail App Password (you don't invent it — Google generates it)

1. Google Account → **Security** → turn on **2-Step Verification**
   (required — the App passwords page won't appear without it).
2. Same page → **App passwords** → pick any name (e.g. `KilonovaScout`) → **Generate**.
3. Google displays a 16-letter code in four groups, like
   `abcd efgh ijkl mnop`. That display *is* the password — copy it.
4. Paste it into `DIGEST_SMTP_PASS` (Render env dashboard or the
   Observatory settings card), with `DIGEST_SMTP_USER` set to your full
   Gmail address. Spaces are fine — they are stripped automatically.

Three facts worth knowing: it is **not** your login password and cannot log
into your account anywhere; you can **revoke** it in one click without
changing anything else; and if you lose it, just generate a fresh one —
Google never shows it again.

#### Configuring without redeploying (dashboard)

Everything above is also editable live in the Observatory section's
**Notification Settings** card — webhook URL, live-only toggle, digest
switch and hour, SMTP host/port/user/password, sender, and recipients —
no restart needed, changes apply to the next run/mail. Secrets are never
echoed back (the API blanks them; blank resubmits keep stored values).
Use **Send test digest now** (`POST /api/digest/send-now`) to prove mail
delivery in seconds instead of waiting for 06:00 UTC; the result line tells
you exactly what was sent or which setting is missing.

### The approval loop

A run ends in one of two states. `target_acquired` ( skies clear, gate
accepted) arms the human gate: the dashboard shows the approval modal and
`APPROVE & EXECUTE` calls `POST /agent/approve-slew-script`, flipping the
agent to `slewing`. `monitoring`/`weather_blocked` (dome unsafe or
overcast) never asks — it logs, notifies via webhook, and waits. Rejecting
is closing the modal: no approval, no slew, full audit trail retained.

### Runbook

```bash
# Health (process alive, observatory, model IDs)
/health
# Liveness + poller state (cheap; safe to hit every minute)
/api/ping
# Latest run, candidates, provenance, rationale
/api/latest-event
# Step-event stream for a run (what the telemetry console shows)
/api/runs/{run_id}/events
# Observation report (Markdown + print-ready HTML + LaTeX)
/api/runs/{run_id}/report
```

Watch the logs for `[MEM]` (memory per stage), `[POLL]` (poller cycles),
`[ALERT]` (webhook deliveries), and `[GCN]` (Kafka state). Run history is
in-memory and capped at 20 — export reports promptly; restarts lose
history. Update by pulling and rebuilding; no migrations, no database.

Minimal systemd unit for a lab server:

```ini
[Unit]
Description=KilonovaScout targeting agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=kilonova
WorkingDirectory=/opt/KiloNOVAScout
EnvironmentFile=/opt/KiloNOVAScout/.env
Environment=PYTHONPATH=src
ExecStart=/opt/KiloNOVAScout/.venv/bin/python -u -m backend.main
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Safety notes: keep `.env` (never committed) restricted to the service
user; drill (`role="test"`) notices are ignored by design — validate the
live path with `python scripts/check_live_path.py` instead; weather
fallback snapshots are labeled and fail *open*, so flip `dome_safe`
handling before this software is allowed near real dome hardware.

## Data Files

| File | Description |
|------|-------------|
| `src/backend/data/bayestar.fits.gz` | GW170817 BAYESTAR skymap, degraded to nside 256 for the 512 MB budget (exact nested coarsening; 90% area 31.16 deg² and distance 36.0 Mpc conserved — see `scripts/degrade_bayestar.py`) |
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

Acceptance checks (run before any deployment or demo):

```bash
python scripts/check_event_classes.py   # gates, scoring profiles, topics (offline)
python scripts/check_llm_parse.py       # rationale extraction (offline)
python scripts/check_notifier.py        # webhook payload + failure paths (offline)
python scripts/check_gracedb_poller.py  # poller rules + live GraceDB discovery (network)
python scripts/check_live_path.py       # full live pipeline on real S190425z (network, ~3 min)
```

The system includes an integrated `EventSimulator` that loads a faithful GW170817 replay packet for reproducible end-to-end testing without waiting for real gravitational-wave detections. `check_live_path.py` is the complement: it replays the real S190425z VOEvent and skymap through the production live entrypoint and asserts all-`live` provenance.

## License

© 2026 KiloNOVAScout. All rights reserved.
