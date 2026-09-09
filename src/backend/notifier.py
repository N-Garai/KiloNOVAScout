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
import smtplib
import threading
import time
import urllib.request
from email.message import EmailMessage
from typing import Any, Callable, Dict, List, Optional


def _get_dict_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Runtime preference overlay: the dashboard settings form writes here so
# operators can change notification behavior without a restart or redeploy.
# Every read falls back to the environment (Render dashboard / .env), so
# keys never touched in the UI behave exactly as before.
_RUNTIME_PREFS: Dict[str, str] = {}

# Config keys the UI may manage (secrets handled separately — see below).
PREF_KEYS = (
    "ALERT_WEBHOOK_URL", "ALERT_WEBHOOK_SECRET", "ALERT_LIVE_ONLY",
    "DIGEST_ENABLED", "DIGEST_HOUR_UTC",
    "DIGEST_SMTP_HOST", "DIGEST_SMTP_PORT", "DIGEST_SMTP_USER",
    "DIGEST_SMTP_PASS", "DIGEST_FROM", "DIGEST_TO",
)

# Suffixes treated as secrets: never echoed back, only overwritten by
# non-empty input (protects saved values from blank form resubmits).
_SECRET_SUFFIXES = ("_SECRET", "_PASS", "_TOKEN", "_KEY")


def _is_secret_key(key: str) -> bool:
    return key.upper().endswith(_SECRET_SUFFIXES)


def get_setting(key: str, default: str = "") -> str:
    """Read a notification preference: runtime overlay first, env fallback."""
    if key in _RUNTIME_PREFS:
        return _RUNTIME_PREFS[key]
    return (os.getenv(key, "") or "").strip() or default


