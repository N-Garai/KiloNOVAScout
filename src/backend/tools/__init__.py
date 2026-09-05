"""KilonovaScoutTools - Tool collection for the orchestrator agent.

This module wraps the specialized tools from astrometry_tools, network_tools, and hardware_tools
into a unified interface for the master orchestrator agent.

All methods are decorated with @strands.tool so they can be passed directly
to a strands.Agent as callable tools.
"""

import datetime
import io
import json
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


def _load_scoring_weights() -> dict:
    """Load scoring weights from config/ with a robust fallback."""
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
        "spatial_prior": 1.0,
        "galaxy_mass_prior": 0.6,
        "airmass_penalty": 0.2,
        "cloud_cover_penalty": 0.5,
        "grb_coincidence_boost": 3.0
    }


class KilonovaScoutTools:
    """Collection of tools for the KilonovaScout agent."""

    def __init__(self, observatory_name: str = "Palomar", lat: float = 33.356, lon: float = -116.865, alt: float = 1706):
        self.observatory_name = observatory_name
        self.observatory_location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt * u.m)

    @tool
    def parse_healpix_map(self, skymap_url: str) -> HealpixSkymap:
        """Parses a HEALPix skymap from a FITS file URL and extracts key information.

        Falls back to a synthetic GW170817-like skymap when the download
        fails (e.g. GraceDB requires authentication), keeping the demo
        reproducible without network access to the skymap host.
        """
        try:
            with urllib.request.urlopen(skymap_url) as response:
                fits_bytes = response.read()
        except Exception as e:
            print(f"[SYS] skymap download failed ({e}); using synthetic GW170817 fallback.")
            return HealpixSkymap(
                url=skymap_url,
                nside=512,
                probdensity=[0.95, 0.88, 0.85, 0.75, 0.70],
                supercell_indices=[1, 2, 3, 4, 5],
                localization_area_sq_deg=31.0,
            )

        table = Table.read(io.BytesIO(fits_bytes))
        prob = np.array(table['PROB'])
        distmu = np.array(table['DISTMU'])
        distsigma = np.array(table['DISTSIGMA'])

        sorted_idx = np.argsort(prob)[::-1]
        cum_prob = np.cumsum(prob[sorted_idx])
        top_90_idx = sorted_idx[cum_prob <= 0.90]

        nside = ah.npix_to_nside(len(prob))
        ra, dec = ah.healpix_to_lonlat(top_90_idx, nside, order='nested')

        mean_dist = float(np.average(distmu[top_90_idx], weights=prob[top_90_idx]))
        dist_std = float(np.average(distsigma[top_90_idx], weights=prob[top_90_idx]))

        return HealpixSkymap(
            url=skymap_url,
            nside=int(nside),
            probdensity=prob[top_90_idx].tolist(),
            supercell_indices=top_90_idx.tolist(),
            localization_area_sq_deg=float(np.sum(prob[top_90_idx]) * (4 * np.pi / len(prob)) * (180 / np.pi) ** 2),
        )

    @tool
    def query_glade_catalog(self, skymap: HealpixSkymap) -> List[Galaxy]:
        """Queries a mock GLADE+ catalog for galaxies within the skymap's high-probability regions."""
        # In a real scenario, this would involve spatial queries against a galaxy database
        # using the skymap data. For the hackathon demo, we return mock galaxies.
        mock_galaxies = [
            Galaxy(name="NGC 4993", ra_deg=197.451, dec_deg=-23.382, redshift=0.0097, distance_mpc=40.0, probability_overlap=0.95, pgc="PGC 045410", luminosity_k=1e10),
            Galaxy(name="ESO 445-IG29", ra_deg=197.5, dec_deg=-23.5, redshift=0.010, distance_mpc=41.0, probability_overlap=0.88, pgc="PGC 045411", luminosity_k=8e9),
            Galaxy(name="Galaxy A", ra_deg=197.4, dec_deg=-23.4, redshift=0.009, distance_mpc=38.0, probability_overlap=0.85, pgc="PGC 045412", luminosity_k=5e9),
            Galaxy(name="Galaxy B", ra_deg=197.6, dec_deg=-23.2, redshift=0.011, distance_mpc=42.0, probability_overlap=0.75, pgc="PGC 045413", luminosity_k=3e9),
            Galaxy(name="Galaxy C", ra_deg=197.3, dec_deg=-23.6, redshift=0.008, distance_mpc=37.0, probability_overlap=0.70, pgc="PGC 045414", luminosity_k=2e9),
        ]

        # Apply composite scoring formula from PRD
        # Score = w1 * P_spatial + w2 * log(L_K / L*) - w3 * X_airmass - w4 * C_cloud + w5 * B_GRB
        weights = _load_scoring_weights()

        # Schechter characteristic luminosity L* (approximate for K-band)
        L_STAR = 5.0e10  # K-band solar luminosities

        # Get current weather for cloud fraction
        try:
            weather = self.check_observatory_weather()
            f_cloud = min(1.0, max(0.0, weather.cloud_cover_percent / 100.0))
        except Exception:
            f_cloud = 0.5  # fallback

        for galaxy in mock_galaxies:
            # Spatial containment probability (normalized to 0-1)
            P_spatial = galaxy.probability_overlap

            # Mass/luminosity weight (L_K / L*)
            L_ratio = galaxy.luminosity_k / L_STAR if galaxy.luminosity_k else 0.1

            # Airmass penalty (need to calculate for current time)
            current_time = Time.now()
            target_coord = SkyCoord(ra=galaxy.ra_deg * u.deg, dec=galaxy.dec_deg * u.deg, frame='icrs')
            altaz_frame = AltAz(obstime=current_time, location=self.observatory_location)
            target_altaz = target_coord.transform_to(altaz_frame)
            X_i = float(target_altaz.secz.value) if target_altaz.alt.value > 0 else 10.0

            # Coincidence boost (mock - would check GRB catalog in production)
            B_i = 1.0  # Default, would be 3.0 if GRB coincidence detected

            # Composite score from PRD formula (additive weighted sum)
            composite_score = (
                weights.get('spatial_prior', 1.0) * P_spatial +
                weights.get('galaxy_mass_prior', 0.6) * float(np.log10(L_ratio + 1e-12)) +
                -weights.get('airmass_penalty', 0.2) * X_i +
                -weights.get('cloud_cover_penalty', 0.5) * f_cloud +
                (weights.get('grb_coincidence_boost', 3.0) if B_i > 1.0 else 0.0)
            )

            galaxy.composite_score = composite_score
            galaxy.score_breakdown = ScoreBreakdown(
                weights={
                    "spatial_prior": weights.get('spatial_prior', 1.0),
                    "galaxy_mass_prior": weights.get('galaxy_mass_prior', 0.6),
                    "airmass_penalty": weights.get('airmass_penalty', 0.2),
                    "cloud_cover_penalty": weights.get('cloud_cover_penalty', 0.5),
                    "grb_coincidence_boost": weights.get('grb_coincidence_boost', 3.0),
                },
                terms={
                    "spatial": P_spatial,
                    "mass": float(np.log10(L_ratio + 1e-12)),
                    "airmass": X_i,
                    "cloud": f_cloud,
                    "grb_boost": B_i,
                },
                total=float(composite_score),
            )

        return sorted(mock_galaxies, key=lambda g: getattr(g, 'composite_score', 0), reverse=True)[:5]

    @tool
    def check_observatory_weather(self) -> ObservatoryWeather:
        """Queries Open-Meteo for cloud cover at the observatory's GPS coordinates."""
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
            return ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=float(cloud_cover),
                seeing_conditions=seeing_conditions,
                humidity_pct=float(humidity),
                dome_safe=dome_safe
            )
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

    @tool
    def generate_telescope_slew_script(self, galaxies: List[Galaxy]) -> TelescopeSlewScript:
        """Generates a mock ASCOM/INDI XML slew script for the robotic telescope."""
        root = ET.Element("ASCOM_INDI_SlewScript")
        root.set("generatedAt", datetime.datetime.utcnow().isoformat())
        root.set("observatory", self.observatory_name)

        for i, galaxy in enumerate(galaxies):
            target = ET.SubElement(root, "Target", id=str(i + 1))
            ET.SubElement(target, "Name").text = galaxy.name
            ET.SubElement(target, "RA_Deg").text = str(galaxy.ra_deg)
            ET.SubElement(target, "Dec_Deg").text = str(galaxy.dec_deg)
            ET.SubElement(target, "Priority").text = str(5 - i)

            # Simulate visibility check
            current_time = Time.now()
            target_coord = SkyCoord(ra=galaxy.ra_deg * u.deg, dec=galaxy.dec_deg * u.deg, frame='icrs')
            altaz_frame = AltAz(obstime=current_time, location=self.observatory_location)
            target_altaz = target_coord.transform_to(altaz_frame)

            if target_altaz.alt.value > 30:
                ET.SubElement(target, "Status").text = "Visible"
            else:
                ET.SubElement(target, "Status").text = "Low Horizon"

        script_content = ET.tostring(root, encoding='unicode')
        return TelescopeSlewScript(
            script_content=script_content,
            target_galaxies=galaxies,
        )

    @tool
    def send_sms_alert(self, message: str) -> AgentOutput:
        """Mocks sending an SMS alert to the astronomer."""
        print(f"[SMS Alert Mock] Sending to Astronomer: {message}")
        return AgentOutput(
            message=f"SMS alert sent: {message}",
            details={"recipient": "Astronomer", "channel": "mock_sms"},
            action_status="success",
        )
