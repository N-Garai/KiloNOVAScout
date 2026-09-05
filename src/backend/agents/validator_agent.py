from strands import Agent, tool
import json

@tool
def evaluate_gamma_ray_coincidence(gw_time_iso: str, target_ra: float, target_dec: float, grb_catalog_json: str) -> dict:
    """Evaluates spatial-temporal overlap between GW trigger and high-energy GRB notices."""
    from astropy.time import Time
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    
    grb_notices = json.loads(grb_catalog_json)
    gw_time = Time(gw_time_iso)
    target_coord = SkyCoord(ra=target_ra * u.deg, dec=target_dec * u.deg)
    
    matched = False
    coincident_grb = None
    
    for grb in grb_notices:
        dt = abs((Time(grb["time"]) - gw_time).sec)
        if dt <= 60.0:
            grb_coord = SkyCoord(ra=grb["ra"] * u.deg, dec=grb["dec"] * u.deg)
            sep = target_coord.separation(grb_coord).deg
            if sep <= grb["error_radius_deg"]:
                matched = True
                coincident_grb = grb["id"]
                break
    
    return {
        "coincidence_detected": matched,
        "grb_id": coincident_grb,
        "priority_boost_factor": 3.0 if matched else 1.0
    }

validator_agent = Agent(
    name="MultiMessengerValidatorAgent",
    system_prompt="You are a high-energy multi-messenger analyst correlating gravitational waves with prompt gamma-ray bursts.",
    tools=[evaluate_gamma_ray_coincidence]
)