
import datetime
import json
from typing import Dict, Any

from .models import GcnKafkaPayload, Voevent

class EventSimulator:
    """Simulates GCN Kafka events for testing KilonovaScout.

    Provides a mock NASA GCN Kafka payload based on GW170817.
    """

    def __init__(self):
        pass

    def get_mock_gw170817_payload(self) -> GcnKafkaPayload:
        """Returns a mock GCN Kafka payload for GW170817 neutron star merger.

        This payload is designed to mimic the structure of a real GCN Kafka alert
        containing a VOEvent, for reproducible hackathon demonstrations.
        """
        # This mock data is based on the structure of real GCN VOEvents
        # for GW170817, simplified for brevity and focus on core fields.
        # In a full system, this would be a more complete VOEvent XML parsing.
        mock_voevent_data = {
            "ivorn": "ivo://gcn.nasa.gov/GW170817#LVC_GRB_S170817A-1-1",
            "role": "observation",
            "description": "Candidate GCN-circular from LVC for GW170817 (BNS merger).",
            "wherewhen": {
                "coordsystem": "UTC-TOPOCENTER",
                "time": datetime.datetime(2017, 8, 17, 12, 41, 4, 400000, tzinfo=datetime.timezone.utc),
                "observatory": "LIGO/Virgo",
                "skymap_url": "https://gracedb.ligo.org/api/superevents/S170817A/files/LALInference_skymap.fits.gz",
                "trigger_id": "S170817A",
            },
            "what": [
                {
                    "name": "P_EM",
                    "value": "0.99",
                    "unit": "probability",
                    "description": "Probability of electromagnetic counterpart."
                },
                {
                    "name": "FAR",
                    "value": "1.0e-27",
                    "unit": "Hz",
                    "description": "False Alarm Rate."
                },
                {
                    "name": "EVENT_TYPE",
                    "value": "BNS",
                    "description": "Binary Neutron Star Merger."
                },
                {
                    "name": "SKYMAPP_PROB_90",
                    "value": "28.0",
                    "unit": "deg^2",
                    "description": "90% localization area in square degrees."
                }
            ]
        }

        return GcnKafkaPayload(
            topic="gcn.classic.voevent.LVC_EARLY_WARNING",
            offset=123456789,
            timestamp=datetime.datetime.utcnow(),
            voevent=Voevent(**mock_voevent_data),
        )

    def simulate_event_delivery(self, payload: GcnKafkaPayload):
        """Mocks the delivery of an event to the agent's processing loop.

        In a real application, this would put the payload onto a queue
        or call the agent's processing function directly.
        For the hackathon, we will just print it and use it as a direct input.
        """
        print(f"[SIMULATOR] Delivering simulated GCN event: {payload.voevent.ivorn}")
        # In `main.py`, this payload will be passed directly to the agent.process_gcn_event

