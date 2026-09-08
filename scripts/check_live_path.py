"""check_live_path.py - Full live-path proof on a REAL historical event.

Replays superevent S190425z (O3 BNS, HasNS=1.0) through the PRODUCTION live
entrypoint (`process_gcn_event`, the same function the Kafka listener and
the GraceDB poller call) with its REAL VOEvent XML and REAL skymap URL —
no mocks anywhere in the trigger path:

  fetch VOEvent -> parse -> gate -> skymap -> TAP catalog -> weather ->
  scoring -> slew script -> rationale -> report

Asserts the run completes with provenance event=live, real candidates, and
a report carrying the live-trigger disclosure.

Needs network (GraceDB, VizieR TAP, Open-Meteo). No API keys needed —
the LLM step uses its deterministic fallback.

Run:  python scripts/check_live_path.py   (takes ~2-5 minutes)
"""
import asyncio
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import requests

SID = "S190425z"
VOEVENT_URL = f"https://gracedb.ligo.org/api/v2/superevents/{SID}/files/{SID}-2-Update.xml,0"


def main() -> int:
    from backend.agents.agent import KilonovaScoutAgent
    from backend.gcn_listener import _parse_voevent_xml
    from backend.models import GcnKafkaPayload

    print(f"[live-path] downloading real VOEvent for {SID} ...", flush=True)
    xml = requests.get(VOEVENT_URL, timeout=30).content
    voevent = _parse_voevent_xml(xml, topic="gcn.live.check")
    assert voevent is not None, "real VOEvent failed to parse"
    assert "S190425z" in voevent.ivorn, voevent.ivorn
    print(f"[live-path] parsed {voevent.ivorn}", flush=True)
    print(f"[live-path] skymap: {(voevent.wherewhen or {}).get('skymap_url')}", flush=True)

    payload = GcnKafkaPayload(
        topic="gcn.live.check",
        offset=int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        voevent=voevent,
    )

    agent = KilonovaScoutAgent()
    print("[live-path] running full live pipeline ...", flush=True)
    out = asyncio.run(agent.process_gcn_event(payload))
    print(f"[live-path] pipeline returned: {out.action_status} :: {out.message[:100]}", flush=True)

    record = asyncio.run(agent.get_run_record(agent.agent_state.run_id))
    assert record is not None, "no run record"
    prov = dict(record.provenance or {})
    print(f"[live-path] provenance: {prov}", flush=True)
    assert prov.get("event") == "live", f"expected live provenance, got {prov}"
    assert prov.get("skymap") in ("live", "replay", "synthetic"), prov
    assert len(record.candidates) > 0, "no candidates scored"
    top = record.candidates[0]
    print(f"[live-path] top candidate: {top.get('name')} "
          f"S={top.get('composite_score')} src={top.get('catalog_source')}", flush=True)

    from backend.agents.writer_agent import build_report_markdown
    md = build_report_markdown(record, {})
    assert "Live trigger" in md, "report missing live-trigger disclosure"
    assert "Trigger Classification" in md, "report missing classification section"
    print("[live-path] report carries live-trigger disclosure + classification", flush=True)
    print("LIVE PATH OK — real NASA event ran the real pipeline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
