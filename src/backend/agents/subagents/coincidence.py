"""coincidence.py — CoincidenceAgent (M12).

Fires only when a BNS trigger has a GRB error circle <5° away.
Runs the validator and returns an LLM coincidence narrative (not just B=3.0).
Hook-gated via AfterToolCallEvent, 0 cost unless a nearby GRB exists.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def should_fire(event_class: str, grb_error_deg: Optional[float]) -> bool:
    try:
        return event_class == "bns" and grb_error_deg is not None and float(grb_error_deg) < 5.0
    except Exception:
        return False


def coincidence_narrative(gw_time: str, ra: float, dec: float, grb_catalog: List[Dict[str, Any]]) -> Optional[str]:
    """LLM narrative for a nearby GRB — gated, short, advisory only."""
    try:
        import os
        from ...llm_reasoner import _primary_model_id

        prompt = (
            f"In one sentence, assess GW-GRB coincidence: GW at RA {ra:.2f} Dec {dec:.2f} time {gw_time} "
            f"vs GRB catalog {json.dumps(grb_catalog)[:400]}. Say 'coincident within X°/Y s' or 'no match'. Under 30 words."
        )
        model = _primary_model_id()
        key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
        if not key:
            key = (os.getenv("GROQ_API_KEY", "") or "").strip()
            if key:
                model = os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")
            else:
                return None
        from litellm import completion

        resp = completion(model=model, api_key=key, messages=[{"role": "user", "content": prompt}], temperature=0.3, max_tokens=80, timeout=15)
        text = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
        return text[:200] if text else None
    except Exception:
        return None


class CoincidenceHook:
    """Strands hook provider for CoincidenceAgent (M12)."""

    def register_hooks(self, registry, **kwargs) -> None:
        try:
            from strands.hooks import AfterToolCallEvent

            registry.add_callback(AfterToolCallEvent, self._after_tool_call)
        except Exception as e:
            print(f"[COIN HOOK] registration skipped: {e}")

    def _after_tool_call(self, event) -> None:
        try:
            tu = getattr(event, "tool_use", None)
            name = tu.get("name") if isinstance(tu, dict) else getattr(tu, "name", None)
            if name == "validator.multimessenger":
                print("[COIN HOOK] validator completed — DAG gates narrative on should_fire()")
        except Exception:
            pass
