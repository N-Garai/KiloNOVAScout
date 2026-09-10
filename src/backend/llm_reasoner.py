"""LLM reasoning module for KilonovaScout v2/v4.

v2: ACCEPT/REJECT + rationale via Gemini primary / Groq fallback.
v4 M14: structured 6-field JSON {decision,confidence,risks,actions,rationale,citations}
v4 M16: robustness — 512 tok, json_object, 1-4-16s backoff, finish_reason/usage logging.
Both keys are optional: the pipeline works with zero keys.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Any, Optional, Tuple, List

import requests


def _primary_model_id() -> str:
    return os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")


def _fallback_model_id() -> str:
    return os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")


def _build_reasoning_prompt(
    verdict: Dict[str, Any],
    galaxies: list,
    weather: Any,
    skymap_summary: Dict[str, Any] | None,
) -> str:
    """Assemble a structured prompt for the reasoning LLM (M14 6-field)."""

    def _get_nested(obj, *keys, default=None):
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

    # M14: ask for 6-field structured output (was 2-field in v2)
    return f"""You are KilonovaScout, an autonomous multi-messenger astronomy targeting agent.

Given the following event pipeline data, return a JSON object with SIX fields:
1. "decision": "ACCEPT" or "REJECT"
2. "confidence": number 0.0-1.0 (your confidence in the decision)
3. "risks": array of short risk strings (e.g. ["cloud 62%", "moon 18°"])
4. "actions": array of 2-3 suggested actions from ["approve","monitor","reject"]
5. "rationale": 2-3 sentence plain-English justification for the dashboard
6. "citations": array of data citations (e.g. ["VOEvent BNS=0.98", "Open-Meteo cloud=62%"])

Do NOT return anything except the JSON object. Keep rationale under 40 words.

--- Trigger Verdict ---
IVORN: {verdict.get('superevent_id', 'unknown')}
FAR: {verdict.get('far', 'unknown')}
p_astro: {verdict.get('p_astro', 'unknown')}
BNS: {verdict.get('BNS', verdict.get('bns', 'unknown'))} NSBH: {verdict.get('NSBH', verdict.get('nsbh', 'unknown'))} HasNS: {verdict.get('gate_confidence', verdict.get('HasNS', 'unknown'))}
gate: {verdict.get('gate_reason', verdict.get('gate_subclass', ''))}

--- Skymap ---
{json.dumps(skymap_summary, indent=2) if skymap_summary else 'synthetic fallback'}

--- Ranked Candidate Galaxies ---
{galaxies_text if galaxies_text else 'no candidates yet'}

--- Observatory Weather ({getattr(weather, 'observatory_name', 'unknown')}) ---
{weather_text}

--- Instructions ---
Evaluate whether the trigger warrants follow-up. FAR must be <1e-7 Hz, HasNS>0.2, dome_safe=True.
Return ONLY JSON with the six keys above.
"""


def _call_litellm(model_id: str, prompt: str, api_key: str, timeout: int = 20) -> str:
    """Invoke litellm with JSON mode, 512-token budget, and 1-4-16s retry (M16)."""
    last_exc: Optional[Exception] = None
    # Spec M16: backoff 1s -> 4s -> 16s (not 1-2-4)
    backoffs = [1, 4, 16]
    for attempt in range(3):
        try:
            from litellm import completion

            response = completion(
                model=model_id,
                api_key=api_key,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            # M16: log finish_reason and usage for truncation diagnosis
            try:
                choice = response.choices[0] if getattr(response, "choices", None) else None
                fr = getattr(choice, "finish_reason", None) if choice else None
                usage = getattr(response, "usage", None)
                prompt_tok = getattr(usage, "prompt_tokens", None) if usage else None
                comp_tok = getattr(usage, "completion_tokens", None) if usage else None
                total_tok = getattr(usage, "total_tokens", None) if usage else None
                print(f"[LLM] {model_id} finish_reason={fr} usage={{prompt:{prompt_tok} comp:{comp_tok} total:{total_tok}}}")
                if fr == "length":
                    print(f"[LLM] WARNING truncation (finish_reason=length) — consider raising max_tokens")
            except Exception:
                pass
            text = response.choices[0].message.content
            if text:
                return text
            raise RuntimeError("Empty completion")
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "429" in msg or "503" in msg or "rate" in msg or "overload" in msg or "429" in msg:
                wait = backoffs[attempt] if attempt < len(backoffs) else 16
                print(f"[LLM] {model_id} rate-limited, retry {attempt+1}/3 in {wait}s")
                time.sleep(wait)
                continue
            break
    # Fallback: direct HTTP to the provider
    if "gemini" in model_id:
        return _call_gemini_rest(api_key, prompt, timeout, model_id)
    elif "groq" in model_id:
        return _call_groq_rest(api_key, prompt, timeout, model_id)
    if last_exc:
        raise last_exc
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
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # M16: log finishReason + usageMetadata
    try:
        cand = (data.get("candidates") or [{}])[0]
        fr = cand.get("finishReason")
        usage = data.get("usageMetadata", {})
        print(f"[LLM] {model} finishReason={fr} usageMetadata={usage}")
    except Exception:
        pass
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq_rest(api_key: str, prompt: str, timeout: int, model_id: str = "") -> str:
    """Direct Groq REST call for Llama 3."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _model_name(model_id) or "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        choice = (data.get("choices") or [{}])[0]
        fr = choice.get("finish_reason")
        usage = data.get("usage", {})
        print(f"[LLM] groq finish_reason={fr} usage={usage}")
    except Exception:
        pass
    return data["choices"][0]["message"]["content"]


