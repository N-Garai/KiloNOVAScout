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

# Live NASA lookup (v4 M17): the GraceDB significant-superevent catalog is a
# single anonymous JSON page. Everything else (per-event group, skymap file
# listing) is also anonymous — p_astro needs credentials, so live entries
# carry no HasNS and the gate scores them as unclassified (conf 0.5, honest).
GRACEDB_API = "https://gracedb.ligo.org/api/superevents/"
GRACEDB_SIGNIF_QUERY = "category: Production far < 3.2e-08"
# GraceDB t_0 is GPS seconds (epoch 1980-01-06); convert to Unix with this offset.
_GPS_EPOCH_OFFSET = 315964800


def _grace_get(url: str, timeout: int = 20):
    """Anonymous GraceDB GET returning parsed JSON (raises on failure)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _t0_year(t_0) -> Optional[int]:
    try:
        import datetime
        return datetime.datetime.fromtimestamp(float(t_0) + _GPS_EPOCH_OFFSET, datetime.timezone.utc).year
    except Exception:
        return None

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


_LIVE_CACHE: Dict[str, Dict[str, Any]] = {}


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    """Look up one event: live-search cache first, then the curated corpus."""
    if event_id in _LIVE_CACHE:
        return dict(_LIVE_CACHE[event_id])
    for e in load_corpus():
        if e.get("event_id") == event_id:
            entry = dict(e)
            entry.setdefault("origin", "curated")
            return entry
    return None


def _normalize_curated(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    out.setdefault("origin", "curated")
    return out


# Superevent IDs encode their creation date (S + YYMMDD), so one anonymous
# per-year prefix query replaces 55 pages of blind pagination. Years before
# 2015 have no S-IDs (pre-O1 era) and are skipped client-side — the curated
# archive covers everything older.
GRACEDB_MAX_YEARS_PER_SEARCH = 12
_YEAR_CACHE: Dict[int, Any] = {}
_YEAR_CACHE_TTL = 3600.0


def _created_year(created) -> Optional[int]:
    try:
        return int(str(created)[:4])
    except Exception:
        return None


def _detail_live(se) -> Optional[Dict[str, Any]]:
    """Single-event fetch: keep CBC (gate sorts BNS/NSBH/BBH at analysis)."""
    try:
        full = _grace_get(GRACEDB_API + se["superevent_id"] + "/", timeout=15)
    except Exception:
        return None
    group = ((full.get("preferred_event_data") or {}).get("group")) or ""
    if group != "CBC":
        return None
    try:
        import datetime
        trig = datetime.datetime.fromtimestamp(
            float(full.get("t_0")) + _GPS_EPOCH_OFFSET, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        year = int(trig[:4])
    except Exception:
        trig, year = "", _created_year(se.get("created"))
    return {
        "event_id": full.get("superevent_id"),
        "event_class": "bns",
        "trigger_time": trig,
        "ra_deg": None, "dec_deg": None, "error_radius_deg": None,
        "distance_mpc": None,
        "skymap_url": None,
        "alert_properties": {"far": full.get("far")},
        "source": "gracedb",
        "year": year,
        "official_ref": f"https://gracedb.ligo.org/superevents/{full.get('superevent_id')}/view/",
        "origin": "live",
    }


def _fetch_year_bns(year: int, timeout: int = 25) -> List[Dict[str, Any]]:
    """One year's significant Production superevents (cached 1h, raises on failure)."""
    import time as _time
    import urllib.parse
    from concurrent.futures import ThreadPoolExecutor
    hit = _YEAR_CACHE.get(year)
    if hit and _time.time() - hit[0] < _YEAR_CACHE_TTL:
        return list(hit[1])
    catalog = _grace_get(
        GRACEDB_API + "?query=" + urllib.parse.quote(
            f"S{year % 100:02d}* category: Production") + "&count=150",
        timeout=timeout)
    cands = []
    for se in catalog.get("superevents", []) or []:
        if _created_year(se.get("created")) != year:
            continue
        try:
            farok = se.get("far") is not None and float(se["far"]) < 3.2e-8
        except Exception:
            farok = False
        if farok:
            cands.append(se)
    cands.sort(key=lambda s: str(s.get("created", "")), reverse=True)
    out = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for entry in pool.map(_detail_live, cands[:40]):
            if entry:
                out.append(entry)
                _LIVE_CACHE[entry["event_id"]] = entry
    _YEAR_CACHE[year] = (_time.time(), out)
    return out


