import json
import math
import requests

def generate_cache():
    # NOTE: verified against live VizieR — GLADE (VII/281/glade2) exposes the
    # luminosity distance as `Dist` (Mpc), not `dL` as sketched in the PRD.
    # `Bmag` is deliberately NOT selected: the table has both `Bmag` and
    # `BMAG` columns and TAPVizieR rejects any query that references the
    # ambiguous name (even qualified).
    query = """
    SELECT TOP 50 PGC, GWGC, HyperLEDA, RAJ2000, DEJ2000, Kmag, Dist
    FROM "VII/281/glade2"
    WHERE RAJ2000 BETWEEN 195.0 AND 200.0
      AND DEJ2000 BETWEEN -26.0 AND -20.0
      AND Dist BETWEEN 30.0 AND 50.0
    """
    url = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
    resp = requests.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query}, timeout=15)
    resp.raise_for_status()
    # VizieR TAP sometimes returns HTML on error; guard against it.
    if not resp.text.strip().startswith("{"):
        print(f"[WARN] VizieR returned non-JSON (status {resp.status_code}); falling back to bundled cache.")
        return
    data = resp.json()

    cache = []
    for row in data.get("data", []):
        pgc, gwcg, hyperleda, ra, dec, kmag, dist = row
        # K-band luminosity in solar luminosities. Convert apparent Kmag to
        # absolute via the distance modulus (Dist is in Mpc), then apply the
        # solar absolute K magnitude (~3.28, rounded to 3.5 following the
        # PRD convention): L/L_sun = 10^(-0.4*(M_K - 3.5)).
        dist = float(dist)
        if kmag is not None and dist > 0:
            M_k = float(kmag) - 5.0 * math.log10(dist) - 25.0
        else:
            M_k = -18.0  # typical dwarf-galaxy default absolute magnitude
        k_lum = 10.0 ** (-0.4 * (M_k - 3.5))
        name = next(
            (n for n in (gwcg, hyperleda, f"PGC {pgc}" if pgc else None)
             if n and str(n).strip() and str(n).strip() != "---"),
            f"GLADE {len(cache)+1}",
        )
        cache.append({
            "pgc": str(pgc) if pgc is not None else None,
            "ra": float(ra),
            "dec": float(dec),
            "distance_mpc": dist,
            "luminosity_k": float(k_lum),
            "name": str(name).strip(),
        })

    out = "src/backend/data/GW170817_region_glade.json"
    with open(out, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"Cached {len(cache)} galaxies to {out}")

if __name__ == "__main__":
    generate_cache()