def reason_about_event(
    verdict: Dict[str, Any],
    galaxies: list,
    weather: Any,
    skymap_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Invoke the LLM to reason about the event (M14 6-field).

    Returns dict with keys {decision, confidence, risks, actions, rationale, citations}.
    Falls back deterministically if keys absent or both models fail.
    For backward compat, also supports tuple unpacking via ``__iter__`` shim — but
    callers should use the dict.
    """
    primary_id = _primary_model_id()
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

    # Both failed or keys absent — deterministic fallback (6-field)
    print("[LLM] No API keys available or both models failed; using deterministic rationale.")
    if verdict.get("status") == "REJECTED":
        return {
            "decision": "REJECT",
            "confidence": 0.9,
            "risks": [str(verdict.get("gate_reason", "rejected"))],
            "actions": ["reject"],
            "rationale": "Trigger rejected by ingestion filter.",
            "citations": [f"gate {verdict.get('gate_reason','')}"],
        }
    cloud = getattr(weather, "cloud_cover_percent", 0) if weather else 0
    dome = getattr(weather, "dome_safe", True) if weather else True
    risks = []
    if cloud and float(cloud) > 40:
        risks.append(f"cloud {cloud}%")
    if not dome:
        risks.append("dome unsafe")
    return {
        "decision": "ACCEPT",
        "confidence": 0.75,
        "risks": risks,
        "actions": ["approve"] if dome and float(cloud or 0) < 60 else ["monitor", "approve"],
        "rationale": f"Trigger accepted (p_astro={verdict.get('p_astro', '?')}). {len(galaxies)} candidate(s) identified.",
        "citations": [f"p_astro {verdict.get('p_astro','?')}", f"cloud {cloud}%"],
    }


def _extract_json_object(raw: str) -> Optional[dict]:
    """Extract the first balanced {...} JSON object from model output."""
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


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    """Parse LLM JSON response into 6-field dict (M14) — never leaks raw braces."""
    raw = (raw or "").strip()
    data = _extract_json_object(raw)
    if data is not None:
        decision = str(data.get("decision", "ACCEPT")).upper()
        if decision not in ("ACCEPT", "REJECT"):
            decision = "ACCEPT"
        rationale = str(data.get("rationale", "")).strip() or "Target candidates identified for follow-up."
        # Confidence 0..1
        try:
            conf = float(data.get("confidence", 0.75))
            confidence = max(0.0, min(1.0, conf))
        except Exception:
            confidence = 0.75
        # Risks / actions / citations — normalize to lists of strings
        def _list(key, default):
            val = data.get(key, default)
            if val is None:
                return default
            if isinstance(val, str):
                return [val] if val else default
            if isinstance(val, list):
                return [str(x) for x in val][:5]
            return default
        risks = _list("risks", [])
        actions = _list("actions", ["approve"] if decision == "ACCEPT" else ["reject"])
        citations = _list("citations", [])
        return {
            "decision": decision,
            "confidence": round(confidence, 3),
            "risks": risks,
            "actions": actions,
            "rationale": rationale[:600],
            "citations": citations[:5],
        }
    # No parseable object — extract what we can, never raw JSON braces.
    text = raw.strip().strip("`").strip()
    if text.startswith("{"):
        text = ""
    if "REJECT" in text.upper():
        return {"decision": "REJECT", "confidence": 0.6, "risks": [], "actions": ["reject"], "rationale": (text or "Trigger rejected by model.")[:300], "citations": []}
    return {"decision": "ACCEPT", "confidence": 0.7, "risks": [], "actions": ["approve"], "rationale": (text or "Target candidates identified for follow-up.")[:300], "citations": []}


# Backward-compat shim: older code did ``decision, rationale = reason_about_event(...)``
# Keep a helper that returns a 2-tuple for those call sites while new code uses the dict.
def _parse_llm_response_legacy(raw: str) -> Tuple[str, str]:
    d = _parse_llm_response(raw)
    return d["decision"], d["rationale"]
