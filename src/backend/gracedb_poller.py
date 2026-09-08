"""gracedb_poller.py - IPv6-free live trigger path for Render free tier.

Render's free egress cannot route IPv6 to kafka*.gcn.nasa.gov, so the Kafka
listener idles in mock mode there no matter how good the credentials are.
GraceDB's public REST API, however, is plain IPv4 HTTPS — the same class of
egress Open-Meteo and VizieR already use successfully from Render.

This module polls ``GET /api/superevents/`` for new *significant* production
superevents and injects them into the pipeline through the exact same
``on_notice`` entrypoint (and the exact same VOEvent-XML parser) as live
Kafka notices.  Provenance therefore reads ``event: live`` honestly.

Rules (conservative by design):
  * Only ``category == "Production"`` + ``SIGNIF_LOCKED`` label + FAR below
    threshold + created within the lookback window.  MDC/test events never
    fire (wrong category, no SIGNIF_LOCKED).
  * The seen-set is seeded with everything significant on the FIRST poll so
    a fresh boot never replays stale history — only newly-appearing events
    trigger runs.  Retraction VOEvents are skipped, never fired.
  * Skymap URL is overridden to the event's flat ``bayestar.fits.gz`` flavor
    when listed (the parser only understands flat maps, not multi-order).

Opt-in only: ``GRACEDB_POLL=true`` (default off — zero behavior change),
``GRACEDB_POLL_MINUTES`` (default 15), ``GRACEDB_FAR_HZ`` (default 1/yr).
BNS class only: GraceDB carries gravitational-wave superevents.
"""

from __future__ import annotations

import asyncio
import datetime
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from .event_classes import FAR_PER_YEAR_HZ

GRACEDB_API = "https://gracedb.ligo.org"
LIST_URL = GRACEDB_API + "/api/superevents/"
SEEN_CAP = 500


def _as_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def is_significant_candidate(se: Dict[str, Any], far_hz: float, lookback_h: float, now: float) -> Tuple[bool, str]:
    """Decide whether a superevent dict deserves a pipeline run."""
    sid = se.get("superevent_id", "?")
    if se.get("category") != "Production":
        return False, f"{sid}: category {se.get('category')} is not Production"
    labels = se.get("labels") or []
    if "SIGNIF_LOCKED" not in labels:
        return False, f"{sid}: no SIGNIF_LOCKED label"
    far = _as_float(se.get("far"))
    if far is None or far > far_hz:
        return False, f"{sid}: FAR {se.get('far')} above threshold"
    t0 = _as_float(se.get("t_0"))
    if t0 is not None and (now - t0) > lookback_h * 3600.0:
        return False, f"{sid}: older than lookback window"
    return True, f"{sid}: significant (FAR {far:.2e} Hz)"


