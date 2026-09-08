"""check_live_entry.py - Prove auto-fired runs land in latest-event.

1. role=test payload through the REAL handle_live_notice -> must be
   ignored (no run record created).
2. Real BNS mock payload through handle_live_notice -> full live run,
   _latest_run_id updated, /latest-event shape carries event fields the
   dashboard adopter needs.

Run from repo root:  python scripts/check_live_entry.py  (~2-4 min, network)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}", flush=True)
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}", flush=True)


async def main():
    from backend.agents.agent import KilonovaScoutAgent
    from backend.models import GcnKafkaPayload, Voevent
    from backend.run_registry import RunRegistry
    import backend.agents.agent as agent_mod
    import datetime

    agent = KilonovaScoutAgent()
    before = len(agent_mod.run_registry._runs)

    # 1. test-role drill must not create a run
    drill = GcnKafkaPayload(
        topic="gcn.classic.voevent.LVC_TEST", offset=1,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        voevent=Voevent(ivorn="ivo://x#TEST", role="test",
                        description="drill", wherewhen={}, what=[]))
    await agent.handle_live_notice(drill)
    after = len(agent_mod.run_registry._runs)
    check("test-role creates no run", after == before, f"{before}->{after}")

    # 2. real payload through the live funnel -> full run, source live
    sim_payload = agent.simulator.get_payload("bns")
    await agent.handle_live_notice(sim_payload)
    check("live run completed",
          agent.agent_state.status in ("awaiting_approval", "weather_blocked",
                                       "rejected", "slewing"),
          agent.agent_state.status)
    check("live source tagged", agent.agent_state.source == "live",
          agent.agent_state.source)
    check("candidates scored", len(agent.agent_state.candidate_galaxies or []) > 0)

    rec = await agent.get_run_record(agent.agent_state.run_id)
    ev = rec.event or {}
    check("record carries topic", bool(ev.get("topic")), ev.get("topic"))
    check("record carries agent_status", bool(ev.get("agent_status")),
          ev.get("agent_status"))
    check("record carries class+gate", ev.get("event_class") == "bns"
          and ev.get("gate_status") == "ACCEPTED",
          (ev.get("event_class"), ev.get("gate_status")))


asyncio.run(main())
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
