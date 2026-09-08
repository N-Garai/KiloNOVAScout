"""LLM reasoning module for KilonovaScout v2 Milestone 1.

Provides `reason_about_event()` which invokes an LLM (Gemini 1.5 Flash primary,
Groq Llama 3 fallback) with the full pipeline context and returns an
ACCEPT/REJECT triage plus a plain-English rationale.

Both keys are optional: the pipeline works with zero keys, returning an
empty rationale string.  Failover is manual per the pinned SDK constraint.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Any, Optional, Tuple

import requests


def _primary_model_id() -> str:
    # 1.5-flash (HTTP 404) and 2.0-flash (retired Mar 2026) are both dead.
    # gemini-2.5-flash is GA, documented, and free-tier.  Overridable.
    return os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")


def _fallback_model_id() -> str:
    # llama-3.3-70b-versatile was shut down Aug 16, 2026 (free/dev tiers).
    # Groq's Production-tier replacement is openai/gpt-oss-120b.
    return os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")


def _build_reasoning_prompt(
    verdict: Dict[str, Any],
    galaxies: list,
    weather: Any,
    skymap_summary: Dict[str, Any] | None,
) -> str:
    """Assemble a structured prompt for the reasoning LLM."""

    def _get_nested(obj, *keys, default=None):
        """Safely walk nested dicts/pydantic models."""
        cur = obj
        for key in keys:
            if cur is None:
                return default
            if isinstance(cur, dict):
                cur = cur.get(key)
            elif hasattr(cur, key):
                cur = getattr(cur, key)
            else:
                return default
        return cur if cur is not None else default

    galaxies_text = "\n".join(
        f"  {i+1}. {_get_nested(g, 'name', default='?')} — "
        f"RA/Dec {_get_nested(g, 'ra', default=0):.3f}/{_get_nested(g, 'dec', default=0):.3f}, "
        f"dist {_get_nested(g, 'distance_mpc', default='?')} Mpc, "
        f"composite_score={_get_nested(g, 'composite_score', default=0):.3f}, "
        f"P_spatial={_get_nested(g, 'score_breakdown', 'terms', 'spatial', default=0.0):.3f}"
        for i, g in enumerate(galaxies[:5])
    )

    weather_text = "unknown"
    if weather is not None:
        weather_text = (
            f"cloud_cover={weather.cloud_cover_percent}%, "
            f"seeing={weather.seeing_conditions}, "
            f"humidity={weather.humidity_pct}%, "
            f"dome_safe={weather.dome_safe}"
        )

    return f"""You are KilonovaScout, an autonomous multi-messenger astronomy targeting agent.

Given the following event pipeline data, return a JSON object with two fields:
1. "decision": "ACCEPT" or "REJECT"
2. "rationale": A 2-3 sentence plain-English justification for the dashboard.

Do NOT return anything except the JSON object.

--- Trigger Verdict ---
IVORN: {verdict.get('superevent_id', 'unknown')}
FAR: {verdict.get('far', 'unknown')}
p_astro: {verdict.get('p_astro', 'unknown')}

--- Skymap ---
{json.dumps(skymap_summary, indent=2) if skymap_summary else 'synthetic fallback'}

--- Ranked Candidate Galaxies ---
{galaxies_text if galaxies_text else 'no candidates yet'}

--- Observatory Weather ({getattr(weather, 'observatory_name', 'unknown')}) ---
{weather_text}

