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
