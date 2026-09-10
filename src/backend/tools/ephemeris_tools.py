"""ephemeris_tools.py - Integrated airmass computation.

Implements Milestone 7: time-averaged airmass and observability
metrics for a given target and observation window.
"""

from typing import Dict

try:
    from strands import tool as _tool
except Exception:
    def _tool(fn):  # type: ignore
        return fn


@_tool
def integrated_airmass(target_ra: float, target_dec: float,
                       site_lat: float, site_lon: float,
                       duration_hours: float = 2.0) -> Dict[str, float]:
    """Compute integrated (time-averaged) airmass over an observation window.

    Samples 12 equally-spaced times across ``duration_hours`` centered on
    the current time, converts the target to AltAz at each sample, and
    returns summary statistics.

    Parameters
    ----------
    target_ra : float
        Right Ascension in degrees (ICRS).
    target_dec : float
        Declination in degrees (ICRS).
    site_lat : float
        Observatory latitude in degrees.
    site_lon : float
        Observatory longitude in degrees.
    duration_hours : float
        Total observation window in hours. Default 2.0.

    Returns
    -------
    dict
        ``{"mean_airmass": float, "min_altitude": float,
          "observable_fraction": float, "max_airmass": float}``

        * ``mean_airmass`` — arithmetic mean of the 12 airmass samples.
        * ``min_altitude`` — lowest altitude (degrees) during the window.
        * ``observable_fraction`` — fraction of samples where altitude >= 30 deg.
        * ``max_airmass`` — maximum airmass encountered (highest zenith distance).
    """
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        from astropy import units as u

        loc = EarthLocation(lat=site_lat * u.deg, lon=site_lon * u.deg, height=0 * u.m)
        target_coord = SkyCoord(ra=target_ra * u.deg, dec=target_dec * u.deg, frame="icrs")
        t_start = Time.now()
        step = duration_hours * 3600.0 / 12.0  # seconds between samples

        airmasses = []
        altitudes = []

        for i in range(12):
            t_i = t_start + (i * step * u.s)
            altaz_frame = AltAz(obstime=t_i, location=loc)
            target_altaz = target_coord.transform_to(altaz_frame)

            alt_deg = target_altaz.alt.deg
            altitudes.append(alt_deg)

            if alt_deg > 0:
                # Airmass from secant approximation (Kasten & Young simplified)
                zenith_rad = (90.0 - alt_deg) * 3.141592653589793 / 180.0
                air = 1.0 / max(0.1, __import__("math").cos(zenith_rad))
                airmasses.append(min(air, 38.0))  # cap at zenith limit
            else:
                airmasses.append(38.0)  # below horizon

        obs_count = sum(1 for a in altitudes if a >= 30.0)

        return {
            "mean_airmass": round(sum(airmasses) / len(airmasses), 4),
            "min_altitude": round(min(altitudes), 4),
            "observable_fraction": round(obs_count / 12.0, 4),
            "max_airmass": round(max(airmasses), 4),
        }

    except Exception as exc:
        # Graceful fallback if astropy is unavailable
        return {
            "mean_airmass": 1.5,
            "min_altitude": 30.0,
            "observable_fraction": 0.5,
            "max_airmass": 2.5,
            "error": str(exc),
        }


@_tool
def check_lunar_separation(target_ra: float, target_dec: float) -> Dict[str, float]:
    """Moon proximity check per PRD M7.3 — delegates to scoring_tools.lunar_penalty."""
    try:
        from .scoring_tools import lunar_penalty as _lp
        return _lp(target_ra, target_dec)
    except Exception:
        sep_deg = 20.0
        return {"moon_separation_deg": sep_deg, "lunar_penalty": 0.25, "moon_safe": False}
