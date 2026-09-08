"""check_gracedb_poller.py - Verification for the GraceDB REST poller.

Part 1 (offline, stdlib): selection rules, flat-map picker, VOEvent picker.
Part 2 (live, read-only): fetch the real superevent list, run discovery,
download one real VOEvent XML and parse it with the production parser.
No side effects: nothing is fired, nothing is written.

Run:  python scripts/check_gracedb_poller.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from backend.gracedb_poller import (
    is_significant_candidate,
    select_new_triggers,
    pick_flat_skymap,
    pick_latest_voevent,
)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


NOW = time.time()
FAR = 3.17e-8


def se(sid, **kw):
    d = {"superevent_id": sid, "category": "Production",
         "labels": ["SIGNIF_LOCKED", "EM_READY"], "far": 1e-9,
         "t_0": NOW - 3600}
    d.update(kw)
    return d


print("== selection rules ==")
check("significant accepted", is_significant_candidate(se("S1"), FAR, 48, NOW)[0])
check("MDC category rejected", not is_significant_candidate(se("S2", category="MDC"), FAR, 48, NOW)[0])
check("no SIGNIF_LOCKED rejected",
      not is_significant_candidate(se("S3", labels=["EM_READY"]), FAR, 48, NOW)[0])
check("high FAR rejected", not is_significant_candidate(se("S4", far=1e-5), FAR, 48, NOW)[0])
check("stale rejected", not is_significant_candidate(se("S5", t_0=NOW - 200 * 3600), FAR, 48, NOW)[0])

print("== dedup ==")
listing = {"superevents": [se("A"), se("B"), se("C", far=1.0)]}
new, seen = select_new_triggers(listing, set(), far_hz=FAR, lookback_h=48, now=NOW)
check("two new significant", sorted(n["superevent_id"] for n in new) == ["A", "B"], str(new))
new2, _ = select_new_triggers(listing, seen, far_hz=FAR, lookback_h=48, now=NOW)
check("second pass quiet", new2 == [], str(new2))
check("seen capped type", isinstance(seen, set) and {"A", "B", "C"} <= seen)

print("== flat map picker ==")
files = {"bayestar.multiorder.fits": "u1", "bayestar.fits.gz": "u2", "em_bright.json": "u3"}
check("prefers flat bayestar", pick_flat_skymap(files) == "u2")
check("multiorder excluded", pick_flat_skymap({"bayestar.multiorder.fits": "u1"}) is None)
check("empty -> None", pick_flat_skymap({}) is None)

print("== voevent picker ==")
vl = {"voevents": [
    {"voevent_type": "PR", "N": 1},
    {"voevent_type": "RT", "N": 9},
    {"voevent_type": "UP", "N": 3},
    {"voevent_type": "IN", "N": 2},
]}
check("latest non-RT wins", pick_latest_voevent(vl)["N"] == 3)
check("all-RT -> None", pick_latest_voevent({"voevents": [{"voevent_type": "RT", "N": 1}]}) is None)

print("== live read-only discovery ==")
try:
    import requests
    from backend.gcn_listener import _parse_voevent_xml

    listing = requests.get("https://gracedb.ligo.org/api/superevents/", timeout=25).json()
    n_total = len(listing.get("superevents", []))
    new, _ = select_new_triggers(listing, set(), far_hz=FAR, lookback_h=24 * 30)
    print(f"  info {n_total} recent superevents listed; {len(new)} significant+fresh (30d lookback)")
    check("live list fetched", n_total > 0)

    # Parse one REAL VOEvent XML with the production parser.
    xml = requests.get(
        "https://gracedb.ligo.org/api/v2/superevents/S230518h/files/S230518h-2-Initial.xml,0",
        timeout=25).content
    v = _parse_voevent_xml(xml, topic="gcn.live.gracedb-probe")
    check("real VOEvent parses", v is not None and "S230518h" in (v.ivorn or ""))
    check("real VOEvent has skymap url",
          bool((v.wherewhen or {}).get("skymap_url")), str((v.wherewhen or {}).keys()))
except Exception as exc:
    FAIL += 1
    print(f"  FAIL live discovery ({exc})")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
