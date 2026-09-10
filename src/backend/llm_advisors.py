"""llm_advisors.py — Gated per-stage LLM advisors for v4 M11.

Three advisory LLM calls, each gated on borderline conditions so 95% of
clear-sky runs pay 0 extra latency/cost. All are advisory-only: they
return a string appended to the trace, never blocking the deterministic
pipeline. Each is a @tool with 15s timeout + deterministic fallback ("").
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    from strands import tool as _tool
except Exception:
    def _tool(fn):  # type: ignore
        return fn


def _should_triage_advise(verdict: Dict[str, Any]) -> bool:
    """Borderline HasNS / FAR — where a human would hesitate."""
    try:
        hasns = float(verdict.get("gate_confidence", verdict.get("p_astro", 1)) or 1)
        far = float(verdict.get("far", 0) or 0)
        # Gate 0.2 is the BNS threshold; advise when near it or FAR marginal.
        return 0.15 < hasns < 0.85 or (1e-9 < far < 1e-7)
    except Exception:
        return False


def _should_host_explain(candidates: List[Any]) -> bool:
    """Top two hosts within 0.3 of each other — Schechter vs. airmass trade-off."""
    try:
        if len(candidates) < 2:
            return False
        s0 = float(getattr(candidates[0], "composite_score", 0) or candidates[0].get("composite_score", 0))
        s1 = float(getattr(candidates[1], "composite_score", 0) or candidates[1].get("composite_score", 0))
        return abs(s0 - s1) < 0.3
    except Exception:
        return False


def _should_weather_risk(weather: Any) -> bool:
    """Cloud 40–80% or dome marginal — approve-only-if-urgent band."""
    try:
        cloud = float(getattr(weather, "cloud_cover_percent", 0) or 0)
        dome = bool(getattr(weather, "dome_safe", True))
        return (40 <= cloud <= 80) or (not dome and cloud < 80)
    except Exception:
        return False


@_tool
def triage_note(verdict: Dict[str, Any]) -> Optional[str]:
    """One-sentence triage note for ingestion — gated, @tool with 15s timeout."""
    if not _should_triage_advise(verdict):
        return None
    prompt = f"""In one sentence, explain this GCN trigger gate for an astronomer.
HasNS={verdict.get('gate_subclass')} gate={verdict.get('gate_reason')} confidence={verdict.get('gate_confidence')}.
Keep under 25 words, plain English, no JSON."""
    return _call_advisor(prompt)


@_tool
def host_explain(candidates: List[Any]) -> Optional[str]:
    """One-sentence host ranking explainer — gated on close race, @tool."""
    if not _should_host_explain(candidates):
        return None
    top = candidates[0] if candidates else {}
    second = candidates[1] if len(candidates) > 1 else {}
    def _get(c, k, d="?"):
        return getattr(c, k, None) if hasattr(c, k) else (c.get(k, d) if isinstance(c, dict) else d)
    prompt = f"""In one sentence, explain why host { _get(top,'name')} (S={_get(top,'composite_score',0):.2f}) outranks { _get(second,'name')} (S={_get(second,'composite_score',0):.2f}) for a kilonova follow-up. Mention Schechter vs. airmass trade-off if relevant. Under 30 words."""
    return _call_advisor(prompt)


@_tool
def weather_risk(weather: Any) -> Optional[str]:
    """One-sentence weather risk phrase — gated on marginal band, @tool."""
    if not _should_weather_risk(weather):
        return None
    cloud = getattr(weather, "cloud_cover_percent", "?")
    dome = getattr(weather, "dome_safe", "?")
    prompt = f"""In one sentence, assess observing risk: cloud {cloud}%, dome_safe={dome}. Say "approve only if urgent" when marginal, else clear. Under 25 words."""
    return _call_advisor(prompt)


def _call_advisor(prompt: str) -> Optional[str]:
    """Single LLM call for an advisor — 15s timeout, 256 tok max, advisory-only."""
    try:
        from .llm_reasoner import _primary_model_id

        model = _primary_model_id()
        key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
        if not key:
            key = (os.getenv("GROQ_API_KEY", "") or "").strip()
            if key:
                model = os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")
            else:
                return None
        # 256 tokens per spec (was 128), 15s timeout, advisory-only fallback ""
        from litellm import completion

        resp = completion(
            model=model,
            api_key=key,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
            timeout=15,
        )
        text = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
        return text[:200] if text else None
    except Exception:
        return None
