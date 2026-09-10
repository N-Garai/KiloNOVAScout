"""KilonovaScoutTools - Tool collection for the orchestrator agent.

This module wraps the specialized tools from astrometry_tools, network_tools, and hardware_tools
into a unified interface for the master orchestrator agent.

All methods are decorated with @strands.tool so they can be passed directly
to a strands.Agent as callable tools.
"""

import datetime
import gc
import io
import json
import math
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import numpy as np
import requests
import astropy_healpix as ah
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.table import Table
from astropy.time import Time
from astropy import units as u
from strands import tool

from ..models import (
    HealpixSkymap,
    Galaxy,
    ObservatoryWeather,
    TelescopeSlewScript,
    AgentOutput,
    ScoreBreakdown,
)
from .scoring_tools import (
    schechter_weight,
    atmospheric_extinction,
    estimate_kilonova_snr,
    lunar_penalty,
    check_lunar_separation,
    compute_full_score,
)
from .ephemeris_tools import integrated_airmass
from .ephemeris_tools import check_lunar_separation as ephemeris_check_lunar
from .scheduling_tools import optimize_slew_order

# M13 skills auto-discover (A.R.I.E.S pattern) — keep import side-effect for audit greps
try:
    from ..skills import discover_skills as _discover_skills
    _discover_skills()
except Exception:
    pass
from ..event_classes import get_profile, flux_proxy


