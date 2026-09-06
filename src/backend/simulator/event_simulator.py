from typing import Dict, Any
import json
from datetime import datetime

from ..models import GcnKafkaPayload, Voevent


class EventSimulator:
    """Simulates NASA GCN Kafka payloads for reproducible demo and testing.

    When the bundled replay packet (``data/GW170817_initial.json``, v3 PRD
    M4.1) is present it is loaded verbatim — a faithful VOEvent replay with the
    real IVORN and trigger time.  Otherwise an equivalent packet is built
    inline so the demo never breaks.
    
    Uses the famous GW170817 neutron star merger as the template event,
    allowing a 100% reproducible demo without waiting for real detections.
    """

    def __init__(self):
        self.mock_payload = self._load_replay_packet() or self._create_gw170817_payload()

    def _load_replay_packet(self):
        """Load the bundled GW170817_initial.json replay packet, if present."""
        try:
            import os
            here = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(here, "..", "data", "GW170817_initial.json")
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return GcnKafkaPayload(**raw)
        except Exception as exc:
            print(f"[SYS] replay packet load failed ({exc}); using inline mock")
            return None
    def _create_gw170817_payload(self) -> GcnKafkaPayload:
        """Creates a mock GW170817 payload based on historical data."""
        return GcnKafkaPayload(
            topic="gcn.classic.voevent.LVC_INITIAL",
            offset=123456789,
            timestamp=datetime.fromisoformat("2017-08-17T12:41:04Z"),
            voevent=Voevent(
                ivorn="ivo://gcn.nasa.gov/LVC#GW170817-Initial",
                role="observation",
                description="LIGO/Virgo Binary Neutron Star Merger Candidate - GW170817",
                wherewhen={
                    "skymap_url": "https://gracedb.ligo.org/api/superevents/GW170817/files/bayestar.multiorder.fits",
                    "trigger_id": "GW170817",
                    "event_time": "2017-08-17T12:41:04Z"
                },
                what=[
                    {
                        "far": 1.2e-9,
                        "properties": {
                            "BNS": 0.95,
                            "NSBH": 0.03,
                            "BBH": 0.01,
                            "Terrestrial": 0.01,
                            "HasNS": 0.98
                        }
                    }
                ]
            )
        )

    def get_mock_gw170817_payload(self) -> GcnKafkaPayload:
        """Returns the pre-configured GW170817 mock payload."""
        return self.mock_payload


# Convenience function for direct import
event_simulator = EventSimulator()