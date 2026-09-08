"""check_notifier.py - Verification for the outbound webhook notifier.

Covers: alert payload content (pure function), env-gated no-op without a
URL, and graceful failure on unreachable endpoints. Never sends a real
alert (no URL is configured in this environment).

Run:  python scripts/check_notifier.py
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from backend.notifier import build_alert_payload, maybe_notify

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def rec():
    return SimpleNamespace(
        run_id="live-1", source="live", status="completed",
        event={"ivorn": "ivo://gwnet/LVC#S1-Initial", "trigger_id": "S1",
               "event_class": "bns", "class_label": "Neutron-star merger",
               "gate_status": "ACCEPTED", "gate_reason": "HasNS = 0.98",
               "gate_confidence": 0.95},
        provenance={"skymap": "live", "catalog": "cached", "event": "live",
                    "weather": "live"},
        candidates=[{"name": "NGC 4993", "composite_score": 1.23,
                     "distance_mpc": 40.0, "catalog_source": "cached"}],
        weather={"observatory_name": "Palomar", "dome_safe": True},
        llm_rationale=None, slew_script=None, steps=[],
        observation_header=None, visualizations=None,
    )


p = build_alert_payload(rec())
check("headline names event + top target",
      "S1" in p["text"] and "NGC 4993" in p["text"], p["text"])
check("report path present", p["report_path"] == "/api/runs/live-1/report", p["report_path"])
check("gate + provenance carried",
      p["gate"]["status"] == "ACCEPTED" and p["provenance"]["skymap"] == "live")
check("empty candidates safe",
      build_alert_payload(rec()).get("candidates") == 1)

os.environ.pop("ALERT_WEBHOOK_URL", None)
check("no URL -> silent no-op", maybe_notify(rec()) is False)

os.environ["ALERT_WEBHOOK_URL"] = "http://127.0.0.1:9/unroutable-hook"
check("unreachable URL fails gracefully", maybe_notify(rec()) is False)
os.environ.pop("ALERT_WEBHOOK_URL", None)

from backend.notifier import _build_request

ntfy_req = _build_request("https://ntfy.sh/kilonova-test-topic-xyz",
                          build_alert_payload(rec()), "wrong-secret-ignored")
check("ntfy posts plain text, not JSON",
      ntfy_req.full_url == "https://ntfy.sh/kilonova-test-topic-xyz"
      and b"KilonovaScout" in ntfy_req.data
      and b'"run_id"' not in ntfy_req.data)
check("ntfy urgent priority with candidates",
      ntfy_req.get_header("Priority") == "4"
      and ntfy_req.get_header("Title") == "KilonovaScout follow-up alert"
      and "telescope" in (ntfy_req.get_header("Tags") or ""))
check("ntfy skips bearer (public topic would 401)",
      ntfy_req.get_header("Authorization") is None)

json_req = _build_request("https://discord.com/api/webhooks/abc",
                          build_alert_payload(rec()), "s3cret")
check("generic webhook keeps JSON + bearer",
      json.loads(json_req.data)["run_id"] == "live-1"
      and json_req.get_header("Authorization") == "Bearer s3cret"
      and json_req.get_header("Content-type") == "application/json")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
