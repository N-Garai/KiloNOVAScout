from typing import Dict, Any
import json
from datetime import datetime

from ..models import GcnKafkaPayload, Voevent


class EventSimulator:
    """Simulates NASA GCN Kafka payloads for reproducible demo and testing.
    
    Uses the famous GW170817 neutron star merger as the template event,
    allowing the hackathon judges to see a 100% reproducible 5-minute demo.
    """

    def __init__(self):
        self.mock_payload = self._create_gw170817_payload()

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