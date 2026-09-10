"""retraction.py — RetractionAgent (M12).

Fires only when a GCN notice has role=="retraction". Marks the superseded
run as rejected and emits a banner so the observer never slews at a dead
event. Hook-gated via BeforeInvocationEvent, 0 cost on 99% of runs.
"""

from __future__ import annotations

from typing import Any, Dict


def should_fire(payload: Any) -> bool:
    try:
        return (payload.voevent.role or "").lower() == "retraction"
    except Exception:
        return False


def handle_retraction(payload: Any, run_id: str) -> Dict[str, Any]:
    """Return a retraction verdict — caller marks the run REJECTED and superseded run."""
    ivorn = getattr(getattr(payload, "voevent", None), "ivorn", "unknown")
    return {
        "status": "REJECTED",
        "gate_reason": f"Retraction notice {ivorn} — superseded event withdrawn, no follow-up.",
        "gate_subclass": "retraction",
        "banner": f"RETRACTED: {ivorn} — pipeline halted, no slew requested.",
    }


class RetractionHook:
    """Strands hook provider for RetractionAgent (M12)."""

    def register_hooks(self, registry, **kwargs) -> None:
        try:
            from strands.hooks import BeforeInvocationEvent

            registry.add_callback(BeforeInvocationEvent, self._before_invoke)
        except Exception as e:
            print(f"[RETRACTION HOOK] registration skipped: {e}")

    def _before_invoke(self, event) -> None:
        try:
            # Hook is advisory — actual retraction logic lives in the DAG
            pass
        except Exception:
            pass
