"""fetch_historical_bns.py — Refresh/validate BNS entries in the historical corpus.

Reads src/backend/data/historical_events.json, checks every ``bns`` entry for
schema completeness, and (best-effort, offline-safe) HEADs each official
``skymap_url`` on GraceDB. Unreachable URLs are REPORTED, never deleted: the
pipeline's FITS fallback chain (live → bundled replay) handles dead links
honestly at analysis time.

Usage:
    py scripts/fetch_historical_bns.py
    py scripts/fetch_historical_bns.py --add S200115j  # append skeleton entry

Official source: https://gracedb.ligo.org/superevents/<ID>/view/
GraceDB file downloads may require credentials; the corpus stores the
canonical URL pattern and the pipeline attempts it at analysis time.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "src", "backend", "data", "historical_events.json")

REQUIRED = ["event_id", "event_class", "trigger_time", "distance_mpc",
            "skymap_url", "alert_properties", "source", "year", "official_ref"]


def load():
    with open(CORPUS, "r", encoding="utf-8") as f:
        return json.load(f)


def save(events):
    with open(CORPUS, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
        f.write("\n")


def head_ok(url, timeout=10):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except Exception as exc:
        print(f"  [warn] {url} unreachable ({exc})")
        return False


def main():
    args = sys.argv[1:]
    events = load()
    if "--add" in args:
        idx = args.index("--add")
        for sid in args[idx + 1:]:
            if sid.startswith("-"):
                break
            if any(e.get("event_id") == sid for e in events):
                print(f"  [skip] {sid} already in corpus")
                continue
            events.append({
                "event_id": sid,
                "event_class": "bns",
                "trigger_time": "YYYY-MM-DDTHH:MM:SSZ",
                "ra_deg": None, "dec_deg": None, "error_radius_deg": None,
                "distance_mpc": None,
                "skymap_url": f"https://gracedb.ligo.org/api/superevents/{sid}/files/Bayestar.fits.gz",
                "alert_properties": {"BNS": None, "HasNS": None},
                "source": "gracedb",
                "year": None,
                "official_ref": f"https://gracedb.ligo.org/superevents/{sid}/view/",
            })
            print(f"  [add] skeleton for {sid} — fill trigger_time/distance/year from the official page")
        save(events)
        return 0
    bns = [e for e in events if e.get("event_class") == "bns"]
    print(f"BNS entries: {len(bns)}")
    problems = 0
    for e in bns:
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            print(f"  [schema] {e.get('event_id')}: missing {missing}")
            problems += 1
        url = e.get("skymap_url")
        if url:
            ok = head_ok(url)
            print(f"  [{'ok' if ok else 'dead-link (fallback covers it)'}] {e.get('event_id')}: {url}")
    print(f"done ({problems} schema problems). Corpus unchanged (validation only).")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
