"""fetch_historical_grb.py — Refresh/validate GRB entries in the historical corpus.

Reads src/backend/data/historical_events.json and checks every ``grb`` entry
for schema completeness. GRB follow-up needs no FITS download (the pipeline
builds a point-map from the notice position), so validation focuses on the
position + burst properties that drive the analysis.

Usage:
    py scripts/fetch_historical_grb.py
    py scripts/fetch_historical_grb.py --add GRB230307A  # append skeleton entry

Official source: Fermi GBM Burst Catalog,
https://heasarc.gsfc.nasa.gov/dbase/grb/fermigbrst.html
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "src", "backend", "data", "historical_events.json")

REQUIRED = ["event_id", "event_class", "trigger_time", "ra_deg", "dec_deg",
            "error_radius_deg", "alert_properties", "source", "year", "official_ref"]
PROPS = ["T90", "Fluence", "Peak_Flux"]


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
        for gid in args[idx + 1:]:
            if gid.startswith("-"):
                break
            if any(e.get("event_id") == gid for e in events):
                print(f"  [skip] {gid} already in corpus")
                continue
            events.append({
                "event_id": gid,
                "event_class": "grb",
                "trigger_time": "YYYY-MM-DDTHH:MM:SSZ",
                "ra_deg": None, "dec_deg": None, "error_radius_deg": 3.0,
                "distance_mpc": None,
                "skymap_url": None,
                "alert_properties": {"T90": None, "Fluence": None, "Peak_Flux": None},
                "source": "fermi_gbm",
                "year": None,
                "official_ref": "https://heasarc.gsfc.nasa.gov/dbase/grb/fermigbrst.html",
            })
            print(f"  [add] skeleton for {gid} — fill position/trigger_time/year from the GBM catalog")
        save(events)
        return 0
    grbs = [e for e in events if e.get("event_class") == "grb"]
    print(f"GRB entries: {len(grbs)}")
    problems = 0
    for e in grbs:
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            print(f"  [schema] {e.get('event_id')}: missing {missing}")
            problems += 1
        props = e.get("alert_properties") or {}
        missing_p = [p for p in PROPS if p not in props]
        if missing_p:
            print(f"  [props] {e.get('event_id')}: missing burst props {missing_p}")
            problems += 1
        if e.get("ra_deg") is None or e.get("dec_deg") is None:
            print(f"  [position] {e.get('event_id')}: no RA/Dec — point-map needs a position")
            problems += 1
    print(f"done ({problems} problems). Corpus unchanged (validation only).")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
