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
    Additional classes (GRB, neutrino) ship calibrated inline packets modeled
    on published archetypes (GRB 170817A short burst; an IceCube gold-alert
    track in the TXS 0506+056 region).
    """

    def __init__(self):
        self.mock_payload = self._load_replay_packet() or self._create_gw170817_payload()
        self._packets = {
            "bns": self.mock_payload,
            "grb": self._create_grb_payload(),
            "neutrino": self._create_neutrino_payload(),
        }

    def get_payload(self, event_class: str = "bns") -> GcnKafkaPayload:
        """Return the demo packet for an event class (unknown → bns)."""
        key = (event_class or "bns").lower()
        return self._packets.get(key, self._packets["bns"])

    def _create_grb_payload(self) -> GcnKafkaPayload:
        """Fermi-GBM-style short-burst packet calibrated on GRB 170817A
        (T90 ~ 2 s, fluence ~2.4e-7 erg/cm², GBM-scale error circle)."""
        return GcnKafkaPayload(
            topic="gcn.classic.voevent.FERMI_GBM_ALERT",
            offset=170817529,
            timestamp=datetime.fromisoformat("2017-08-17T12:41:06+00:00"),
            voevent=Voevent(
                ivorn="ivo://gcn.nasa.gov/FERMI#GBM_170817529-Alert",
                role="observation",
                description="Fermi-GBM Short Gamma-Ray Burst Candidate (GRB 170817A-like)",
                wherewhen={
                    "trigger_id": "GBM_170817529",
                    "event_time": "2017-08-17T12:41:06Z",
                    "ra_deg": 197.3,
                    "dec_deg": -23.3,
                    "error_radius_deg": 3.0,
                    "event_class": "grb",
                },
                what=[
                    {"name": "T90", "value": "2.0"},
                    {"name": "Fluence", "value": "2.4e-7"},
                    {"name": "Peak_Flux", "value": "3.7"},
                    {"name": "Hardness", "value": "1.2"},
                ],
            ),
        )

    def _create_neutrino_payload(self) -> GcnKafkaPayload:
        """IceCube-gold-style track packet representative of gold alerts
        (signalness ~0.6, degree-scale error; IC170922A-like region)."""
        return GcnKafkaPayload(
            topic="gcn.classic.voevent.ICECUBE_ASTROTRACK_GOLD",
            offset=924220922,
            timestamp=datetime.fromisoformat("2017-09-22T20:54:30+00:00"),
            voevent=Voevent(
                ivorn="ivo://gcn.nasa.gov/ICECUBE#ASTROTRACK_GOLD-170922A",
                role="observation",
                description="IceCube Gold-Tier High-Energy Neutrino Track (IC170922A-like)",
                wherewhen={
                    "trigger_id": "IC170922A",
                    "event_time": "2017-09-22T20:54:30Z",
                    "ra_deg": 77.43,
                    "dec_deg": 5.72,
                    "error_radius_deg": 2.0,
                    "event_class": "neutrino",
                },
                what=[
                    {"name": "Signalness", "value": "0.6"},
                    {"name": "Angular_Error", "value": "2.0"},
                ],
            ),
        )

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