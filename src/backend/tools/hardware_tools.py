import json
import requests
from strands import tool

@tool
def dispatch_ascom_alpaca_slew(alpaca_host: str, alpaca_port: int, device_number: int, ra_hours: float, dec_deg: float) -> dict:
    """Dispatches an asynchronous slew command to an ASCOM Alpaca mount endpoint."""
    url = f"http://{alpaca_host}:{alpaca_port}/api/v1/telescope/{device_number}/slewtocoordinatesasync"
    payload = {
        "RightAscension": ra_hours,
        "Declination": dec_deg,
        "ClientID": 1,
        "ClientTransactionID": 101
    }
    response = requests.put(url, json=payload, timeout=5) # Use json=payload for POST/PUT
    return response.json()

@tool
def format_indi_exposure_vector(target_name: str, exposure_seconds: int, filter_slot: int) -> str:
    """Formats an INDI XML command block for robotic camera exposure and filter positioning."""
    return f"""
    <!-- Sequence {target_name} -->
    <newSwitchVector device="Filter Wheel" name="FILTER_SLOT">
        <oneSwitch name="SLOT_{filter_slot}">ON</oneSwitch>
    </newSwitchVector>
    <newTextVector device="CCD Camera" name="FITS_HEADER_OBJECT">
        <oneText name="OBJECT">{target_name}</oneText>
    </newTextVector>
    <newNumberVector device="CCD Camera" name="CCD_EXPOSURE">
        <oneNumber name="EXPOSURE_VALUE">{exposure_seconds}</oneNumber>
    </newNumberVector>
    """


def generate_indi_xml(targets, exposure_time: int = 120, filter_name: str = "r") -> str:
    """Builds an INDI XML sequence for a list of targets.

    Each target is a mapping with ``name`` (or ``Name``) and optional
    ``ra``/``dec`` keys. ``filter_name`` maps to a wheel slot when it is
    a known SDSS band, otherwise slot 1 is used as a safe default.
    """
    try:
        filter_slot = {"u": 1, "g": 2, "r": 3, "i": 4, "z": 5}.get(
            str(filter_name).lower(), 1)
    except Exception:
        filter_slot = 1
    blocks = []
    for t in targets or []:
        name = t.get("name", t.get("Name", "UNKNOWN")) if isinstance(t, dict) else str(t)
        blocks.append(f"""
    <!-- Sequence {name} -->
    <newSwitchVector device="Filter Wheel" name="FILTER_SLOT">
        <oneSwitch name="SLOT_{filter_slot}">ON</oneSwitch>
    </newSwitchVector>
    <newTextVector device="CCD Camera" name="FITS_HEADER_OBJECT">
        <oneText name="OBJECT">{name}</oneText>
    </newTextVector>
    <newNumberVector device="CCD Camera" name="CCD_EXPOSURE">
        <oneNumber name="EXPOSURE_VALUE">{exposure_time}</oneNumber>
    </newNumberVector>
    """)
    return "<IndiSequence>\n" + "\n".join(blocks) + "\n</IndiSequence>"


def generate_ascom_json(targets, exposure_time: int = 120, filter_name: str = "r") -> str:
    """Builds an ASCOM Alpaca-style JSON slew/exposure plan for a list of targets."""
    plan = []
    for i, t in enumerate(targets or []):
        if isinstance(t, dict):
            name = t.get("name", t.get("Name", f"Target-{i + 1}"))
            ra = t.get("ra", t.get("RA_Deg"))
            dec = t.get("dec", t.get("Dec_Deg"))
        else:
            name, ra, dec = str(t), None, None
        plan.append({
            "Target": name,
            "RightAscension": ra,
            "Declination": dec,
            "ExposureSeconds": exposure_time,
            "Filter": filter_name,
        })
    return json.dumps({"Targets": plan}, indent=2)
