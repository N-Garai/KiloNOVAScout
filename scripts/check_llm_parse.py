"""check_llm_parse.py - Executable verification for LLM response parsing.

Covers the production failure: model wraps JSON in prose/fences/trailing
commentary, which must NEVER leak raw braces into the dashboard rationale.
Extended for v4 M14 6-field + M16 robustness (overflow).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from backend.llm_reasoner import _parse_llm_response

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _get(result, key):
    """Handle both dict (new) and tuple (legacy) return shapes."""
    if isinstance(result, dict):
        return result.get(key)
    if isinstance(result, (list, tuple)) and len(result) == 2:
        return result[0] if key == "decision" else result[1] if key == "rationale" else None
    return None


# 1. Clean JSON (the case that already worked) — now 2-field still passes via defaults
result = _parse_llm_response('{"decision": "ACCEPT", "rationale": "Clear skies, go observe."}')
check("clean json", _get(result, "decision") == "ACCEPT" and _get(result, "rationale") == "Clear skies, go observe.", (result))

# 2. Fenced block (common model habit)
result = _parse_llm_response('```json\n{"decision": "REJECT", "rationale": "Overcast."}\n```')
check("fenced json", _get(result, "decision") == "REJECT" and _get(result, "rationale") == "Overcast.", (result))

# 3. Prose preamble + trailing commentary (the production failure)
raw = ('Here is my assessment:\n{"decision": "ACCEPT", '
       '"rationale": "Five hosts ranked, NGC 4993 on top."}\nHope this helps!')
result = _parse_llm_response(raw)
check("prose-wrapped json", _get(result, "decision") == "ACCEPT" and _get(result, "rationale") == "Five hosts ranked, NGC 4993 on top.", (result))
check("no braces leak", "{" not in str(_get(result, "rationale")) and "}" not in str(_get(result, "rationale")), _get(result, "rationale"))

# 4. Braces inside quoted strings must not unbalance the scan
raw = '{"decision": "ACCEPT", "rationale": "Score {S} = 1.2 {units} looks good"}'
result = _parse_llm_response(raw)
check("braces in strings", _get(result, "decision") == "ACCEPT" and "{S}" in str(_get(result, "rationale")), (result))

# 5. Garbage in, graceful out (never raw JSON, never empty)
result = _parse_llm_response('Internal server error, try later')
check("garbage fallback", _get(result, "decision") == "ACCEPT" and _get(result, "rationale") == "Internal server error, try later", (result))
result = _parse_llm_response('')
check("empty fallback", _get(result, "decision") == "ACCEPT" and len(str(_get(result, "rationale"))) > 0, (result))
result = _parse_llm_response('{not valid json')
check("broken brace fallback", "{" not in str(_get(result, "rationale")), _get(result, "rationale"))

# 6. M14 6-field structured output (v4)
raw = '{"decision":"ACCEPT","confidence":0.82,"risks":["cloud 62%","moon 18°"],"actions":["approve","monitor"],"rationale":"Five hosts ranked; NGC 4993 on top. 62% cloud — approve only if urgent.","citations":["VOEvent BNS=0.98","Open-Meteo cloud=62%"]}'
result = _parse_llm_response(raw)
check("6-field decision", _get(result, "decision") == "ACCEPT", result)
check("6-field confidence", abs(float(result.get("confidence", 0) if isinstance(result, dict) else 0) - 0.82) < 0.01, result)
check("6-field risks", isinstance(result.get("risks", None), list) and "cloud 62%" in result.get("risks", []) if isinstance(result, dict) else False, result)
check("6-field actions", isinstance(result.get("actions", None), list) and "approve" in result.get("actions", []) if isinstance(result, dict) else False, result)
check("6-field citations", isinstance(result.get("citations", None), list) and len(result.get("citations", [])) == 2 if isinstance(result, dict) else False, result)
check("6-field rationale", "NGC 4993" in str(_get(result, "rationale")), result)

# 7. M14 fenced 6-field
raw = '```json\n{"decision":"REJECT","confidence":0.91,"risks":["dome unsafe"],"actions":["reject"],"rationale":"Far too high, dome closed.","citations":["FAR 1e-6"]}\n```'
result = _parse_llm_response(raw)
check("fenced 6-field", _get(result, "decision") == "REJECT" and float(result.get("confidence",0) if isinstance(result, dict) else 0) > 0.8, result)

# 8. M16 max_tokens overflow / truncation — model clipped mid-JSON (no closing brace)
truncated = '{"decision": "ACCEPT", "rationale": "Five hosts ranked, NGC 4993 on top. 62% cloud makes dome ma'
result = _parse_llm_response(truncated)
check("truncation no braces leak", "{" not in str(_get(result, "rationale")), _get(result, "rationale"))
check("truncation fallback not empty", len(str(_get(result, "rationale"))) > 0, result)

# 9. M16 overflow with 6-field truncated inside risks array
truncated6 = '{"decision":"ACCEPT","confidence":0.75,"risks":["cloud 62%","moon'
result = _parse_llm_response(truncated6)
check("6-field truncation safe", _get(result, "decision") in ("ACCEPT","REJECT") and "{" not in str(_get(result, "rationale")), result)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
