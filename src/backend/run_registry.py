"""Run registry and report assembly for KilonovaScout v2.

Provides:
- In-memory per-run step ledger / event queue
- DAG-style orchestration for agent pipeline
- Markdown report generation for Milestone 2
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .models import (
    AgentState,
    AgentOutput,
    Galaxy,
    HealpixSkymap,
    ObservatoryWeather,
    RunRecord,
    ScoreBreakdown,
    StepEvent,
    TelescopeSlewScript,
)


MAX_RUN_HISTORY = 20


# Live-trigger claim registry: superevent IDs that already ran the live
# pipeline, whichever entrypoint fired them (Kafka notice, GraceDB poller,
# LAUNCH-time check).  Claiming is atomic; a second claim of the same id is
# refused so one cosmic event can never produce two live runs.
_live_claims: Set[str] = set()
_live_claims_lock = threading.Lock()
_live_run_ids: Dict[str, str] = {}


def claim_live_trigger(superevent_id: str) -> bool:
    """Atomically claim a live superevent. True on first claim, False if
    this id already ran (caller must skip the duplicate run)."""
    if not superevent_id:
        return True
    with _live_claims_lock:
        if superevent_id in _live_claims:
            return False
        _live_claims.add(superevent_id)
        return True


def note_live_run(superevent_id: str, run_id: str) -> None:
    """Record which run id served a claimed superevent (for reference)."""
    if not superevent_id or not run_id:
        return
    with _live_claims_lock:
        _live_run_ids[superevent_id] = run_id


def live_run_id(superevent_id: str) -> Optional[str]:
    """Return the run id that served a superevent, if any."""
    with _live_claims_lock:
        return _live_run_ids.get(superevent_id)


@dataclass
class _RunBuffer:
    record: RunRecord
    event_queue: asyncio.Queue


class RunRegistry:
    """Thread-safe-ish in-memory registry for pipeline runs."""

    def __init__(self) -> None:
        self._runs: Dict[str, _RunBuffer] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, source: str, event: Dict[str, Any]) -> RunRecord:
        run_id = f"{source}-{int(time.time() * 1000)}"
        record = RunRecord(run_id=run_id, source=source, status="running", started_at=_now(), event=event)
        buffer = _RunBuffer(record=record, event_queue=asyncio.Queue())
        async with self._lock:
            self._runs[run_id] = buffer
            self._trim()
        await self._emit(record.run_id, _step_event(record.run_id, 0, "run", "completed", 0, "run created", event=event))
        return record

    async def append_step(self, run_id: str, step: StepEvent) -> None:
        buffer = self._runs.get(run_id)
        if not buffer:
            return
        buffer.record.steps.append(step)
        await self._emit(run_id, step)

    async def attach(
        self,
        run_id: str,
        *,
        provenance: Optional[Dict[str, str]] = None,
        visualizations: Optional[Dict[str, str]] = None,
        observation_header: Optional[str] = None,
        event_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attach v3 run artifacts (provenance, plots, FITS header, skymap stats).

        Called by the orchestrator as artifacts become available; all fields
        are optional and merge into the existing record.
        """
        buffer = self._runs.get(run_id)
        if not buffer:
            return
        if provenance:
            merged = dict(buffer.record.provenance or {})
            merged.update(provenance)
            buffer.record.provenance = merged
        if visualizations:
            merged_viz = dict(buffer.record.visualizations or {})
            merged_viz.update(visualizations)
            buffer.record.visualizations = merged_viz
        if observation_header is not None:
            buffer.record.observation_header = observation_header
        if event_update:
            event = dict(buffer.record.event or {})
            event.update(event_update)
            buffer.record.event = event

    async def finish_run(self, run_id: str, status: str, llm_rationale: Optional[str] = None, candidates: Optional[List[Dict[str, Any]]] = None, error: str = "", weather: Optional[Dict[str, Any]] = None, slew_script: Optional[str] = None) -> None:
        buffer = self._runs.get(run_id)
        if not buffer:
            return
        buffer.record.status = status
        buffer.record.finished_at = _now()
        buffer.record.llm_rationale = llm_rationale
        buffer.record.candidates = candidates or []
        buffer.record.weather = weather or buffer.record.weather
        buffer.record.slew_script = slew_script if slew_script is not None else buffer.record.slew_script
        await self._emit(run_id, _step_event(run_id, 999, "run", "completed", 1, "run finished", output_summary=status, error=error))

    async def get_record(self, run_id: str) -> Optional[RunRecord]:
        buffer = self._runs.get(run_id)
        return buffer.record if buffer else None

    def recent_records(self, hours: float = 24.0) -> List[RunRecord]:
        """Retained run records started within the last `hours` (newest last).

        Synchronous on purpose: the digest thread must not touch the event
        loop.  Best-effort ordering; unparseable timestamps sort oldest.
        Tolerates concurrent mutation by the loop thread (returns whatever
        snapshot survives, never raises).
        """
        try:
            cutoff = time.time() - float(hours) * 3600.0
        except (TypeError, ValueError):
            cutoff = time.time() - 24.0 * 3600.0
        try:
            buffers = list(self._runs.values())
        except RuntimeError:
            return []

        def _ts(rec: RunRecord) -> float:
            try:
                # 'Z' suffix needs normalizing on Python < 3.11.
                iso = str(rec.started_at)
                if iso.endswith(("Z", "z")):
                    iso = iso[:-1] + "+00:00"
                return datetime.datetime.fromisoformat(iso).timestamp()
            except (TypeError, ValueError):
                return 0.0

        return sorted(
            (b.record for b in buffers if _ts(b.record) >= cutoff),
            key=_ts,
        )

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        buffer = self._runs.get(run_id)
        if not buffer:
            raise KeyError(run_id)
        return buffer.event_queue

    async def _emit(self, run_id: str, step: StepEvent) -> None:
        buffer = self._runs.get(run_id)
        if not buffer:
            return
        try:
            buffer.event_queue.put_nowait(step)
        except asyncio.QueueFull:
            pass

    def _trim(self) -> None:
        keys = list(self._runs.keys())
        for key in keys[:-MAX_RUN_HISTORY]:
            self._runs.pop(key, None)


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _step_event(
    run_id: str,
    step: int,
    tool_name: str,
    status: str,
    attempt: int,
    summary: str,
    *,
    input_summary: str = "",
    output_summary: str = "",
    error: str = "",
    event: Optional[Dict[str, Any]] = None,
    started_at: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> StepEvent:
    return StepEvent(
        run_id=run_id,
        step=step,
        tool_name=tool_name,
        status=status,
        attempt=attempt,
        started_at=started_at or _now(),
        duration_ms=duration_ms,
        input_summary=input_summary or summary,
        output_summary=output_summary or summary,
        error=error,
    )


def build_report_markdown(record: RunRecord, weights: Dict[str, float]) -> str:
    """Assemble a Markdown observation report for one finished run."""
    lines: List[str] = []
    lines.append(f"# KiloNovaScout Observation Report — `{record.run_id}`")
    lines.append("")
    lines.append(f"- **Source:** {record.source}")
    lines.append(f"- **Status:** {record.status}")
    lines.append(f"- **Started:** {record.started_at}")
    lines.append(f"- **Finished:** {record.finished_at or '—'}")
    lines.append("")

    event = record.event or {}
    lines.append("## Trigger Verdict")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| IVORN | {event.get('ivorn', '—')} |")
    lines.append(f"| Topic | {event.get('topic', '—')} |")
    lines.append(f"| Event time | {event.get('event_time', '—')} |")
    lines.append(f"| Distance | {event.get('distance_mpc', '—')} Mpc |")
    lines.append(f"| Confidence | {event.get('confidence', '—')}% |")
    lines.append("")

    skymap = event.get("skymap_summary") if isinstance(event, dict) else None
    if skymap:
        lines.append("## Skymap Summary")
        lines.append("")
        lines.append(f"- NSIDE: `{skymap.get('nside')}`")
        lines.append(f"- 90% credible pixels: `{skymap.get('pixel_count_90')}`")
        lines.append(f"- RA range: `{float(skymap.get('ra_min', 0)):.3f}` – `{float(skymap.get('ra_max', 0)):.3f}`")
        lines.append(f"- Dec range: `{float(skymap.get('dec_min', 0)):.3f}` – `{float(skymap.get('dec_max', 0)):.3f}`")
        lines.append(f"- Distance mean/std: `{float(skymap.get('dist_mean', 0)):.2f}` ± `{float(skymap.get('dist_std', 0)):.2f}` Mpc")
        lines.append("")

    lines.append("## Candidates")
    lines.append("")
    for cand in record.candidates:
        cand_name = _get_dict_attr(cand, "name", "Candidate")
        lines.append(f"### {cand_name}")
        lines.append("")
        lines.append(f"- RA/Dec: `{_get_dict_attr(cand, 'ra')}` / `{_get_dict_attr(cand, 'dec')}`")
        lines.append(f"- Distance: `{_get_dict_attr(cand, 'distance_mpc')}` Mpc")
        lines.append(f"- Priority: `{_get_dict_attr(cand, 'priority', _get_dict_attr(cand, 'normalized_priority', '—'))}`")
        lines.append(f"- Composite score: `{_get_dict_attr(cand, 'composite_score', '—')}`")
        bd = _get_dict_attr(cand, "score_breakdown")
        if bd:
            lines.append("")
            lines.append("```text")
            lines.append(_format_score_line(cand_name, bd, weights))
            lines.append("```")
        lines.append("")

    weather = record.weather or (event.get("weather") if isinstance(event, dict) else None)
    if weather:
        lines.append("## Weather Snapshot")
        lines.append("")
        lines.append(f"- Observatory: `{weather.get('observatory_name')}`")
        lines.append(f"- Cloud cover: `{weather.get('cloud_cover_percent')}`%")
        lines.append(f"- Dome safe: `{weather.get('dome_safe')}`")
        lines.append("")

    slew = record.slew_script or (event.get("slew_script") if isinstance(event, dict) else None)
    if slew:
        lines.append("## Slew Script")
        lines.append("")
        lines.append("```xml")
        lines.append(slew)
        lines.append("```")
        lines.append("")

    if record.llm_rationale:
        lines.append("## LLM Rationale")
        lines.append("")
        lines.append(record.llm_rationale)
        lines.append("")

    return "\n".join(lines)


def _format_score_line(name: str, bd: Dict[str, Any], weights: Dict[str, float]) -> str:
    """Render one candidate's v3 scoring formula as a single-line trace.

    v3 formula (PRD M10):
      S = α·P + β·w_Sch − γ·X̄ − δ·C + ε·B_GRB + ζ·SNR − η·L_moon
    """
    terms = _get_dict_attr(bd, "terms", {})
    w = weights or {}
    total = _get_dict_attr(bd, "total", 0)
    try:
        alpha = w.get("spatial_weight_alpha", w.get("alpha", 1.0))
        beta = w.get("mass_weight_beta", w.get("beta", 0.5))
        gamma = w.get("extinction_gamma", w.get("gamma", 0.3))
        delta = w.get("weather_delta", w.get("delta", 0.2))
        epsilon = w.get("coincidence_boost", w.get("epsilon", 3.0))
        zeta = w.get("snr_weight_zeta", w.get("zeta", 0.15))
        eta = w.get("lunar_penalty_eta", w.get("eta", 0.1))
        line = (
            f"S({name}) = {alpha:.2f}×{terms.get('spatial', 0):.4f}"
            f" + {beta:.2f}×{terms.get('schechter', 0):.4f}"
            f" − {gamma:.2f}×{terms.get('airmass', 0):.3f}"
            f" − {delta:.2f}×{terms.get('cloud', 0):.3f}"
            f" + {epsilon:.2f}×{terms.get('grb_boost', 0):.1f}"
            f" + {zeta:.2f}×{terms.get('snr', 0):.4f}"
            f" − {eta:.2f}×{terms.get('lunar', 0):.3f}"
            f" = {float(total):.4f}"
        )
    except Exception:
        line = f"S({name}) = {total}"
    return line


def _get_dict_attr(obj, key, default=None):
    """Read `key` from a dict or a pydantic model."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalize_priorities(candidates: List[Galaxy]) -> List[Galaxy]:
    scores = [float(getattr(g, "composite_score", 0.0) or 0.0) for g in candidates]
    if not scores:
        return candidates
    min_s = min(scores)
    max_s = max(scores)
    span = max_s - min_s if max_s != min_s else 1.0
    for g in candidates:
        s = float(getattr(g, "composite_score", 0.0) or 0.0)
        setattr(g, "normalized_priority", round((s - min_s) / span * 100, 2))
    return candidates
