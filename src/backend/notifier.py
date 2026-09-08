"""notifier.py - Outbound run notifications for 24/7 observatory operation.

The dashboard approval modal only works when a human is looking at it.
For unattended operation, set ``ALERT_WEBHOOK_URL`` to any HTTPS endpoint
that accepts a JSON POST — Discord/Slack webhook, PagerDuty Events API,
ntfy.sh topic (``https://ntfy.sh/<topic>`` needs no account), or a custom
relay that drives SMS/sirens.  An optional ``ALERT_WEBHOOK_SECRET`` is sent
as a Bearer token.

Fires on EVERY finished run (completed AND failed — a dead pipeline at 3am
is exactly what must wake someone).  Never raises, never blocks the
pipeline: all network I/O is bounded (10 s) and wrapped.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.request
from typing import Any, Dict, Optional


def _get_dict_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_alert_payload(record: Any) -> Dict[str, Any]:
    """Build the provider-agnostic alert body from a finished run record.

    Pure function (no I/O) so alert content is unit-testable.
    """
    event = _get_dict_attr(record, "event", {}) or {}
    prov = _get_dict_attr(record, "provenance", {}) or {}
    candidates = _get_dict_attr(record, "candidates", []) or []
    weather = _get_dict_attr(record, "weather", {}) or {}
    top = candidates[0] if candidates else {}
    status = _get_dict_attr(record, "status", "unknown")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    headline = (
        f"KilonovaScout {status.upper()}: "
        f"{event.get('class_label') or event.get('event_class') or 'event'} "
        f"{event.get('trigger_id') or event.get('ivorn') or ''}".strip()
    )
    if top:
        headline += (f" — top target {top.get('name')} "
                     f"(S={top.get('composite_score')}, "
                     f"{top.get('distance_mpc')} Mpc)")
    return {
        "text": headline,  # ntfy/Discord/Slack all render `text`
        "title": "KilonovaScout follow-up alert",
        "run_id": _get_dict_attr(record, "run_id"),
        "status": status,
        "source": _get_dict_attr(record, "source"),
        "event_class": event.get("event_class"),
        "ivorn": event.get("ivorn"),
        "trigger_id": event.get("trigger_id"),
        "gate": {
            "status": event.get("gate_status"),
            "reason": event.get("gate_reason"),
            "confidence": event.get("gate_confidence"),
        },
        "top_candidate": {
            "name": top.get("name"),
            "composite_score": top.get("composite_score"),
            "distance_mpc": top.get("distance_mpc"),
            "catalog_source": top.get("catalog_source"),
        } if top else None,
        "candidates": len(candidates),
        "provenance": dict(prov),
        "observatory": weather.get("observatory_name"),
        "dome_safe": weather.get("dome_safe"),
        "report_path": f"/api/runs/{_get_dict_attr(record, 'run_id')}/report",
        "at": now,
    }


def _is_ntfy_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower() == "ntfy.sh"
    except Exception:
        return False


def _build_request(url: str, payload: Dict[str, Any], secret: str) -> urllib.request.Request:
    """Build the POST for a webhook URL (pure constructor, unit-testable).

    ntfy.sh topics speak plain text + headers (Title/Priority/Tags) — a raw
    JSON blob would arrive as unreadable text — so ntfy targets get a native
    message: urgent priority when candidates exist, a telescope tag, and no
    Bearer header (a wrong token would 401 a public topic).  Every other
    host (Discord/Slack/PagerDuty/custom relay) gets the full JSON body,
    with the secret as a Bearer token when configured.
    """
    if _is_ntfy_url(url):
        from urllib.parse import urlparse
        topic = (urlparse(url).path or "/").strip("/")
        headers = {
            "Title": str(payload.get("title") or "KilonovaScout follow-up alert"),
            "Priority": "4" if payload.get("candidates") else "3",
            "Tags": "telescope,warning" if payload.get("dome_safe") is False else "telescope",
            "User-Agent": "KilonovaScout/3.0",
        }
        return urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=str(payload.get("text", "")).encode("utf-8"),
            headers=headers, method="POST",
        )
    headers = {"Content-Type": "application/json",
               "User-Agent": "KilonovaScout/3.0"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )


def maybe_notify(record: Any) -> bool:
    """POST the alert if ALERT_WEBHOOK_URL is configured. Never raises."""
    url = (os.getenv("ALERT_WEBHOOK_URL", "") or "").strip()
    if not url or record is None:
        return False
    try:
        secret = (os.getenv("ALERT_WEBHOOK_SECRET", "") or "").strip()
        req = _build_request(url, build_alert_payload(record), secret)
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
        print(f"[ALERT] webhook {'delivered' if ok else 'rejected'} "
              f"for run {_get_dict_attr(record, 'run_id')}")
        return bool(ok)
    except Exception as exc:
        print(f"[ALERT] webhook failed ({exc})")
        return False
