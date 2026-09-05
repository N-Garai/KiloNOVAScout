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
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    # bd may be a plain dict OR a pydantic ScoreBreakdown model
    terms = _get_dict_attr(bd, "terms", {})
    w = weights or {}
    total = _get_dict_attr(bd, "total", 0)
    try:
        line = (
            f"S({name}) = {w.get('spatial_prior', 1.0):.2f} × {terms.get('spatial', 0):.3f}"
            f" + {w.get('galaxy_mass_prior', 0.6):.2f} × {terms.get('mass', 0):.3f}"
            f" − {w.get('airmass_penalty', 0.2):.2f} × {terms.get('airmass', 0):.3f}"
            f" − {w.get('cloud_cover_penalty', 0.5):.2f} × {terms.get('cloud', 0):.3f}"
            f" + {w.get('grb_coincidence_boost', 3.0) if terms.get('grb_boost', 0) else 0:.2f} × {terms.get('grb_boost', 0):.3f}"
            f" = {float(total):.3f}"
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