def set_runtime_prefs(mapping: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Store UI-submitted preferences (pure logic, unit-testable).

    Secret keys update only on non-empty input so a masked echo-back
    ("" or "***") can never wipe a saved credential.  All other known keys
    update whenever present.  Unknown keys are ignored.  Returns the full
    effective snapshot with secrets masked for safe display.
    """
    for key, value in (mapping or {}).items():
        if key not in PREF_KEYS:
            continue
        text = "" if value is None else str(value).strip()
        if _is_secret_key(key):
            if text and text != "***":
                _RUNTIME_PREFS[key] = text
        else:
            _RUNTIME_PREFS[key] = text
    return masked_snapshot()


def masked_snapshot() -> Dict[str, str]:
    """Effective preferences with every secret blanked (safe for GET)."""
    out: Dict[str, str] = {}
    for key in PREF_KEYS:
        if _is_secret_key(key):
            out[key] = ""
        else:
            out[key] = get_setting(key)
    return out


def _live_only() -> bool:
    return get_setting("ALERT_LIVE_ONLY").lower() in ("1", "true", "yes")


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
    report_path = f"/api/runs/{_get_dict_attr(record, 'run_id')}/report"
    # Absolute link when the public base URL is known (Render injects
    # RENDER_EXTERNAL_URL): a relative path is useless inside a phone
    # notification, so prefer the clickable form and keep the path too.
    base = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    report_url = f"{base}{report_path}" if base else report_path
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
        "report_path": report_path,
        "report_url": report_url,
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


def _live_only() -> bool:
    return get_setting("ALERT_LIVE_ONLY").lower() in ("1", "true", "yes")


def maybe_notify(record: Any) -> bool:
    """POST the alert if ALERT_WEBHOOK_URL is configured. Never raises.

    With ALERT_LIVE_ONLY=true, mock/demo runs are skipped silently so the
    on-call human is woken only by genuine triggers.
    """
    url = get_setting("ALERT_WEBHOOK_URL")
    if not url or record is None:
        return False
    if _live_only() and _get_dict_attr(record, "source") != "live":
        print(f"[ALERT] skipped mock run {_get_dict_attr(record, 'run_id')} (ALERT_LIVE_ONLY)")
        return False
    try:
        secret = get_setting("ALERT_WEBHOOK_SECRET")
        req = _build_request(url, build_alert_payload(record), secret)
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
        print(f"[ALERT] webhook {'delivered' if ok else 'rejected'} "
              f"for run {_get_dict_attr(record, 'run_id')}")
        return bool(ok)
    except Exception as exc:
        print(f"[ALERT] webhook failed ({exc})")
        return False


def _smtp_config() -> Optional[Dict[str, Any]]:
    """Read digest SMTP settings; None when incompletely configured."""
    host = get_setting("DIGEST_SMTP_HOST")
    user = get_setting("DIGEST_SMTP_USER")
    # Google displays App Passwords grouped with spaces ("abcd efgh ijkl
    # mnop"); SMTP login wants the bare 16 letters, so all whitespace is
    # stripped. Real passwords never legitimately need surrounding space.
    password = "".join(get_setting("DIGEST_SMTP_PASS").split())
    to_raw = get_setting("DIGEST_TO")
    if not (host and user and password and to_raw):
        return None
    try:
        port = int(get_setting("DIGEST_SMTP_PORT", "465") or 465)
    except (TypeError, ValueError):
        port = 465
    recipients = [t.strip() for t in to_raw.replace(";", ",").split(",") if t.strip()]
    if not recipients:
        return None
    return {
        "host": host, "port": port, "user": user, "password": password,
        "from_addr": get_setting("DIGEST_FROM") or user,
        "to": recipients,
    }


def _report_link(run_id: Any) -> str:
    base = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    path = f"/api/runs/{run_id}/report"
    return f"{base}{path}" if base else path


def build_digest_message(records: List[Any], sender: str = "KilonovaScout") -> EmailMessage:
    """Build the daily digest mail (pure constructor, unit-testable).

    Lists every retained run from the window with status, top candidate and
    report link; a quiet period still sends, explicitly saying so, so silence
    is distinguishable from a broken scheduler.
    """
    lines = [
        f"{sender} daily digest — {len(records)} run(s) in the last 24 hours",
        "",
    ]
    if not records:
        lines.append("Quiet sky: no pipeline runs were recorded in this window.")
    for rec in records:
        event = _get_dict_attr(rec, "event", {}) or {}
        prov = _get_dict_attr(rec, "provenance", {}) or {}
        cands = _get_dict_attr(rec, "candidates", []) or []
        top = cands[0] if cands else {}
        rid = _get_dict_attr(rec, "run_id", "?")
        lines.append(
            f"- [{_get_dict_attr(rec, 'status', '?')}] "
            f"{event.get('class_label') or event.get('event_class') or 'event'} "
            f"{event.get('trigger_id') or event.get('ivorn') or ''} "
            f"(source={_get_dict_attr(rec, 'source', '?')}, "
            f"skymap={prov.get('skymap', '?')}, catalog={prov.get('catalog', '?')})")
        if top:
            lines.append(
                f"    top: {top.get('name')} "
                f"(S={top.get('composite_score')}, {top.get('distance_mpc')} Mpc)")
        lines.append(f"    report: {_report_link(rid)}")
    lines += ["", "--", "Turn this off with DIGEST_ENABLED=false."]
    msg = EmailMessage()
    n_live = sum(1 for r in records if _get_dict_attr(r, "source") == "live")
    msg["Subject"] = (f"[{sender}] daily digest: {len(records)} runs"
                      + (f" ({n_live} live)" if n_live else " (all quiet/demo)"))
    msg.set_content("\n".join(lines))
    return msg


def should_send_digest(now_utc: datetime.datetime, last_sent_iso: Optional[str],
                       enabled: bool, hour: int) -> bool:
    """True once per UTC day when the scheduled hour has passed (pure)."""
    if not enabled:
        return False
    if now_utc.hour < hour:
        return False
    if not last_sent_iso:
        return True
    try:
        last = datetime.datetime.fromisoformat(last_sent_iso)
        if last.tzinfo is None:
            last = last.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return True
    return last.date() < now_utc.date()


def send_digest_email(records: List[Any]) -> bool:
    """Send the digest if fully configured. Never raises."""
    cfg = _smtp_config()
    if not cfg:
        print("[DIGEST] not configured (need DIGEST_SMTP_HOST/USER/PASS/TO); skipping")
        return False
    try:
        msg = build_digest_message(records)
        msg["From"] = cfg["from_addr"]
        msg["To"] = ", ".join(cfg["to"])
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        print(f"[DIGEST] sent to {len(cfg['to'])} recipient(s), {len(records)} run(s)")
        return True
    except Exception as exc:
        print(f"[DIGEST] send failed ({exc})")
        return False


def _digest_hour() -> int:
    try:
        return max(0, min(23, int(get_setting("DIGEST_HOUR_UTC", "6") or 6)))
    except (TypeError, ValueError):
        return 6


def digest_status() -> Dict[str, Any]:
    """Operator-facing digest state (safe to expose: no secrets included)."""
    cfg = _smtp_config()
    return {
        "enabled": get_setting("DIGEST_ENABLED").lower() in ("1", "true", "yes"),
        "hour_utc": _digest_hour(),
        "configured": cfg is not None,
        "recipients": len(cfg["to"]) if cfg else 0,
        "webhook_set": bool(get_setting("ALERT_WEBHOOK_URL")),
        "live_only": _live_only(),
    }


def start_digest(fetch_recent: Callable[[float], List[Any]],
                 stop_event: threading.Event) -> None:
    """Daily digest scheduler loop (runs in its own daemon thread).

    Wakes every 10 minutes; once per UTC day after DIGEST_HOUR_UTC it mails
    the last 24 h of retained runs.  All failures are logged, never raised —
    a dead mail server must not take down the agent.
    """
    last_sent: Optional[str] = None
    while not stop_event.is_set():
        try:
            enabled = get_setting("DIGEST_ENABLED").lower() in ("1", "true", "yes")
            now = datetime.datetime.now(datetime.timezone.utc)
            if should_send_digest(now, last_sent, enabled, _digest_hour()):
                records = fetch_recent(24.0) or []
                if send_digest_email(records):
                    last_sent = now.isoformat()
        except Exception as exc:
            print(f"[DIGEST] cycle failed ({exc})")
        stop_event.wait(600.0)
