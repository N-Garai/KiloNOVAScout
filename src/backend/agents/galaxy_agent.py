from strands import Agent
from ..tools.network_tools import query_glade_vizier_tap

galaxy_agent = Agent(
    name="GalaxyPrioritizationAgent",
    system_prompt="You are an extragalactic astrophysicist identifying probable host galaxies in GW volumes.",
    tools=[query_glade_vizier_tap]
)