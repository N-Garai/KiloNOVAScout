"""KilonovaScout Backend API.

Render-compatible FastAPI service exposing:
- /api/simulate-event
- /agent/config
- /agent/state
- /agent/status
- /api/latest-event
- /api/ping
- /api/runs/{run_id}/events
- /api/report/{run_id}
- /health
- static frontend SPA serving from /assets and fallback index.html
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()  # repo-root .env support for laptop runs (Render uses dashboard env)

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agents.agent import KilonovaScoutAgent, run_registry
from .models import (
    AgentState,
    GcnKafkaPayload,
    AgentOutput,
    TelescopeSlewScript,
    ObservatoryConfig,
    RunRecord,
    StepEvent,
)
from .event_classes import ALL_CLASSES, METADATA, enabled_classes, topics_for
from .tools import KilonovaScoutTools
from .simulator.event_simulator import EventSimulator
from .run_registry import build_report_markdown
from .agents.writer_agent import build_report_markdown as build_writer_markdown, build_report_html, build_report_latex
from .gcn_listener import GcnListener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kilonovascout")


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_port(default: int = 8000) -> int:
    try:
        port = int(os.getenv("PORT", default))
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


# Observatory Configuration
OBSERVATORY_NAME = os.getenv("OBSERVATORY_NAME", "Palomar")
OBSERVATORY_LAT = _get_float("OBSERVATORY_LAT", 33.356)
OBSERVATORY_LON = _get_float("OBSERVATORY_LON", -116.865)
OBSERVATORY_ALT = _get_float("OBSERVATORY_ALT", 1706)

# LLM Configuration
PRIMARY_LLM = os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")
FALLBACK_LLM = os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")

# GraceDB REST poller (opt-in live BNS path that needs no Kafka/IPv6).
GRACEDB_POLL = os.getenv("GRACEDB_POLL", "false").lower() in ("1", "true", "yes")
try:
    GRACEDB_POLL_MINUTES = max(5.0, float(os.getenv("GRACEDB_POLL_MINUTES", "15")))
except (TypeError, ValueError):
    GRACEDB_POLL_MINUTES = 15.0

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the GCN listener (non-blocking; mock-only without creds).

    Module-global agent/tools are resolved at call time, so this is defined
    before the app and passed to the constructor (replaces deprecated
    @app.on_event("startup")).
    """
    try:
        listener = GcnListener(on_notice=kilonova_agent.handle_live_notice)
        asyncio.ensure_future(listener._run())
        app.state.gcn_listener = listener
        logger.info("[startup] GCN listener scheduled (mock-only mode if no creds).")
    except Exception as e:
        logger.warning(f"[startup] GCN listener start failed (continuing): {e}")
    app.state.gracedb = {"enabled": False, "last_check": None, "last_result": "disabled"}
    if GRACEDB_POLL:
        try:
            from .gracedb_poller import start_poller
            loop = asyncio.get_running_loop()
            state: dict = {"enabled": True, "last_check": None, "last_result": "starting"}
            app.state.gracedb = state
            # Fresh handler lookup per trigger: observatory updates recreate
            # the agent, and the poller must never call a stale instance.
            stopper = start_poller(lambda: kilonova_agent.handle_live_notice,
                                   loop, state, interval_min=GRACEDB_POLL_MINUTES)
            app.state.gracedb_stopper = stopper
            logger.info(f"[startup] GraceDB poller on (every {GRACEDB_POLL_MINUTES:.0f} min).")
        except Exception as e:
            logger.warning(f"[startup] GraceDB poller start failed (continuing): {e}")
    yield
    try:
        listener = getattr(app.state, "gcn_listener", None)
        if listener is not None:
            listener.stop()
        stopper = getattr(app.state, "gracedb_stopper", None)
        if stopper is not None:
            stopper.set()
    except Exception:
        pass


