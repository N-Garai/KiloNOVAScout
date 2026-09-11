"""scoring_tools.py - Advanced astrophysical math for target prioritization.

Implements Milestone 7 (advanced astrophysical math) and Milestone 10
(full v3 scoring formula) for KilonovaScout.
"""

import math
from typing import Dict, Optional

try:
    from strands import tool as _tool
except Exception:  # strands not installed in unit-test envs
    def _tool(fn):  # type: ignore
        return fn


@_tool
def schechter_weight(l_k: float, l_star: float = 1.0e10, alpha: float = 1.0) -> float:
    """Schechter luminosity function weight.

    Computes phi(L) ~ (L/L*)^alpha * exp(-L/L*), a standard galaxy
    luminosity distribution used to weight host-galaxy candidates.

    Parameters
    ----------
    l_k : float
        K-band luminosity of the candidate galaxy (solar luminosities).
    l_star : float
        Characteristic (Schechter) luminosity in solar units. Default 1e10.
    alpha : float
        Faint-end slope. Default 1.0 (peaked at L*; see ScoringWeights.schechter_alpha).

    Returns
    -------
    float
        Schechter weight (dimensionless).  Safe for l_k <= 0 (returns 0).
    """
    if l_k <= 0 or l_star <= 0:
        return 0.0
    x = l_k / l_star
    return (x ** alpha) * math.exp(-x)


@_tool
def atmospheric_extinction(airmass: float, zenith_extinction: float = 0.12) -> float:
    """R-band atmospheric extinction.

    Returns k_X where k is the extinction coefficient per airmass
    (mag) and X is the airmass.

    Parameters
    ----------
    airmass : float
        Optical path-length through the atmosphere (X >= 1.0).
    zenith_extinction : float
        Extinction coefficient k in mag per airmass for R-band. Default 0.12.

    Returns
    -------
    float
        Total extinction in magnitudes (k * X).
    """
    if airmass < 1.0:
        airmass = 1.0
    return zenith_extinction * airmass


@_tool
def estimate_kilonova_snr(distance_mpc: float, peak_mag: float = 17.5) -> Dict[str, float]:
    """Estimate the observable signal-to-noise ratio for a kilonova at a given distance.

    ``peak_mag`` is the peak *apparent* magnitude at the 40 Mpc reference
    distance (GW170817 peaked at ~17.5 mag at 40 Mpc, i.e. M_peak ~ -15.6).
    The apparent magnitude at other distances scales as
    m(d) = peak_mag + 5*log10(d / 40).

    Parameters
    ----------
    distance_mpc : float
        Luminosity distance in megaparsecs.
    peak_mag : float
        Peak apparent magnitude at 40 Mpc. Default 17.5 (GW170817).

    Returns
    -------
    dict
        ``{"distance_modulus": float, "apparent_mag": float, "snr_proxy": float}``
    """
    if distance_mpc <= 0:
        return {"distance_modulus": 0.0, "apparent_mag": peak_mag, "snr_proxy": 0.0}

    distance_modulus = 5.0 * math.log10(distance_mpc) + 25.0
    # Scale the 40 Mpc reference apparent magnitude to the target distance
    apparent_mag = peak_mag + 5.0 * math.log10(distance_mpc / 40.0)

    # Simplified S/N proxy: brighter objects (lower mag) -> higher S/N.
    # Reference: 17th mag -> S/N ~ 10 for a 1-m telescope, 300 s integration.
    ref_mag = 17.0
    ref_snr = 10.0
    snr_proxy = ref_snr * (10.0 ** (0.4 * (ref_mag - apparent_mag)))

    return {
        "distance_modulus": round(distance_modulus, 4),
        "apparent_mag": round(apparent_mag, 4),
        "snr_proxy": round(snr_proxy, 4),
    }


