from strands import Agent, tool
import json

@tool
def evaluate_gw_trigger(notice_json: str) -> dict:
    """Evaluates gravitational wave trigger viability based on FAR and source classification."""
    notice = json.loads(notice_json)
    far = notice.get("far", 1.0)
    properties = notice.get("properties", {})
    p_bns = properties.get("BNS", 0.0)
    p_nsbh = properties.get("NSBH", 0.0)
    p_has_ns = properties.get("HasNS", 0.0)
    p_terr = properties.get("Terrestrial", 0.0)
      
    if far <= 3.17e-8 and p_terr < 0.50 and (p_has_ns > 0.20 or (p_bns + p_nsbh) > 0.20):
        return {
            "status": "ACCEPTED",
            "superevent_id": notice.get("superevent_id"),
            "skymap_url": notice.get("urls", {}).get("skymap"),
            "event_time": notice.get("event_time"),
            "p_astro": 1.0 - p_terr
        }
    return {"status": "REJECTED", "reason": "High FAR or insufficient neutron star probability"}

ingestion_agent = Agent(
    name="IngestionFilterAgent",
    system_prompt="You are an astrophysicist triage daemon evaluating incoming GCN gravitational wave notices.",
    tools=[evaluate_gw_trigger]
)
