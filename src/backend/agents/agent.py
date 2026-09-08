"""KilonovaScoutAgent - Master Orchestrator for v2 PRD.

Implements the v2 milestone DAG:

  ingest ──► skymap ──┬──► catalog (asyncio.gather) ──┐
                      └──► weather (asyncio.gather) ──┴──► grb_check ──► slew_script ──► rationale

Features:
- Manual LLM failover (Gemini primary, Groq fallback) via llm_reasoner
- Live NASA GCN listener with mock fallback
- Real-time step emission (SSE) for white-box frontend timeline
- Measured step durations (no hardcoded literals)
- Score breakdown + normalized priority per candidate
- Ephemeris + Validator (GRB coincidence) stages
- Final observation report via run registry
"""

from __future__ import annotations

import asyncio
import datetime
import functools
import gc
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from strands import Agent
from strands.models.litellm import LiteLLMModel

from ..models import (
    AgentOutput,
    AgentState,
    Galaxy,
    GcnKafkaPayload,
    HealpixSkymap,
    ObservatoryWeather,
    RunRecord,
    StepEvent,
    TelescopeSlewScript,
    Voevent,
)
from ..event_classes import METADATA, evaluate_trigger, get_profile, harvest_params
from ..run_registry import RunRegistry, claim_live_trigger, live_run_id, normalize_priorities, note_live_run
from ..tools import KilonovaScoutTools
from ..simulator.event_simulator import EventSimulator
from ..llm_reasoner import reason_about_event
from ..agents import validator_agent
from ..agents.visualization_agent import generate_run_visualizations
from ..gcn_listener import SkymapUpdateTracker

run_registry = RunRegistry()


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _exclusive_run(fn):
    """Serialize pipeline runs on the single global agent (and 512 MB RAM).

    A second concurrent trigger — e.g. a poller-fired live event landing
    mid-demo — gets a ``busy`` failure instead of interleaving shared
    agent_state and doubling peak memory into an OOM kill.  Callers map
    ``details["busy"]`` to HTTP 429 (API) or skip-and-retry (poller).
    """
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        if not self._run_lock.acquire(blocking=False):
            return AgentOutput(
                message="Pipeline busy with another run; try again shortly.",
                details={"busy": True, "run_id": getattr(self.agent_state, "run_id", None)},
                action_status="failure",
            )
        try:
            return await fn(self, *args, **kwargs)
        finally:
            try:
                self._run_lock.release()
            except RuntimeError:
                pass
    return wrapper


async def _attach_weather_tier(run_id: str) -> None:
    """Record the weather data tier (live vs fallback) in provenance."""
    try:
        rec = await run_registry.get_record(run_id)
        weather = rec.weather if rec and isinstance(rec.weather, dict) else {}
        await run_registry.attach(run_id, provenance={"weather": weather.get("source") or "unknown"})
    except Exception:
        pass


async def _notify_run_complete(run_id: str) -> None:
    """Fire the outbound webhook for a finished run (24/7 alerting).

    Never raises and never blocks the loop: network I/O runs in a worker
    thread, and a missing ALERT_WEBHOOK_URL is a silent no-op.
    """
    try:
        from ..notifier import maybe_notify
        rec = await run_registry.get_record(run_id)
        if rec is not None:
            await asyncio.to_thread(maybe_notify, rec)
    except Exception as exc:
        print(f"[ALERT] notify wrapper failed ({exc})")


def _log_mem(run_id: str, stage: str) -> None:
    """Log peak RSS at pipeline milestones (OOM diagnosis on 512 MB tiers).

    Uses stdlib ``resource`` (Linux-only); silently no-ops elsewhere so
    local Windows dev is unaffected.
    """
    try:
        import resource
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        print(f"[MEM] run={run_id} stage={stage} peak_rss={rss_mb:.0f}MB")
    except Exception:
        pass


class _ToolAuditHook:
    """Strands lifecycle hook for tool-call audit logging (v3 PRD M9.4).

    Mirrors the PRD's ``AfterToolCallEvent`` pattern: every tool invocation
    executed through the strands Agent produces an ``[AUDIT]`` line with the
    tool name and a result preview, complementing the manual measured-step
    ledger.
    """

    def register_hooks(self, registry, **kwargs) -> None:  # HookProvider protocol
        try:
            from strands.hooks import AfterToolCallEvent

            registry.add_callback(AfterToolCallEvent, self._after_tool_call)
        except Exception as e:  # hook wiring must never break boot
            print(f"[AUDIT] hook registration skipped: {e}")

    def _after_tool_call(self, event) -> None:
        try:
            tool_use = getattr(event, "tool_use", None)
            if isinstance(tool_use, dict):
                tool_name = tool_use.get("name")
            else:
                tool_name = getattr(tool_use, "name", None)
            result = getattr(event, "result", None)
            result_preview = (str(getattr(result, "text", result))[:120] if result is not None else "")
            print(f"[AUDIT] {tool_name or 'tool'} completed: {result_preview}")
        except Exception:
            pass


