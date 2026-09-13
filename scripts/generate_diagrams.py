"""Generate PNG diagrams from mermaid scripts using mermaid.ink API."""

import base64
import os
import sys
import urllib.request
import urllib.parse
import time

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets")
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets-script")

DIAGRAMS = [
    ("01-system-architecture", "System Architecture"),
    ("02-agent-pipeline-dag", "Agent Pipeline DAG"),
    ("03-event-class-triage", "Event Class Triage"),
    ("04-data-fallback-chain", "Data Fallback Chain"),
    ("05-deployment-topology", "Deployment Topology"),
    ("06-scoring-formula", "Scoring Formula"),
]


def render_mermaid(script_path: str, output_path: str, width: int = 2400, height: int = 2400):
    """Render a mermaid script to PNG via mermaid.ink API."""
    with open(script_path, "r", encoding="utf-8") as f:
        mermaid_code = f.read()

    # Strip the %%{init: ...}%% line and use plain theme for light background
    lines = mermaid_code.strip().split("\n")
    clean_lines = []
    for l in lines:
        stripped = l.strip()
        if stripped.startswith("%%{"):
            continue
        # Replace dark theme styles with defaults
        clean_lines.append(l)
    clean_code = "\n".join(clean_lines)

    # Encode for mermaid.ink with white background
    encoded = base64.urlsafe_b64encode(clean_code.encode("utf-8")).decode("utf-8")
    url = f"https://mermaid.ink/img/{encoded}?w={width}&h={height}&bgColor=ffffff&theme=default"

    try:
        print(f"  Fetching: {url[:80]}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            with open(output_path, "wb") as f:
                f.write(data)
            size_kb = len(data) / 1024
            print(f"  Saved: {output_path} ({size_kb:.0f} KB)")
            return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)

    results = []
    for name, title in DIAGRAMS:
        script = os.path.join(SCRIPTS_DIR, f"{name}.mmd")
        output = os.path.join(ASSETS_DIR, f"{name}.png")
        print(f"[{title}]")
        if not os.path.exists(script):
            print(f"  Script not found: {script}")
            results.append((name, False))
            continue
        ok = render_mermaid(script, output)
        results.append((name, ok))
        time.sleep(1)

    print("\n--- Results ---")
    for name, ok in results:
        status = "OK" if ok else "FAILED"
        print(f"  {name}: {status}")

    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"\n{len(failed)} diagrams failed.")
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} diagrams generated successfully.")


if __name__ == "__main__":
    main()