app = FastAPI(
    title="KilonovaScout Backend API",
    description="Autonomous Multi-Messenger Astronomy Targeting Agent.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

kilonova_tools = KilonovaScoutTools(
    observatory_name=OBSERVATORY_NAME,
    lat=OBSERVATORY_LAT,
    lon=OBSERVATORY_LON,
    alt=OBSERVATORY_ALT,
)

kilonova_agent = KilonovaScoutAgent(
    agent_name="kilonovascout-core",
    tools=kilonova_tools,
)

event_simulator = EventSimulator()
_latest_run_id: Optional[str] = None

# Live-watch event classes (bns, grb, neutrino).  Overridable via the
# ALERT_CLASSES env var and at runtime through PUT /agent/config.
ALERT_CLASSES: List[str] = enabled_classes()


def _galaxy_to_dict(g) -> dict:
    # NOTE: getattr defaults do NOT cover fields that exist but are None,
    # so coalesce explicitly — the frontend calls .toFixed() unconditionally.
    score_breakdown = getattr(g, "score_breakdown", None)
    observability = getattr(g, "observability", None)
    return {
        "name": g.name,
        "ra": g.ra_deg,
        "dec": g.dec_deg,
        "distance_mpc": g.distance_mpc,
        "probability": g.probability_overlap,
        "composite_score": getattr(g, "composite_score", 0.0) or 0.0,
        "normalized_priority": getattr(g, "normalized_priority", None),
        "luminosity_k": getattr(g, "luminosity_k", None),
        "pgc": getattr(g, "pgc", None),
        "catalog_source": getattr(g, "catalog_source", None) or "unknown",
        "observability": observability if isinstance(observability, dict) else None,
        "score_breakdown": score_breakdown.model_dump() if hasattr(score_breakdown, "model_dump") else score_breakdown,
    }


async def _build_simulate_response(agent_output, run_id: str) -> dict:
    details = agent_output.details if agent_output.details else {}
    galaxies_raw = kilonova_agent.agent_state.candidate_galaxies or []
    galaxies = [_galaxy_to_dict(g) for g in galaxies_raw]
    try:
        record = await run_registry.get_record(run_id)
        run_event = (record.event or {}) if record else {}
    except Exception:
        run_event = {}
    event_class = run_event.get("event_class") or "bns"
    event_type = {
        "bns": "Binary Neutron Star Merger",
        "grb": "Gamma-Ray Burst",
        "neutrino": "High-Energy Neutrino Track",
    }.get(event_class, "Binary Neutron Star Merger")

    status = {
        "awaiting_approval": "target_acquired",
        "weather_blocked": "monitoring",
        "processing": "processing",
        "error": "error",
        "listening": "listening",
        "rejected": "rejected",
    }.get(kilonova_agent.agent_state.status, "processing")

    return {
        "alert": {
            "alert_id": run_event.get("trigger_id") or (details.get("targets") and "GW170817-A" or "GW170817"),
            "event_type": event_type,
            "ivorn": kilonova_agent.agent_state.last_gcn_event or "GW170817",
            "distance_mpc": 40.8,
            "confidence": 90.0,
            "observatory": kilonova_agent.agent_state.observatory_weather.observatory_name if kilonova_agent.agent_state.observatory_weather else OBSERVATORY_NAME,
            "source": kilonova_agent.agent_state.source or "mock",
            "event_class": event_class,
            "class_label": METADATA.get(event_class, METADATA["bns"])["label"],
            "gate_status": run_event.get("gate_status"),
            "gate_reason": run_event.get("gate_reason"),
        },
        "status": status,
        "candidates": galaxies,
        "execution_traces": kilonova_agent.get_execution_traces(),
        "message": agent_output.message,
        "slew_script": details.get("slew_script", ""),
        "run_id": run_id,
        "llm_rationale": kilonova_agent.agent_state.llm_rationale,
        # v3 provenance badge (M4.4): skymap/catalog/event data-source attribution
        "provenance": await _run_provenance(run_id),
        "visualizations": await _run_visualizations(run_id),
    }


async def _run_provenance(run_id: Optional[str]) -> Optional[dict]:
    """Fetch the provenance dict attached to a run record, if any."""
    if not run_id:
        return None
    try:
        record = await run_registry.get_record(run_id)
    except Exception:
        return None
    return dict(record.provenance) if record and record.provenance else None


async def _run_visualizations(run_id: Optional[str]) -> Optional[dict]:
    """Fetch the visualization PNGs attached to a run record, if any."""
    if not run_id:
        return None
    try:
        record = await run_registry.get_record(run_id)
    except Exception:
        return None
    return dict(record.visualizations) if record and record.visualizations else None


@app.get("/api/event-classes")
async def api_event_classes():
    """Supported trigger families + which are live-watched (for the UI)."""
    return {
        "classes": [METADATA[k] for k in ALL_CLASSES],
        "enabled": list(ALERT_CLASSES),
        "topics": topics_for(ALERT_CLASSES),
    }


@app.get("/agent/config")
async def get_agent_config():
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
        alert_classes=list(ALERT_CLASSES),
    )