def _pnum(value) -> Optional[float]:
    """Coerce a harvested trigger parameter to float (None if absent)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _cone_pixel_indices(ra_deg: float, dec_deg: float, radius_deg: float, nside: int) -> np.ndarray:
    """HEALPix cone search implemented manually with NumPy.

    ``astropy_healpix`` ships no cone-search routine (verified through v2.x),
    so this vectorizes the haversine separation over the pixel grid instead.
    Callers cap nside at 256 (786k pixels ≈ 19 MB transient), keeping this
    cheap on 512 MB instances.  Returns int64 nested pixel indices within
    ``radius_deg`` of the center (possibly empty — callers fall back).
    """
    from astropy_healpix import healpix_to_lonlat, nside_to_npix
    npix = int(nside_to_npix(nside))
    ra_arr, dec_arr = healpix_to_lonlat(np.arange(npix, dtype=np.int64), nside, order="nested")
    ra0 = math.radians(float(ra_deg))
    dec0 = math.radians(float(dec_deg))
    ra = np.radians(np.asarray(ra_arr.deg, dtype=np.float64))
    dec = np.radians(np.asarray(dec_arr.deg, dtype=np.float64))
    sin_d = np.sin((dec - dec0) / 2.0) ** 2 + np.cos(dec0) * np.cos(dec) * np.sin((ra - ra0) / 2.0) ** 2
    sep = 2.0 * np.degrees(np.arcsin(np.sqrt(np.clip(sin_d, 0.0, 1.0))))
    del ra_arr, dec_arr, ra, dec, sin_d
    return np.nonzero(sep <= float(radius_deg))[0].astype(np.int64)


def _load_scoring_weights() -> dict:
    """Load scoring weights from config/ with a robust fallback.

    Includes the full v3 formula weights (Milestone 10) with sane defaults
    matching the documented ScoringWeights model.
    """
    try:
        from config import load_scoring_weights as _loader
        return _loader()
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, '..', '..', '..', 'config', 'scoring_weights.json'),  # repo/config
        os.path.join(here, '..', '..', 'config', 'scoring_weights.json'),
        os.path.join(here, 'config', 'scoring_weights.json'),
        os.path.join(os.getcwd(), 'config', 'scoring_weights.json'),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
    return {
        "spatial_weight_alpha": 1.0,
        "mass_weight_beta": 0.5,
        "extinction_gamma": 0.3,
        "weather_delta": 0.2,
        "coincidence_boost": 3.0,
        "snr_weight_zeta": 0.15,
        "lunar_penalty_eta": 0.1,
        "schechter_l_star": 1.0e10,
        "schechter_alpha": 1.0,
        "zenith_extinction": 0.12,
        "peak_kilonova_mag": 17.5,
        "probability_threshold": 0.01,
    }


class KilonovaScoutTools:
    """Collection of tools for the KilonovaScout agent."""

    def __init__(self, observatory_name: str = "Palomar", lat: float = 33.356, lon: float = -116.865, alt: float = 1706):
        self.observatory_name = observatory_name
        self.observatory_location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt * u.m)
        self._weather_cache: Optional[ObservatoryWeather] = None
        self._weather_cache_time: Optional[Time] = None
        # Multi-event support: the orchestrator sets these per run before
        # calling query_glade_catalog.  Defaults reproduce the v3 BNS path.
        self.active_class: str = "bns"
        self.active_trigger_params: Dict[str, Any] = {}

    @tool
    def parse_healpix_map(self, skymap_url: str) -> HealpixSkymap:
        """Parses a HEALPix skymap from a FITS file URL.

        Fallback chain (v3 PRD M4.2):
        1. Live download from skymap_url
        2. Bundled bayestar.fits.gz replay
        3. Synthetic GW170817-like fallback
        """
        import gzip

        fits_bytes = None
        source = "synthetic"

        # Tier 1: live download
        try:
            with urllib.request.urlopen(skymap_url, timeout=15) as r:
                fits_bytes = r.read()
                source = "live"
            # OOM guard: peek at the row count from the FITS header WITHOUT
            # loading pixel data. Anything above nside-512 scale (3.1M rows)
            # cannot be parsed inside 512 MB (the old bundled nside-2048 map
            # was 50M rows / 1.6 GB and SIGKILLed free-tier instances), so
            # oversize files are declined here and fall through to replay.
            try:
                from astropy.io import fits as _fits
                with _fits.open(io.BytesIO(fits_bytes)) as _hdul:
                    _nrow = int(_hdul[1].header.get("NAXIS2", 0)) if len(_hdul) > 1 else 0
            except Exception:
                _nrow = 0
            if _nrow > 3145728:
                print(f"[SYS] live skymap too large ({_nrow} rows); using replay tier")
                fits_bytes = None
                source = "synthetic"
        except Exception as e:
            print(f"[SYS] skymap download failed ({e})")

        # Tier 2: bundled GW170817 replay
        if fits_bytes is None:
            here = os.path.dirname(os.path.abspath(__file__))
            bundled = os.path.join(here, '..', 'data', 'bayestar.fits.gz')
            if os.path.exists(bundled):
                try:
                    with open(bundled, 'rb') as f:
                        fits_bytes = gzip.decompress(f.read())
                    source = "replay"
                except Exception as e:
                    print(f"[SYS] bundled skymap load failed ({e})")

        # Tier 3: synthetic (last resort) — calibrated from published GW170817
        # parameters (90% area ~31 deg^2, distance 40 +/- 8 Mpc).
        if fits_bytes is None:
            print("[SYS] no skymap available; using synthetic fallback reconstructed from published parameters")
            return HealpixSkymap(
                url=skymap_url,
                nside=512,
                probdensity=[0.95, 0.88, 0.85, 0.75, 0.70],
                supercell_indices=[1, 2, 3, 4, 5],
                localization_area_sq_deg=31.0,
                provenance_source="synthetic",
                dist_mean=40.0,
                dist_std=8.0,
            )

        # Parse real FITS bytes (live or replay — same code path).
        # GraceDB serves *.fits.gz files as raw gzip bytes (urllib does not
        # decode them); decompress on the gzip magic before Table.read, which
        # otherwise fails with "Format could not be identified".
        if fits_bytes[:2] == b"\x1f\x8b":
            print("[SYS] live skymap is gzip-compressed; decompressing")
            fits_bytes = gzip.decompress(fits_bytes)
        # float32 throughout: halves the transient peak vs float64 with no
        # science impact at these precisions.  BAYESTAR DISTMU/DISTSIGMA
        # legitimately contain inf/NaN in zero-probability pixels — the
        # isfinite guards below (plus probability weighting) handle that.
        table = Table.read(io.BytesIO(fits_bytes))
        prob = np.array(table['PROB'], dtype=np.float32)
        distmu = np.array(table['DISTMU'], dtype=np.float32)
        distsigma = np.array(table['DISTSIGMA'], dtype=np.float32)
        del table
        gc.collect()

        npix = len(prob)
        nside = ah.npix_to_nside(npix)
        pixel_area_sr = 4.0 * np.pi / npix

        # LIGO skymaps store PROB as probability DENSITY (per steradian) when
        # npix is large; normalize to per-pixel probabilities so downstream
        # consumers get values on a true 0..1 probability scale.
        p_pix = prob * np.float32(pixel_area_sr)
        total_p = float(p_pix.sum())
        if total_p > 0:
            p_pix = p_pix / total_p

        sorted_idx = np.argsort(p_pix)[::-1]
        cum_prob = np.cumsum(p_pix[sorted_idx])
        top_90_idx = sorted_idx[cum_prob <= 0.90]
        if len(top_90_idx) == 0:
            top_90_idx = sorted_idx[:1]

        ra, dec = ah.healpix_to_lonlat(top_90_idx, nside, order='nested')

        w = p_pix[top_90_idx]
        with np.errstate(invalid="ignore", divide="ignore"):
            mean_dist = float(np.average(distmu[top_90_idx], weights=w))
            dist_std = float(np.average(distsigma[top_90_idx], weights=w))

        # 90% credible area = number of pixels in the region x pixel area
        area_sq_deg = float(len(top_90_idx) * pixel_area_sr * (180.0 / np.pi) ** 2)

        # Materialize the small 90% outputs FIRST, then release the full-sky
        # working arrays (order matters — the return below needs them).
        probdensity_out = p_pix[top_90_idx].tolist()
        supercell_out = top_90_idx.tolist()
        del prob, distmu, distsigma, p_pix, sorted_idx, cum_prob, top_90_idx, w
        gc.collect()

        return HealpixSkymap(
            url=skymap_url,
            nside=int(nside),
            probdensity=probdensity_out,
            supercell_indices=supercell_out,
            localization_area_sq_deg=area_sq_deg,
            provenance_source=source,
            dist_mean=mean_dist if np.isfinite(mean_dist) else 40.0,
            dist_std=dist_std if np.isfinite(dist_std) else 8.0,
        )

    @tool
    def build_point_skymap(self, ra_deg: float, dec_deg: float, radius_deg: float = 1.0) -> HealpixSkymap:
        """Builds a HEALPix localization map for point-position triggers.

        GRB and neutrino notices carry a sky position plus an error radius —
        not a FITS skymap.  This constructs the equivalent 90%-credible
        HEALPix map (Gaussian falloff, normalized) so every downstream stage
        (catalog crossmatch, scoring, visualization, report) runs on the
        identical code path as FITS triggers.  Provenance is ``point`` (built
        from the notice's own coordinates — real localization, not a FITS
        download, and not the reconstructed GW fallback which keeps the name
        ``synthetic``).
        """
        sigma = max(float(radius_deg or 1.0), 0.05)
        # Adaptive resolution: keep the 90% pixel count in the hundreds for
        # the 512 MB Render budget regardless of error-circle size.
        nside = 64 if sigma >= 2.0 else (128 if sigma >= 0.5 else 256)
        r90 = 2.146 * sigma  # Gaussian 90% containment radius
        npix = 12 * nside * nside
        pixel_area_deg2 = 41253.0 / npix

        center = SkyCoord(ra=float(ra_deg) * u.deg, dec=float(dec_deg) * u.deg, frame="icrs")
        try:
            idx = _cone_pixel_indices(float(ra_deg), float(dec_deg), r90, nside)
        except Exception as e:
            print(f"[SYS] point cone search failed ({e}); single-pixel fallback")
            idx = np.asarray([ah.lonlat_to_healpix(center.ra, center.dec, nside, order="nested")], dtype=np.int64)
        if len(idx) == 0:
            idx = np.asarray([ah.lonlat_to_healpix(center.ra, center.dec, nside, order="nested")], dtype=np.int64)

        ra_arr, dec_arr = ah.healpix_to_lonlat(idx, nside, order="nested")
        pts = SkyCoord(ra=ra_arr, dec=dec_arr, frame="icrs")
        sep_deg = center.separation(pts).deg
        p = np.exp(-0.5 * (sep_deg / sigma) ** 2)
        total = float(p.sum())
        p = p / total if total > 0 else np.full_like(p, 1.0 / len(p))

        order = np.argsort(p)[::-1]
        cum = np.cumsum(p[order])
        top_90 = order[cum <= 0.90]
        if len(top_90) == 0:
            top_90 = order[:1]
        sel_idx = idx[top_90]
        sel_p = p[top_90]

        return HealpixSkymap(
            url=f"point://{float(ra_deg):.3f},{float(dec_deg):.3f}/r{sigma:.2f}deg",
            nside=int(nside),
            probdensity=[float(v) for v in sel_p],
            supercell_indices=[int(v) for v in sel_idx],
            localization_area_sq_deg=float(len(sel_idx) * pixel_area_deg2),
            provenance_source="point",
            dist_mean=None,
            dist_std=None,
        )

    @tool
    def query_glade_catalog(self, skymap: HealpixSkymap) -> List[Galaxy]:
        """Queries GLADE+ catalog for galaxies within the skymap's high-probability regions.

        Fallback chain (v3 PRD M4.3):
        1. Live VizieR TAP query
        2. Bundled regional cache (GW170817_region_glade.json)
        3. Mock rows (last resort)

        All candidates are scored with the identical full v3 formula
        (Milestones 7 + 10) regardless of data source:
          S = alpha*P_spatial + beta*Schechter(L_K) - gamma*X_i - delta*C
              + epsilon*B_GRB + zeta*snr_proxy - eta*L_moon
              (+ theta*flux + kappa*signalness for non-merger classes)

        Multi-event support: the orchestrator sets ``active_class`` (and the
        harvested ``active_trigger_params``) per run.  The BNS class keeps
        reading the tunable config file exactly as before; other classes use
        their registry profile (host-mass and kilonova terms disabled where
        the physics does not apply).
        """
        from .network_tools import query_glade_vizier_tap, load_bundled_glade_cache, get_mock_galaxies

        active_class = getattr(self, "active_class", "bns") or "bns"
        profile = get_profile(active_class)
        weights = _load_scoring_weights()
        if active_class == "bns":
            # BNS keeps the tunable config-file weights exactly as before.
            alpha = float(weights.get("spatial_weight_alpha", 1.0))
            beta = float(weights.get("mass_weight_beta", 0.5))
            gamma = float(weights.get("extinction_gamma", 0.3))
            delta = float(weights.get("weather_delta", 0.2))
            epsilon = float(weights.get("coincidence_boost", 3.0))
            zeta = float(weights.get("snr_weight_zeta", 0.15))
            eta = float(weights.get("lunar_penalty_eta", 0.1))
        else:
            pw = profile["weights"]
            alpha = float(pw["alpha"])
            beta = float(pw["beta"])
            gamma = float(pw["gamma"])
            delta = float(pw["delta"])
            epsilon = float(pw["epsilon"])
            zeta = float(pw["zeta"])
            eta = float(pw["eta"])
        # Shared physics constants always come from the config file.
        theta = float(profile["weights"]["theta"])
        kappa = float(profile["weights"]["kappa"])
        l_star = float(weights.get("schechter_l_star", 1.0e10))
        schechter_alpha = float(weights.get("schechter_alpha", -1.0))
        k_ext = float(weights.get("zenith_extinction", 0.12))
        peak_mag = float(weights.get("peak_kilonova_mag", 17.5))

        catalog_source = "mock"
        candidates_raw: List[Dict[str, Any]] = []

        # Derive the skymap 90%-region centroid from the actual supercell pixel
        # centers (probability-weighted mean on the unit sphere) — no hardcoded
        # GW170817 coordinates anywhere (M4.5.2).
        ra_center, dec_center, prob_lookup = self._skymap_geometry(skymap)
        # Distance window: point-localized events (GRB/neutrino) carry no
        # distance estimate, so use a wide window = no distance constraint.
        if getattr(skymap, "dist_mean", None) is None:
            dist_mean, dist_std = 150.0, 150.0
        else:
            dist_mean = float(getattr(skymap, "dist_mean", None) or 40.0)
            dist_std = float(getattr(skymap, "dist_std", None) or 8.0)
        # Search box scales with the localization area (GW170817's 31 deg^2
        # reproduces the historical half-width of ~2.8 deg).
        area = float(getattr(skymap, "localization_area_sq_deg", None) or 31.0)
        span = min(5.0, max(1.0, math.sqrt(area) / 2.0))
        ra_span, dec_span = span, span

        # Tier 1: live VizieR TAP query.  The pool is deliberately wide
        # (120 rows): TAP returns an arbitrary TOP N with no spatial ordering,
        # so a narrow pool can drown the true host in background galaxies.  A
        # cheap centroid pre-filter below restores recall before the expensive
        # per-candidate astrometry runs.
        try:
            raw = query_glade_vizier_tap(
                ra_min=ra_center - ra_span,
                ra_max=ra_center + ra_span,
                dec_min=dec_center - dec_span,
                dec_max=dec_center + dec_span,
                dist_mean=dist_mean,
                dist_std=dist_std,
                limit=120,
            )
            if raw:
                candidates_raw = raw
                catalog_source = "live"
        except Exception as e:
            print(f"[SYS] VizieR TAP query failed ({e})")

        # Tier 2: bundled regional cache
        if not candidates_raw:
            cached = load_bundled_glade_cache()
            if cached:
                candidates_raw = cached
                catalog_source = "cached"

        # Tier 3: mock rows (last resort)
        if not candidates_raw:
            candidates_raw = get_mock_galaxies()
            catalog_source = "mock"

        # Recall guard: keep the 60 rows nearest the 90%-region centroid.
        # Pure haversine, no network, no astropy — microseconds per row — so
        # the costly windowed-airmass scoring loop stays bounded while a host
        # sitting almost on top of the centroid can no longer be crowded out
        # by an arbitrary TOP-N cut.
        if len(candidates_raw) > 60:
            rc = math.radians(ra_center)
            dc = math.radians(dec_center)

            def _centroid_sep(c: Dict[str, Any]) -> float:
                """Great-circle distance (radians) to the 90% centroid, RA-wrap safe."""
                try:
                    ra = math.radians(float(c.get("ra", c.get("RAJ2000", 0)) or 0.0))
                    dec = math.radians(float(c.get("dec", c.get("DEJ2000", 0)) or 0.0))
                except (TypeError, ValueError):
                    return float("inf")
                dra = abs(ra - rc)
                if dra > math.pi:
                    dra = 2.0 * math.pi - dra
                ddec = dec - dc
                a = (math.sin(ddec / 2.0) ** 2
                     + math.cos(dc) * math.cos(dec) * math.sin(dra / 2.0) ** 2)
                return 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))

            kept = sorted(candidates_raw, key=_centroid_sep)[:60]
            print(f"[SYS] catalog pre-filter: {len(candidates_raw)} -> {len(kept)} nearest centroid")
            candidates_raw = kept

        # Weather is fetched ONCE per run (TTL cache) and shared by the whole
        # scoring loop — never per-candidate network calls.
        try:
            weather = self.get_weather_cached()
            f_cloud = min(1.0, max(0.0, weather.cloud_cover_percent / 100.0)) if weather else 0.0
        except Exception:
            weather = None
            f_cloud = 0.0

        site_lat = self.observatory_location.lat.value
        site_lon = self.observatory_location.lon.value

        formula_weights = {
            "alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta,
            "epsilon": epsilon, "zeta": zeta, "eta": eta,
            "theta": theta, "kappa": kappa,
        }
        # Class-specific trigger energetics (harvested once per run, shared
        # by every candidate — never per-candidate network calls).
        trig = getattr(self, "active_trigger_params", {}) or {}
        trig_flux = flux_proxy(
            fluence=_pnum(trig.get("fluence", trig.get("burst_fluence"))),
            peak_flux=_pnum(trig.get("peak_flux", trig.get("peakflux", trig.get("flux_peak")))),
        ) if theta > 0 else 0.0
        trig_signalness = (_pnum(trig.get("signalness", trig.get("signal_trackness", trig.get("p_astro")))) or 0.0) if kappa > 0 else 0.0

        galaxies: List[Galaxy] = []
        for c in candidates_raw:
            name = str(c.get("name") or f"PGC {c.get('pgc', '?')}")
            ra = float(c.get("ra", c.get("RAJ2000", 0)) or 0)
            dec = float(c.get("dec", c.get("DEJ2000", 0)) or 0)
            dist = float(c.get("distance_mpc", c.get("dL", 0)) or 0)
            lum_k = float(c.get("luminosity_k", 0) or 0)

            # Real spatial overlap: skymap probability density at the galaxy's
            # HEALPix pixel, integrated over a 1 deg^2 follow-up field of view
            # (clipped to 1). Zero when the galaxy lies outside the 90% region.
            nside_skymap = int(getattr(skymap, "nside", 512) or 512)
            pixel_area_deg2 = (4.0 * math.pi / (12.0 * nside_skymap * nside_skymap)) * (180.0 / math.pi) ** 2
            try:
                pix_idx = int(ah.lonlat_to_healpix(
                    ra * u.deg, dec * u.deg, nside_skymap, order='nested'
                ))
            except Exception:
                pix_idx = -1
            p_pixel = float(prob_lookup.get(pix_idx, 0.0))
            prob_overlap = min(1.0, (p_pixel / pixel_area_deg2) * 1.0)

            # Windowed airmass over the 2-hour observation window (M7.5)
            obs = integrated_airmass(ra, dec, site_lat, site_lon, duration_hours=2.0)
            X_i = float(obs.get("mean_airmass", 1.5))

            # Lunar proximity penalty via astropy get_body (M7.3)
            lunar = lunar_penalty(ra, dec)
            L_moon = float(lunar.get("lunar_penalty", 0.0))

            # Schechter luminosity function weight (M7.1).  Skipped when the
            # active class disables host-mass weighting (beta = 0).
            w_schechter = schechter_weight(lum_k, l_star=l_star, alpha=schechter_alpha) if (lum_k > 0 and beta > 0) else 0.0

            # Distance-based kilonova detectability proxy (M7.6).  Skipped
            # when the active class disables it (zeta = 0: the KN peak-magnitude
            # scale is meaningless for GRB afterglows and neutrinos).
            if zeta > 0:
                snr_info = estimate_kilonova_snr(dist, peak_mag=peak_mag)
                snr_proxy = float(snr_info.get("snr_proxy", 0.0))
                apparent_mag = snr_info.get("apparent_mag")
            else:
                snr_proxy, apparent_mag = 0.0, None

            # R-band atmospheric extinction in magnitudes (M7.4)
            extinction_mag = atmospheric_extinction(X_i, zenith_extinction=k_ext)

            terms = {
                "spatial": prob_overlap,
                "schechter": w_schechter,
                "airmass": X_i,
                "cloud": f_cloud,
                "grb_boost": 0.0,  # applied later by the validator stage
                "snr": snr_proxy,
                "lunar": L_moon,
                "flux": trig_flux,
                "signalness": trig_signalness,
            }
            composite_score = compute_full_score(terms, formula_weights)

            g = Galaxy(
                name=name,
                ra_deg=ra,
                dec_deg=dec,
                redshift=dist / 4400.0 if dist > 0 else 0.0,  # rough Hubble law
                distance_mpc=dist,
                probability_overlap=prob_overlap,
                pgc=c.get("pgc"),
                luminosity_k=lum_k,
                catalog_source=catalog_source,
                observability={
                    "mean_airmass": X_i,
                    "min_altitude": obs.get("min_altitude"),
                    "observable_fraction": obs.get("observable_fraction"),
                    "extinction_mag": round(extinction_mag, 4),
                    "moon_separation_deg": lunar.get("moon_separation_deg"),
                    "moon_safe": lunar.get("moon_safe"),
                    "apparent_mag": apparent_mag,
                    "snr_proxy": snr_proxy,
                    "flux_proxy": trig_flux,
                    "signalness": trig_signalness,
                },
            )
            g.composite_score = composite_score
            g.score_breakdown = ScoreBreakdown(
                weights={
                    **formula_weights,
                    "schechter_l_star": l_star,
                    "schechter_alpha": schechter_alpha,
                    "zenith_extinction": k_ext,
                    "peak_kilonova_mag": peak_mag,
                },
                terms=terms,
                total=float(composite_score),
            )
            galaxies.append(g)

        return sorted(galaxies, key=lambda g: getattr(g, 'composite_score', 0), reverse=True)[:5]

    def _skymap_geometry(self, skymap: HealpixSkymap):
        """Derive the 90%-region centroid and a pixel->probability lookup map.

        The centroid is the probability-weighted mean of the supercell pixel
        centers converted to Cartesian coordinates (robust across the RA=0/360
        seam).  Returns (ra_center, dec_center, prob_lookup) where prob_lookup
        maps HEALPix nested pixel indices to their per-pixel probability.
        """
        indices = list(getattr(skymap, "supercell_indices", []) or [])
        probs = list(getattr(skymap, "probdensity", []) or [])

        if indices and probs and len(indices) == len(probs):
            nside = int(getattr(skymap, "nside", 512) or 512)
            try:
                ra_arr, dec_arr = ah.healpix_to_lonlat(
                    np.asarray(indices, dtype=np.int64), nside, order='nested'
                )
                ra_deg = np.asarray(ra_arr.deg)
                dec_deg = np.asarray(dec_arr.deg)
                p = np.asarray(probs, dtype=float)
                # Cartesian weighted mean (seam-safe)
                ra_rad = np.radians(ra_deg)
                dec_rad = np.radians(dec_deg)
                x = float(np.sum(p * np.cos(dec_rad) * np.cos(ra_rad)))
                y = float(np.sum(p * np.cos(dec_rad) * np.sin(ra_rad)))
                z = float(np.sum(p * np.sin(dec_rad)))
                norm = math.sqrt(x * x + y * y + z * z)
                if norm > 0:
                    ra_c = math.degrees(math.atan2(y, x)) % 360.0
                    dec_c = math.degrees(math.asin(max(-1.0, min(1.0, z / norm))))
                    lookup = {int(idx): float(pi) for idx, pi in zip(indices, p)}
                    return float(ra_c), float(dec_c), lookup
            except Exception as e:
                print(f"[SYS] skymap geometry failed ({e}); falling back to first supercell")

        # Fallback: center of the first supercell pixel
        if indices:
            nside = int(getattr(skymap, "nside", 512) or 512)
            try:
                ra0, dec0 = ah.healpix_to_lonlat(int(indices[0]), nside, order='nested')
                return float(ra0.deg), float(dec0.deg), {}
            except Exception:
                pass
        return 197.45, -23.38, {}

    @tool
    def check_observatory_weather(self) -> ObservatoryWeather:
        """Queries Open-Meteo for cloud cover at the observatory's GPS coordinates.

        Results are cached for 10 minutes so multiple pipeline stages (weather
        step, scoring, dome-safety re-check) share a single API call.
        """
        cached = self._weather_cache
        if cached is not None and self._weather_cache_time is not None:
            age_s = (Time.now() - self._weather_cache_time).sec
            if age_s < 600.0:
                return cached

        api_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.observatory_location.lat.value,
            "longitude": self.observatory_location.lon.value,
            "current": "cloudcover,relativehumidity_2m,dewpoint_2m",
            "forecast_days": 1
        }
        try:
            response = requests.get(api_url, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
            cloud_cover = data["current"]["cloudcover"]
            humidity = data["current"]["relativehumidity_2m"]
            seeing_conditions = "clear" if cloud_cover < 30 else ("partly cloudy" if cloud_cover < 70 else "overcast")
            dome_safe = humidity < 85.0
            wx = ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=float(cloud_cover),
                seeing_conditions=seeing_conditions,
                humidity_pct=float(humidity),
                dome_safe=dome_safe
            )
            self._weather_cache = wx
            self._weather_cache_time = Time.now()
            return wx
        except requests.exceptions.RequestException as e:
            print(f"Error fetching weather data: {e}")
            return ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=0.0,
                seeing_conditions="unknown (API fallback)",
                humidity_pct=0.0,
                dome_safe=True
            )

    def get_weather_cached(self) -> Optional[ObservatoryWeather]:
        """Return the last cached weather snapshot without triggering network I/O."""
        return self._weather_cache

    @tool
    def check_dome_safety(self) -> ObservatoryWeather:
        """Re-checks weather conditions mid-sequence for emergency abort (v3 PRD M9.5).

        Emergency abort thresholds: humidity > 85% or cloud cover > 40%.
        Always performs a fresh API call (bypasses the TTL cache) so a
        deterioration between slew-script generation and human approval
        is caught. Called between slew script generation and human approval.
        """
        api_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.observatory_location.lat.value,
            "longitude": self.observatory_location.lon.value,
            "current": "cloudcover,relativehumidity_2m,dewpoint_2m",
            "forecast_days": 1
        }
        try:
            response = requests.get(api_url, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
            cloud_cover = float(data["current"]["cloudcover"])
            humidity = float(data["current"]["relativehumidity_2m"])
            dome_safe = humidity <= 85.0 and cloud_cover <= 40.0
            wx = ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=cloud_cover,
                seeing_conditions="clear" if cloud_cover < 30 else ("partly cloudy" if cloud_cover < 70 else "overcast"),
                humidity_pct=humidity,
                dome_safe=dome_safe
            )
            self._weather_cache = wx
            self._weather_cache_time = Time.now()
            return wx
        except requests.exceptions.RequestException as e:
            print(f"[SYS] dome safety re-check failed ({e}); assuming last known conditions")
            return self.get_weather_cached() or ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=0.0,
                seeing_conditions="unknown (re-check failed)",
                humidity_pct=0.0,
                dome_safe=True,
            )

    @tool
    def generate_telescope_slew_script(self, galaxies: List[Galaxy]) -> TelescopeSlewScript:
        """Generates an ASCOM/INDI XML slew script with TSP-optimized ordering (v3 PRD M7.2).

        Targets are reordered with a greedy nearest-neighbor heuristic on the
        local alt/az sphere to minimize total slew distance before the script
        is written.
        """
        targets = [
            {"name": g.name, "ra": g.ra_deg, "dec": g.dec_deg}
            for g in galaxies
        ]
        site_lat = self.observatory_location.lat.value
        site_lon = self.observatory_location.lon.value
        ordered = optimize_slew_order(targets, site_lat, site_lon)

        root = ET.Element("ASCOM_INDI_SlewScript")
        root.set("generatedAt", datetime.datetime.utcnow().isoformat())
        root.set("observatory", self.observatory_name)
        root.set("slewOptimization", "nearest-neighbor-TSP")

        current_time = Time.now()
        altaz_frame = AltAz(obstime=current_time, location=self.observatory_location)

        for i, t in enumerate(ordered):
            target = ET.SubElement(root, "Target", id=str(i + 1))
            ET.SubElement(target, "Name").text = str(t.get("name", f"Target {i+1}"))
            ET.SubElement(target, "RA_Deg").text = str(t.get("ra", 0.0))
            ET.SubElement(target, "Dec_Deg").text = str(t.get("dec", 0.0))
            ET.SubElement(target, "Priority").text = str(len(ordered) - i)
            ET.SubElement(target, "SlewDistance_Deg").text = str(t.get("slew_distance_deg", 0.0))

            # Visibility check at generation time
            try:
                target_coord = SkyCoord(ra=float(t["ra"]) * u.deg, dec=float(t["dec"]) * u.deg, frame='icrs')
                target_altaz = target_coord.transform_to(altaz_frame)
                status = "Visible" if target_altaz.alt.value > 30 else "Low Horizon"
            except Exception:
                status = "Unknown"
            ET.SubElement(target, "Status").text = status

        script_content = ET.tostring(root, encoding='unicode')
        return TelescopeSlewScript(
            script_content=script_content,
            target_galaxies=galaxies,
        )

    @tool
    def suggest_tiling(self, skymap: HealpixSkymap, fov_deg: float = 1.0) -> Dict[str, Any]:
        """Suggests a tiling pattern for large error regions (M13).

        For point-localized events (GRB/neutrino) with degree-scale errors,
        ranking individual hosts is less useful than covering the region.
        Returns a 3×3 grid of pointings centered on the 90% centroid, each
        with RA/Dec and approximate probability coverage. Advisory only.
        """
        try:
            ra_c, dec_c, _ = self._skymap_geometry(skymap)
            # 3×3 grid, 1 FOV spacing (configurable). Simple, no overlap calc.
            fov = max(0.5, min(2.0, float(fov_deg or 1.0)))
            tiles = []
            for d_dec in (-fov, 0, fov):
                for d_ra in (-fov, 0, fov):
                    # RA wrap, Dec clamp
                    ra = (ra_c + d_ra / max(0.1, math.cos(math.radians(dec_c)))) % 360.0
                    dec = max(-90.0, min(90.0, dec_c + d_dec))
                    tiles.append({"ra": round(ra, 4), "dec": round(dec, 4), "fov_deg": fov})
            return {
                "center_ra": round(ra_c, 4),
                "center_dec": round(dec_c, 4),
                "fov_deg": fov,
                "tiles": tiles,
                "note": "3×3 grid covering ~9 deg²; use for wide-field tiling when host ranking is ambiguous.",
            }
        except Exception as e:
            return {"error": str(e), "tiles": []}

    @tool
    def write_observation_header(self, galaxies: List[Galaxy], weather: Optional[ObservatoryWeather] = None,
                                 slew_script: str = "") -> Dict[str, str]:
        """Packages the decision into a standardized FITS observation header (v3 PRD M9.1).

        Uses ``astropy.io.fits.Header`` so the card layout is standard-compliant
        and importable by any downstream analysis pipeline.  Returns the header
        text plus a base64-encoded FITS block for the run record.
        """
        import base64
        from astropy.io import fits as afits

        header = afits.Header()
        header["ORIGIN"] = ("KilonovaScout v3", "Autonomous targeting pipeline")
        header["OBSERVAT"] = (self.observatory_name[:18], "Observatory name")
        header["OBSGEO-B"] = (round(self.observatory_location.lat.value, 6), "Site latitude (deg)")
        header["OBSGEO-L"] = (round(self.observatory_location.lon.value, 6), "Site longitude (deg)")
        header["OBSGEO-H"] = (round(float(self.observatory_location.height.to_value(u.m)), 2), "Site altitude (m)")
        header["DATE-OBS"] = (datetime.datetime.utcnow().isoformat() + "Z", "Decision UTC timestamp")
        header["NTARGET"] = (len(galaxies), "Number of ranked targets")

        for i, g in enumerate(galaxies[:5], start=1):
            header[f"TGT{i}-NM"] = (g.name[:28], f"Target {i} name")
            header[f"TGT{i}-RA"] = (round(g.ra_deg, 6), f"Target {i} RA (deg)")
            header[f"TGT{i}-DE"] = (round(g.dec_deg, 6), f"Target {i} Dec (deg)")
            header[f"TGT{i}-PR"] = (round(float(getattr(g, "composite_score", 0.0) or 0.0), 6), f"Target {i} score")

        if weather is not None:
            header["CLD-CVR"] = (round(weather.cloud_cover_percent, 2), "Cloud cover (%)")
            header["HUMIDITY"] = (round(weather.humidity_pct, 2), "Relative humidity (%)")
            header["DOME-SAF"] = (bool(weather.dome_safe), "Dome safety flag")

        header["SLEW-XML"] = (bool(slew_script), "Slew script attached to run record")

        header_text = "\n".join(str(card) for card in header.cards)
        try:
            hdul = afits.HDUList([afits.PrimaryHDU(header=header)])
            buf = io.BytesIO()
            hdul.writeto(buf)
            fits_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            print(f"[SYS] FITS serialization failed ({e}); header text only")
            fits_b64 = ""

        return {"header_text": header_text, "fits_base64": fits_b64}

    # ── M7 standalone tool wrappers (PRD table expects these names as @tool) ──
    @tool
    def schechter_weight_tool(self, l_k: float, l_star: float = 1.0e10, alpha: float = 1.0) -> float:
        """Schechter weight (PRD M7.1) — wrapper so the standalone function is also an instance tool."""
        return schechter_weight(l_k, l_star=l_star, alpha=alpha)

    @tool
    def atmospheric_extinction_tool(self, airmass: float, zenith_extinction: float = 0.12) -> float:
        """Atmospheric extinction R-band (PRD M7.4)."""
        return atmospheric_extinction(airmass, zenith_extinction=zenith_extinction)

    @tool
    def estimate_kilonova_snr_tool(self, distance_mpc: float, peak_mag: float = 17.5) -> Dict[str, float]:
        """Kilonova SNR proxy (PRD M7.6)."""
        return estimate_kilonova_snr(distance_mpc, peak_mag=peak_mag)

    @tool
    def lunar_penalty_tool(self, target_ra: float, target_dec: float) -> Dict[str, float]:
        """Lunar penalty (M7.3 implementation)."""
        return lunar_penalty(target_ra, target_dec)

    @tool
    def check_lunar_separation_tool(self, target_ra: float, target_dec: float) -> Dict[str, float]:
        """PRD-spec name for lunar separation (M7.3)."""
        return check_lunar_separation(target_ra, target_dec)

    @tool
    def integrated_airmass_tool(self, target_ra: float, target_dec: float, site_lat: float, site_lon: float, duration_hours: float = 2.0) -> Dict[str, float]:
        """Windowed airmass (PRD M7.5)."""
        return integrated_airmass(target_ra, target_dec, site_lat, site_lon, duration_hours=duration_hours)

    @tool
    def optimize_slew_order_tool(self, targets: List[Dict[str, Any]], site_lat: float, site_lon: float) -> List[Dict[str, Any]]:
        """TSP slew order (PRD M7.2)."""
        return optimize_slew_order(targets, site_lat, site_lon)

    # ── M13 new tools (crossmatch_ztf, em_bright_fetcher, tiling_planner) ──
    @tool
    def crossmatch_ztf(self, ra: float, dec: float, radius_arcsec: float = 5.0) -> Dict[str, Any]:
        """ZTF crossmatch — check for recent transient at host position (M13)."""
        try:
            import requests
            url = "https://api.alerce.online/ztf/v1/objects"
            params = {"ra": float(ra), "dec": float(dec), "radius": float(radius_arcsec) / 3600.0}
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", data.get("objects", []))
            count = len(items) if isinstance(items, list) else 0
            if count > 0:
                return {"found": True, "count": count, "note": f"{count} ZTF source(s) within {radius_arcsec}″ — possible counterpart.", "catalog": "ZTF/ALeRCE"}
            return {"found": False, "count": 0, "note": "No ZTF transient within search radius.", "catalog": "ZTF/ALeRCE"}
        except Exception as e:
            return {"found": False, "count": 0, "note": f"ZTF check unavailable: {e}", "catalog": "ZTF/ALeRCE"}

    @tool
    def em_bright_fetcher(self, superevent_id: str) -> Dict[str, Any]:
        """Fetch GraceDB em_bright.json for tighter distance prior (M13)."""
        try:
            import requests
            sid = (superevent_id or "").split("/")[-1].split("#")[-1]
            if not sid.startswith("S"):
                # Try to extract S-id via regex fallback
                import re
                m = re.search(r"S\d{6}[a-z]+", superevent_id or "")
                sid = m.group(0) if m else sid
            if not sid.startswith("S"):
                return {"fetched": False, "note": "No GraceDB S-id in ivorn — skipping em_bright fetch."}
            url = f"https://gracedb.ligo.org/api/superevents/{sid}/files/em_bright.json"
            resp = requests.get(url, timeout=8)
            if resp.status_code == 404:
                return {"fetched": False, "note": f"em_bright.json not found for {sid}"}
            resp.raise_for_status()
            data = resp.json()
            return {"fetched": True, "data": data, "note": f"em_bright for {sid}: HasNS={data.get('HasNS')}, HasRemnant={data.get('HasRemnant')}"}
        except Exception as e:
            return {"fetched": False, "note": f"em_bright fetch failed: {e}"}

    @tool
    def tiling_planner(self, skymap: HealpixSkymap, fov_deg: float = 1.0) -> Dict[str, Any]:
        """Tiling planner for point tier (M13) — alias for suggest_tiling per PRD spec name."""
        return self.suggest_tiling(skymap, fov_deg=fov_deg)

    @tool
    def send_sms_alert(self, message: str) -> AgentOutput:
        """Mocks sending an SMS alert to the astronomer."""
        print(f"[SMS Alert Mock] Sending to Astronomer: {message}")
        return AgentOutput(
            message=f"SMS alert sent: {message}",
            details={"recipient": "Astronomer", "channel": "mock_sms"},
            action_status="success",
        )