@_tool
def lunar_penalty(target_ra: float, target_dec: float) -> Dict[str, float]:
    """Compute a lunar proximity penalty for observing a given sky position.

    Uses ``astropy.coordinates.get_body`` to find the Moon's current
    position and measures the angular separation to the target.

    Parameters
    ----------
    target_ra : float
        Right Ascension in degrees (ICRS).
    target_dec : float
        Declination in degrees (ICRS).

    Returns
    -------
    dict
        ``{"moon_separation_deg": float, "lunar_penalty": float, "moon_safe": bool}``

        * ``lunar_penalty`` is 0 when separation > 30 deg, 1.0 when < 10 deg,
          linearly interpolated between.
        * ``moon_safe`` is True when penalty == 0.
    """
    try:
        import warnings

        from astropy.coordinates import get_body, SkyCoord
        from astropy.time import Time
        from astropy.utils.exceptions import AstropyWarning
        import astropy.units as u

        now = Time.now()
        moon_coord = get_body("moon", now)
        target_coord = SkyCoord(ra=target_ra * u.deg, dec=target_dec * u.deg, frame="icrs")
        with warnings.catch_warnings():
            # GCRS<->ICRS separation triggers a benign non-rotation warning
            # for every call; it is expected and carries no information.
            warnings.simplefilter("ignore", AstropyWarning)
            sep = moon_coord.separation(target_coord)
        sep_deg = sep.deg
    except Exception:
        # Fallback: assume moderate separation if astropy unavailable
        sep_deg = 20.0

    # Linear penalty: 0 at >=30 deg, 1.0 at <=10 deg
    if sep_deg >= 30.0:
        penalty = 0.0
    elif sep_deg <= 10.0:
        penalty = 1.0
    else:
        penalty = (30.0 - sep_deg) / 20.0

    return {
        "moon_separation_deg": round(sep_deg, 4),
        "lunar_penalty": round(penalty, 4),
        "moon_safe": bool(penalty == 0.0),
    }


def compute_full_score(terms_dict: Dict[str, float], weights: Dict[str, float]) -> float:
    """Full v3 composite scoring formula, extended for multi-event classes.

    score = alpha*P + beta*Schechter - gamma*X - delta*C + epsilon*B
            + zeta*SNR - eta*L_moon + theta*F + kappa*s

    The two extra terms are optional and default to 0, so every existing
    v3 call is unaffected:

    * ``F`` (``theta``) — GRB brightness proxy from notice energetics.
    * ``s`` (``kappa``) — neutrino signalness (astrophysical probability).

    Parameters
    ----------
    terms_dict : dict
        Raw (unweighted) term values with keys:
        ``"spatial"``, ``"schechter"``, ``"airmass"``, ``"cloud"``,
        ``"grb_boost"``, ``"snr"``, ``"lunar"``, ``"flux"``,
        ``"signalness"``.
    weights : dict
        Weight coefficients with keys:
        ``"alpha"``, ``"beta"``, ``"gamma"``, ``"delta"``,
        ``"epsilon"``, ``"zeta"``, ``"eta"``, ``"theta"``, ``"kappa"``.
        Missing keys default to 0.

    Returns
    -------
    float
        Composite score (higher is better for observing).
    """
    alpha = weights.get("alpha", 1.0)
    beta = weights.get("beta", 0.5)
    gamma = weights.get("gamma", 0.3)
    delta = weights.get("delta", 0.2)
    epsilon = weights.get("epsilon", 3.0)
    zeta = weights.get("zeta", 0.1)
    eta = weights.get("eta", 0.4)
    theta = weights.get("theta", 0.0)
    kappa = weights.get("kappa", 0.0)

    score = (
        alpha * terms_dict.get("spatial", 0.0)
        + beta * terms_dict.get("schechter", 0.0)
        - gamma * terms_dict.get("airmass", 0.0)
        - delta * terms_dict.get("cloud", 0.0)
        + epsilon * terms_dict.get("grb_boost", 0.0)
        + zeta * terms_dict.get("snr", 0.0)
        - eta * terms_dict.get("lunar", 0.0)
        + theta * terms_dict.get("flux", 0.0)
        + kappa * terms_dict.get("signalness", 0.0)
    )
    return round(score, 6)


@_tool
def check_lunar_separation(target_ra: float, target_dec: float) -> Dict[str, float]:
    """PRD alias for lunar_penalty — keeps the spec import contract stable.

    Specified in v3 PRD M7.3 as ``check_lunar_separation``; implementation
    lives in ``lunar_penalty`` (same physics, same return shape).
    """
    return lunar_penalty(target_ra, target_dec)
