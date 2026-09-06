"""scheduling_tools.py - TSP nearest-neighbor slew optimization.

Implements Milestone 7: scheduling/slew-order optimization using a
greedy nearest-neighbor heuristic on the alt/az sphere.
"""

import json
from typing import List, Dict, Any


def _angular_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle angular distance between two points on the celestial sphere (degrees)."""
    from math import radians, cos, sin, sqrt, atan2

    ra1, dec1, ra2, dec2 = map(radians, (ra1, dec1, ra2, dec2))
    d_ra = ra2 - ra1
    d_dec = dec2 - dec1
    a = sin(d_dec / 2) ** 2 + cos(dec1) * cos(dec2) * sin(d_ra / 2) ** 2
    return 2 * atan2(sqrt(a), sqrt(1 - a)) * 180.0 / 3.141592653589793


def _altaz_distance(ra1: float, dec1: float, ra2: float, dec2: float,
                    site_lat: float, site_lon: float, obstime=None) -> float:
    """Angular separation in the local Alt/Az frame (degrees).

    Uses astropy to transform ICRS coordinates to AltAz at the given
    site and time, then computes the angular distance on the horizon sphere.
    """
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u

        if obstime is None:
            obstime = Time.now()

        loc = EarthLocation(lat=site_lat * u.deg, lon=site_lon * u.deg, height=0 * u.m)
        c1 = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg, frame="icrs")
        c2 = SkyCoord(ra=ra2 * u.deg, dec=dec2 * u.deg, frame="icrs")
        altaz = AltAz(obstime=obstime, location=loc)
        a1 = c1.transform_to(altaz)
        a2 = c2.transform_to(altaz)
        return a1.separation(a2).deg
    except Exception:
        # Fallback: use great-circle distance on the celestial sphere
        return _angular_distance(ra1, dec1, ra2, dec2)


def optimize_slew_order(targets: List[Dict[str, Any]], site_lat: float, site_lon: float,
                        obstime=None) -> List[Dict[str, Any]]:
    """Greedy nearest-neighbor TSP heuristic for telescope slew ordering.

    Starts from the first target in the list, then repeatedly picks the
    unvisited target with the smallest alt/az angular distance from the
    current position.

    Parameters
    ----------
    targets : list of dict
        Each dict must have keys ``"ra"``, ``"dec"``, ``"name"`` (degrees).
    site_lat : float
        Observatory latitude in degrees.
    site_lon : float
        Observatory longitude in degrees.
    obstime : astropy.time.Time, optional
        Observation time for AltAz conversion. Defaults to now.

    Returns
    -------
    list of dict
        Targets reordered for minimal slew distance, each with an added
        ``"slew_distance_deg"`` key (0 for the first target).
    """
    if not targets:
        return []

    if obstime is None:
        from astropy.time import Time
        obstime = Time.now()

    unvisited = [dict(t) for t in targets]
    ordered = []

    # Start from first target
    current = unvisited.pop(0)
    current["slew_distance_deg"] = 0.0
    ordered.append(current)

    while unvisited:
        # Find nearest in AltAz frame
        best_idx = -1
        best_dist = float("inf")
        for i, t in enumerate(unvisited):
            d = _altaz_distance(current["ra"], current["dec"], t["ra"], t["dec"],
                                site_lat, site_lon, obstime)
            if d < best_dist:
                best_dist = d
                best_idx = i

        if best_idx >= 0:
            current = unvisited.pop(best_idx)
            current["slew_distance_deg"] = round(best_dist, 4)
            ordered.append(current)

    return ordered


def slew_script_from_ordered(targets: List[Dict[str, Any]]) -> str:
    """Generate a simple ASCOM/INDI-style XML slew script from an ordered target list."""
    import xml.etree.ElementTree as ET
    import datetime

    root = ET.Element("ASCOM_INDI_SlewScript")
    root.set("generatedAt", datetime.datetime.utcnow().isoformat())
    root.set("observatory", "Palomar")

    for i, target in enumerate(targets):
        tgt = ET.SubElement(root, "Target", id=str(i + 1))
        ET.SubElement(tgt, "Name").text = target.get("name", f"Target {i+1}")
        ET.SubElement(tgt, "RA_Deg").text = str(target.get("ra", 0.0))
        ET.SubElement(tgt, "Dec_Deg").text = str(target.get("dec", 0.0))
        ET.SubElement(tgt, "Priority").text = str(len(targets) - i)
        ET.SubElement(tgt, "SlewDistance_Deg").text = str(target.get("slew_distance_deg", 0.0))

    return ET.tostring(root, encoding="unicode")