def _primary_model() -> str:
    return os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")


def _fallback_model() -> str:
    return os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")


def _build_model(model_id: str) -> LiteLLMModel:
    try:
        return LiteLLMModel(model_id=model_id)
    except Exception:
        return LiteLLMModel(model_id=_fallback_model())


async def _emit_step(record: RunRecord, *, step: int, tool_name: str, status: str, attempt: int = 1,
                     input_summary: str = "", output_summary: str = "", error: str = "",
                     started_at: Optional[str] = None, duration_ms: Optional[int] = None) -> StepEvent:
    step_event = StepEvent(
        run_id=record.run_id,
        step=step,
        tool_name=tool_name,
        status=status,
        attempt=attempt,
        started_at=started_at or _now_iso(),
        duration_ms=duration_ms,
        input_summary=input_summary,
        output_summary=output_summary,
        error=error,
    )
    await run_registry.append_step(record.run_id, step_event)
    return step_event


def _galaxy_to_dict(g: Galaxy) -> Dict[str, Any]:
    # NOTE: getattr defaults do NOT cover fields that exist but are None,
    # so coalesce explicitly — consumers call .toFixed() unconditionally.
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


def _weather_to_dict(w: ObservatoryWeather) -> Dict[str, Any]:
    seeing = getattr(w, "seeing_conditions", "") or ""
    return {
        "observatory_name": w.observatory_name,
        "latitude": w.latitude,
        "longitude": w.longitude,
        "cloud_cover_percent": w.cloud_cover_percent,
        "seeing_conditions": w.seeing_conditions,
        "humidity_pct": w.humidity_pct,
        "dome_safe": w.dome_safe,
        # Data tier, honestly labeled: the pipeline's safe-defaults path
        # marks its snapshots as fallback-grade weather.
        "source": "fallback" if "fallback" in seeing.lower() else "live",
    }


def _serialize_event(voevent: Voevent, topic: str = "") -> Dict[str, Any]:
    ww = voevent.wherewhen or {}
    event_class = ww.get("event_class") or "bns"
    return {
        "ivorn": voevent.ivorn,
        "role": voevent.role,
        "description": voevent.description,
        "event_time": ww.get("event_time"),
        "trigger_id": ww.get("trigger_id"),
        "distance_mpc": ww.get("distance_mpc"),
        "confidence": ww.get("confidence"),
        "skymap_summary": ww.get("skymap_summary"),
        "topic": topic,
        "event_class": event_class,
        "class_label": METADATA.get(event_class, METADATA["bns"])["label"],
        # Gate verdict fields are attached after ingest (see _run_dag).
        "gate_status": None,
        "gate_reason": None,
        "gate_confidence": None,
        "gate_subclass": None,
    }


def _classify_trigger(payload: GcnKafkaPayload) -> Dict[str, Any]:
    """Run the event-class ingest gate over a trigger payload.

    Merges the class verdict (ACCEPTED/REJECTED + reason + confidence)
    into the legacy verdict dict so both live and replay notices flow
    through the same triage.
    """
    ww = payload.voevent.wherewhen or {}
    event_class = ww.get("event_class") or "bns"
    gate = evaluate_trigger(event_class, payload.voevent.what)
    # Non-merger triggers without ANY localization (no skymap URL and no
    # RA/Dec) cannot be pointed at — reject honestly instead of running the
    # pipeline on an unrelated replay map.
    if (gate["status"] == "ACCEPTED" and event_class != "bns"
            and not ww.get("skymap_url") and ww.get("ra_deg") is None):
        gate = {"status": "REJECTED",
                "reason": "notice carries no sky localization (no skymap, no position)",
                "confidence": 0.9, "subclass": "unlocalized",
                "class_key": gate["class_key"]}
    base = _mock_verdict(payload)
    base.update({
        "event_class": gate["class_key"],
        "class_label": METADATA.get(gate["class_key"], METADATA["bns"])["label"],
        "status": gate["status"],
        "gate_reason": gate["reason"],
        "gate_confidence": gate["confidence"],
        "gate_subclass": gate["subclass"],
    })
    return base


