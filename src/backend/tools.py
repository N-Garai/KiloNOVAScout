
import datetime
import json
import random
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import healpy as hp
import numpy as np
import requests
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.time import Time
from astropy import units as u

from .models import HealpixSkymap, Galaxy, ObservatoryWeather, TelescopeSlewScript, AgentOutput


class KilonovaScoutTools:
    """Collection of tools for the KilonovaScout agent."""

    def __init__(self, observatory_name: str = "Palomar", lat: float = 33.356, lon: float = -116.865, alt: float = 1706):
        self.observatory_name = observatory_name
        self.observatory_location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt * u.m)

    def parse_healpix_map(self, skymap_url: str) -> HealpixSkymap:
        """Parses a HEALPix skymap from a FITS file URL and extracts key information.
        This is a simplified mock for hackathon demo purposes.
        """
        # In a real scenario, this would download and parse the FITS file using `healpy.read_map`
        # and perform localization calculations.
        # For this hackathon, we'll simulate a parsed map.
        nside = 512  # Example nside
        npix = hp.nside2npix(nside)
        probdensity = [random.random() for _ in range(100)]  # Mock some values
        supercell_indices = random.sample(range(npix), 5) # Mock 5 significant regions
        localization_area_sq_deg = random.uniform(10, 500) # Mock area

        return HealpixSkymap(
            url=skymap_url,
            nside=nside,
            probdensity=probdensity,
            supercell_indices=supercell_indices,
            localization_area_sq_deg=localization_area_sq_deg,
        )

    def query_glade_catalog(self, skymap: HealpixSkymap) -> List[Galaxy]:
        """Queries a mock GLADE+ catalog for galaxies within the skymap's high-probability regions.
        This is a simplified mock for hackathon demo purposes.
        """
        # In a real scenario, this would involve spatial queries against a galaxy database
        # using the skymap data.
        mock_galaxies = [
            Galaxy(name="NGC 4993", ra_deg=197.451, dec_deg=-23.382, redshift=0.0097, distance_mpc=40.0, probability_overlap=0.95),
            Galaxy(name="ESO 445-IG29", ra_deg=197.5, dec_deg=-23.5, redshift=0.010, distance_mpc=41.0, probability_overlap=0.88),
            Galaxy(name="Galaxy A", ra_deg=random.uniform(180, 210), dec_deg=random.uniform(-30, -15), redshift=random.uniform(0.005, 0.015), distance_mpc=random.uniform(20, 60), probability_overlap=random.uniform(0.6, 0.8)),
            Galaxy(name="Galaxy B", ra_deg=random.uniform(180, 210), dec_deg=random.uniform(-30, -15), redshift=random.uniform(0.005, 0.015), distance_mpc=random.uniform(20, 60), probability_overlap=random.uniform(0.5, 0.7)),
            Galaxy(name="Galaxy C", ra_deg=random.uniform(180, 210), dec_deg=random.uniform(-30, -15), redshift=random.uniform(0.005, 0.015), distance_mpc=random.uniform(20, 60), probability_overlap=random.uniform(0.4, 0.6)),
        ]
        return sorted(mock_galaxies, key=lambda g: g.probability_overlap, reverse=True)[:5]

    def check_observatory_weather(self) -> ObservatoryWeather:
        """Queries Open-Meteo for cloud cover at the observatory's GPS coordinates."""
        api_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.observatory_location.lat.value,
            "longitude": self.observatory_location.lon.value,
            "current": "cloudcover",
            "forecast_days": 1
        }
        try:
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            data = response.json()
            cloud_cover = data["current"]["cloudcover"]
            seeing_conditions = "clear" if cloud_cover < 30 else ("partly cloudy" if cloud_cover < 70 else "overcast")
            return ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=float(cloud_cover),
                seeing_conditions=seeing_conditions
            )
        except requests.exceptions.RequestException as e:
            print(f"Error fetching weather data: {e}")
            return ObservatoryWeather(
                observatory_name=self.observatory_name,
                latitude=self.observatory_location.lat.value,
                longitude=self.observatory_location.lon.value,
                cloud_cover_percent=100.0, # Assume overcast on error
                seeing_conditions="unknown (API error)"
            )

    def generate_telescope_slew_script(self, galaxies: List[Galaxy]) -> TelescopeSlewScript:
        """Generates a mock ASCOM/INDI XML slew script for the robotic telescope.
        """
        root = ET.Element("ASCOM_INDI_SlewScript")
        root.set("generatedAt", datetime.datetime.utcnow().isoformat())
        root.set("observatory", self.observatory_name)

        for i, galaxy in enumerate(galaxies):
            target = ET.SubElement(root, "Target", id=str(i + 1))
            ET.SubElement(target, "Name").text = galaxy.name
            ET.SubElement(target, "RA_Deg").text = str(galaxy.ra_deg)
            ET.SubElement(target, "Dec_Deg").text = str(galaxy.dec_deg)
            ET.SubElement(target, "Priority").text = str(5 - i) # Higher probability gets higher priority

            # Simulate visibility check (simplified)
            current_time = Time.now()
            target_coord = SkyCoord(ra=galaxy.ra_deg * u.deg, dec=galaxy.dec_deg * u.deg, frame='icrs')
            altaz_frame = AltAz(obstime=current_time, location=self.observatory_location)
            target_altaz = target_coord.transform_to(altaz_frame)

            if target_altaz.alt.value > 30:
                ET.SubElement(target, "Status").text = "Visible"
            else:
                ET.SubElement(target, "Status").text = "Low Horizon"

        script_content = ET.tostring(root, encoding='unicode', pretty_print=True)
        return TelescopeSlewScript(
            script_content=script_content,
            target_galaxies=galaxies,
        )

    def send_sms_alert(self, message: str) -> AgentOutput:
        """Mocks sending an SMS alert to the astronomer.
        In a real scenario, this would integrate with Twilio or similar service.
        """
        print(f"[SMS Alert Mock] Sending to Astronomer: {message}")
        return AgentOutput(
            message=f"SMS alert sent: {message}",
            details={"recipient": "Astronomer", "channel": "mock_sms"},
            action_status="success",
        )
