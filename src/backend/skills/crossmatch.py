"""crossmatch.py — ZTF crossmatch skill (M13).

Checks the top host position for a recent ZTF transient (would have caught
AT2017gfo-like rebrightening).  Advisory only, never blocks.
"""

from __future__ import annotations

from . import Skill


class ZTFCrossmatchSkill(Skill):
    name = "crossmatch_ztf"
    description = "Check ZTF/ALeRCE for recent transients at the host position."

    def run(self, ra: float, dec: float, radius_arcsec: float = 5.0):
        try:
            import requests
            # ALeRCE ZTF object cone search (anonymous, lightweight)
            url = "https://api.alerce.online/ztf/v1/objects"
            params = {"ra": float(ra), "dec": float(dec), "radius": float(radius_arcsec) / 3600.0}
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", [])
            if items:
                return {"found": True, "count": len(items), "note": f"{len(items)} ZTF source(s) within {radius_arcsec}″ — possible counterpart."}
            return {"found": False, "count": 0, "note": "No ZTF transient within search radius."}
        except Exception as e:
            return {"found": False, "count": 0, "note": f"ZTF check unavailable: {e}"}
