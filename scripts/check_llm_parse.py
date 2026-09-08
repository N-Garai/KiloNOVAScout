"""check_llm_parse.py - Executable verification for LLM response parsing.

Covers the production failure: model wraps JSON in prose/fences/trailing
commentary, which must NEVER leak raw braces into the dashboard rationale.

Run:  python scripts/check_llm_parse.py
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


# 1. Clean JSON (the case that already worked)
d, r = _parse_llm_response('{"decision": "ACCEPT", "rationale": "Clear skies, go observe."}')
check("clean json", d == "ACCEPT" and r == "Clear skies, go observe.", (d, r))

# 2. Fenced block (common model habit)
d, r = _parse_llm_response('```json\n{"decision": "REJECT", "rationale": "Overcast."}\n```')
check("fenced json", d == "REJECT" and r == "Overcast.", (d, r))

# 3. Prose preamble + trailing commentary (the production failure)
raw = ('Here is my assessment:\n{"decision": "ACCEPT", '
       '"rationale": "Five hosts ranked, NGC 4993 on top."}\nHope this helps!')
d, r = _parse_llm_response(raw)
check("prose-wrapped json", d == "ACCEPT" and r == "Five hosts ranked, NGC 4993 on top.", (d, r))
check("no braces leak", "{" not in r and "}" not in r, r)

# 4. Braces inside quoted strings must not unbalance the scan
raw = '{"decision": "ACCEPT", "rationale": "Score {S} = 1.2 {units} looks good"}'
d, r = _parse_llm_response(raw)
check("braces in strings", d == "ACCEPT" and "{S}" in r, (d, r))

# 5. Garbage in, graceful out (never raw JSON, never empty)
d, r = _parse_llm_response('Internal server error, try later')
check("garbage fallback", d == "ACCEPT" and r == "Internal server error, try later", (d, r))
d, r = _parse_llm_response('')
check("empty fallback", d == "ACCEPT" and len(r) > 0, (d, r))
d, r = _parse_llm_response('{not valid json')
check("broken brace fallback", "{" not in r, r)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
