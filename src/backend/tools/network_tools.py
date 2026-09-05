import requests
from strands import tool

@tool
def query_glade_vizier_tap(ra_min: float, ra_max: float, dec_min: float, dec_max: float, dist_mean: float, dist_std: float) -> list:
    """Executes ADQL TAP query on CDS VizieR for GLADE+ galaxies within the 3D probability envelope."""
    d_min = max(0.0, dist_mean - 2.5 * dist_std)
    d_max = dist_mean + 2.5 * dist_std
      
    query = f"""
    SELECT TOP 50 PGC, RAJ2000, DEJ2000, Bmag, Kmag, dL
    FROM "VII/281/glade2"
    WHERE RAJ2000 BETWEEN {ra_min} AND {ra_max}
      AND DEJ2000 BETWEEN {dec_min} AND {dec_max}
      AND dL BETWEEN {d_min} AND {d_max}
      AND dL IS NOT NULL
    """
      
    url = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
    payload = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query}
      
    response = requests.post(url, data=payload, timeout=15)
    data = response.json()
      
    candidates = []
    for row in data.get("data", []):
        pgc, ra, dec, bmag, kmag, dl = row
        k_lum = 10.0 ** (-0.4 * (kmag if kmag is not None else (bmag - 3.5 if bmag is not None else 18.0)))
        candidates.append({
            "pgc": str(pgc),
            "ra": float(ra),
            "dec": float(dec),
            "distance_mpc": float(dl),
            "luminosity_k": float(k_lum)
        })
    return candidates

@tool
def get_open_meteo_weather(lat: float, lon: float) -> dict:
    """Fetches real-time cloud cover, seeing, and humidity from Open-Meteo astronomical model."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=cloudcover,relativehumidity_2m,dewpoint_2m&current_weather=true"
    resp = requests.get(url, timeout=5).json()
    
    hourly = resp.get("hourly", {})
    cloud_cover = hourly.get("cloudcover", [100])[0]
    humidity = hourly.get("relativehumidity_2m", [100])[0]
    
    dome_safe = humidity < 85.0
    sky_clear = cloud_cover < 30.0
    
    return {
        "dome_safe": dome_safe,
        "cloud_cover_pct": cloud_cover,
        "humidity_pct": humidity,
        "sky_quality_pass": dome_safe and sky_clear
    }