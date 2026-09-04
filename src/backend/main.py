import os
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from strands_sdk.llm import LiteLLMClient

from .agent import KilonovaScoutAgent
from .models import AgentState, GcnKafkaPayload, AgentOutput, TelescopeSlewScript, ObservatoryConfig
from .tools import KilonovaScoutTools
from .simulator import EventSimulator

# --- Configuration (Load from Environment with Robust Fallbacks) ---

# Observatory Configuration
# Falls back to Palomar Observatory (California) if not provided
OBSERVATORY_NAME = os.getenv("OBSERVATORY_NAME", "Palomar")
OBSERVATORY_LAT = float(os.getenv("OBSERVATORY_LAT", 33.356))
OBSERVATORY_LON = float(os.getenv("OBSERVATORY_LON", -116.865))
OBSERVATORY_ALT = float(os.getenv("OBSERVATORY_ALT", 1706))

# LLM Configuration
# Primary: Google Gemini 1.5 Flash (Fast and high rate limits)
# Fallback: Groq Llama 3 (Ultra-fast, useful if Google API is down)
PRIMARY_LLM = os.getenv("PRIMARY_LLM", "google/gemini-1.5-flash")
FALLBACK_LLM = os.getenv("FALLBACK_LLM", "groq/llama3-70b-8192")

# --- FastAPI App Setup ---
app = FastAPI(
    title="KilonovaScout Backend API",
    description="Autonomous Multi-Messenger Astronomy Targeting Agent.",
    version="1.1.0",
)

# Allow CORS for frontend development and production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your actual Render URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Agent and Tools Initialization ---

# Initialize the Tools with user-provided or fallback location
kilonova_tools = KilonovaScoutTools(
    observatory_name=OBSERVATORY_NAME,
    lat=OBSERVATORY_LAT,
    lon=OBSERVATORY_LON,
    alt=OBSERVATORY_ALT
)

# Initialize the Agent with Primary and Fallback model capability
# Note: The custom logic for fallback is handled within the Agent's process loop
kilonova_agent = KilonovaScoutAgent(
    agent_name="kilonovascout-core",
    tools=kilonova_tools,
    llm_model=PRIMARY_LLM,
    fallback_llm=FALLBACK_LLM
)

event_simulator = EventSimulator()

# --- API Endpoints ---

# Store current observatory config (mutable state for runtime updates)
_current_config = {
    "name": OBSERVATORY_NAME,
    "lat": OBSERVATORY_LAT,
    "lon": OBSERVATORY_LON,
    "alt": OBSERVATORY_ALT,
}

@app.get("/agent/config", response_model=ObservatoryConfig)
async def get_agent_config():
    """Get the current observatory configuration."""
    return ObservatoryConfig(**_current_config)

@app.put("/agent/config", response_model=ObservatoryConfig)
async def update_agent_config(config: ObservatoryConfig):
    """Update observatory configuration dynamically.
    Falls back to Palomar if values are missing or invalid.
    """
    global kilonova_tools, kilonova_agent, _current_config

    # Apply fallback to Palomar for any invalid/missing data
    new_name = config.name if config.name and config.name.strip() else "Palomar"
    new_lat = config.lat if config.lat is not None else 33.356
    new_lon = config.lon if config.lon is not None else -116.865
    new_alt = config.alt if config.alt is not None else 1706

    # Clamp lat/lon to valid ranges
    new_lat = max(-90.0, min(90.0, new_lat))
    new_lon = max(-180.0, min(180.0, new_lon))

    _current_config = {
        "name": new_name,
        "lat": new_lat,
        "lon": new_lon,
        "alt": new_alt,
    }

    # Re-initialize tools with new location
    kilonova_tools = KilonovaScoutTools(
        observatory_name=new_name,
        lat=new_lat,
        lon=new_lon,
        alt=new_alt
    )

    # Re-initialize agent with updated tools
    kilonova_agent = KilonovaScoutAgent(
        agent_name="kilonovascout-core",
        tools=kilonova_tools,
        llm_model=PRIMARY_LLM,
        fallback_llm=FALLBACK_LLM
    )

    print(f"[API] Observatory updated: {new_name} ({new_lat}, {new_lon}, {new_alt}m)")
    return ObservatoryConfig(**_current_config)

@app.get("/agent/state", response_model=AgentState)
async def get_agent_state():
    """Get the current state of the KilonovaScout agent."""
    return kilonova_agent.get_agent_state()

@app.post("/simulate-gcn-alert", response_model=AgentOutput)
async def simulate_gcn_alert():
    """Simulate a NASA GCN alert (GW170817 template).
    This triggers the autonomous agent loop.
    """
    mock_payload = event_simulator.get_mock_gw170817_payload()
    print(f"[API] Simulated GCN delivery: {mock_payload.voevent.ivorn}")
    agent_output = await kilonova_agent.process_gcn_event(mock_payload)
    return agent_output

@app.post("/agent/approve-slew-script", response_model=AgentOutput)
async def approve_slew_script():
    """Endpoint for human approval of the telescope script."""
    return await kilonova_agent.approve_slew_script()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "observatory": OBSERVATORY_NAME, "primary_llm": PRIMARY_LLM}

if __name__ == "__main__":
    # Use port from environment for Render compatibility
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