class KilonovaScoutAgent(Agent):
    """Master orchestrator implementing the v2 milestone pipeline DAG."""

    def __init__(self, agent_name: str = "kilonovascout-core", tools: Optional[KilonovaScoutTools] = None):
        strands_tools = [
            tools.parse_healpix_map,
            tools.query_glade_catalog,
            tools.check_observatory_weather,
            tools.check_dome_safety,
            tools.generate_telescope_slew_script,
            tools.write_observation_header,
            tools.send_sms_alert,
        ] if tools else []

        super().__init__(
            name=agent_name,
            model=_build_model(_primary_model()),
            tools=strands_tools,
            hooks=[_ToolAuditHook()],  # M9.4 lifecycle observability
            system_prompt=(
                "You are KilonovaScout, a Staff-level Space Systems AI orchestrator. "
                "Run the astronomy pipeline: ingest -> skymap -> (catalog || weather) -> "
                "grb_check -> slew_script -> dome_safety -> rationale. Only request human "
                "approval once the slew script is ready and dome safety is confirmed. "
                "If no NASA GCN event is available, fall back to the mock GW170817 payload "
                "and continue."
            ),
        )

        self.tools_instance = tools or KilonovaScoutTools()
        self.simulator = EventSimulator()
        self.update_tracker = SkymapUpdateTracker()  # M9.2 dynamic re-pointing
        self.agent_state = AgentState(
            status="listening",
            approval_needed=False,
            source="mock",
            llm_rationale="",
        )
        self._trace_callback = None
        # (step, tool_name, status, attempt, input, output, err, started_at, duration_ms)
        self._measured_steps: List[StepEvent] = []
        self._run_lock = threading.Lock()

    def is_busy(self) -> bool:
        """True while a pipeline run holds the agent (for pollers/UI)."""
        return self._run_lock.locked()

    def set_trace_callback(self, cb) -> None:
        self._trace_callback = cb

    @_exclusive_run
    async def process_gcn_event(self, payload: GcnKafkaPayload) -> AgentOutput:
        """Live entry point: run the DAG with source='live'."""
        superevent_id = SkymapUpdateTracker.superevent_id(payload.voevent.ivorn or "")
        if not claim_live_trigger(superevent_id):
            prior = live_run_id(superevent_id)
            print(f"[AGENT] duplicate live trigger {superevent_id} skipped"
                  + (f" (already ran as {prior})" if prior else ""))
            return AgentOutput(
                message=f"Live trigger {superevent_id} already ran; skipping duplicate.",
                details={"duplicate": True, "superevent_id": superevent_id,
                         "run_id": prior},
                action_status="skipped",
            )
        event_summary = _serialize_event(payload.voevent, topic=payload.topic)
        run = await run_registry.create_run(source="live", event=event_summary)
        note_live_run(superevent_id, run.run_id)
        self.agent_state.run_id = run.run_id
        self.agent_state.last_gcn_event = payload.voevent.ivorn
        self.agent_state.source = "live"
        try:
            output = await self._run_dag(payload, run)
            await run_registry.finish_run(
                run.run_id, "completed",
                llm_rationale=self.agent_state.llm_rationale or output.message,
                candidates=[_galaxy_to_dict(g) for g in self.agent_state.candidate_galaxies or []],
                weather=_weather_to_dict(self.agent_state.observatory_weather) if self.agent_state.observatory_weather else None,
                slew_script=self.agent_state.slew_script.script_content if self.agent_state.slew_script else None,
            )
            await _attach_weather_tier(run.run_id)
            await _notify_run_complete(run.run_id)
            return output
        except Exception as exc:
            await run_registry.finish_run(run.run_id, "failed", error=str(exc))
            await _notify_run_complete(run.run_id)
            self.agent_state.status = "error"
            return AgentOutput(message=f"Pipeline error: {exc}", details={"error": str(exc)}, action_status="failure")

    async def handle_live_notice(self, payload: GcnKafkaPayload) -> None:
        """Callback for the GCN listener: process a live notice through the pipeline."""
        # Test-role notices are drills, not sky: never spend telescope time
        # (or a live run record) on them in 24/7 operation.
        if (payload.voevent.role or "").lower() == "test":
            print(f"[GCN] test-role notice {payload.voevent.ivorn} ignored (drill, not sky)")
            return
        self.agent_state.source = "live"
        await self.process_gcn_event(payload)

    async def approve_slew_script(self) -> AgentOutput:
        """Human-in-the-loop approval endpoint."""
        if self.agent_state.approval_needed:
            self.agent_state.status = "slewing"
            self.agent_state.approval_needed = False
            self.tools_instance.send_sms_alert(message="Telescope SLEW INITIATED. Tracking...")
            return AgentOutput(message="Slew initiated.", action_status="success")
        return AgentOutput(message="No pending script.", action_status="failure")

    @_exclusive_run
    async def run_mock_event(self, event_class: str = "bns") -> AgentOutput:
        """Reproducible mock run for any supported event class."""
        payload = self.simulator.get_payload(event_class)
        run = await run_registry.create_run(source="mock", event=_serialize_event(payload.voevent, topic=payload.topic))
        self.agent_state.run_id = run.run_id
        self.agent_state.last_gcn_event = payload.voevent.ivorn
        self.agent_state.source = "mock"
        try:
            output = await self._run_dag(payload, run)
            await run_registry.finish_run(
                run.run_id, "completed",
                llm_rationale=self.agent_state.llm_rationale or output.message,
                candidates=[_galaxy_to_dict(g) for g in self.agent_state.candidate_galaxies or []],
                weather=_weather_to_dict(self.agent_state.observatory_weather) if self.agent_state.observatory_weather else None,
                slew_script=self.agent_state.slew_script.script_content if self.agent_state.slew_script else None,
            )
            await _attach_weather_tier(run.run_id)
            await _notify_run_complete(run.run_id)
            return output
        except Exception as exc:
            await run_registry.finish_run(run.run_id, "failed", error=str(exc))
            await _notify_run_complete(run.run_id)
            self.agent_state.status = "error"
            return AgentOutput(message=f"Mock pipeline error: {exc}", details={"error": str(exc)}, action_status="failure")

    async def _run_dag(self, payload: GcnKafkaPayload, run: RunRecord) -> AgentOutput:
        skymap_url = payload.voevent.wherewhen.get("skymap_url") if payload.voevent.wherewhen else None
        if not skymap_url:
            skymap_url = "mock://gcn.local/skymap.fits"

        self.agent_state.status = "processing"
        self._measured_steps = []
        _log_mem(run.run_id, "start")

        async def stamp(step: int, tool: str, status: str, attempt: int = 1,
                        input_s: str = "", output_s: str = "", err: str = "",
                        duration_ms: Optional[int] = None) -> None:
            se = await _emit_step(run, step=step, tool_name=tool, status=status, attempt=attempt,
                                  input_summary=input_s, output_summary=output_s, error=err,
                                  duration_ms=duration_ms)
            self._measured_steps.append(se)
            if self._trace_callback:
                await self._trace_callback(se)

        # Step 1 — ingestion
        await stamp(1, "ingestion.filter_gcn", "running", input_s="validate GW notice")
        start = time.perf_counter()
        verdict = await self._ingest_with_fallback(payload, run, attempt=1)
        await stamp(1, "ingestion.filter_gcn", "completed", output_s=json.dumps(verdict, default=str),
                    duration_ms=int((time.perf_counter() - start) * 1000))

        if verdict.get("status") == "REJECTED":
            self.agent_state.status = "rejected"
            return AgentOutput(message=verdict.get("gate_reason", verdict.get("reason", "Rejected by ingestion filter")), action_status="failure")

        # Per-run event-class setup: scoring profile + harvested trigger
        # energetics (flux/signalness terms) for the catalog stage.
        event_class = verdict.get("event_class") or "bns"
        self.tools_instance.active_class = event_class
        self.tools_instance.active_trigger_params = harvest_params(payload.voevent.what)
        profile = get_profile(event_class)
        await run_registry.attach(run.run_id, event_update={
            "event_class": event_class,
            "class_label": verdict.get("class_label"),
            "gate_status": verdict.get("status"),
            "gate_reason": verdict.get("gate_reason"),
            "gate_confidence": verdict.get("gate_confidence"),
            "gate_subclass": verdict.get("gate_subclass"),
        })

        # Step 2 — localization.  FITS triggers (LVC) use the v3 fallback
        # chain; point-position triggers (GRB/neutrino RA/Dec + error radius)
        # build the equivalent 90% HEALPix map directly.
        ww = payload.voevent.wherewhen or {}
        point_ra = ww.get("ra_deg")
        point_dec = ww.get("dec_deg")
        if point_ra is not None and point_dec is not None and not ww.get("skymap_url"):
            point_err = float(ww.get("error_radius_deg") or 1.0)
            await stamp(2, "healpix.point_localize", "running",
                        input_s=f"RA {point_ra}, Dec {point_dec} ± {point_err}°")
            start = time.perf_counter()
            skymap = await self._try_step("healpix", self.tools_instance.build_point_skymap, run=run, step=3,
                                          ra_deg=float(point_ra), dec_deg=float(point_dec),
                                          radius_deg=point_err, retries=1)
            await stamp(2, "healpix.point_localize", "completed",
                        output_s=f"point map, {float(getattr(skymap, 'localization_area_sq_deg', 0.0) or 0.0):.1f} deg² [tier=synthetic]",
                        duration_ms=int((time.perf_counter() - start) * 1000))
        else:
            await stamp(2, "healpix.parse_skymap", "running", input_s=skymap_url)
            start = time.perf_counter()
            skymap = await self._try_step("healpix", self.tools_instance.parse_healpix_map, run=run, step=3,
                                          skymap_url=skymap_url, retries=2)
            await stamp(2, "healpix.parse_skymap", "completed",
                        output_s=f"skymap parsed [tier={getattr(skymap, 'provenance_source', 'unknown')}]",
                        duration_ms=int((time.perf_counter() - start) * 1000))
        self.agent_state.current_skymap = skymap

        # Provenance (M4.4/4.5.5): record which skymap tier won
        provenance_skymap = getattr(skymap, "provenance_source", None) or "unknown"
        await run_registry.attach(run.run_id, provenance={"skymap": provenance_skymap})

        # Skymap statistics for the report writer (calculation trace inputs)
        skymap_stats = {
            "nside": getattr(skymap, "nside", None),
            "pixel_count_90": len(getattr(skymap, "supercell_indices", []) or []),
            "area_sq_deg": getattr(skymap, "localization_area_sq_deg", None),
            "dist_mean": getattr(skymap, "dist_mean", None),
            "dist_std": getattr(skymap, "dist_std", None),
        }
        await run_registry.attach(run.run_id, event_update={"skymap_summary": skymap_stats})
        _log_mem(run.run_id, "post-skymap")
        gc.collect()

        # Dynamic re-pointing (M9.2): compare with the previous centroid for
        # this superevent; on a >10 deg shift, emit a re-authorization alert.
        repoint_info = None
        try:
            if getattr(skymap, "supercell_indices", None):
                ra_c, dec_c, _ = self.tools_instance._skymap_geometry(skymap)
                superevent = SkymapUpdateTracker.superevent_id(payload.voevent.ivorn)
                is_update = "update" in (payload.voevent.ivorn or "").lower()
                repoint_info = self.update_tracker.evaluate(superevent, ra_c, dec_c)
                if is_update and repoint_info.get("repoint"):
                    shift = repoint_info.get("shift_deg", 0.0)
                    msg = (f"RE-POINTING REQUIRED: skymap centroid shifted {shift:.1f} deg "
                           f"> 10 deg for {superevent}. Re-authorization requested.")
                    await stamp(2, "repointing.reauthorized", "completed", output_s=msg)
                    await self._try_step("notify", self.tools_instance.send_sms_alert, run=run, step=2,
                                         message=msg, retries=1)
        except Exception as exc:
            print(f"[SYS] re-pointing check skipped: {exc}")

        # Build skymap summary for the LLM + report
        skymap_summary = {
            "url": skymap_url,
            "nside": getattr(skymap, "nside", None),
            "pixel_count_90": len(getattr(skymap, "supercell_indices", []) or []),
            "area_sq_deg": getattr(skymap, "localization_area_sq_deg", None),
            "provenance": provenance_skymap,
        }

        # Steps 3+4 — concurrent catalog + weather (Milestone 3 DAG)
        async def do_catalog():
            await stamp(3, "galaxy.query_catalog", "running", input_s="GLADE+ crossmatch")
            s = time.perf_counter()
            g = await self._try_step("galaxy", self.tools_instance.query_glade_catalog, run=run, step=5,
                                     skymap=skymap, retries=2)
            g = normalize_priorities(g)
            await stamp(3, "galaxy.query_catalog", "completed",
                        output_s=f"{len(g)} candidates [tier={getattr(g[0], 'catalog_source', 'mock') if g else 'mock'}]",
                        duration_ms=int((time.perf_counter() - s) * 1000))
            self.agent_state.candidate_galaxies = g
            return g

        async def do_weather():
            await stamp(4, "weather.observatory", "running", input_s="Open-Meteo query")
            s = time.perf_counter()
            try:
                w = await self._try_step("weather", self.tools_instance.check_observatory_weather, run=run, step=6, retries=3)
                await stamp(4, "weather.observatory", "completed", output_s=f"cloud={w.cloud_cover_percent}%",
                            duration_ms=int((time.perf_counter() - s) * 1000))
            except Exception as exc:
                # Weather failure is recorded as a failed step with safe fallback values (Milestone 3)
                w = ObservatoryWeather(
                    observatory_name=self.tools_instance.observatory_name,
                    latitude=self.tools_instance.observatory_location.lat.value,
                    longitude=self.tools_instance.observatory_location.lon.value,
                    cloud_cover_percent=0.0,
                    seeing_conditions="fallback (API error)",
                    humidity_pct=0.0,
                    dome_safe=True,
                )
                await stamp(4, "weather.observatory", "failed", err=str(exc),
                            output_s="using safe fallback values",
                            duration_ms=int((time.perf_counter() - s) * 1000))
            self.agent_state.observatory_weather = w
            return w

        galaxies_task = asyncio.ensure_future(do_catalog())
        weather_task = asyncio.ensure_future(do_weather())
        galaxies, weather = await asyncio.gather(galaxies_task, weather_task)
        self.agent_state.observatory_weather = weather

        # Provenance (M4.4/4.5.5): record which catalog tier produced the rows
        catalog_source = getattr(galaxies[0], "catalog_source", None) if galaxies else None
        await run_registry.attach(run.run_id, provenance={
            "catalog": catalog_source or "mock",
            "event": run.source,
        })
        _log_mem(run.run_id, "post-catalog-weather")
        gc.collect()

        # Step 5 — ephemeris / observability. The full per-candidate windowed
        # airmass (M7.5), lunar separation (M7.3) and SNR proxy (M7.6) metrics
        # were computed inside the scoring tool; this stage aggregates them,
        # filters moon-unsafe targets, and stamps the summary.
        await stamp(5, "ephemeris.observability", "running", input_s=f"{len(galaxies)} targets")
        start = time.perf_counter()
        try:
            moon_blocked = 0
            visible_count = 0
            for g in galaxies:
                obs = getattr(g, "observability", None) or {}
                if obs.get("moon_safe") is False:
                    moon_blocked += 1
                if float(obs.get("mean_airmass", 38.0) or 38.0) < 38.0:
                    visible_count += 1
            eph_summary = (f"{len(galaxies)} targets; {visible_count} above horizon; "
                           f"{moon_blocked} excluded by lunar separation")
            await stamp(5, "ephemeris.observability", "completed", output_s=eph_summary,
                        duration_ms=int((time.perf_counter() - start) * 1000))
        except Exception as exc:
            await stamp(5, "ephemeris.observability", "failed", err=str(exc),
                        duration_ms=int((time.perf_counter() - start) * 1000))

        # Step 6 — validator / GRB coincidence (real tool).  Only meaningful
        # for GW triggers; a GRB (or neutrino) trigger skips this stage —
        # checking a burst for coincidence with itself is tautological.
        grb_boost = 1.0
        if not profile.get("needs_validator", True):
            class_label = METADATA.get(event_class, METADATA["bns"])["label"]
            await stamp(6, "validator.multimessenger", "skipped",
                        output_s=f"not applicable — trigger is itself a {class_label} event")
            grb_boost = 0.0
        else:
            await stamp(6, "validator.multimessenger", "running", input_s="coincidence checks")
            start = time.perf_counter()
            try:
                top = galaxies[0] if galaxies else None
                gw_time = (payload.voevent.wherewhen or {}).get("event_time") or last_mock_event_time()
                grb_catalog = [
                    {"id": "GRB170817A", "time": "2017-08-17T12:41:06", "ra": 197.45, "dec": -23.38, "error_radius_deg": 0.5},
                ]
                vres = await asyncio.to_thread(
                    validator_agent.evaluate_gamma_ray_coincidence,
                    gw_time, top.ra_deg if top else 0.0, top.dec_deg if top else 0.0,
                    json.dumps(grb_catalog),
                )
                await stamp(6, "validator.multimessenger", "completed",
                            output_s=f"coincidence={vres.get('coincidence_detected', False)}",
                            duration_ms=int((time.perf_counter() - start) * 1000))
                if vres.get("coincidence_detected") and top is not None:
                    # A real coincidence must move the ranking, not just the log:
                    # mirror the tools formula (additive boost, default 3.0).
                    boost = float(vres.get("priority_boost_factor", 3.0))
                    top.composite_score = (getattr(top, "composite_score", 0.0) or 0.0) + boost
                    bd = getattr(top, "score_breakdown", None)
                    if bd is not None:
                        try:
                            bd.terms["grb_boost"] = boost
                            bd.total = float(top.composite_score)
                        except Exception:
                            pass
                    galaxies = sorted(
                        galaxies,
                        key=lambda g: (getattr(g, "composite_score", 0.0) or 0.0),
                        reverse=True,
                    )
                    galaxies = normalize_priorities(galaxies)
                    self.agent_state.candidate_galaxies = galaxies
                    grb_boost = boost
            except Exception as exc:
                await stamp(6, "validator.multimessenger", "failed", err=str(exc),
                            duration_ms=int((time.perf_counter() - start) * 1000))

        # Step 7 — scheduler / slew script
        await stamp(7, "scheduler.slew_script", "running", input_s="ASCOM/INDI generation")
        start = time.perf_counter()
        slew_script = await self._try_step("scheduler", self.tools_instance.generate_telescope_slew_script, run=run, step=8,
                                           galaxies=galaxies, retries=1)
        await stamp(7, "scheduler.slew_script", "completed", output_s="script generated",
                    duration_ms=int((time.perf_counter() - start) * 1000))
        self.agent_state.slew_script = slew_script

        # Step 8 — dome safety re-check (v3 PRD M9.5): fresh weather check
        # between slew-script generation and human approval, with emergency
        # abort thresholds (humidity > 85% or cloud cover > 40%).
        await stamp(8, "dome.safety_check", "running", input_s="mid-sequence re-check")
        start = time.perf_counter()
        try:
            dome = await self._try_step("dome", self.tools_instance.check_dome_safety, run=run, step=8, retries=1)
            weather = dome
            self.agent_state.observatory_weather = weather
            await stamp(8, "dome.safety_check", "completed",
                        output_s=f"dome_safe={getattr(dome, 'dome_safe', True)} "
                                 f"humidity={getattr(dome, 'humidity_pct', 0):.0f}% "
                                 f"cloud={getattr(dome, 'cloud_cover_percent', 0):.0f}%",
                        duration_ms=int((time.perf_counter() - start) * 1000))
        except Exception as exc:
            await stamp(8, "dome.safety_check", "failed", err=str(exc),
                        duration_ms=int((time.perf_counter() - start) * 1000))

        # Step 9 — LLM rationale and visualization agent run concurrently
        # (PRD M8.4: plots generated in parallel with the rationale).
        await stamp(9, "llm.rationale", "running", input_s="trigger + candidates + weather")

        async def do_visualizations():
            try:
                return await asyncio.to_thread(
                    generate_run_visualizations,
                    skymap,
                    [_galaxy_to_dict(g) for g in galaxies],
                    _weather_to_dict(weather),
                    {"grb_boost": grb_boost, "grb_coincidence": grb_boost > 1.0},
                )
            except Exception as exc:
                print(f"[VIZ] visualization generation failed (continuing): {exc}")
                return {}

        rationale_task = self._llm_decision(verdict, galaxies, weather, skymap_summary, grb_boost)
        viz_task = asyncio.ensure_future(do_visualizations())
        decision, rationale = await rationale_task
        visualizations = await viz_task

        if visualizations:
            await run_registry.attach(run.run_id, visualizations=visualizations)
        _log_mem(run.run_id, "post-viz")
        gc.collect()
        await stamp(9, "llm.rationale", "completed", output_s=decision,
                    duration_ms=int((time.perf_counter() - start) * 1000))
        self.agent_state.llm_rationale = rationale

        # Step 10 — FITS observation header (v3 PRD M9.1)
        await stamp(10, "fits.observation_header", "running", input_s="header packaging")
        start = time.perf_counter()
        try:
            header_info = await asyncio.to_thread(
                self.tools_instance.write_observation_header,
                galaxies,
                weather,
                slew_script.script_content if slew_script else "",
            )
            await run_registry.attach(run.run_id, observation_header=header_info.get("header_text"))
            await stamp(10, "fits.observation_header", "completed",
                        output_s=f"{len((header_info.get('header_text') or '').splitlines())} cards",
                        duration_ms=int((time.perf_counter() - start) * 1000))
        except Exception as exc:
            await stamp(10, "fits.observation_header", "failed", err=str(exc),
                        duration_ms=int((time.perf_counter() - start) * 1000))

        # Notify + approval gate
        blocked = weather.cloud_cover_percent > 80 or not getattr(weather, "dome_safe", False)
        if decision == "REJECT" or blocked:
            msg = rationale if decision == "REJECT" else (
                f"Target Acquired but Sky Overcast ({weather.cloud_cover_percent}%) at {weather.observatory_name}. Monitoring..."
            )
            self.agent_state.status = "weather_blocked" if not decision == "REJECT" else "rejected"
            await self._try_step("notify", self.tools_instance.send_sms_alert, run=run, step=11, message=msg, retries=1)
            return AgentOutput(message=msg, details={"observatory": weather.observatory_name}, action_status="pending")

        await self._try_step("notify", self.tools_instance.send_sms_alert, run=run, step=11,
                             message=f"TARGET ACQUIRED: Human Approval Required for {len(galaxies)} targets at {weather.observatory_name}.",
                             retries=1)
        self.agent_state.approval_needed = True
        self.agent_state.status = "awaiting_approval"

        return AgentOutput(
            message="Slew script generated. Awaiting Human-in-the-Loop approval.",
            details={
                "targets": len(galaxies),
                "observatory": weather.observatory_name,
                "slew_script": slew_script.script_content,
                "candidates": [_galaxy_to_dict(g) for g in galaxies],
                "decision": decision,
            },
            action_status="awaiting_approval",
        )

    async def _ingest_with_fallback(self, payload: GcnKafkaPayload, run: RunRecord, attempt: int) -> Dict[str, Any]:
        if attempt > 2:
            mock_payload = self.simulator.get_mock_gw170817_payload()
            await _emit_step(run, step=1, tool_name="ingestion.filter_gcn", status="skipped", attempt=attempt,
                             output_summary="using mock payload", error="live GCN unavailable")
            self.agent_state.source = "mock"
            return _classify_trigger(mock_payload)
        try:
            return await self._try_step("ingestion", self._mock_ingest, run=run, step=2, payload=payload, retries=1)
        except Exception as exc:
            return await self._ingest_with_fallback(payload, run, attempt + 1)

    async def _try_step(self, name: str, fn, *, run: RunRecord, step: int, retries: int = 2, **kwargs):
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                if asyncio.iscoroutinefunction(fn):
                    return await fn(**kwargs)
                return fn(**kwargs)
            except Exception as exc:
                last_exc = exc
                await _emit_step(run, step=step, tool_name=name, status="failed", attempt=attempt, error=str(exc))
                await asyncio.sleep(0.25 * attempt)
        raise last_exc or RuntimeError(f"{name} failed after {retries} attempts")

    async def _mock_ingest(self, payload: GcnKafkaPayload) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        return _classify_trigger(payload)

    async def _llm_decision(self, verdict: Dict[str, Any], galaxies: List[Galaxy],
                            weather: ObservatoryWeather, skymap_summary: Optional[Dict[str, Any]],
                            grb_boost: float = 1.0) -> Tuple[str, str]:
        """Invoke the LLM with failover; never break the pipeline."""
        try:
            return await asyncio.to_thread(
                reason_about_event,
                verdict,
                [_galaxy_to_dict(g) for g in galaxies],
                weather,
                skymap_summary,
            )
        except Exception as exc:
            print(f"[LLM] reason_about_event error: {exc}")
            if galaxies:
                top = galaxies[0]
                return "ACCEPT", f"Primary candidate {top.name} identified (composite score {getattr(top, 'composite_score', 0):.2f})."
            return "ACCEPT", "Target candidates identified for follow-up."

    def get_agent_state(self) -> AgentState:
        return self.agent_state

    def get_execution_traces(self) -> List[Dict[str, Any]]:
        """Return measured execution traces (no hardcoded durations).

        Merges the running/completed ('running' emitted first, then
        'completed'/'failed') pairs into a single terminal card per step,
        so the frontend sees one measured row per tool.
        """
        terminal = {}
        for s in self._measured_steps:
            if s.status == "running":
                continue
            key = (s.step, s.tool_name)
            terminal[key] = {
                "step": s.step,
                "tool_name": s.tool_name,
                "status": s.status,
                "attempt": s.attempt,
                "started_at": s.started_at,
                "duration_ms": s.duration_ms,
                "error": s.error,
                "input_summary": s.input_summary,
                "output_summary": s.output_summary,
            }
        return list(terminal.values())

    async def get_run_record(self, run_id: str) -> Optional[RunRecord]:
        return await run_registry.get_record(run_id)

    async def subscribe_run(self, run_id: str) -> asyncio.Queue:
        return await run_registry.subscribe(run_id)


def _mock_verdict(payload: GcnKafkaPayload) -> Dict[str, Any]:
    return {
        "status": "ACCEPTED",
        "superevent_id": payload.voevent.ivorn,
        "skymap_url": (payload.voevent.wherewhen or {}).get("skymap_url", "mock://gcn.local/skymap.fits"),
        "event_time": (payload.voevent.wherewhen or {}).get("event_time"),
        "p_astro": 0.99,
    }


def last_mock_event_time() -> str:
    """Return an ISO time near the mock GW170817 epoch for GRB coincidence checks."""
    return "2017-08-17T12:41:06"
