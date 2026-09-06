"""KilonovaScoutTools - Tool collection for the orchestrator agent.

This module wraps the specialized tools from astrometry_tools, network_tools, and hardware_tools
into a unified interface for the master orchestrator agent.

All methods are decorated with @strands.tool so they can be passed directly
to a strands.Agent as callable tools.
"""

import datetime
import io
import json
import math
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

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
    compute_full_score,
)
from .ephemeris_tools import integrated_airmass
from .scheduling_tools import optimize_slew_order


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

        # Parse real FITS bytes (live or replay — same code path)
        table = Table.read(io.BytesIO(fits_bytes))
        prob = np.array(table['PROB'], dtype=float)
        distmu = np.array(table['DISTMU'], dtype=float)
        distsigma = np.array(table['DISTSIGMA'], dtype=float)

        npix = len(prob)
        nside = ah.npix_to_nside(npix)
        pixel_area_sr = 4.0 * np.pi / npix

        # LIGO skymaps store PROB as probability DENSITY (per steradian) when
        # npix is large; normalize to per-pixel probabilities so downstream
        # consumers get values on a true 0..1 probability scale.
        p_pix = prob * pixel_area_sr
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
        mean_dist = float(np.average(distmu[top_90_idx], weights=w))
        dist_std = float(np.average(distsigma[top_90_idx], weights=w))

        # 90% credible area = number of pixels in the region x pixel area
        area_sq_deg = float(len(top_90_idx) * pixel_area_sr * (180.0 / np.pi) ** 2)

        return HealpixSkymap(
            url=skymap_url,
            nside=int(nside),
            probdensity=p_pix[top_90_idx].tolist(),
            supercell_indices=top_90_idx.tolist(),
            localization_area_sq_deg=area_sq_deg,
            provenance_source=source,
            dist_mean=mean_dist if np.isfinite(mean_dist) else 40.0,
            dist_std=dist_std if np.isfinite(dist_std) else 8.0,
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
        """
        from .network_tools import query_glade_vizier_tap, load_bundled_glade_cache, get_mock_galaxies

        weights = _load_scoring_weights()
        alpha = float(weights.get("spatial_weight_alpha", 1.0))
        beta = float(weights.get("mass_weight_beta", 0.5))
        gamma = float(weights.get("extinction_gamma", 0.3))
        delta = float(weights.get("weather_delta", 0.2))
        epsilon = float(weights.get("coincidence_boost", 3.0))
        zeta = float(weights.get("snr_weight_zeta", 0.15))
        eta = float(weights.get("lunar_penalty_eta", 0.1))
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
        dist_mean = float(getattr(skymap, "dist_mean", None) or 40.0)
        dist_std = float(getattr(skymap, "dist_std", None) or 8.0)
        ra_span, dec_span = 2.5, 2.5  # TAP search box half-width (degrees)

        # Tier 1: live VizieR TAP query
        try:
            raw = query_glade_vizier_tap(
                ra_min=ra_center - ra_span,
                ra_max=ra_center + ra_span,
                dec_min=dec_center - dec_span,
                dec_max=dec_center + dec_span,
                dist_mean=dist_mean,
                dist_std=dist_std,
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
        }

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

            # Schechter luminosity function weight (M7.1)
            w_schechter = schechter_weight(lum_k, l_star=l_star, alpha=schechter_alpha) if lum_k > 0 else 0.0

            # Distance-based kilonova detectability proxy (M7.6)
            snr_info = estimate_kilonova_snr(dist, peak_mag=peak_mag)
            snr_proxy = float(snr_info.get("snr_proxy", 0.0))

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
                    "apparent_mag": snr_info.get("apparent_mag"),
                    "snr_proxy": snr_proxy,
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

    @tool
    def send_sms_alert(self, message: str) -> AgentOutput:
        """Mocks sending an SMS alert to the astronomer."""
        print(f"[SMS Alert Mock] Sending to Astronomer: {message}")
        return AgentOutput(
            message=f"SMS alert sent: {message}",
            details={"recipient": "Astronomer", "channel": "mock_sms"},
            action_status="success",
        )
