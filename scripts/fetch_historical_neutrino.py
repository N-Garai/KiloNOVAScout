"""fetch_historical_neutrino.py — Refresh/validate neutrino entries in the corpus.

Reads src/backend/data/historical_events.json and checks every ``neutrino``
entry for schema completeness. Neutrino follow-up needs no FITS download
(the pipeline builds a point-map from the track direction), so validation
focuses on the direction + signalness that drive the analysis.

Usage:
    py scripts/fetch_historical_neutrino.py
    py scripts/fetch_historical_neutrino.py --add IC211208A  # append skeleton

Official sources: NASA GCN archive (https://gcn.nasa.gov) and
IceCube data releases (https://icecube.wisc.edu/data-releases).
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "src", "backend", "data", "historical_events.json")

REQUIRED = ["event_id", "event_class", "trigger_time", "ra_deg", "dec_deg",
            "error_radius_deg", "alert_properties", "source", "year", "official_ref"]
PROPS = ["Signalness", "Angular_Error"]


def load():
    with open(CORPUS, "r", encoding="utf-8") as f:
        return json.load(f)


def save(events):
    with open(CORPUS, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
        f.write("\n")


def main():
    args = sys.argv[1:]
    events = load()
    if "--add" in args:
        idx = args.index("--add")
        for nid in args[idx + 1:]:
            if nid.startswith("-"):
                break
            if any(e.get("event_id") == nid for e in events):
                print(f"  [skip] {nid} already in corpus")
                continue
            events.append({
                "event_id": nid,
                "event_class": "neutrino",
                "trigger_time": "YYYY-MM-DDTHH:MM:SSZ",
                "ra_deg": None, "dec_deg": None, "error_radius_deg": 2.0,
                "distance_mpc": None,
                "skymap_url": None,
                "alert_properties": {"Signalness": None, "Angular_Error": None},
                "source": "icecube",
                "year": None,
                "official_ref": "https://gcn.nasa.gov",
            })
            print(f"  [add] skeleton for {nid} — fill direction/trigger_time/year from the GCN archive")
        save(events)
        return 0
    nus = [e for e in events if e.get("event_class") == "neutrino"]
    print(f"Neutrino entries: {len(nus)}")
    problems = 0
    for e in nus:
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            print(f"  [schema] {e.get('event_id')}: missing {missing}")
            problems += 1
        props = e.get("alert_properties") or {}
        missing_p = [p for p in PROPS if p not in props]
        if missing_p:
            print(f"  [props] {e.get('event_id')}: missing track props {missing_p}")
            problems += 1
        if e.get("ra_deg") is None or e.get("dec_deg") is None:
            print(f"  [position] {e.get('event_id')}: no direction — point-map needs RA/Dec")
            problems += 1
    print(f"done ({problems} problems). Corpus unchanged (validation only).")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
