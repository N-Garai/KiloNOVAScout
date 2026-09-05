import requests
from strands import Agent, tool

@tool
def get_site_meteorology(lat: float, lon: float) -> dict:
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

weather_agent = Agent(
    name="AtmosphericMeteorologyAgent",
    system_prompt="You are an observatory weather safety daemon evaluating local meteorological safety.",
    tools=[get_site_meteorology]
)