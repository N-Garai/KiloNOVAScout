'''models.py - Data models and Pydantic schemas for KilonovaScout.

This module defines the data structures used throughout the KilonovaScout
application, including input schemas for GCN alerts, internal representations
of sky maps and galaxy catalogs, and the final telescope slew script.
'''

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import datetime

# --- GCN Alert Models (Input) ---

class Voevent(BaseModel):
    """Simplified model for a GCN VOEvent XML payload."""
    ivorn: str = Field(..., description="IVORN identifier for the VOEvent.")
    role: str = Field(..., description="Role of the VOEvent (e.g., test, observation).")
    description: str = Field(..., description="A brief description of the event.")
    wherewhen: Dict[str, Any] = Field(..., description="Location and time information (e.g., HEALPix skymap URL).")
    what: List[Dict[str, Any]] = Field(..., description="Detailed event parameters.")

class GcnKafkaPayload(BaseModel):
    """Model for the NASA GCN Kafka stream payload."""
    topic: str = Field(..., description="Kafka topic name.")
    offset: int = Field(..., description="Kafka message offset.")
    timestamp: datetime.datetime = Field(..., description="Timestamp of the Kafka message.")
    voevent: Voevent = Field(..., description="Parsed VOEvent content.")

# --- Internal Data Models ---

class HealpixSkymap(BaseModel):
    """Represents a parsed HEALPix skymap."""
    url: str = Field(..., description="URL of the original HEALPix FITS file.")
    nside: int = Field(..., description="HEALPix Nside parameter.")
    probdensity: List[float] = Field(..., description="Probability density values for each pixel.")
    supercell_indices: List[int] = Field(..., description="Indices of significant HEALPix supercells.")
    localization_area_sq_deg: float = Field(..., description="Area of localization in square degrees.")
    provenance_source: Optional[str] = Field(None, description="live | replay | synthetic | point (built from notice RA/Dec)")
    dist_mean: Optional[float] = Field(None, description="Probability-weighted mean luminosity distance (Mpc).")
    dist_std: Optional[float] = Field(None, description="Probability-weighted distance uncertainty (Mpc).")

class ScoreBreakdown(BaseModel):
    """Term-level audit trail for one candidate's composite score."""
    weights: Dict[str, float] = Field(..., description="Weights used for this calculation.")
    terms: Dict[str, float] = Field(..., description="Raw term contributions before weighting.")
    total: float = Field(..., description="Final composite score.")

class Galaxy(BaseModel):
    """Represents a potential host galaxy from the GLADE+ catalog."""
    name: str = Field(..., description="Galaxy common name or identifier.")
    ra_deg: float = Field(..., description="Right Ascension in degrees.")
    dec_deg: float = Field(..., description="Declination in degrees.")
    redshift: float = Field(..., description="Redshift of the galaxy.")
    distance_mpc: float = Field(..., description="Luminosity distance in Mpc.")
    probability_overlap: float = Field(..., description="Overlap probability with the GW skymap.")
    # Extended fields from GLADE+ query
    pgc: Optional[str] = Field(None, description="PGC identifier.")
    luminosity_k: Optional[float] = Field(None, description="K-band luminosity.")
    composite_score: Optional[float] = Field(None, description="Composite prioritization score.")
    score_breakdown: Optional[ScoreBreakdown] = Field(None, description="Per-candidate scoring audit trail.")
    normalized_priority: Optional[float] = Field(None, description="Normalized 0-100 priority across the run.")
    catalog_source: Optional[str] = Field(None, description="live | cached | mock — data source for this candidate row.")
    observability: Optional[Dict[str, Any]] = Field(None, description="Windowed airmass, lunar separation, SNR proxy and extinction metrics.")

class ObservatoryWeather(BaseModel):
    """Current weather conditions at an observatory location."""
    observatory_name: str = Field(..., description="Name of the observatory.")
    latitude: float = Field(..., description="Latitude of the observatory.")
    longitude: float = Field(..., description="Longitude of the observatory.")
    cloud_cover_percent: float = Field(..., description="Cloud cover percentage (0-100).")
    seeing_conditions: str = Field(..., description="Qualitative seeing conditions (e.g., 'clear', 'partly cloudy', 'overcast').")
    humidity_pct: float = Field(0.0, description="Relative humidity percentage.")
    dome_safe: bool = Field(False, description="Whether dome environment is safe for operation.")

class TelescopeSlewScript(BaseModel):
    """Represents the generated ASCOM/INDI XML slew script."""
    script_content: str = Field(..., description="The actual XML script content for telescope slewing.")
    target_galaxies: List[Galaxy] = Field(..., description="List of target galaxies in the script.")
    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, description="UTC timestamp of script generation.")

# --- Agent State & Output Models ---

class AgentState(BaseModel):
    """Current state of the KilonovaScout agent."""
    status: str = Field(..., description="Current status of the agent (e.g., 'listening', 'processing', 'awaiting_approval').")
    last_gcn_event: Optional[str] = Field(None, description="IVORN of the last processed GCN event.")
    current_skymap: Optional[HealpixSkymap] = Field(None, description="Current HEALPix skymap being processed.")
    candidate_galaxies: List[Galaxy] = Field([], description="List of candidate galaxies identified.")
    observatory_weather: Optional[ObservatoryWeather] = Field(None, description="Weather at the target observatory.")
    slew_script: Optional[TelescopeSlewScript] = Field(None, description="Generated telescope slew script.")
    approval_needed: bool = Field(False, description="True if human approval is required for the script.")
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, description="Last update timestamp.")
    source: Optional[str] = Field(None, description="Event source: live or mock.")
    llm_rationale: Optional[str] = Field(None, description="Live LLM triage/justification text.")
    run_id: Optional[str] = Field(None, description="Current run identifier.")