@app.put("/agent/config")
async def update_agent_config(config: ObservatoryConfig):
    global kilonova_tools, kilonova_agent, OBSERVATORY_NAME, OBSERVATORY_LAT, OBSERVATORY_LON, OBSERVATORY_ALT, ALERT_CLASSES

    new_name = config.name if config.name and config.name.strip() else "Palomar"
    new_lat = config.lat if config.lat is not None else 33.356
    new_lon = config.lon if config.lon is not None else -116.865
    new_alt = config.alt if config.alt is not None else 1706

    new_lat = max(-90.0, min(90.0, new_lat))
    new_lon = max(-180.0, min(180.0, new_lon))

    OBSERVATORY_NAME = new_name
    OBSERVATORY_LAT = new_lat
    OBSERVATORY_LON = new_lon
    OBSERVATORY_ALT = new_alt

    if config.alert_classes is not None:
        cleaned = [c.strip().lower() for c in config.alert_classes if c and c.strip().lower() in ALL_CLASSES]
        if cleaned:
            ALERT_CLASSES = cleaned
            try:
                listener = getattr(app.state, "gcn_listener", None)
                if listener is not None:
                    listener.update_topics(topics_for(ALERT_CLASSES))
            except Exception as exc:
                logger.warning(f"[API] listener resubscribe skipped ({exc})")
            logger.info(f"[API] Alert classes updated: {ALERT_CLASSES}")

    kilonova_tools = KilonovaScoutTools(
        observatory_name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
    )

    kilonova_agent = KilonovaScoutAgent(
        agent_name="kilonovascout-core",
        tools=kilonova_tools,
    )

    # The startup GCN listener captured the previous agent instance's bound
    # handler — rebind it so live notices reach the reconfigured agent.
    try:
        listener = getattr(app.state, "gcn_listener", None)
        if listener is not None:
            listener.on_notice = kilonova_agent.handle_live_notice
    except Exception as exc:
        logger.warning(f"[API] GCN listener rebind skipped ({exc})")

    logger.info(f"[API] Observatory updated: {OBSERVATORY_NAME} ({OBSERVATORY_LAT}, {OBSERVATORY_LON}, {OBSERVATORY_ALT}m)")
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
        alert_classes=list(ALERT_CLASSES),
    )


@app.get("/agent/state")
async def get_agent_state():
    return kilonova_agent.get_agent_state()


@app.get("/agent/status")
async def get_agent_status():
    state = kilonova_agent.get_agent_state()
    return {
        "status": state.status,
        "last_gcn_event": state.last_gcn_event,
        "source": state.source,
        "run_id": state.run_id,
        "approval_needed": state.approval_needed,
    }


@app.post("/simulate-gcn-alert")
async def simulate_gcn_alert():
    mock_payload = event_simulator.get_mock_gw170817_payload()
    logger.info(f"[API] Simulated GCN delivery: {mock_payload.voevent.ivorn}")
    agent_output = await kilonova_agent.process_gcn_event(mock_payload)
    global _latest_run_id
    _latest_run_id = kilonova_agent.agent_state.run_id
    return await _build_simulate_response(agent_output, _latest_run_id)


@app.post("/api/simulate-event")
async def api_simulate_event(event_class: str = "bns"):
    event_class = (event_class or "bns").lower()
    if event_class not in ALL_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown event class '{event_class}'. Choose from {ALL_CLASSES}.")
    try:
        agent_output = await kilonova_agent.run_mock_event(event_class)
    except Exception as exc:
        # Never drop the connection: surface pipeline crashes as JSON 500
        # (a bare 502 from the proxy means the process itself died).
        logger.exception(f"[API] simulate-event crashed: {exc}")
        raise HTTPException(status_code=500, detail=f"Pipeline crashed: {exc}")
    global _latest_run_id
    _latest_run_id = kilonova_agent.agent_state.run_id
    return await _build_simulate_response(agent_output, _latest_run_id)


