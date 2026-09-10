"""anomaly.py — AnomalyAgent (M12).

Fires only when catalog_source=="live" && top P_overlap<0.02 — the
live catalog is authoritative but the top host is faint/far, suggesting
the host list is ambiguous and wider tiling should be considered.
Hook-gated via AfterToolCallEvent, 0 cost unless top is outlier.
"""

from __future__ import annotations

import os
from typing import Any, List


def should_fire(candidates: List[Any], catalog_source: str | None = None) -> bool:
    """Predicate per PRD M12: live catalog && top P<0.02."""
    try:
        if not candidates:
            return False
        top = candidates[0]
        p = float(getattr(top, "probability_overlap", None) or (top.get("probability_overlap", 0) if isinstance(top, dict) else 0))
        # catalog_source may be passed explicitly or inferred from the candidate row
        src = catalog_source
        if src is None:
            src = getattr(top, "catalog_source", None) or (top.get("catalog_source") if isinstance(top, dict) else None)
        if src is not None and str(src).lower() != "live":
            return False
        return p < 0.02
    except Exception:
        return False


def anomaly_note(candidates: List[Any]) -> str | None:
    """One-sentence outlier check — gated, advisory only."""
    try:
        from ...llm_reasoner import _primary_model_id

        top = candidates[0] if candidates else {}
        name = getattr(top, "name", None) or (top.get("name", "?") if isinstance(top, dict) else "?")
        p = getattr(top, "probability_overlap", None) or (top.get("probability_overlap", 0) if isinstance(top, dict) else 0)
        prompt = f"""In one sentence, flag that host {name} has low spatial overlap P={float(p):.3f} despite ranking first. Suggest wider tiling or deeper search. Under 30 words."""
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


class AnomalyHook:
    """Strands hook provider for AnomalyAgent (M12). Fires only on trigger."""

    def register_hooks(self, registry, **kwargs) -> None:
        try:
            from strands.hooks import AfterToolCallEvent

            registry.add_callback(AfterToolCallEvent, self._after_tool_call)
        except Exception as e:
            print(f"[ANOMALY HOOK] registration skipped: {e}")

    def _after_tool_call(self, event) -> None:
        try:
            tool_name = getattr(getattr(event, "tool_use", None), "get", lambda k, d=None: None)("name") if isinstance(getattr(event, "tool_use", None), dict) else getattr(getattr(event, "tool_use", None), "name", None)
            if tool_name == "query_glade_catalog":
                # Predicate evaluated in the DAG (needs candidate list) — hook is advisory log only
                print("[ANOMALY HOOK] catalog step completed — DAG will evaluate should_fire()")
        except Exception:
            pass
