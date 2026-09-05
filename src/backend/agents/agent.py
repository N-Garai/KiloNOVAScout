import asyncio
import datetime
import json
import os
from typing import Dict, Any, List, Optional

from strands import Agent
from strands.models.litellm import LiteLLMModel

from ..models import (
    GcnKafkaPayload,
    AgentState,
    AgentOutput,
    HealpixSkymap,
    Galaxy,
    ObservatoryWeather,
    TelescopeSlewScript,
)
from ..tools import KilonovaScoutTools


def build_primary_model(primary_model: str, fallback_model: str) -> LiteLLMModel:
    """Builds the LLM model for the agent.

    LiteLLM handles provider routing via the model_id prefix
    (e.g. ``gemini/gemini-1.5-flash``, ``groq/llama3-70b-8192``) and reads
    provider API keys from environment variables (``GEMINI_API_KEY``,
    ``GROQ_API_KEY``).

    NOTE: ``strands.models.routing.ModelRouter`` (primary/fallback failover)
    is only available in newer strands-agents releases than the pinned one
    and the deterministic pipeline below invokes tools directly without
    calling the LLM, so a single LiteLLM model is sufficient here. If the
    primary model id is empty, the fallback model id is used.
    """
    model_id = primary_model or fallback_model
    if not model_id:
        raise ValueError("At least one LLM model must be configured (set PRIMARY_LLM).")
    return LiteLLMModel(model_id=model_id)


class KilonovaScoutAgent(Agent):
    """Master Orchestrator Agent for KilonovaScout.

    Coordinates the specialized astronomy pipeline through Strands agent tools
    and manages the end-to-end follow-up:
      Ingestion -> HEALPix triage -> Galaxy crossmatch -> Weather validation
      -> Slew-script generation -> Human approval.
    """

    def __init__(self, agent_name: str, tools: KilonovaScoutTools,
                 model: str = "google/gemini-1.5-flash",
                 fallback_model: str = "groq/llama3-70b-8192"):
        llm_model = build_primary_model(model, fallback_model)

        # All tool methods are @tool decorated; Strands accepts them directly.
        strands_tools = [
            tools.parse_healpix_map,
            tools.query_glade_catalog,
            tools.check_observatory_weather,
            tools.generate_telescope_slew_script,
            tools.send_sms_alert,
        ]

        super().__init__(
            name=agent_name,
            model=llm_model,
            tools=strands_tools,
            system_prompt=(
                "You are KilonovaScout, a Staff-level Space Systems AI orchestrator. "
                "Process NASA GCN alerts through the pipeline: Ingestion -> HEALPix "
                "Triage -> Galaxy Crossmatch -> Ephemeris/Weather validation -> "
                "Multi-Messenger Coincidence -> Scheduling -> Human Approval. "
                "Only request human approval once the slew script is ready."
            ),
        )

        self.tools_instance = tools
        self.primary_model = model
        self.fallback_model = fallback_model
        self.agent_state = AgentState(status="listening", approval_needed=False)

    # ------------------------------------------------------------------ #
    # Public pipeline entrypoints
    # ------------------------------------------------------------------ #
    async def process_gcn_event(self, payload: GcnKafkaPayload) -> AgentOutput:
        """Processes a GCN event through the full follow-up pipeline."""
        try:
            return await self._run_agent_loop(payload)
        except Exception as e:
            print(f"[FATAL] Agent pipeline error: {e}")
            import traceback
            traceback.print_exc()
            self.agent_state.status = "error"
            self.agent_state.approval_needed = False
            return AgentOutput(
                message=f"Pipeline error: {e}",
                details={"error": str(e)},
                action_status="failure",
            )

    async def _run_agent_loop(self, payload: GcnKafkaPayload) -> AgentOutput:
        """The core logic of the agent processing loop."""
        event_ivorn = payload.voevent.ivorn
        skymap_url = payload.voevent.wherewhen.get('skymap_url')

        if not skymap_url:
            return AgentOutput(message=f"No skymap in {event_ivorn}", action_status="failure")

        self.agent_state.status = "processing"
        self.agent_state.last_gcn_event = event_ivorn

        # Step 1: Geometry - Parse HEALPix skymap
        print(f"[SYS] astropy_healpix.cone_search... EXEC")
        skymap = self.tools_instance.parse_healpix_map(skymap_url=skymap_url)
        self.agent_state.current_skymap = skymap

        # Step 2: Catalog Search - Query GLADE+ (composite scoring inside)
        print(f"[SYS] query_glade_catalog... EXEC")
        galaxies: List[Galaxy] = self.tools_instance.query_glade_catalog(skymap=skymap)
        self.agent_state.candidate_galaxies = galaxies

        # Step 3: Local Weather at the configured Observatory
        print(f"[SYS] open_meteo.cloud_cover... EXEC")
        weather: ObservatoryWeather = self.tools_instance.check_observatory_weather()
        self.agent_state.observatory_weather = weather

        if weather.cloud_cover_percent > 80:
            msg = (f"Target Acquired but Sky Overcast ({weather.cloud_cover_percent}%) at "
                   f"{weather.observatory_name}. Monitoring...")
            self.tools_instance.send_sms_alert(message=msg)
            self.agent_state.status = "weather_blocked"
            return AgentOutput(
                message=msg,
                details={"observatory": weather.observatory_name,
                         "cloud_cover_percent": weather.cloud_cover_percent},
                action_status="pending",
            )

        # Step 4: Slew Script Generation
        print(f"[SYS] ascom_indi.slew_script... EXEC")
        slew_script: TelescopeSlewScript = self.tools_instance.generate_telescope_slew_script(galaxies=galaxies)
        self.agent_state.slew_script = slew_script
        self.agent_state.approval_needed = True
        self.agent_state.status = "awaiting_approval"

        alert = (f"TARGET ACQUIRED: Human Approval Required for {len(galaxies)} targets "
                 f"at {weather.observatory_name}.")
        self.tools_instance.send_sms_alert(message=alert)

        return AgentOutput(
            message="Slew script generated. Awaiting Human-in-the-Loop approval.",
            details={
                "targets": len(galaxies),
                "observatory": weather.observatory_name,
                "slew_script": slew_script.script_content,
            },
            action_status="awaiting_approval",
        )

    async def approve_slew_script(self) -> AgentOutput:
        """Human-in-the-loop approval endpoint."""
        if self.agent_state.approval_needed:
            self.agent_state.status = "slewing"
            self.agent_state.approval_needed = False
            self.tools_instance.send_sms_alert(message="Telescope SLEW INITIATED. Tracking...")
            return AgentOutput(message="Slew initiated.", action_status="success")
        return AgentOutput(message="No pending script.", action_status="failure")

    def get_agent_state(self) -> AgentState:
        return self.agent_state