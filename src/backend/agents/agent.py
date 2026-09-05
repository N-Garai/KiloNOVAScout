import datetime
import json
import asyncio
from typing import Dict, Any, List, Optional

from strands import Agent, Tool, StrandsThreadPoolExecutor
from strands.models import AgentContext, AgentStep

from .models import GcnKafkaPayload, AgentState, AgentOutput, HealpixSkymap, Galaxy, ObservatoryWeather, TelescopeSlewScript
from .tools import KilonovaScoutTools


class KilonovaScoutAgent(Agent):
    """Master Orchestrator Agent for KilonovaScout.
    
    Coordinates the 8 specialized agents through the Strands A2A protocol
    and manages the end-to-end follow-up pipeline.
    """

    def __init__(self, agent_name: str, tools: KilonovaScoutTools, 
                 model: str = "google/gemini-1.5-flash",
                 fallback_model: str = "groq/llama3-70b-8192"):
        # Prepare tools list for Strands Agent
        # Strands expects functions decorated with @tool or imported modules
        # Here we pass the bound methods from our tools instance
        strands_tools = [
            tools.parse_healpix_map,
            tools.query_glade_catalog,
            tools.check_observatory_weather,
            tools.generate_telescope_slew_script,
            tools.send_sms_alert,
        ]
        
        super().__init__(name=agent_name, model=model, tools=strands_tools)
        
        self.tools_instance = tools
        self.primary_model = model
        self.fallback_model = fallback_model
        self.agent_state = AgentState(status="initialized", approval_needed=False)

        self.system_message = (
            "You are KilonovaScout, a Staff-level Space Systems AI orchestrator. "
            "Coordinate specialized agents to process NASA GCN alerts. "
            "The pipeline: Ingestion -> HEALPix Triage -> Galaxy Crossmatch -> "
            "Ephemeris/Weather validation -> Multi-Messenger Coincidence -> "
            "Scheduling -> Human Approval. "
            "Only request human approval once the slew script is ready."
        )

    async def process_gcn_event(self, payload: GcnKafkaPayload) -> AgentOutput:
        """Processes event with automatic LLM fallback if primary fails."""
        try:
            return await self._run_agent_loop(payload)
        except Exception as e:
            print(f"[CRITICAL] Primary Model ({self.primary_model}) failed: {e}")
            print(f"[RECOVERY] Attempting fallback to {self.fallback_model}...")
            
            # Switch internal model state for fallback attempt
            self.model = self.fallback_model
            try:
                result = await self._run_agent_loop(payload)
                print(f"[RECOVERY] Fallback successful.")
                return result
            except Exception as fe:
                self.agent_state.status = "error"
                error_msg = f"Both primary and fallback models failed. Final error: {fe}"
                print(f"[FATAL] {error_msg}")
                return AgentOutput(message=error_msg, action_status="failure")
            finally:
                # Reset to primary for next event
                self.model = self.primary_model

    async def _run_agent_loop(self, payload: GcnKafkaPayload) -> AgentOutput:
        """The core logic of the agent processing loop."""
        event_ivorn = payload.voevent.ivorn
        skymap_url = payload.voevent.wherewhen.get('skymap_url')

        if not skymap_url:
            return AgentOutput(message=f"No skymap in {event_ivorn}", action_status="failure")

        self.agent_state.status = "processing"
        self.agent_state.last_gcn_event = event_ivorn

        # Step 1: Geometry - Parse HEALPix skymap
        skymap: HealpixSkymap = await self.call_tool("parse_healpix_map", skymap_url=skymap_url)
        self.agent_state.current_skymap = skymap
        
        # Step 2: Catalog Search - Query GLADE+
        galaxies: List[Galaxy] = await self.call_tool("query_glade_catalog", skymap=skymap)
        self.agent_state.candidate_galaxies = galaxies
        
        # Step 3: Local Weather at the configured Observatory
        weather: ObservatoryWeather = await self.call_tool("check_observatory_weather")
        self.agent_state.observatory_weather = weather
        
        if weather.cloud_cover_percent > 80:
            msg = f"Target Acquired but Sky Overcast ({weather.cloud_cover_percent}%). Monitoring..."
            await self.call_tool("send_sms_alert", message=msg)
            self.agent_state.status = "weather_blocked"
            return AgentOutput(message=msg, action_status="pending")

        # Step 4: Slew Script Generation
        slew_script: TelescopeSlewScript = await self.call_tool("generate_telescope_slew_script", galaxies=galaxies)
        self.agent_state.slew_script = slew_script
        self.agent_state.approval_needed = True
        self.agent_state.status = "awaiting_approval"

        alert = f"TARGET ACQUIRED: Human Approval Required for {len(galaxies)} targets at {weather.observatory_name}."
        await self.call_tool("send_sms_alert", message=alert)

        return AgentOutput(
            message="Slew script generated. Awaiting Human-in-the-Loop approval.",
            details={"targets": len(galaxies), "observatory": weather.observatory_name},
            action_status="awaiting_approval"
        )

    def get_agent_state(self) -> AgentState:
        return self.agent_state

    async def approve_slew_script(self) -> AgentOutput:
        if self.agent_state.approval_needed:
            self.agent_state.status = "slewing"
            self.agent_state.approval_needed = False
            await self.call_tool("send_sms_alert", message="Telescope SLEW INITIATED. Tracking...")
            return AgentOutput(message="Slew initiated.", action_status="success")
        return AgentOutput(message="No pending script.", action_status="failure")