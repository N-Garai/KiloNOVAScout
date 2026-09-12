"""historical.py — Curated historical-event corpus + payload builder (v4 M17).

The corpus (data/historical_events.json) stores lightweight metadata plus
OFFICIAL data links for real past events across all three classes. Nothing
heavy is committed: BNS skymap FITS files are downloaded at ANALYSIS time
from the stored official URL (reusing the pipeline's existing download path
with its honest replay fallback); GRB/neutrino entries carry positions, so
the pipeline builds point-maps with no download at all.

This module never touches the network. It reads the local corpus and builds
GcnKafkaPayload objects shaped exactly like live notices, so the existing
DAG runs unchanged (source='historical', no live-check, no fallback chain
beyond the DAG's own per-stage tiers).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import GcnKafkaPayload, Voevent

_HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(_HERE, "data", "historical_events.json")

_TOPICS = {
    "bns": "gcn.classic.voevent.LVC_INITIAL",
    "grb": "gcn.classic.voevent.FERMI_GBM_ALERT",
    "neutrino": "gcn.classic.voevent.ICECUBE_ASTROTRACK_GOLD",
}


def load_corpus() -> List[Dict[str, Any]]:
    """Load the curated corpus (empty list if the file is missing)."""
    try:
        with open(CORPUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def filter_events(event_classes=None, start_year=None, end_year=None) -> List[Dict[str, Any]]:
    """Filter the corpus by class and year range (local JSON, no network)."""
    classes = None
    if event_classes:
        if isinstance(event_classes, str):
            classes = {c.strip().lower() for c in event_classes.split(",") if c.strip()}
        else:
            classes = {str(c).lower() for c in event_classes}
    out = []
    for e in load_corpus():
        ec = str(e.get("event_class", "")).lower()
        if classes and ec not in classes:
            continue
        yr = e.get("year")
        if start_year is not None and isinstance(yr, int) and yr < start_year:
            continue
        if end_year is not None and isinstance(yr, int) and yr > end_year:
            continue
        out.append(e)
    return out


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    """Look up one corpus entry by event_id (case-sensitive)."""
    for e in load_corpus():
        if e.get("event_id") == event_id:
            return e
    return None


def build_payload(entry: Dict[str, Any]) -> GcnKafkaPayload:
    """Build a live-shaped GcnKafkaPayload from a corpus entry.

    BNS entries carry an official skymap_url (downloaded at analysis time by
    the existing DAG stage); GRB/neutrino entries carry a position for
    point-map synthesis. Alert properties become the VoEvent `what` params
    the ingest gate already parses.
    """
    event_class = str(entry.get("event_class", "bns")).lower()
    if event_class not in _TOPICS:
        event_class = "bns"
    props = entry.get("alert_properties") or {}
    wherewhen: Dict[str, Any] = {
        "trigger_id": entry.get("event_id"),
        "event_time": entry.get("trigger_time"),
        "event_class": event_class,
    }
    if entry.get("skymap_url"):
        wherewhen["skymap_url"] = entry["skymap_url"]
    if entry.get("ra_deg") is not None:
        wherewhen["ra_deg"] = entry["ra_deg"]
    if entry.get("dec_deg") is not None:
        wherewhen["dec_deg"] = entry["dec_deg"]
    if entry.get("error_radius_deg") is not None:
        wherewhen["error_radius_deg"] = entry["error_radius_deg"]
    if entry.get("distance_mpc") is not None:
        wherewhen["distance_mpc"] = entry["distance_mpc"]

    what = []
    if event_class == "bns":
        what = [{
            "far": props.get("far", 1e-9),
            "properties": {
                "BNS": props.get("BNS", 0.9),
                "NSBH": props.get("NSBH", 0.0),
                "BBH": props.get("BBH", 0.0),
                "Terrestrial": props.get("Terrestrial", 0.01),
                "HasNS": props.get("HasNS", 0.9),
            },
        }]
    elif event_class == "grb":
        what = [
            {"name": "T90", "value": str(props.get("T90", ""))},
            {"name": "Fluence", "value": str(props.get("Fluence", ""))},
            {"name": "Peak_Flux", "value": str(props.get("Peak_Flux", ""))},
        ]
    else:
        what = [
            {"name": "Signalness", "value": str(props.get("Signalness", ""))},
            {"name": "Angular_Error", "value": str(props.get("Angular_Error", props.get("error_radius_deg", "")))},
        ]

    try:
        ts = datetime.fromisoformat(str(entry.get("trigger_time", "")).replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now()
    return GcnKafkaPayload(
        topic=_TOPICS[event_class],
        offset=0,
        timestamp=ts,
        voevent=Voevent(
            ivorn=f"historical://kilonovascout/{entry.get('event_id', 'unknown')}",
            role="observation",
            description=f"Historical {event_class.upper()} event {entry.get('event_id')} (retrospective analysis)",
            wherewhen=wherewhen,
            what=what,
        ),
    )