@app.post("/api/simulate-gcn-alert")
async def api_simulate_gcn_alert():
    """Legacy alias keeping the previous contract."""
    return await simulate_gcn_alert()


@app.post("/agent/approve-slew-script")
async def approve_slew_script():
    return await kilonova_agent.approve_slew_script()


@app.get("/api/latest-event")
async def api_latest_event(response: Response):
    global _latest_run_id
    run_id = _latest_run_id or kilonova_agent.agent_state.run_id
    if not run_id:
        response.status_code = 204
        return
    record = await run_registry.get_record(run_id)
    if not record:
        response.status_code = 204
        return
    return {
        "run_id": record.run_id,
        "source": record.source,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "event": record.event,
        "llm_rationale": record.llm_rationale,
        "candidates": record.candidates,
        "provenance": dict(record.provenance) if record.provenance else None,
        "execution_traces": kilonova_agent.get_execution_traces(),
    }


@app.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str):
    try:
        queue = await run_registry.subscribe(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        while True:
            step = await queue.get()
            yield f"data: {step.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/report")
async def api_run_report(run_id: str):
    """Writer-agent report (v3 PRD M6.6).

    Returns the report in dual format: rich HTML (print-to-PDF ready, with
    embedded visualizations and calculation traces) plus Markdown, LaTeX
    source, and data provenance. ``pdf_url`` is only populated when a
    server-side PDF renderer (weasyprint/xelatex) is available — Option C
    (browser print) is the Render-safe default.
    """
    record = await run_registry.get_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        from config import load_scoring_weights as _loader
        weights = _loader()
    except Exception:
        weights = {}

    def _render():
        md = build_writer_markdown(record, weights)
        html_doc = build_report_html(record, weights, visualizations=record.visualizations)
        latex = build_report_latex(record, weights)
        return md, html_doc, latex

    try:
        markdown, html_doc, latex = await asyncio.to_thread(_render)
    except Exception as exc:
        logger.warning(f"[API] writer report failed ({exc}); falling back to legacy markdown")
        markdown = build_report_markdown(record, weights)
        html_doc, latex = None, None

    return {
        "run_id": run_id,
        "format": "dual",
        "markdown": markdown,
        "html": html_doc,
        "latex": latex,
        "pdf_url": None,  # populated only when weasyprint/xelatex is available
        "provenance": dict(record.provenance) if record.provenance else None,
        "visualizations": list((record.visualizations or {}).keys()),
    }


@app.get("/api/report/{run_id}")
async def api_report(run_id: str):
    """Legacy Markdown report endpoint (kept for API compatibility)."""
    record = await run_registry.get_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        from config import load_scoring_weights as _loader
        weights = _loader()
    except Exception:
        weights = {}
    try:
        markdown = build_writer_markdown(record, weights)
    except Exception as exc:
        logger.warning(f"[API] writer markdown failed ({exc}); using legacy builder")
        markdown = build_report_markdown(record, weights)
    return {"run_id": run_id, "format": "markdown", "content": markdown}


@app.get("/api/ping")
async def api_ping():
    """Cheap keep-alive / warm-up probe (Render spin-down avoidance).

    Per version-docs/QnA.md ("Cold-Start Problem") the service is
    event-driven with a playback harness — not a 24/7 listener. An open
    demo tab pings this endpoint every few minutes (visible tabs only) so
    the instance stays warm during active viewing. Does zero pipeline work.
    """
    import datetime
    return {
        "status": "ok",
        "observatory": OBSERVATORY_NAME,
        "time": datetime.datetime.utcnow().isoformat() + "Z",
        "gracedb_poll": dict(getattr(app.state, "gracedb", {"enabled": False})),
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "observatory": OBSERVATORY_NAME,
        "primary_llm": PRIMARY_LLM,
        "fallback_llm": FALLBACK_LLM,
    }


DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.isdir(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(os.path.join(DIST_DIR, "index.html"))

    @app.head("/", include_in_schema=False)
    async def serve_root_head():
        # Render's port scanner probes HEAD / — answer 200 instead of 405.
        return Response(status_code=200)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "agent/", "health", "openapi.json", "docs", "redoc")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.join(DIST_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_get_port())
