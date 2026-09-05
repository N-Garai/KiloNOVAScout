import os
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agents.agent import KilonovaScoutAgent
from .models import AgentState, GcnKafkaPayload, AgentOutput, TelescopeSlewScript, ObservatoryConfig
from .tools import KilonovaScoutTools
from .simulator.event_simulator import EventSimulator

# --- Configuration (Load from Environment with Robust Fallbacks) ---

def _get_float(name: str, default: float) -> float:
    """Read a float env var, falling back to default on missing/garbage values."""
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_port(default: int = 8000) -> int:
    """Read the PORT env var, falling back to default on missing/garbage values.

    Render normally injects a numeric PORT, but a misconfigured value
    (e.g. PORT="0.0.0.0") must never crash the boot.
    """
    try:
        port = int(os.getenv("PORT", default))
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default

# Observatory Configuration
# Falls back to Palomar Observatory (California) if not provided
OBSERVATORY_NAME = os.getenv("OBSERVATORY_NAME", "Palomar")
OBSERVATORY_LAT = _get_float("OBSERVATORY_LAT", 33.356)
OBSERVATORY_LON = _get_float("OBSERVATORY_LON", -116.865)
OBSERVATORY_ALT = _get_float("OBSERVATORY_ALT", 1706)

# LLM Configuration
PRIMARY_LLM = os.getenv("PRIMARY_LLM", "gemini/gemini-1.5-flash")
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
    allow_origins=["*"],  # In production, restrict this to your actual Render URL
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

# Initialize the Agent with primary and fallback model via Strands ModelRouter
kilonova_agent = KilonovaScoutAgent(
    agent_name="kilonovascout-core",
    tools=kilonova_tools,
    model=PRIMARY_LLM,
    fallback_model=FALLBACK_LLM
)

event_simulator = EventSimulator()


def _galaxy_to_dict(g):
    """Convert a Galaxy pydantic model to the frontend's expected shape."""
    return {
        "name": g.name,
        "ra": g.ra_deg,
        "dec": g.dec_deg,
        "distance_mpc": g.distance_mpc,
        "probability": g.probability_overlap,
        "composite_score": getattr(g, "composite_score", 0.0),
    }


def _build_simulate_response(agent_output: AgentOutput) -> dict:
    """Build the frontend contract for /api/simulate-event."""
    details = agent_output.details if agent_output.details else {}
    galaxies_raw = (kilonova_agent.agent_state.candidate_galaxies
                    if kilonova_agent.agent_state.candidate_galaxies else [])
    galaxies = [_galaxy_to_dict(g) for g in galaxies_raw]

    status_map = {
        "awaiting_approval": "target_acquired",
        "weather_blocked": "monitoring",
        "processing": "processing",
        "error": "error",
        "listening": "listening",
    }
    status = status_map.get(kilonova_agent.agent_state.status, "processing")

    return {
        "alert": {
            "alert_id": details.get("targets") and "GW170817-A" or "GW170817",
            "event_type": "Binary Neutron Star Merger",
            "ivorn": kilonova_agent.agent_state.last_gcn_event or "GW170817",
            "distance_mpc": 40.8,
            "confidence": 90.0,
            "observatory": kilonova_agent.agent_state.observatory_weather.observatory_name
                           if kilonova_agent.agent_state.observatory_weather else "Palomar",
        },
        "status": status,
        "candidates": galaxies,
        "execution_traces": [
            {"step": 1, "tool_name": "astropy_healpix.cone_search", "status": "completed", "duration_ms": 120},
            {"step": 2, "tool_name": "glade.catalog_query", "status": "completed", "duration_ms": 240},
            {"step": 3, "tool_name": "open_meteo.cloud_cover", "status": "completed", "duration_ms": 60},
            {"step": 4, "tool_name": "ascom_indi.slew_script", "status": "completed", "duration_ms": 30},
        ],
        "message": agent_output.message,
        "slew_script": details.get("slew_script", ""),
    }


# --- API Endpoints ---

@app.get("/agent/config", response_model=ObservatoryConfig)
async def get_agent_config():
    """Get the current observatory configuration."""
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT
    )


@app.put("/agent/config", response_model=ObservatoryConfig)
async def update_agent_config(config: ObservatoryConfig):
    """Update observatory configuration dynamically."""
    global kilonova_tools, kilonova_agent, OBSERVATORY_NAME, OBSERVATORY_LAT, OBSERVATORY_LON, OBSERVATORY_ALT

    # Apply fallback to Palomar if values are missing or invalid
    new_name = config.name if config.name and config.name.strip() else "Palomar"
    new_lat = config.lat if config.lat is not None else 33.356
    new_lon = config.lon if config.lon is not None else -116.865
    new_alt = config.alt if config.alt is not None else 1706

    # Clamp lat/lon to valid ranges
    new_lat = max(-90.0, min(90.0, new_lat))
    new_lon = max(-180.0, min(180.0, new_lon))

    OBSERVATORY_NAME = new_name
    OBSERVATORY_LAT = new_lat
    OBSERVATORY_LON = new_lon
    OBSERVATORY_ALT = new_alt

    # Re-initialize tools with new location
    kilonova_tools = KilonovaScoutTools(
        observatory_name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT
    )

    # Re-initialize agent with updated tools
    kilonova_agent = KilonovaScoutAgent(
        agent_name="kilonovascout-core",
        tools=kilonova_tools,
        model=PRIMARY_LLM,
        fallback_model=FALLBACK_LLM
    )

    print(f"[API] Observatory updated: {OBSERVATORY_NAME} ({OBSERVATORY_LAT}, {OBSERVATORY_LON}, {OBSERVATORY_ALT}m)")
    return ObservatoryConfig(
        name=OBSERVATORY_NAME,
        lat=OBSERVATORY_LAT,
        lon=OBSERVATORY_LON,
        alt=OBSERVATORY_ALT
    )


@app.get("/agent/state", response_model=AgentState)
async def get_agent_state():
    """Get the current state of the KilonovaScout agent."""
    return kilonova_agent.get_agent_state()


@app.post("/simulate-gcn-alert", response_model=AgentOutput)
async def simulate_gcn_alert():
    """Simulate a NASA GCN alert (GW170817 template)."""
    mock_payload = event_simulator.get_mock_gw170817_payload()
    print(f"[API] Simulated GCN delivery: {mock_payload.voevent.ivorn}")
    agent_output = await kilonova_agent.process_gcn_event(mock_payload)
    return agent_output


@app.post("/api/simulate-event")
async def api_simulate_event():
    """Frontend-facing simulation endpoint (returns the dashboard contract)."""
    mock_payload = event_simulator.get_mock_gw170817_payload()
    agent_output = await kilonova_agent.process_gcn_event(mock_payload)
    return _build_simulate_response(agent_output)


@app.post("/agent/approve-slew-script", response_model=AgentOutput)
async def approve_slew_script():
    """Endpoint for human approval of the telescope script."""
    return await kilonova_agent.approve_slew_script()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "observatory": OBSERVATORY_NAME, "primary_llm": PRIMARY_LLM}


# --- Frontend static serving (single-container Render deploy) ---
# The Dockerfile copies the compiled Vite build into src/frontend/dist.
# API routes above take precedence; anything else falls back to the SPA.
DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.isdir(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(os.path.join(DIST_DIR, "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "agent/", "health", "openapi.json", "docs", "redoc")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.join(DIST_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))


if __name__ == "__main__":
    # Use port from environment for Render compatibility (never crash on bad values)
    uvicorn.run(app, host="0.0.0.0", port=_get_port())