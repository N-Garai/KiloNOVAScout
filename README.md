# KiloNOVAScout

Autonomous multi-messenger astronomy targeting agent. Processes NASA gravitational-wave, gamma-ray burst, and high-energy neutrino alerts, cross-matches with GLADE+ galaxy catalogs, computes observability with real weather data, and generates telescope slew scripts — all without human intervention until the final approval step.

Built with [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and designed to run on Render Free Tier (512 MB RAM, $0/month).

---

## Who is this for?

**Astronomers and observatory staff** who want to respond faster to cosmic alerts. When LIGO detects a neutron star merger, or Fermi catches a gamma-ray burst, or IceCube spots a high-energy neutrino, there is a narrow window to point telescopes before the signal fades. This agent compresses hours of manual data processing — sky map parsing, galaxy cross-matching, weather checks, target scoring, observation plan writing — into about 90 seconds. The astronomer approves at the end. Everything before that is autonomous.

**Multi-messenger researchers** who work across gravitational-wave, gamma-ray, and neutrino astronomy and need a single tool that handles all three event classes with dedicated scoring profiles and report sections.

**Developers and hackathon participants** who want to see a real-world agentic pipeline built with Strands Agents SDK — multi-stage DAG, hook-gated specialists, LLM reasoning, parallel tool calls, SSE streaming, and graceful degradation to offline mode.

---

## Will it work for me?

| Environment | Live alerts | Live catalog | Live weather | Historical search | Notes |
|-------------|-------------|--------------|--------------|-------------------|-------|
| **Render Free Tier** | GraceDB poller only (no Kafka — IPv6 required) | Yes (VizieR) | Yes (Open-Meteo) | Yes | Good for demos and opportunistic coverage. Sleeps after ~15 min idle. |
| **Laptop / lab server** | Kafka push + GraceDB poller | Yes | Yes | Yes | Full operation. Recommended for unattended sentinel. |
| **VPS with IPv6** | Kafka push + GraceDB poller | Yes | Yes | Yes | Best for 24/7 operation. |
| **Offline / no network** | Bundled replay packets | Bundled GLADE+ cache | Safe-default snapshot | Curated archive only | Runs identically with zero network. All fallbacks labeled. |

**Kafka requires IPv6.** NASA's Kafka servers (`kafka*.gcn.nasa.gov:9092`) only accept IPv6 connections. If your host does not have IPv6 (most home networks, Render Free Tier), use the **GraceDB poller** instead — it uses plain HTTPS, no credentials needed, and covers all significant BNS events. Set `GRACEDB_POLL=true` in your `.env`.

---

## Features

### Multi-event classes

The agent triages three cosmic trigger families end-to-end — each with its own ingest gate, scoring profile, and report section:

| Class | Notices | Gate | Ranking math |
|-------|---------|------|--------------|
| Neutron-star merger | LVC INITIAL/PRELIMINARY/UPDATE | HasNS / BNS+NSBH component, FAR < 1/yr | Full 7-term formula incl. Schechter host mass |
| Gamma-ray burst | Fermi-GBM Alert/Fin-Pos, Swift-BAT | T90 duration + fluence/peak-flux triage | Host/SNR terms off; burst-flux proxy drives priority; point-localized HEALPix built from RA/Dec + error radius |
| High-energy neutrino | IceCube Gold/Bronze tracks | Signalness tiers (gold >= 0.5, bronze >= 0.3) | Containment + signalness over degree-scale region; tiling guidance in report |

Users choose what to be alerted on two ways: **Live watch** toggles in the demo section (persisted to backend config, listener resubscribes without restart) and a **demo trigger-class picker** (`POST /api/simulate-event?event_class=grb`). `GET /api/event-classes` lists families, enablement, and subscribed topics.

---

### LLM reasoning

The agent uses LLM reasoning (Gemini 2.5 Flash primary, Groq gpt-oss-120b fallback) for rationale generation and decision classification. Every run produces a 6-field structured JSON output: `decision`, `confidence`, `risks`, `actions`, `rationale`, `citations`. The prompt is class-aware — it does not reject BNS events for missing FAR, does not reject neutrinos for missing signalness, and does not reject GRBs for missing brightness. A truncation-safe fallback parser handles malformed LLM output.

---

### Visualization selector

A pool of 7 plot types is available: Mollweide skymap with candidates, scoring breakdown bars, observing conditions radar, distance distribution histogram, score vs airmass, tiling map, and weather gauge. The LLM selects 2-4 per run based on event context (e.g. tiling maps only for large error regions). Plots are generated concurrently with the LLM rationale using matplotlib's Agg backend.

---

### Historical analysis

The dashboard offers retrospective analysis of real past events: pick classes + a year range, search, tick events, and launch a batch. Every event runs through the identical pipeline (same scoring, same report, same approval flow) — only the provenance label differs (`historical:<ID>`).

BNS rows marked with a live badge are queried live from the NASA GraceDB significant-superevent catalog for the chosen range (each links to its official superevent page). GRB/neutrino rows come from a curated archive because no stable anonymous JSON catalog exists for those yet — the origin badge says which is which. Batch traces stream into the shared Agent Observatory in realtime, results compare side by side, and each row opens its own full report.

#### Why the historical archive starts in 1987

There are no localizable transients in these three classes before 1987: gravitational-wave detectors did not exist (first detection 2015), gamma-ray burst positions did not exist before BeppoSAX localized GRB 970228 (1997), and neutrino telescopes did not exist before SN 1987A — the February 1987 MeV burst seen by IMB/Kamiokande/Baksan, which opens the archive. The year picker runs 1987 to current year (the end advances automatically). Anything earlier would be an empty search by construction, not a data gap.

---

### Authentic data fallback chain

Every external data source has a documented fallback so the app runs identically with zero network:

| Input | Live source | Fallback chain | Needs |
|-------|-------------|----------------|-------|
| Trigger | NASA GCN Kafka (push) or GraceDB REST poller | Per-class replay packets (GW170817 / GBM_170817529 / IC170922A-like) | Kafka: credentials + IPv6 egress. Poller: plain HTTPS only |
| Skymap | FITS download from the notice URL | Bundled bayestar.fits.gz -> calibrated synthetic | HTTPS (or nothing) |
| Catalog | CDS VizieR TAP (anonymous ADQL) | Bundled GLADE+ cache -> deterministic mock rows | HTTPS (or nothing) |
| Weather | Open-Meteo API (keyless) | Safe-default snapshot, labeled fallback | HTTPS (or nothing) |
| Rationale | Gemini -> Groq | Deterministic summary (always works, zero keys) | API keys (or nothing) |

The winning tier per run is recorded in `run_record.provenance = {skymap, catalog, event, weather}` and displayed as a frontend badge.

---

### Scoring engine

A 7-term composite formula ranks each candidate host galaxy:

```
Si = alpha*Pspatial + beta*wSchechter - gamma*Xbar - delta*C + epsilon*BGRB + zeta*SNR - eta*Lmoon
```

| Term | Weight | Description |
|------|--------|-------------|
| alpha | 1.0 | Spatial containment probability |
| beta | 0.5 | Schechter luminosity function weight |
| gamma | 0.3 | Windowed airmass (2-hour integration) |
| delta | 0.2 | Cloud cover penalty |
| epsilon | 3.0 | GRB coincidence boost |
| zeta | 0.15 | Distance-based SNR proxy |
| eta | 0.1 | Lunar proximity penalty |

Every term and its weights are retained per-candidate in a `ScoreBreakdown` for full auditability. See `config/scoring_weights.json` for all parameters including Schechter L-star, alpha, zenith extinction, and peak kilonova magnitude.

---

### Additional capabilities

- **TSP-optimized slew scheduling** — Greedy nearest-neighbor heuristic on the local alt/az sphere minimizes total telescope slew distance.
- **Writer agent** — Generates observation reports in Markdown, print-optimized HTML (PDF via browser print), and LaTeX source. Every measurement includes a step-by-step calculation trace. Includes a GCN Circular draft.
- **FITS observation header** — Standardized 31-card FITS header for scientific reproducibility.
- **Dynamic re-pointing** — `SkymapUpdateTracker` detects >10 degree centroid shifts on skymap updates and triggers re-authorization.
- **Mid-sequence dome safety** — Fresh weather check between slew-script generation and human approval with emergency abort thresholds (humidity >85%, cloud cover >40%).
- **Tool-call audit logging** — Strands `AfterToolCallEvent` hook for observability.
- **Scroll-triggered architecture panel** — Real-time agent dispatch log fetched from `/api/latest-event`.

---

## Architecture

```
NASA GCN Kafka -> Ingestion -> HEALPix Triage -> Galaxy Crossmatch ->
  |-- Ephemeris & Weather (parallel) --|
  +-- GRB Validator --> Scheduler (TSP) --> Dome Safety -->
      LLM Rationale || Visualization (parallel) --> FITS Header -->
      Writer Agent --> Human Approval
```

High-resolution diagrams are available in `docs/assets/` (system architecture, agent pipeline, event class triage, data fallback chain, deployment topology, scoring formula). Source mermaid scripts are in `docs/assets-script/`.

See [docs/architecture.md](docs/architecture.md) for the full component architecture.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Agent SDK | Strands Agents 1.26.0 |
| LLM | LiteLLM -> Gemini 2.5 Flash (primary) / Groq gpt-oss-120b (fallback) |
| Backend | FastAPI, Python 3.11 |
| Astronomy | astropy, astropy-healpix, numpy |
| Weather | Open-Meteo API (keyless) |
| Galaxy catalog | CDS VizieR TAP (anonymous ADQL) |
| GW alerts | gcn-kafka client |
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion, Three.js |
| Hosting | Render Free Tier (512 MB RAM) |
| Containerization | Docker multi-stage build |

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- Git

### Quick start (local development)

1. Clone the repository:

```bash
git clone https://github.com/N-Garai/KiloNOVAScout.git
cd KiloNOVAScout
```

2. Set up the backend:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r src/backend/requirements.txt
```

3. Set up the frontend:

```bash
cd src/frontend && npm install
```

4. Copy `.env.example` to `.env` and fill in your API keys (see [Configuration](#configuration) below).

5. Run the backend from the repo root (package mode is required for relative imports):

```bash
PYTHONPATH=src python -u -m backend.main
```

6. Run the frontend in a separate terminal:

```bash
cd src/frontend && npm run dev
```

7. Open http://localhost:5173. Vite proxies `/api` and `/agent` to the backend on :8000.

Windows PowerShell equivalents:

```powershell
$env:PYTHONPATH = 'src'; python -u -m backend.main
cd src/frontend; npm run dev
```

### Lab setup (unattended sentinel)

This is for running KiloNOVAScout on a lab server, department machine, or home server that stays on 24/7 and watches for cosmic alerts unattended.

**Step 1: Clone and install**

```bash
git clone https://github.com/N-Garai/KiloNOVAScout.git /opt/KiloNOVAScout
cd /opt/KiloNOVAScout
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/backend/requirements.txt
```

**Step 2: Configure environment**

```bash
cp .env.example .env
nano .env  # or your preferred editor
```

Minimum for unattended operation:

```
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
OBSERVATORY_NAME=Your Observatory
OBSERVATORY_LAT=your_latitude
OBSERVATORY_LON=your_longitude
OBSERVATORY_ALT=your_altitude_meters
GRACEDB_POLL=true
ALERT_WEBHOOK_URL=https://ntfy.sh/your-unguessable-topic-name
ALERT_LIVE_ONLY=true
```

For email digest (optional):

```
DIGEST_ENABLED=true
DIGEST_SMTP_HOST=smtp.gmail.com
DIGEST_SMTP_PORT=465
DIGEST_SMTP_USER=your_email@gmail.com
DIGEST_SMTP_PASS=your_16_char_app_password
DIGEST_FROM=KiloNOVAScout <your_email@gmail.com>
DIGEST_TO=your_email@gmail.com
```

**Step 3: Test locally first**

```bash
PYTHONPATH=src python -u -m backend.main
```

Verify the boot log shows `GraceDB poller on ...` and no `Subscribed topic not available` errors. Hit `http://localhost:8000/health` to confirm.

**Step 4: Set up as a systemd service**

```bash
sudo cp /opt/KiloNOVAScout/scripts/kilonovascout.service /etc/systemd/system/
# or create manually — see the unit file below
sudo systemctl daemon-reload
sudo systemctl enable kilonovascout
sudo systemctl start kilonovascout
```

Minimal systemd unit:

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

**Step 5: Verify it's running**

```bash
sudo systemctl status kilonovascout
curl http://localhost:8000/api/ping
# Should return JSON with "gracedb_poll": {"last_check": ..., "last_result": ...}
```

**What you get in lab mode:**

- Live BNS alerts from GraceDB (polled every 15 minutes by default)
- Live galaxy catalog from VizieR (anonymous, no API key)
- Live weather from Open-Meteo (keyless)
- Webhook notifications on every run (ntfy.sh, Discord, Slack, etc.)
- Daily email digest of all runs
- Historical event search and batch analysis
- Full dashboard at `http://your-server:8000`

**What you don't get on lab without IPv6:**

- Kafka push alerts (NASA's Kafka servers require IPv6 — use the GraceDB poller instead)

### Docker

```bash
docker build -t kilonovascout .
docker run -p 8000:8000 kilonovascout
```

The Dockerfile uses a multi-stage build: Python builder -> Node.js frontend build -> Python runtime. The compiled frontend is copied into the backend's static serving path.

On Render, the Dockerfile is auto-detected. Set environment variables in the Render dashboard.

---

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
| GET | `/api/historical/events` | Search past events by class + year range (live GraceDB BNS + curated archive) |
| POST | `/api/historical/analyze` | Run a retrospective batch over event IDs |
| GET | `/api/historical/batch/{batch_id}` | Batch status + per-event comparison table |
| GET | `/health` | Health check |

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | For LLM reasoning | — | Google AI Studio API key ([free](https://aistudio.google.com/app/apikey)) |
| `GROQ_API_KEY` | For LLM failover | — | Groq Cloud API key ([free](https://console.groq.com/keys)) |
| `GCN_KAFKA_CLIENT_ID` | For live alerts | — | NASA GCN Kafka client ID ([free](https://gcn.nasa.gov/quickstart)) |
| `GCN_KAFKA_CLIENT_SECRET` | For live alerts | — | NASA GCN Kafka client secret |
| `PRIMARY_LLM` | No | `gemini/gemini-2.5-flash` | Primary LLM model ID |
| `FALLBACK_LLM` | No | `groq/openai/gpt-oss-120b` | Fallback LLM model ID |
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
| `ALERT_EMAIL_ENABLED` | No | `false` | Set `true` to mail the full report (Markdown + HTML attached) to `DIGEST_TO` the moment a genuine live trigger finishes; mock/demo/historical runs never mail |
| `DIGEST_ENABLED` | No | `false` | Set `true` for the daily digest mail |
| `DIGEST_HOUR_UTC` | No | `6` | Hour of day (UTC, 0-23) the digest is sent |
| `DIGEST_SMTP_HOST` / `DIGEST_SMTP_PORT` | With digest | — | SMTP server, e.g. `smtp.gmail.com` / `465` (SSL) |
| `DIGEST_SMTP_USER` / `DIGEST_SMTP_PASS` | With digest | — | SMTP credentials (Gmail: App Password, not login password) |
| `DIGEST_FROM` / `DIGEST_TO` | With digest | — | Sender display and recipient address(es, comma-separated) |
| `PORT` | Do not set | `8000` | Render injects this automatically |

No keys needed for: VizieR TAP (anonymous), Open-Meteo (keyless), bundled replay data (in repo), matplotlib (local Agg backend).

---

### Render deployment

1. Create a new Web Service on Render
2. Connect your GitHub repo
3. Set environment variables above in the Render dashboard
4. Render will auto-detect the Dockerfile and build

---

## Observatory Operations

This section is for astronomers and observatory staff who want KilonovaScout watching the sky unattended and waking a human on every cosmic event.

### What "live" means

"Live" is tracked per input, never as a single claim. Every run carries provenance `{skymap, catalog, event, weather}` with values `live | replay | cached | point | synthetic | mock`, shown in the dashboard badge, the telemetry console, and the report header. A run can legitimately be a mock trigger with a live catalog and live weather — the UI always says which is which.

### Choosing a host

Minimum: Python 3.11, ~1 GB RAM recommended (512 MB proven workable — watch the `[MEM] stage=... peak_rss=...MB` log lines; sustained readings above ~450 MB mean the host is too small), negligible disk, outbound HTTPS. Kafka push additionally needs IPv6 egress to `kafka*.gcn.nasa.gov:9092`.

- **Render Free**: fine for demos and opportunistic live coverage. Not true 24/7 — the platform sleeps idle services after ~15 minutes, one always-on service consumes ~720 of the 750 monthly instance-hours, and Kafka is unreachable (IPv6). Use it as a public dashboard, not a sentinel.
- **Laptop / lab server / VPS with IPv6**: full operation, including Kafka push. This is the recommended sentinel host. Same repo, same `.env` keys, `python -u -m backend.main` (see Local Development). A minimal systemd unit is provided below.

---

### Kafka consumer setup (live alerts from NASA)

**Requires IPv6.** NASA's Kafka servers (`kafka*.gcn.nasa.gov:9092`) only accept IPv6 connections. If your host does not have IPv6, skip this and use the [GraceDB poller](#gracedb-poller-kafka-free-live-bns-coverage) instead.

**Step 1: Get GCN credentials**

1. Go to https://gcn.nasa.gov/quickstart
2. Sign in (free NASA Earthdata account)
3. Create a credential with scope `gcn.nasa.gov/kafka-public-consumer` (selected by default)
4. Copy the client ID and client secret

**Step 2: Choose notice format and topics**

Format: **VOEvent** (the pipeline parses VOEvent XML only — JSON/Text/Binary notices are dropped with a log line).

Notice types to subscribe to:
- **Fermi** — gamma-ray burst alerts
- **Swift** — gamma-ray burst alerts
- **IceCube** (+AMON) — high-energy neutrino alerts

Skip these:
- **Heartbeat** — 1 message/second flood, not real alerts
- **Circulars** — not trigger notices
- **CHIME/DSA/EP/MAXI/SuperK/BOOM** — no pipeline class, would mislabel as BNS

There is no LVK entry: LVK discontinued VOEvent distribution in July 2026. BNS live coverage comes from the GraceDB poller.

**Step 3: Set environment variables**

```
GCN_KAFKA_CLIENT_ID=your_client_id
GCN_KAFKA_CLIENT_SECRET=your_client_secret
```

**Step 4: Restart and verify**

```bash
# Check the boot log for:
#   Listening on N topics (...)
#   (no "Subscribed topic not available" lines)
#   (no "role=test" lines — those are drills, deliberately ignored)
```

```bash
curl http://localhost:8000/api/ping
# Should show kafka topics with no errors
```

---

### GraceDB poller (Kafka-free live BNS coverage)

This is the recommended way to get live gravitational-wave alerts. No Kafka, no IPv6, no credentials — just plain HTTPS to NASA's public GraceDB API.

**Step 1: Enable it**

```
GRACEDB_POLL=true
```

Optionally change the poll interval (default 15 minutes, minimum 5):

```
GRACEDB_POLL_MINUTES=10
```

**Step 2: Restart and verify**

```bash
# Boot log should show:
#   GraceDB poller on ... (every N minutes)
```

```bash
curl http://localhost:8000/api/ping
# Response should include:
#   "gracedb_poll": {"last_check": "2026-09-13T...", "last_result": "ok"}
```

**How it works:**

Every interval, the poller asks public GraceDB for new significant Production superevents (SIGNIF_LOCKED, FAR below threshold). Each new event runs through the full live pipeline — same as a Kafka alert.

**Safety guards:**

- **Seen-set seeding** — on boot, the poller loads recent history so it never replays old events
- **Retraction skipping** — retracted superevents are ignored
- **Once-only claim registry** — a superevent can never produce two live runs, whichever entrypoint fires first
- **Pipeline busy-lock** — a second concurrent run gets HTTP 429 instead of doubling peak memory into an OOM kill

**What it covers:**

- All significant BNS (binary neutron star) and NSBH (neutron star-black hole) superevents
- Does NOT cover GRBs or neutrinos (no stable anonymous catalog for those — use the curated historical archive)

---

### Getting woken up (alerting)

The dashboard approval modal only works when a human is looking at it. For unattended operation, you need webhook notifications.

**Step 1: Pick a notification channel**

| Channel | Setup time | Cost | Needs account? |
|---------|-----------|------|----------------|
| **ntfy.sh** (recommended) | 2 minutes | Free | No — pick a topic name, that's it |
| Discord webhook | 5 minutes | Free | Yes — create a Discord server |
| Slack webhook | 5 minutes | Free | Yes — create a Slack workspace |
| PagerDuty | 15 minutes | Paid | Yes |

**Step 2: Get the webhook URL**

For ntfy.sh (fastest):
1. Pick an unguessable topic name (e.g. `kilonova-alerts-xyz789`). This doubles as the password — no account exists.
2. Your URL is `https://ntfy.sh/your-unguessable-topic-name`
3. Install the ntfy app on your phone, subscribe to the same topic.

For Discord:
1. Right-click a channel -> Integrations -> Webhooks -> New Webhook.
2. Copy the webhook URL.

For Slack:
1. Go to api.slack.com -> Your Apps -> Incoming Webhooks -> Add.
2. Pick a channel, copy the URL.

**Step 3: Set the environment variable**

```
ALERT_WEBHOOK_URL=https://ntfy.sh/your-unguessable-topic-name
```

Optionally:
```
ALERT_WEBHOOK_SECRET=your_bearer_token   # sent as Authorization: Bearer <token>
ALERT_LIVE_ONLY=true                      # skip mock/demo runs, notify only on genuine triggers
```

**Step 4: Test it**

```bash
curl -X POST http://localhost:8000/api/simulate-event
# Check your phone — you should get a notification within 90 seconds
```

Or trigger a test webhook directly:

```bash
curl -X POST https://ntfy.sh/your-topic-name -d "KiloNOVAScout test alert"
```

**What the notification contains:**

JSON POST with: event ID, event class, gate verdict (target_acquired/weather_blocked/monitoring), top candidate galaxy + score, provenance badges, observatory name, dome status, and report path. For ntfy.sh targets, it sends a native message with title header and urgent priority when candidates exist.

**What it does NOT do:**

- No built-in SMS — `send_sms_alert` only logs. Wire your own relay behind the webhook.
- No built-in Telegram — use a Telegram bot webhook as the alert endpoint.
- No phone call — for that, integrate with PagerDuty or Twilio behind the webhook.

---

### Daily digest mail

A daily email summarizing every run from the last 24 hours. Even on a quiet sky, it sends — saying "all quiet" — so an empty inbox reads as "nothing happened," never as "mailer broken."

**Step 1: Get a Gmail App Password** (or use any SMTP provider)

1. Go to your Google Account -> Security.
2. Turn on 2-Step Verification (required — the App passwords page won't appear without it).
3. Same page -> App passwords -> pick any name (e.g. `KiloNOVAScout`) -> Generate.
4. Google displays a 16-letter code like `abcd efgh ijkl mnop`. Copy it. This is the only time it's shown.

This is not your login password. It can be revoked in one click.

**Step 2: Set the environment variables**

```
DIGEST_ENABLED=true
DIGEST_HOUR_UTC=6
DIGEST_SMTP_HOST=smtp.gmail.com
DIGEST_SMTP_PORT=465
DIGEST_SMTP_USER=your_email@gmail.com
DIGEST_SMTP_PASS=abcd efgh ijkl mnop
DIGEST_FROM=KiloNOVAScout <your_email@gmail.com>
DIGEST_TO=your_email@gmail.com
```

For multiple recipients, comma-separate: `DIGEST_TO=alice@example.com,bob@example.com`

**Step 3: Test it**

```bash
curl -X POST http://localhost:8000/api/digest/send-now
# Check your inbox — you should get the digest within seconds
```

The response tells you exactly what was sent or which setting is missing.

**What's in the digest:**

Each run gets: event ID, event class, gate verdict, top candidate + score, timestamp, and a clickable report link (if `RENDER_EXTERNAL_URL` is set). Quiet-sky days send a one-line "all quiet" message.

---

### Configuring without redeploying (dashboard)

Everything above is also editable live in the Observatory section's Notification Settings card — no restart needed, changes apply to the next run/mail. Secrets are never echoed back (the API blanks them; blank resubmits keep stored values). Use **Send test digest now** (`POST /api/digest/send-now`) to prove mail delivery in seconds instead of waiting for 06:00 UTC; the result line tells you exactly what was sent or which setting is missing.

---

### The approval loop

A run ends in one of two states. `target_acquired` (skies clear, gate accepted) arms the human gate: the dashboard shows the approval modal and `APPROVE & EXECUTE` calls `POST /agent/approve-slew-script`, flipping the agent to `slewing`. `monitoring`/`weather_blocked` (dome unsafe or overcast) never asks — it logs, notifies via webhook, and waits. Rejecting is closing the modal: no approval, no slew, full audit trail retained.

---

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

Watch the logs for `[MEM]` (memory per stage), `[POLL]` (poller cycles), `[ALERT]` (webhook deliveries), and `[GCN]` (Kafka state). Run history is in-memory and capped at 200 — export reports promptly; restarts lose history. Update by pulling and rebuilding; no migrations, no database.

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

Safety notes: keep `.env` (never committed) restricted to the service user; drill (`role="test"`) notices are ignored by design — validate the live path with `python scripts/check_live_path.py` instead; weather fallback snapshots are labeled and fail open, so flip `dome_safe` handling before this software is allowed near real dome hardware.

---

## Data Files

| File | Description |
|------|-------------|
| `src/backend/data/bayestar.fits.gz` | GW170817 BAYESTAR skymap, degraded to nside 256 for the 512 MB budget (exact nested coarsening; 90% area 31.16 deg^2 and distance 36.0 Mpc conserved) |
| `src/backend/data/GW170817_initial.json` | Faithful VOEvent replay packet (real IVORN, trigger time) |
| `src/backend/data/GW170817_region_glade.json` | 29 real GLADE+ galaxies from live VizieR TAP (NGC 4993 verified) |
| `src/backend/data/historical_events.json` | 14 curated historical events (SN1987A through GRB221009A) |
| `config/scoring_weights.json` | Full scoring formula weights |

---

## Testing

Run the demo pipeline:

```bash
curl -X POST http://localhost:8000/api/simulate-event
```

Run the automated test suite (99 tests across 3 scripts):

```bash
python scripts/check_event_classes.py   # gates, scoring profiles, topics (50 tests)
python scripts/check_llm_parse.py       # rationale extraction (18 tests)
python scripts/check_notifier.py        # webhook payload + failure paths (31 tests)
```

Run network-dependent validation scripts:

```bash
python scripts/check_gracedb_poller.py  # poller rules + live GraceDB discovery
python scripts/check_live_path.py       # full live pipeline on real S190425z (~3 min)
```

The system includes an integrated `EventSimulator` that loads a faithful GW170817 replay packet for reproducible end-to-end testing without waiting for real gravitational-wave detections. `check_live_path.py` is the complement: it replays the real S190425z VOEvent and skymap through the production live entrypoint and asserts all-live provenance.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for the full license text.

Copyright 2026 KiloNOVAScout.