--- Instructions ---
Evaluate whether the trigger is astrophysically significant enough to warrant
telescope follow-up.  Consider: FAR must be < 1e-7 Hz, neutron-star probability
> 0.2, weather dome_safe=True, and at least one candidate above horizon.
Return ONLY the JSON with "decision" and "rationale" keys.
"""


def _call_litellm(model_id: str, prompt: str, api_key: str, timeout: int = 15) -> str:
    """Invoke litellm via the REST API or direct import."""
    try:
        from litellm import completion
        response = completion(
            model=model_id,
            api_key=api_key,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
        )
        return response.choices[0].message.content
    except Exception:
        pass

    # Fallback: direct HTTP to the provider
    if "gemini" in model_id:
        return _call_gemini_rest(api_key, prompt, timeout, model_id)
    elif "groq" in model_id:
        return _call_groq_rest(api_key, prompt, timeout, model_id)

    raise RuntimeError(f"No invocation method available for model: {model_id}")


def _model_name(model_id: str) -> str:
    """Strip the litellm provider prefix (``gemini/``, ``groq/``, ``google/``)."""
    name = (model_id or "").split("/", 1)[-1].strip()
    return name or model_id


def _call_gemini_rest(api_key: str, prompt: str, timeout: int, model_id: str = "") -> str:
    """Direct Google AI Studio REST call for Gemini models."""
    model = _model_name(model_id) or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 256},
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq_rest(api_key: str, prompt: str, timeout: int, model_id: str = "") -> str:
    """Direct Groq REST call for Llama 3."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _model_name(model_id) or "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 256,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def reason_about_event(
    verdict: Dict[str, Any],
    galaxies: list,
    weather: Any,
    skymap_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Invoke the LLM to reason about the event.

    Returns (decision, rationale) where decision is 'ACCEPT'/'REJECT'
    and rationale is a plain-English justification.
    Falls back gracefully if keys are missing or both models fail.
    """
    primary_id = _primary_model_id()
    # Strip pasted keys: a trailing newline (copy-paste from dashboards)
    # breaks the Authorization header and killed the Groq fallback in prod.
    primary_key = os.getenv("GEMINI_API_KEY", "").strip()
    fallback_id = _fallback_model_id()
    fallback_key = os.getenv("GROQ_API_KEY", "").strip()

    prompt = _build_reasoning_prompt(verdict, galaxies, weather, skymap_summary)

    # Try primary model
    if primary_key:
        try:
            raw = _call_litellm(primary_id, prompt, primary_key)
            return _parse_llm_response(raw)
        except Exception as e:
            print(f"[LLM] Primary ({primary_id}) failed: {e}")

    # Try fallback model
    if fallback_key:
        try:
            raw = _call_litellm(fallback_id, prompt, fallback_key)
            return _parse_llm_response(raw)
        except Exception as e:
            print(f"[LLM] Fallback ({fallback_id}) failed: {e}")

    # Both failed or keys absent — deterministic fallback
    print("[LLM] No API keys available or both models failed; using deterministic rationale.")
    if verdict.get("status") == "REJECTED":
        return "REJECT", "Trigger rejected by ingestion filter."
    return "ACCEPT", (
        f"Trigger accepted (p_astro={verdict.get('p_astro', '?')}). "
        f"{len(galaxies)} candidate galaxy/galaxies identified for follow-up."
    )


def _extract_json_object(raw: str) -> Optional[dict]:
    """Extract the first balanced {...} JSON object from model output.

    Models routinely wrap the answer in fences, preambles ("Here is..."),
    or trailing commentary — all of which break a naive json.loads and used
    to leak raw JSON into the dashboard rationale.  Brace-matching finds the
    object regardless of surrounding prose (string-aware, so braces inside
    quoted text don't unbalance the scan).
    """
    start = raw.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(raw[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
                return data if isinstance(data, dict) else None
    return None


def _parse_llm_response(raw: str) -> Tuple[str, str]:
    """Parse LLM JSON response into (decision, rationale)."""
    raw = (raw or "").strip()
    data = _extract_json_object(raw)
    if data is not None:
        decision = str(data.get("decision", "ACCEPT")).upper()
        rationale = str(data.get("rationale", "")).strip()
        if decision not in ("ACCEPT", "REJECT"):
            decision = "ACCEPT"
        if rationale:
            return decision, rationale[:600]
    # No parseable object — extract what we can, never raw JSON braces.
    text = raw.strip().strip("`").strip()
    if text.startswith("{"):
        text = ""
    if "REJECT" in text.upper():
        return "REJECT", (text or "Trigger rejected by model.")[:300]
    return "ACCEPT", (text or "Target candidates identified for follow-up.")[:300]