def select_new_triggers(
    list_payload: Dict[str, Any],
    seen: Set[str],
    *,
    far_hz: float = FAR_PER_YEAR_HZ,
    lookback_h: float = 48.0,
    now: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Pick not-yet-seen significant superevents from a list response.

    Returns (new_triggers, updated_seen).  Pure function — unit-testable.
    Each trigger: {superevent_id, far, t_0, reason}.
    """
    now = now if now is not None else time.time()
    prior = set(seen)
    seen = set(seen)
    new: List[Dict[str, Any]] = []
    for se in (list_payload or {}).get("superevents", []) or []:
        sid = se.get("superevent_id")
        if not sid:
            continue
        ok, reason = is_significant_candidate(se, far_hz, lookback_h, now)
        seen.add(sid)
        if ok and sid not in prior:
            new.append({"superevent_id": sid, "far": se.get("far"),
                        "t_0": se.get("t_0"), "reason": reason})
    if len(seen) > SEEN_CAP:
        seen = set(list(seen)[-SEEN_CAP:])
    return new, seen


def pick_flat_skymap(files: Dict[str, str]) -> Optional[str]:
    """Choose the flat BAYESTAR FITS flavor our parser understands.

    Prefers the exact ``bayestar.fits.gz`` entry; multi-order maps are
    deliberately excluded (npix_to_nside cannot parse them).
    """
    if not files:
        return None
    if "bayestar.fits.gz" in files:
        return files["bayestar.fits.gz"]
    for name in sorted(files):
        low = name.lower()
        if "bayestar" in low and low.endswith(".fits.gz") and "multiorder" not in low:
            return files[name]
    return None


def pick_latest_voevent(voevents_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the newest non-retraction VOEvent entry (max N, skip RT type)."""
    best = None
    for v in (voevents_payload or {}).get("voevents", []) or []:
        if not isinstance(v, dict):
            continue
        if str(v.get("voevent_type", "")).upper() == "RT":
            continue
        try:
            n = int(v.get("N", -1))
        except (TypeError, ValueError):
            n = -1
        if best is None or n > best[0]:
            best = (n, v)
    return best[1] if best else None


def _http_get_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    resp = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def poll_once(seen: Set[str], *, far_hz: float = FAR_PER_YEAR_HZ,
              lookback_h: float = 48.0) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """One discovery cycle: list → filter → fetch VOEvent XML per candidate.

    Returns (payloads, updated_seen) where each payload holds everything
    needed to build a GcnKafkaPayload (superevent_id, voevent_xml bytes,
    flat skymap override URL or None).  Network errors propagate to the
    caller (the runner logs + backs off); selection itself never raises.
    """
    listing = _http_get_json(LIST_URL)
    now = time.time()
    prior = set(seen)
    fresh: List[Dict[str, Any]] = []
    for se in listing.get("superevents", []) or []:
        sid = se.get("superevent_id")
        if not sid:
            continue
        ok, reason = is_significant_candidate(se, far_hz, lookback_h, now)
        seen.add(sid)
        if ok and sid not in prior:
            fresh.append({"superevent_id": sid, "far": se.get("far"),
                          "t_0": se.get("t_0"), "reason": reason})
    if len(seen) > SEEN_CAP:
        seen = set(list(seen)[-SEEN_CAP:])

    payloads: List[Dict[str, Any]] = []
    for cand in fresh:
        sid = cand["superevent_id"]
        try:
            vo_list = _http_get_json(f"{GRACEDB_API}/api/v2/superevents/{sid}/voevents/")
            chosen = pick_latest_voevent(vo_list)
            if not chosen:
                continue
            file_link = ((chosen.get("links") or {}).get("file")) or ""
            if not file_link:
                continue
            r = requests.get(file_link, timeout=20)
            r.raise_for_status()
            xml_bytes = r.content
            flat_url = None
            try:
                files = _http_get_json(f"{GRACEDB_API}/api/v2/superevents/{sid}/files/")
                flat_url = pick_flat_skymap(files)
            except Exception:
                flat_url = None
            payloads.append({"superevent_id": sid, "far": cand["far"],
                             "voevent_xml": xml_bytes, "skymap_url": flat_url})
        except Exception as exc:
            print(f"[POLL] {sid} fetch failed ({exc}); will retry next cycle")
    return payloads, seen


def build_live_payload(voevent_xml: bytes, superevent_id: str,
                       skymap_override: Optional[str] = None):
    """Parse fetched VOEvent XML into a live GcnKafkaPayload (lazy imports)."""
    from .gcn_listener import _parse_voevent_xml
    from .models import GcnKafkaPayload
    voevent = _parse_voevent_xml(voevent_xml, topic="gcn.live.gracedb-poll")
    if voevent is None:
        return None
    voevent.wherewhen["event_class"] = "bns"
    if skymap_override:
        voevent.wherewhen["skymap_url"] = skymap_override
        voevent.wherewhen["skymap_summary"] = {"url": skymap_override}
    return GcnKafkaPayload(
        topic="gcn.live.gracedb-poll",
        offset=int(time.time()),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        voevent=voevent,
    )


def start_poller(get_handler: Callable[[], Any], loop: asyncio.AbstractEventLoop,
                 state: Dict[str, Any], interval_min: float = 15.0,
                 far_hz: float = FAR_PER_YEAR_HZ) -> threading.Event:
    """Start the background poll thread (daemon). Returns a stop event.

    ``get_handler`` is resolved fresh on every trigger so agent recreations
    (e.g. observatory updates) never leave the poller calling a stale agent.
    """
    stop = threading.Event()
    seen: Set[str] = set()
    first = True

    def _run() -> None:
        nonlocal seen, first
        while not stop.is_set():
            try:
                if first:
                    # Seed the seen-set so boot never replays stale history.
                    listing = _http_get_json(LIST_URL)
                    for se in listing.get("superevents", []) or []:
                        if se.get("superevent_id"):
                            seen.add(se.get("superevent_id"))
                    first = False
                    state.update({"last_check": _utcnow(), "last_result": f"seeded {len(seen)} ids"})
                else:
                    payloads, seen = poll_once(seen, far_hz=far_hz)
                    if payloads:
                        for p in payloads:
                            live = build_live_payload(p["voevent_xml"], p["superevent_id"], p["skymap_url"])
                            if live is None:
                                continue
                            try:
                                handler = get_handler()
                                result = handler(live)
                                if asyncio.iscoroutine(result):
                                    asyncio.run_coroutine_threadsafe(result, loop)
                            except Exception as exc:
                                print(f"[POLL] on_notice failed ({exc})")
                        state.update({"last_check": _utcnow(),
                                      "last_result": f"{len(payloads)} new trigger(s)"})
                    else:
                        state.update({"last_check": _utcnow(), "last_result": "no new triggers"})
            except Exception as exc:
                state.update({"last_check": _utcnow(), "last_result": f"poll error: {exc}"})
                print(f"[POLL] cycle failed ({exc})")
            stop.wait(interval_min * 60.0)

    threading.Thread(target=_run, name="gracedb-poller", daemon=True).start()
    return stop


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