def fetch_live_bns(start_year: Optional[int] = None,
                   end_year: Optional[int] = None,
                   timeout: int = 25) -> Dict[str, Any]:
    """Query NASA GraceDB LIVE for significant superevents in a year range.

    Returns {"events": [...], "truncated": bool}. Raises on network failure
    so callers can fall back to the curated corpus.
    """
    from concurrent.futures import ThreadPoolExecutor
    lo = max(int(start_year or 2015), 2015)
    hi = int(end_year or 2015)
    years = [y for y in range(lo, hi + 1)]
    truncated = False
    if len(years) > GRACEDB_MAX_YEARS_PER_SEARCH:
        years = years[-GRACEDB_MAX_YEARS_PER_SEARCH:]
        truncated = True
    out: List[Dict[str, Any]] = []
    if not years:
        return {"events": out, "truncated": truncated}
    with ThreadPoolExecutor(max_workers=min(4, len(years))) as pool:
        for entries in pool.map(lambda y: _fetch_year_bns(y, timeout), years):
            out.extend(entries)
    out.sort(key=lambda e: str(e.get("trigger_time", "")), reverse=True)
    return {"events": out, "truncated": truncated}


def resolve_live_skymap(event_id: str, timeout: int = 12) -> Optional[str]:
    """Resolve a live event's flat bayestar FITS URL (None on any failure).

    Called once at analysis time; the DAG's honest replay fallback covers
    dead links exactly like curated entries.
    """
    try:
        files = _grace_get(GRACEDB_API + event_id + "/files/", timeout=timeout)
        names = sorted(set(str(k).split(",")[0] for k in (files or {}).keys()))
        flat = [n for n in names if n == "bayestar.fits.gz"]
        if flat:
            return f"{GRACEDB_API}{event_id}/files/{flat[0]}"
        flat = [n for n in names if n.endswith(".fits.gz") and "multiorder" not in n]
        if flat:
            return f"{GRACEDB_API}{event_id}/files/{flat[0]}"
    except Exception:
        pass
    return None


def search_events(event_classes=None, start_year=None, end_year=None,
                  live: bool = True) -> Dict[str, Any]:
    """Range search: curated corpus + LIVE GraceDB BNS, merged and deduped.

    Live wins on duplicate event_ids. Any live failure degrades to curated
    only (logged, never raised) — the search button always answers.
    """
    curated = [_normalize_curated(e) for e in filter_events(event_classes, start_year, end_year)]
    live_entries: List[Dict[str, Any]] = []
    live_error = ""
    live_truncated = False
    wants_bns = True
    if event_classes:
        if isinstance(event_classes, str):
            wants_bns = "bns" in {c.strip().lower() for c in event_classes.split(",") if c.strip()}
        else:
            wants_bns = any(str(c).lower() == "bns" for c in event_classes)
    if live and wants_bns:
        try:
            live_result = fetch_live_bns(start_year, end_year)
            live_entries = live_result.get("events", [])
            live_truncated = bool(live_result.get("truncated"))
        except Exception as exc:
            live_error = str(exc)[:200]
            print(f"[HIST] live GraceDB lookup failed ({exc}); curated only")
    seen = {e.get("event_id") for e in live_entries}
    merged = list(live_entries) + [e for e in curated if e.get("event_id") not in seen]
    by_class: Dict[str, int] = {}
    for e in merged:
        by_class[e.get("event_class", "?")] = by_class.get(e.get("event_class", "?"), 0) + 1
    return {"events": merged, "total": len(merged), "by_class": by_class,
            "live_bns": len(live_entries), "live_error": live_error,
            "live_truncated": live_truncated}


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
        # Only genuinely present numbers enter the gate: live GraceDB entries
        # carry a real FAR but no p_astro (auth-walled), so they score as
        # unclassified (conf 0.5, honest) instead of inheriting invented values.
        bns_entry: Dict[str, Any] = {}
        if props.get("far") is not None:
            bns_entry["far"] = props["far"]
        propmap = {k: props[k] for k in ("BNS", "NSBH", "BBH", "Terrestrial", "HasNS")
                   if props.get(k) is not None}
        if propmap:
            bns_entry["properties"] = propmap
        if bns_entry:
            what = [bns_entry]
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
