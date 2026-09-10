"""em_bright.py — EM-bright fetcher skill (M13).

Pulls em_bright.json distance prior from GraceDB for tighter dist_mean.
"""

from __future__ import annotations

from . import Skill


class EMBrightSkill(Skill):
    name = "em_bright_fetcher"
    description = "Fetch GraceDB em_bright.json for tighter distance prior."

    def run(self, superevent_id: str):
        try:
            import requests
            # superevent_id is the IVORN suffix or S-identifier, e.g. S190425z
            sid = (superevent_id or "").split("/")[-1].split("#")[-1]
            # Normalize to GraceDB S-id if ivorn contains it
            if not sid.startswith("S"):
                return {"fetched": False, "note": "No GraceDB S-id in ivorn — skipping em_bright fetch."}
            url = f"https://gracedb.ligo.org/api/superevents/{sid}/files/em_bright.json"
            resp = requests.get(url, timeout=8)
            if resp.status_code == 404:
                return {"fetched": False, "note": f"em_bright.json not found for {sid}"}
            resp.raise_for_status()
            data = resp.json()
            return {"fetched": True, "data": data, "note": f"em_bright fetched for {sid}: HasNS={data.get('HasNS')}, HasRemnant={data.get('HasRemnant')}"}
        except Exception as e:
            return {"fetched": False, "note": f"em_bright fetch failed: {e}"}
