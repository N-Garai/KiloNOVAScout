from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
from strands import Agent, tool
import json

@tool
def calculate_target_observability(targets_json: str, site_lat: float, site_lon: float, site_elevation: float) -> list:
    """Calculates instantaneous altitude and airmass for candidate targets from observatory coordinates."""
    targets = json.loads(targets_json)
    location = EarthLocation(lat=site_lat * u.deg, lon=site_lon * u.deg, height=site_elevation * u.m)
    now = Time.now()
    altaz_frame = AltAz(obstime=now, location=location)
      
    observable = []
    for t in targets:
        coord = SkyCoord(ra=t["ra"] * u.deg, dec=t["dec"] * u.deg, frame='icrs')
        transform = coord.transform_to(altaz_frame)
        alt = transform.alt.deg
          
        if alt >= 30.0:
            t["altitude"] = alt
            t["azimuth"] = transform.az.deg
            t["airmass"] = float(transform.secz.value)
            observable.append(t)
              
    return observable

ephemeris_agent = Agent(
    name="EphemerisObservabilityAgent",
    system_prompt="You are an observatory operations astrometrist verifying physical pointing visibility.",
    tools=[calculate_target_observability]
)