class StepEvent(BaseModel):
    """One observed step inside a run."""
    run_id: str = Field(..., description="Run identifier.")
    step: int = Field(..., description="Sequential step number.")
    tool_name: str = Field(..., description="Tool or stage name.")
    status: str = Field(..., description="running | completed | failed | skipped")
    attempt: int = Field(..., description="Attempt count for this step.")
    started_at: str = Field(..., description="ISO start timestamp.")
    duration_ms: Optional[int] = Field(None, description="Measured duration in milliseconds.")
    input_summary: str = Field("", description="Short input summary.")
    output_summary: str = Field("", description="Short output summary.")
    error: str = Field("", description="Error text if failed.")

class RunRecord(BaseModel):
    """Persisted ledger for one pipeline run."""
    run_id: str = Field(..., description="Run identifier.")
    source: str = Field(..., description="live or mock.")
    status: str = Field(..., description="Current run status.")
    started_at: str = Field(..., description="ISO start timestamp.")
    finished_at: Optional[str] = Field(None, description="ISO finish timestamp.")
    event: Optional[Dict[str, Any]] = Field(None, description="Event summary.")
    steps: List[StepEvent] = Field(default_factory=list, description="Ordered step events.")
    llm_rationale: Optional[str] = Field(None, description="LLM rationale if generated.")
    candidates: List[Dict[str, Any]] = Field(default_factory=list, description="Final candidate summary.")
    weather: Optional[Dict[str, Any]] = Field(None, description="Weather snapshot for the run.")
    slew_script: Optional[str] = Field(None, description="Generated slew script content.")
    provenance: Optional[Dict[str, str]] = Field(None, description="Data source attribution: {skymap, catalog, event} with values live | replay | cached | synthetic | point | mock.")
    visualizations: Optional[Dict[str, str]] = Field(None, description="Base64-encoded PNG plots keyed by plot name (Milestone 8).")
    observation_header: Optional[str] = Field(None, description="FITS observation header card text for scientific reproducibility (Milestone 9.1).")

class AgentOutput(BaseModel):
    """Standard output format for the KilonovaScout agent actions."""
    message: str = Field(..., description="A human-readable message about the agent's action.")
    details: Dict[str, Any] = Field({}, description="Additional structured details related to the action.")
    action_status: str = Field(..., description="Status of the action (e.g., 'success', 'failure', 'pending').")
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, description="UTC timestamp of the output.")

# --- Observatory Configuration Models ---

class ObservatoryConfig(BaseModel):
    """Configuration for the observatory location."""
    name: str = Field(default="Palomar", description="Name of the observatory.")
    lat: float = Field(default=33.356, description="Latitude in decimal degrees.")
    lon: float = Field(default=-116.865, description="Longitude in decimal degrees.")
    alt: float = Field(default=1706, description="Altitude in meters.")
    alert_classes: Optional[List[str]] = Field(default=None, description="Enabled live-watch event classes (bns, grb, neutrino).")

# --- Scoring Weights ---
class ScoringWeights(BaseModel):
    """Tuning hyperparameters for the composite target prioritization score.

    Full v3 formula (PRD Milestone 10):
      S_i = alpha * P_spatial + beta * Schechter(L_K) - gamma * X_i
            - delta * C + epsilon * B_GRB + zeta * snr_proxy - eta * L_moon
    """
    spatial_weight_alpha: float = Field(default=1.0, description="Weight for spatial containment probability.")
    mass_weight_beta: float = Field(default=0.5, description="Weight for Schechter luminosity function term.")
    extinction_gamma: float = Field(default=0.3, description="Weight for atmospheric extinction/airmass.")
    weather_delta: float = Field(default=0.2, description="Weight for weather quality.")
    coincidence_boost: float = Field(default=3.0, description="Boost factor for GRB coincidence.")
    snr_weight_zeta: float = Field(default=0.15, description="Weight for the distance-based SNR proxy term.")
    lunar_penalty_eta: float = Field(default=0.1, description="Weight for the lunar proximity penalty term.")
    schechter_l_star: float = Field(default=1.0e10, description="Characteristic Schechter luminosity (solar luminosities).")
    # NOTE: the PRD sketched alpha=-1.0, but the number-density weight
    # (L/L*)^-1 diverges for faint dwarfs and unconditionally outranks bright
    # hosts, violating the PRD's own acceptance criterion ("NGC 4993 in top
    # candidates"). Tuned to +1.0 so the weight peaks at L* and is bounded.
    schechter_alpha: float = Field(default=1.0, description="Schechter faint-end slope (peaked at L* when 1.0).")
    zenith_extinction: float = Field(default=0.12, description="R-band extinction coefficient (mag per airmass).")
    peak_kilonova_mag: float = Field(default=17.5, description="Peak apparent magnitude of the kilonova at the 40 Mpc reference distance (GW170817-calibrated).")
    probability_threshold: float = Field(default=0.01, description="Minimum probability threshold for target consideration.")
