"""Network and catalog tools for KilonovaScout v3.

Provides live TAP queries to CDS VizieR, bundled cache fallback, and
synthetic mock rows when neither is available.
"""
import json
import math
import os
from typing import Any, Dict, List, Optional

import requests


def query_glade_vizier_tap(
    ra_min: float,
    ra_max: float,
    dec_min: float,
    dec_max: float,
    dist_mean: float,
    dist_std: float,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Query CDS VizieR GLADE+ catalog via ADQL.

    Returns a list of dicts with keys: pgc, ra, dec, distance_mpc, luminosity_k, name.
    Raises on network failure so the caller can fall back.
    """
    dist_low = max(0.0, dist_mean - 2 * dist_std)
    dist_high = dist_mean + 2 * dist_std

    # NOTE: verified against live VizieR — GLADE (VII/281/glade2) exposes the
    # luminosity distance as `Dist` (Mpc), not `dL` as sketched in the PRD.
    # `Bmag` is deliberately NOT selected: the table has both `Bmag` and
    # `BMAG` columns and TAPVizieR rejects any query that references the
    # ambiguous name (even qualified).
    query = f"""
    SELECT TOP {limit} PGC, GWGC, HyperLEDA, RAJ2000, DEJ2000, Kmag, Dist
    FROM "VII/281/glade2"
    WHERE RAJ2000 > {ra_min} AND RAJ2000 < {ra_max}
      AND DEJ2000 > {dec_min} AND DEJ2000 < {dec_max}
      AND Dist > {dist_low} AND Dist < {dist_high}
    """
    url = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
    resp = requests.post(
        url,
        data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query},
        timeout=15,
    )
    resp.raise_for_status()
    if not resp.text.strip().startswith("{"):
        raise ValueError(f"VizieR returned non-JSON (status {resp.status_code})")

    data = resp.json()
    rows: List[Dict[str, Any]] = []
    for row in data.get("data", []):
        pgc, gwcg, hyperleda, ra, dec, kmag, dist = row
        # K-band luminosity in solar luminosities. Convert apparent Kmag to
        # absolute via the distance modulus (Dist is in Mpc), then apply the
        # solar absolute K magnitude (~3.28, rounded to 3.5 per PRD).
        dist = float(dist)
        if kmag is not None and dist > 0:
            M_k = float(kmag) - 5.0 * math.log10(dist) - 25.0
        else:
            M_k = -18.0  # typical dwarf-galaxy default absolute magnitude
        k_lum = 10.0 ** (-0.4 * (M_k - 3.5))
        name = next(
            (n for n in (gwcg, hyperleda, f"PGC {pgc}" if pgc else None)
             if n and str(n).strip() and str(n).strip() != "---"),
            f"GLADE {pgc or len(rows)}",
        )
        rows.append(
            {
                "pgc": str(pgc) if pgc is not None else None,
                "ra": float(ra),
                "dec": float(dec),
                "distance_mpc": dist,
                "luminosity_k": float(k_lum),
                "name": str(name).strip(),
            }
        )
    return rows


def load_bundled_glade_cache() -> Optional[List[Dict[str, Any]]]:
    """Load GW170817 regional cache from src/backend/data."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "data", "GW170817_region_glade.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_mock_galaxies() -> List[Dict[str, Any]]:
    """Return deterministic mock galaxies for demo/fallback."""
    return [
        {
            "pgc": "PGC 045410",
            "ra": 197.451,
            "dec": -23.382,
            "distance_mpc": 40.0,
            "luminosity_k": 1e10,
            "name": "NGC 4993",
        },
        {
            "pgc": "PGC 045411",
            "ra": 197.5,
            "dec": -23.5,
            "distance_mpc": 41.0,
            "luminosity_k": 8e9,
            "name": "ESO 445-IG29",
        },
        {
            "pgc": "PGC 045412",
            "ra": 197.4,
            "dec": -23.4,
            "distance_mpc": 38.0,
            "luminosity_k": 5e9,
            "name": "Galaxy A",
        },
        {
            "pgc": "PGC 045413",
            "ra": 197.6,
            "dec": -23.2,
            "distance_mpc": 42.0,
            "luminosity_k": 3e9,
            "name": "Galaxy B",
        },
        {
            "pgc": "PGC 045414",
            "ra": 197.3,
            "dec": -23.6,
            "distance_mpc": 37.0,
            "luminosity_k": 2e9,
            "name": "Galaxy C",
        },
    ]
