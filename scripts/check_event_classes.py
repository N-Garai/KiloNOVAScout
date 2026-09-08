"""check_event_classes.py - Executable verification for the event-class system.

Stdlib only. Run:  python scripts/check_event_classes.py
Covers: param harvesting (all 3 shapes), all three gates incl. REJECT paths,
flux_proxy anchors, per-class profiles, topic mapping, enablement parsing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from backend.event_classes import (
    harvest_params,
    evaluate_trigger,
    flux_proxy,
    get_profile,
    class_for_topic,
    enabled_classes,
    topics_for,
    PROFILES,
    ALL_CLASSES,
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


print("== harvest_params ==")
live = [{"name": "BNS", "value": "0.9"}, {"name": "FAR", "value": "1e-9"}]
check("live name/value shape", harvest_params(live) == {"bns": "0.9", "far": "1e-9"})
mock = [{"far": 1.2e-9, "properties": {"BNS": 0.95, "HasNS": 0.98}}]
h = harvest_params(mock)
check("mock properties shape", h.get("bns") == 0.95 and h.get("hasns") == 0.98 and h.get("far") == 1.2e-9)
check("empty/None safe", harvest_params(None) == {} and harvest_params([None, "x"]) == {})

print("== bns gate ==")
r = evaluate_trigger("bns", [{"far": 1.2e-9, "properties": {"BNS": 0.95, "NSBH": 0.03, "BBH": 0.01, "Terrestrial": 0.01, "HasNS": 0.98}}])
check("GW170817 accepted", r["status"] == "ACCEPTED", str(r))
check("GW170817 subclass", r["subclass"] == "bns", str(r))
r = evaluate_trigger("bns", [{"properties": {"BNS": 0.01, "NSBH": 0.0, "BBH": 0.97, "Terrestrial": 0.02, "HasNS": 0.0}}])
check("BBH rejected", r["status"] == "REJECTED" and r["subclass"] == "bbh", str(r))
r = evaluate_trigger("bns", [{"properties": {"Terrestrial": 0.9}}])
check("terrestrial rejected", r["status"] == "REJECTED", str(r))
r = evaluate_trigger("bns", [])
check("missing params accept-unclassified", r["status"] == "ACCEPTED" and r["confidence"] == 0.5, str(r))
r = evaluate_trigger("bns", [{"name": "HasNS", "value": "0.7"}, {"name": "FAR", "value": "1e-10"}])
check("live-shape HasNS accepted", r["status"] == "ACCEPTED" and r["subclass"] in ("bns", "nsbh"), str(r))

print("== grb gate ==")
r = evaluate_trigger("grb", [{"name": "T90", "value": "0.8"}, {"name": "Fluence", "value": "2.4e-7"}])
check("short GRB accepted", r["status"] == "ACCEPTED" and r["subclass"] == "short" and r["confidence"] == 0.9, str(r))
r = evaluate_trigger("grb", [{"name": "T90", "value": "30"}, {"name": "Fluence", "value": "5e-6"}])
check("bright long GRB accepted", r["status"] == "ACCEPTED" and r["subclass"] == "long-bright", str(r))
r = evaluate_trigger("grb", [{"name": "T90", "value": "30"}])
check("faint long GRB low-confidence accept", r["status"] == "ACCEPTED" and r["confidence"] == 0.55, str(r))
r = evaluate_trigger("grb", [])
check("unclassified GRB proceeds", r["status"] == "ACCEPTED" and r["confidence"] == 0.5, str(r))

print("== neutrino gate ==")
r = evaluate_trigger("neutrino", [{"name": "Signalness", "value": "0.65"}])
check("gold accepted", r["status"] == "ACCEPTED" and r["subclass"] == "gold", str(r))
r = evaluate_trigger("neutrino", [{"name": "signalness", "value": "0.35"}])
check("bronze accepted", r["status"] == "ACCEPTED" and r["subclass"] == "bronze", str(r))
r = evaluate_trigger("neutrino", [{"name": "signalness", "value": "0.1"}])
check("sub-threshold rejected", r["status"] == "REJECTED", str(r))

print("== flux_proxy ==")
check("anchor fluence 1e-6 -> 1.0", flux_proxy(fluence=1e-6) == 1.0, str(flux_proxy(fluence=1e-6)))
check("decade above -> 1.5", flux_proxy(fluence=1e-5) == 1.5, str(flux_proxy(fluence=1e-5)))
check("anchor peak flux 1.0 -> 1.0", flux_proxy(peak_flux=1.0) == 1.0)
check("clamped at 3.0", flux_proxy(fluence=1.0) == 3.0, str(flux_proxy(fluence=1.0)))
check("none -> 0.0", flux_proxy() == 0.0)
check("GRB170817A-like faint -> ~0.7", abs(flux_proxy(fluence=2.4e-7) - 0.69) < 0.01, str(flux_proxy(fluence=2.4e-7)))

print("== profiles ==")
for k in ALL_CLASSES:
    p = get_profile(k)
    check(f"{k} has 9 engine weights", set(p["weights"]) == {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "kappa"}, str(sorted(p["weights"])))
    check(f"{k} has formula+strategy", bool(p["formula"]) and bool(p["strategy"]))
    check(f"{k} has latex formula", "S_i" in p.get("formula_tex", ""), str(p.get("formula_tex", "")[:40]))
check("bns keeps validator", get_profile("bns")["needs_validator"] is True)
check("grb drops host+validator", get_profile("grb")["weights"]["beta"] == 0.0 and get_profile("grb")["needs_validator"] is False)
check("neutrino signalness weight", get_profile("neutrino")["weights"]["kappa"] == 1.5)
check("unknown class falls back to bns", get_profile("quasar")["formula"] == PROFILES["bns"]["formula"])

print("== topics/enablement ==")
check("LVC topic -> bns", class_for_topic("gcn.classic.voevent.LVC_INITIAL") == "bns")
check("GBM topic -> grb", class_for_topic("gcn.classic.voevent.FERMI_GBM_FIN_POS") == "grb")
check("IceCube topic -> neutrino", class_for_topic("gcn.classic.voevent.ICECUBE_ASTROTRACK_GOLD") == "neutrino")
check("Swift BAT position topic -> grb",
      class_for_topic("gcn.classic.voevent.SWIFT_BAT_GRB_POS_ACK") == "grb")
check("Swift XRT topic -> grb",
      class_for_topic("gcn.classic.voevent.SWIFT_XRT_POSITION") == "grb")
from backend.event_classes import CLASS_TOPICS
check("no SWIFT_BAT_ALERT phantom topic",
      not any("SWIFT_BAT_ALERT" in t for ts in CLASS_TOPICS.values() for t in ts))
check("GBM ground refinement subscribed",
      "gcn.classic.voevent.FERMI_GBM_GND_POS" in CLASS_TOPICS["grb"])
check("AMON neutrino streams subscribed",
      "gcn.classic.voevent.AMON_ICECUBE_EHE" in CLASS_TOPICS["neutrino"]
      and "gcn.classic.voevent.AMON_ICECUBE_HESE" in CLASS_TOPICS["neutrino"])
check("AMON EHE maps to neutrino",
      class_for_topic("gcn.classic.voevent.AMON_ICECUBE_EHE") == "neutrino")
check("GBM GND maps to grb",
      class_for_topic("gcn.classic.voevent.FERMI_GBM_GND_POS") == "grb")
check("unknown topic -> bns default", class_for_topic("gcn.classic.text.SOMETHING") == "bns")
os.environ.pop("ALERT_CLASSES", None)
check("env default all three", enabled_classes() == ["bns", "grb", "neutrino"], str(enabled_classes()))
check("env subset parsed", enabled_classes("grb,neutrino") == ["grb", "neutrino"])
check("env junk ignored", enabled_classes("bns,quasar,,") == ["bns"])
ts = topics_for(["bns", "grb"])
check("topics flattened deduped", len(ts) == len(set(ts)) and any("LVC" in t for t in ts) and any("GBM" in t for t in ts))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
