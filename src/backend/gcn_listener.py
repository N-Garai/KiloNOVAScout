"""Live NASA GCN Kafka listener for KilonovaScout v2 Milestone 1.

Subscribes to LVC VOEvent topics via the `gcn-kafka` client.  When live
alerts arrive, they are parsed into `GcnKafkaPayload` and handed to the
orchestrator pipeline.  If credentials are missing or the connection fails,
the app falls back to mock-only mode (boot must never block).

This is a best-effort background task: the demo works with zero GCN creds.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from .models import GcnKafkaPayload, Voevent


TOPICS_DEFAULT = [
    "gcn.classic.voevent.LVC_INITIAL",
    "gcn.classic.voevent.LVC_PRELIMINARY",
    "gcn.classic.voevent.LVC_UPDATE",
]


def _has_gcn_creds() -> bool:
    return bool(os.getenv("GCN_KAFKA_CLIENT_ID") and os.getenv("GCN_KAFKA_CLIENT_SECRET"))


def _parse_voevent_xml(xml_text: bytes) -> Optional[Voevent]:
    """Parse a GCN VOEvent XML payload into a Voevent model.

    Uses a lightweight XML-to-dict extraction.  Falls back to None on
    parse failure so a single bad packet never crashes the listener.
    """
    import xml.etree.ElementTree as ET
    from io import BytesIO

    try:
        # Use defusedxml to guard against XXE/billion-laughs in foreign VOEvent packets.
        from defusedxml.ElementTree import parse as _safe_parse
    except ImportError:
        from xml.etree.ElementTree import parse as _safe_parse

    try:
        # Handle bytes or str input
        if isinstance(xml_text, str):
            xml_text_bytes = xml_text.encode("utf-8")
        else:
            xml_text_bytes = xml_text

        root = _safe_parse(BytesIO(xml_text_bytes)).getroot()

        # Namespace handling
        ns = {"v": "http://www.ivoa.net/xml/VOEvent/v2.0"}
        role = root.get("role", "observation")
        ivorn = root.get("ivorn", "unknown")

        # Description
        description_el = root.find(".//v:Description", ns)
        description = description_el.text if description_el is not None else ""

        # WhereWhen / Coords
        wherewhen: Dict[str, Any] = {}
        t_el = root.find(".//v:ISOTime", ns)
        if t_el is not None:
            wherewhen["event_time"] = t_el.text

        # Find skymap URL from Param with name containing 'skymap' or 'bayestar'
        what: List[Dict[str, Any]] = []
        for param in root.findall(".//v:Param", ns):
            name = param.get("name", "")
            value = param.get("value", "")
            if name and value:
                what.append({"name": name, "value": value})
                if "skymap" in name.lower() or "bayestar" in name.lower() or "url" in name.lower():
                    wherewhen["skymap_url"] = value
                    wherewhen["skymap_summary"] = {"url": value}

        # FAR / classifications from Group / Param
        for param in root.findall(".//v:Param", ns):
            name = param.get("name")
            value = param.get("value")
            if name == "FAR":
                try:
                    wherewhen["far"] = float(value)
                except (TypeError, ValueError):
                    pass

        if not wherewhen.get("skymap_url"):
            # Fallback: no live skymap URL, use mock synthetic fallback
            wherewhen["skymap_url"] = "mock://gcn.local/skymap.fits"
            wherewhen["skymap_summary"] = None

        return Voevent(
            ivorn=ivorn,
            role=role,
            description=description,
            wherewhen=wherewhen,
            what=what,
        )
    except Exception as e:
        print(f"[GCN] Failed to parse VOEvent: {e}")
        return None


class GcnListener:
    """Background listener for live GCN alerts with mock fallback."""

    def __init__(self, on_notice: Callable[[GcnKafkaPayload], Any]):
        self.on_notice = on_notice
        self._task: Optional[asyncio.Task] = None
        self._consumer = None
        self._running = False
        self._latest_live: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the listener.  Non-blocking; safe to call even with no creds."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        if not _has_gcn_creds():
            print("[GCN] No GCN_KAFKA credentials; running in mock-only mode.")
            return
        try:
            # Import lazily so the app boots even if gcn-kafka is not installed
            from gcn_kafka import Consumer
        except Exception as e:
            print(f"[GCN] gcn-kafka import failed ({e}); mock-only mode.")
            return

        self._running = True
        consumer = Consumer(
            client_id=os.getenv("GCN_KAFKA_CLIENT_ID"),
            client_secret=os.getenv("GCN_KAFKA_CLIENT_SECRET"),
        )
        self._consumer = consumer
        try:
            consumer.subscribe(TOPICS_DEFAULT)
            print(f"[GCN] Listening on {len(TOPICS_DEFAULT)} LVC topics...")
            while self._running:
                try:
                    for message in consumer.consume(timeout=1.0):
                        if message is None:
                            continue
                        payload = self._process_message(message)
                        if payload is not None:
                            try:
                                result = self.on_notice(payload)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                print(f"[GCN] on_notice handler error: {e}")
                except Exception as e:
                    print(f"[GCN] consume error: {e}")
                    await asyncio.sleep(1.0)
        except Exception as e:
            print(f"[GCN] listener error: {e}; mock-only mode.")
        finally:
            self._running = False

    def _process_message(self, message) -> Optional[GcnKafkaPayload]:
        try:
            topic = message.topic()
            offset = message.offset()
            timestamp = message.timestamp()[1] if message.timestamp() else None

            voevent = _parse_voevent_xml(bytes(message.value()))
            if voevent is None:
                return None

            if voevent.role == "retraction":
                # Flag retractions in state (handled by caller via on_notice)
                pass

            import datetime
            ts = datetime.datetime.fromtimestamp(timestamp / 1000.0, tz=datetime.timezone.utc) if timestamp else datetime.datetime.utcnow()

            return GcnKafkaPayload(
                topic=topic,
                offset=offset,
                timestamp=ts,
                voevent=voevent,
            )
        except Exception as e:
            print(f"[GCN] message processing error: {e}")
            return None

    async def set_latest_live(self, result: Dict[str, Any]) -> None:
        with self._lock:
            self._latest_live = result

    def get_latest_live(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest_live
