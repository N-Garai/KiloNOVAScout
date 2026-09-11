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
from typing import List, Optional, Set
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

async def _on_live_notice(payload) -> None:
    """Single funnel for every auto-fired live trigger (Kafka + poller).

    Runs the pipeline, then points _latest_run_id at the new run so the
    dashboard's latest-event poll (and any human opening the page at 3am)
    sees it without anyone pressing LAUNCH.  Agent/output globals resolve
    at call time, so observatory recreations are always honored.
    """
    await kilonova_agent.handle_live_notice(payload)
    global _latest_run_id
    rid = kilonova_agent.agent_state.run_id
    if rid:
        _latest_run_id = rid


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the GCN listener (non-blocking; mock-only without creds).

    Module-global agent/tools are resolved at call time, so this is defined
    before the app and passed to the constructor (replaces deprecated
    @app.on_event("startup")).
    """
    try:
        listener = GcnListener(on_notice=_on_live_notice)
        asyncio.ensure_future(listener._run())
        app.state.gcn_listener = listener
        logger.info("[startup] GCN listener scheduled (mock-only mode if no creds).")
    except Exception as e:
        logger.warning(f"[startup] GCN listener start failed (continuing): {e}")
    # Daily digest mailer: always scheduled, self-gating per cycle via
    # notification prefs (env or dashboard). Idle cost is one timer wake
    # every 10 minutes; a dead mail server only logs, never blocks.
    try:
        import threading as _threading
        from .notifier import start_digest
        digest_stop = _threading.Event()
        app.state.digest_stopper = digest_stop
        _threading.Thread(
            target=start_digest,
            args=(lambda hours: run_registry.recent_records(hours), digest_stop),
            name="digest-mailer", daemon=True).start()
        logger.info("[startup] Daily digest mailer scheduled (enable via DIGEST_ENABLED or dashboard).")
    except Exception as e:
        logger.warning(f"[startup] Digest mailer start failed (continuing): {e}")
    app.state.gracedb = {"enabled": False, "last_check": None, "last_result": "disabled"}
    if GRACEDB_POLL:
        try:
            from .gracedb_poller import start_poller
            loop = asyncio.get_running_loop()
            state: dict = {"enabled": True, "last_check": None, "last_result": "starting"}
            app.state.gracedb = state
            # Fresh handler lookup per trigger: observatory updates recreate
            # the agent, and the poller must never call a stale instance.
            stopper = start_poller(_on_live_notice,
                                   loop, state, interval_min=GRACEDB_POLL_MINUTES,
                                   shared_seen=_live_fired,
                                   is_busy=lambda: kilonova_agent.is_busy())
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
        digest_stopper = getattr(app.state, "digest_stopper", None)
        if digest_stopper is not None:
            digest_stopper.set()
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

# Superevents already fired as live runs (shared between the GraceDB poller
# thread and the launch-time live check so neither double-fires).
_live_fired: Set[str] = set()

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
    try:
        record = await run_registry.get_record(run_id)
    except Exception:
        record = None
    run_event = (record.event or {}) if record else {}
    event_class = run_event.get("event_class") or "bns"
    event_type = {
        "bns": "Binary Neutron Star Merger",
        "grb": "Gamma-Ray Burst",
        "neutrino": "High-Energy Neutrino Track",
    }.get(event_class, "Binary Neutron Star Merger")

    # Prefer the immutable run record over shared agent state: an observatory
    # save recreates the agent mid-run, and reading the fresh empty instance
    # blanked the whole response (no candidates, no report buttons).
    if record is not None and (record.candidates or record.status in ("completed", "failed", "skipped")):
        weather = record.weather if isinstance(record.weather, dict) else {}
        if record.status == "failed":
            status = "error"
        else:
            status = _STATUS_MAP.get(run_event.get("agent_status") or "", "processing")
        return {
            "alert": {
                "alert_id": run_event.get("trigger_id") or "GW170817",
                "topic": run_event.get("topic") or "",
                "event_type": event_type,
                "ivorn": run_event.get("ivorn") or "GW170817",
                "distance_mpc": 40.8,
                "confidence": 90.0,
                "observatory": weather.get("observatory_name") or OBSERVATORY_NAME,
                "source": record.source or "mock",
                "event_class": event_class,
                "class_label": METADATA.get(event_class, METADATA["bns"])["label"],
                "gate_status": run_event.get("gate_status"),
                "gate_reason": run_event.get("gate_reason"),
            },
            "status": status,
            "candidates": record.candidates or [],
            "execution_traces": [_step_to_dict(s) for s in (record.steps or [])],
            "message": agent_output.message,
            "slew_script": record.slew_script or "",
            "run_id": run_id,
            "llm_rationale": record.llm_rationale or "",
            "llm_structured": run_event.get("llm_structured") or None,
            # Same shape as the streaming record endpoint: provenance badge,
            # visualizations list, and live-check flags stay available here.
            "provenance": dict(record.provenance) if record.provenance else None,
            "visualizations": list((record.visualizations or {}).keys()),
            "live_trigger_found": (record.source == "live"),
            "live_check_note": run_event.get("live_note") or "",
        }

    galaxies_raw = kilonova_agent.agent_state.candidate_galaxies or []
    galaxies = [_galaxy_to_dict(g) for g in galaxies_raw]
    status = _STATUS_MAP.get(kilonova_agent.agent_state.status, "processing")

    return {
        "alert": {
            "alert_id": run_event.get("trigger_id") or (details.get("targets") and "GW170817-A" or "GW170817"),
            "topic": run_event.get("topic") or "",
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
        "llm_structured": None,
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


def _notification_prefs_response() -> dict:
    """Masked notification prefs for GET (secrets always blanked)."""
    try:
        from .notifier import masked_snapshot
        snap = masked_snapshot()
    except Exception:
        snap = {}

    def _truthy(key: str) -> bool:
        return str(snap.get(key, "") or "").lower() in ("1", "true", "yes")

    def _pint(key: str, default: int) -> int:
        try:
            return int(str(snap.get(key) or default))
        except (TypeError, ValueError):
            return default

    return {
        "alert_webhook_url": snap.get("ALERT_WEBHOOK_URL", ""),
        "alert_webhook_secret": "",
        "alert_live_only": _truthy("ALERT_LIVE_ONLY"),
        "digest_enabled": _truthy("DIGEST_ENABLED"),
        "digest_hour_utc": max(0, min(23, _pint("DIGEST_HOUR_UTC", 6))),
        "digest_smtp_host": snap.get("DIGEST_SMTP_HOST", ""),
        "digest_smtp_port": _pint("DIGEST_SMTP_PORT", 465),
        "digest_smtp_user": snap.get("DIGEST_SMTP_USER", ""),
        "digest_smtp_pass": "",
        "digest_from": snap.get("DIGEST_FROM", ""),
        "digest_to": snap.get("DIGEST_TO", ""),
    }


@app.get("/agent/config")
async def get_agent_config():
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
        alert_classes=list(ALERT_CLASSES),
        **_notification_prefs_response(),
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

    # Notification preferences: absent keys keep stored values; secrets
    # overwrite only on non-empty input (see notifier.set_runtime_prefs).
    try:
        from .notifier import set_runtime_prefs
        incoming: dict = {}
        if config.alert_webhook_url is not None:
            incoming["ALERT_WEBHOOK_URL"] = config.alert_webhook_url
        if config.alert_webhook_secret is not None:
            incoming["ALERT_WEBHOOK_SECRET"] = config.alert_webhook_secret
        if config.alert_live_only is not None:
            incoming["ALERT_LIVE_ONLY"] = "true" if config.alert_live_only else "false"
        if config.digest_enabled is not None:
            incoming["DIGEST_ENABLED"] = "true" if config.digest_enabled else "false"
        if config.digest_hour_utc is not None:
            incoming["DIGEST_HOUR_UTC"] = str(max(0, min(23, int(config.digest_hour_utc))))
        for field, key in (("digest_smtp_host", "DIGEST_SMTP_HOST"),
                           ("digest_smtp_port", "DIGEST_SMTP_PORT"),
                           ("digest_smtp_user", "DIGEST_SMTP_USER"),
                           ("digest_smtp_pass", "DIGEST_SMTP_PASS"),
                           ("digest_from", "DIGEST_FROM"),
                           ("digest_to", "DIGEST_TO")):
            value = getattr(config, field, None)
            if value is not None:
                incoming[key] = str(value)
        if incoming:
            set_runtime_prefs(incoming)
            logger.info("[API] Notification preferences updated (secrets redacted).")
    except Exception as exc:
        logger.warning(f"[API] notification prefs update skipped ({exc})")

    kilonova_tools = KilonovaScoutTools(
        observatory_name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
    )

    _previous_agent = kilonova_agent
    kilonova_agent = KilonovaScoutAgent(
        agent_name="kilonovascout-core",
        tools=kilonova_tools,
    )
    # Carry the run lock across recreation so an in-flight run keeps its
    # exclusivity instead of silently allowing a second concurrent run.
    kilonova_agent._run_lock = _previous_agent._run_lock

    # The central live funnel resolves the agent fresh per call, so the
    # rebind only needs to point at it (never at a bound agent method).
    try:
        listener = getattr(app.state, "gcn_listener", None)
        if listener is not None:
            listener.on_notice = _on_live_notice
    except Exception as exc:
        logger.warning(f"[API] GCN listener rebind skipped ({exc})")

    logger.info(f"[API] Observatory updated: {OBSERVATORY_NAME} ({OBSERVATORY_LAT}, {OBSERVATORY_LON}, {OBSERVATORY_ALT}m)")
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT,
        alert_classes=list(ALERT_CLASSES),
        **_notification_prefs_response(),
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


# Frontend status vocabulary, shared by the legacy sync response and the
# streaming run-record endpoint below.
_STATUS_MAP = {
    "awaiting_approval": "target_acquired",
    "weather_blocked": "monitoring",
    "processing": "processing",
    "error": "error",
    "listening": "listening",
    "rejected": "rejected",
    "skipped": "skipped",
}


async def _check_live_once():
    """One-shot live sky check (BNS). Returns (payload|None, note|None, sid|None).

    Failures fall open to mock with a reason string; never raises.
    """
    try:
        from .gracedb_poller import FAR_PER_YEAR_HZ, build_live_payload, poll_once
    except Exception as exc:
        return None, f"live check unavailable ({exc})", None
    try:
        payloads, _ = await asyncio.wait_for(
            asyncio.to_thread(poll_once, set(_live_fired), far_hz=FAR_PER_YEAR_HZ,
                              lookback_h=6.0),
            timeout=45.0,
        )
    except Exception as exc:
        return None, f"live check failed ({exc}); using fallback simulation", None
    if not payloads:
        return None, None, None
    pick = payloads[0]
    sid = pick["superevent_id"]
    try:
        live = await asyncio.to_thread(
            build_live_payload, pick["voevent_xml"], sid, pick["skymap_url"])
    except Exception as exc:
        return None, f"live trigger {sid} unreadable ({exc}); using fallback simulation", None
    if live is None:
        return None, f"live trigger {sid} unparseable; using fallback simulation", None
    return live, (f"LIVE TRIGGER ACQUIRED: {sid} (FAR {pick.get('far')}) — "
                  "running the real sky, not a replay."), sid


async def _emit_live_check_row(run_id: str, event_class: str,
                               live_note: str | None, duration_ms: int) -> None:
    """Trace row proving the trigger decision in the white-box timeline.

    Answers "did it even try live?" per run: the GraceDB verdict for BNS, or
    an explicit skipped marker for classes with no live REST source.  Step 0
    sibling of the "run" marker — the (step, tool) key never collides with it.
    """
    try:
        import datetime as _dt
        if event_class == "bns":
            summary = live_note or "quiet sky — no live trigger in window; fallback simulation"
            status, detail = "completed", "GraceDB significant-superevent poll (6h lookback)"
        else:
            summary = f"no live REST source for {event_class}; demo simulation by design"
            status, detail = "skipped", "n/a"
        await run_registry.append_step(run_id, StepEvent(
            run_id=run_id, step=0, tool_name="ingestion.live_check",
            status=status, attempt=1,
            started_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            duration_ms=duration_ms, input_summary=detail,
            output_summary=summary))
    except Exception:
        pass


async def _background_run(run_id: str, event_class: str) -> None:
    """Execute the full pipeline for a streaming LAUNCH (fire-and-forget).

    Live-first for BNS via the one-shot GraceDB check; mock otherwise.
    Every outcome — completed, failed, busy-declined, duplicate-skipped —
    lands in the run record, which the UI follows via SSE plus
    GET /api/runs/{run_id}.  Never raises.
    """
    try:
        import datetime as _dt
        record = await run_registry.get_record(run_id)
        if record is None:
            return
        live_payload, live_note, sid = None, None, None
        if event_class == "bns":
            t0 = _dt.datetime.now(_dt.timezone.utc)
            live_payload, live_note, sid = await _check_live_once()
            dt_ms = int((_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds() * 1000)
            await _emit_live_check_row(run_id, event_class, live_note, dt_ms)
        else:
            await _emit_live_check_row(run_id, event_class, None, 0)
        if live_note:
            await run_registry.attach(run_id, event_update={"live_note": live_note})
        if live_payload is not None:
            _live_fired.add(sid)
            output = await kilonova_agent.process_gcn_event(live_payload, run=record)
            if (output.details or {}).get("busy") or (output.details or {}).get("duplicate"):
                _live_fired.discard(sid)
                if (output.details or {}).get("duplicate"):
                    prior = (output.details or {}).get("run_id")
                    await run_registry.attach(run_id, event_update={
                        "live_note": f"live trigger {sid} already ran"
                                     + (f" as {prior}" if prior else "")
                                     + "; running fallback demo instead"})
                    output = await kilonova_agent.run_mock_event(event_class, run=record)
        else:
            output = await kilonova_agent.run_mock_event(event_class, run=record)
        rec = await run_registry.get_record(run_id)
        if rec is not None and rec.status == "running":
            # Agent declined (busy/duplicate/reject-before-DAG): close the
            # record so the SSE stream terminates instead of hanging.
            await run_registry.finish_run(run_id, "skipped", error=(output.message if output else "declined"))
    except Exception as exc:
        logger.exception(f"[API] background run {run_id} crashed: {exc}")
        try:
            rec = await run_registry.get_record(run_id)
            if rec is not None and rec.status == "running":
                await run_registry.finish_run(run_id, "failed", error=str(exc))
        except Exception:
            pass


def _step_to_dict(step) -> dict:
    if hasattr(step, "model_dump"):
        return step.model_dump()
    if hasattr(step, "dict"):
        return step.dict()
    return {"tool_name": str(getattr(step, "tool_name", "?")),
            "status": str(getattr(step, "status", "?"))}


def _to_jsonable(obj):
    """Recursively convert numpy types to native Python for JSON serialization."""
    try:
        import numpy as np
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


@app.post("/api/simulate-event", status_code=202)
async def api_simulate_event(event_class: str = "bns"):
    """Launch a run and return immediately with its id (streaming flow).

    The pipeline executes in a background task; the UI subscribes to
    /api/runs/{run_id}/events for live steps and fetches /api/runs/{run_id}
    when the run-finished event arrives.  A contended pipeline answers 429
    with the in-flight run id so the caller can attach to it instead.
    """
    event_class = (event_class or "bns").lower()
    if event_class not in ALL_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown event class '{event_class}'. Choose from {ALL_CLASSES}.")
    if kilonova_agent.is_busy():
        raise HTTPException(
            status_code=429,
            detail={"message": "Pipeline busy — another run is in progress.",
                    "run_id": kilonova_agent.agent_state.run_id},
        )
    record = await run_registry.create_run(
        source="starting", event={"event_class": event_class, "note": "launch accepted"})
    global _latest_run_id
    _latest_run_id = record.run_id
    asyncio.create_task(_background_run(record.run_id, event_class))
    return {"run_id": record.run_id, "status": "started"}


@app.get("/api/runs/{run_id}")
async def api_run_record(run_id: str):
    """Full run state for the streaming UI (built from the record alone, so
    it stays correct even after later runs move shared agent state)."""
    record = await run_registry.get_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    event = record.event or {}
    prov = dict(record.provenance) if record.provenance else None
    event_class = event.get("event_class") or "bns"
    event_type = {
        "bns": "Binary Neutron Star Merger",
        "grb": "Gamma-Ray Burst",
        "neutrino": "High-Energy Neutrino Track",
    }.get(event_class, "Binary Neutron Star Merger")
    if record.status == "failed":
        status = "error"
    else:
        status = _STATUS_MAP.get(event.get("agent_status") or "", "processing")
    weather = record.weather if isinstance(record.weather, dict) else {}
    return _to_jsonable({
        "alert": {
            "alert_id": event.get("trigger_id") or "GW170817",
            "topic": event.get("topic") or "",
            "event_type": event_type,
            "ivorn": event.get("ivorn") or "GW170817",
            "observatory": weather.get("observatory_name") or OBSERVATORY_NAME,
            "source": record.source or "mock",
            "event_class": event_class,
            "class_label": METADATA.get(event_class, METADATA["bns"])["label"],
            "gate_status": event.get("gate_status"),
            "gate_reason": event.get("gate_reason"),
        },
        "status": status,
        "candidates": record.candidates or [],
        "execution_traces": [_step_to_dict(s) for s in (record.steps or [])],
        "run_id": record.run_id,
        "llm_rationale": record.llm_rationale or "",
        "llm_structured": event.get("llm_structured") or None,
        "provenance": prov,
        "visualizations": list((record.visualizations or {}).keys()),
        "live_trigger_found": (record.source == "live"),
        "live_check_note": event.get("live_note") or "",
    })


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
    return _to_jsonable({
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
    })


@app.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str):
    try:
        queue = await run_registry.subscribe(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        # Keepalive prevents Render/Nginx from buffering or timing out the
        # stream during long blocking stages (e.g. 13-30s TAP query).
        while True:
            try:
                step = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {step.model_dump_json()}\n\n"
                # Terminal marker (step 999, finish_run) closes the stream.
                # Step 0 "run created" must not close it, or the UI freezes
                # at 1 event (Render buffers the rest).
                if step.step == 999 and step.tool_name == "run" and step.status in ("completed", "failed", "skipped"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    try:
        from .notifier import digest_status
        notify_state = digest_status()
    except Exception:
        notify_state = {"enabled": False, "configured": False}
    return {
        "status": "ok",
        "observatory": OBSERVATORY_NAME,
        "time": datetime.datetime.utcnow().isoformat() + "Z",
        "gracedb_poll": dict(getattr(app.state, "gracedb", {"enabled": False})),
        "notifications": notify_state,
    }


@app.post("/api/digest/send-now")
async def api_digest_send_now():
    """Send the digest immediately (tests SMTP config without waiting for
    the scheduled hour). Returns what was sent, or why not."""
    try:
        from .notifier import digest_status, send_digest_email
        recs = await asyncio.to_thread(run_registry.recent_records, 24.0)
        ok = await asyncio.to_thread(send_digest_email, recs)
        state = digest_status()
        if ok:
            return {"sent": True, "recipients": state.get("recipients", 0),
                    "runs": len(recs),
                    "message": f"Digest sent ({len(recs)} run(s))."}
        reason = ("SMTP not configured — set DIGEST_SMTP_HOST/USER/PASS/TO "
                  "first." if not state.get("configured")
                  else "SMTP send failed — check credentials/host and the [DIGEST] log lines.")
        return {"sent": False, "recipients": 0, "runs": len(recs), "message": reason}
    except Exception as exc:
        logger.warning(f"[API] digest send-now failed ({exc})")
        raise HTTPException(status_code=500, detail=f"Digest failed: {exc}")


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
