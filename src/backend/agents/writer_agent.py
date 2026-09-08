"""writer_agent.py - Writer agent for KilonovaScout v3 (PRD Milestone 6).

Produces the structured observation report in dual format:

1. **Markdown** — human/CLI readable, GCN-Circular style.
2. **HTML** — print-optimized stylesheet so the browser "Download PDF"
   (window.print) produces a publication-grade PDF. Render-safe: zero
   system dependencies (PRD 6.5 Option C).

Every measurement carries its full calculation trace (PRD 6.4): inputs,
formula, substitution, and result — no black-box numbers. The trace
serializes the exact ``ScoreBreakdown`` computed by the scoring tool; no
calculation is re-done here.
"""

from __future__ import annotations

import datetime
import html as _html
import json
from typing import Any, Dict, List, Optional

from ..event_classes import METADATA, get_profile


def _fmt(value: Any, nd: int = 4, default: str = "—") -> str:
    try:
        return f"{float(value):.{nd}f}"
    except (TypeError, ValueError):
        return default


def _sci(value: Any, nd: int = 3, default: str = "—") -> str:
    try:
        return f"{float(value):.{nd}e}"
    except (TypeError, ValueError):
        return default


def _candidate_trace_markdown(candidate: Dict[str, Any], event_class: str = "bns") -> List[str]:
    """Step-by-step calculation trace for one candidate (PRD 6.4.2).

    Only the active class terms are rendered — measurements a class does
    not need (e.g. host mass for GRBs) are listed once as skipped, so the
    trace stays an honest audit of what actually ran.
    """
    profile = get_profile(event_class)
    active = set(profile.get("active_terms", []))
    lines: List[str] = []
    bd = candidate.get("score_breakdown") or {}
    terms = bd.get("terms", {}) or {}
    weights = bd.get("weights", {}) or {}
    name = candidate.get("name", "Candidate")
    obs = candidate.get("observability") or {}

    lines.append(f"#### Calculation Trace: {name}")
    lines.append("")
    steps: List[str] = []
    steps.append("**Spatial containment:** "
                 f"P_overlap = {_fmt(terms.get('spatial'))} "
                 "(localization probability density at the candidate pixel, "
                 "integrated over a 1 deg² follow-up field of view)")
    if "schechter" in active:
        steps.append("**Schechter weight:** "
                     f"w = (L_K/L_★)^α · e^(−L_K/L_★) with "
                     f"L_K = {_sci(candidate.get('luminosity_k'))} L_☉, "
                     f"L_★ = {_sci(weights.get('schechter_l_star'))} L_☉, "
                     f"α = {_fmt(weights.get('schechter_alpha'), 1)} "
                     f"→ w = {_fmt(terms.get('schechter'))}")
    steps.append("**Airmass (windowed):** "
                 f"X̄ = (1/N)·Σ sec(z_k) over a 2-hour, 12-sample window "
                 f"→ X̄ = {_fmt(terms.get('airmass'), 3)}")
    steps.append("**Atmospheric extinction:** "
                 f"Δm = k·X̄ with k = {_fmt(weights.get('zenith_extinction'), 2)} mag/airmass "
                 f"→ Δm = {_fmt(obs.get('extinction_mag'))} mag")
    steps.append("**Cloud penalty:** "
                 f"C = {_fmt(terms.get('cloud'), 3)} (fractional, from Open-Meteo)")
    if "grb_boost" in active:
        steps.append("**GRB boost:** "
                     f"B_GRB = {_fmt(terms.get('grb_boost'), 1)} "
                     "(3.0 when multi-messenger coincidence confirmed, else 0)")
    if "snr" in active:
        steps.append("**SNR proxy:** "
                     f"m = {_fmt(obs.get('apparent_mag'), 2)} at d_L → "
                     f"SNR = {_fmt(terms.get('snr'), 3)} "
                     "(10·10^(0.4·(17 − m)); 1-m telescope, 300 s)")
    if "flux" in active:
        steps.append("**Burst flux proxy:** "
                     f"F = {_fmt(terms.get('flux'), 3)} "
                     "(log-scaled notice fluence/peak-flux; 1.0 at 1e-6 erg/cm²)")
    if "signalness" in active:
        steps.append("**Neutrino signalness:** "
                     f"s = {_fmt(terms.get('signalness'), 3)} "
                     "(astrophysical probability from the IceCube notice)")
    steps.append("**Lunar penalty:** "
                 f"Moon separation = {_fmt(obs.get('moon_separation_deg'), 2)}° "
                 f"→ L_moon = {_fmt(terms.get('lunar'), 3)} "
                 "(0 above 30°, 1 below 10°, linear between)")
    skipped = [t for t in ("schechter", "grb_boost", "snr", "flux", "signalness") if t not in active]
    if skipped:
        steps.append(f"**Skipped for this event class:** {', '.join(skipped)} "
                     "(weight 0 — measurement not applicable)")
    steps.append(f"**Final score:** {profile.get('formula', 'S')} = "
                 f"**{_fmt(bd.get('total'))}**")
    for i, step in enumerate(steps, start=1):
        lines.append(f"{i}. {step}")
    lines.append("")
    return lines

def _data_sources_table(record) -> List[str]:
    prov = record.provenance or {}
    skymap_url = "bundled bayestar.fits.gz"
    ss = (record.event or {}).get("skymap_summary")
    if isinstance(ss, dict) and ss.get("url"):
        skymap_url = ss["url"]
    return [
        "| Component | Source | Provenance |",
        "|---|---|---|",
        f"| Skymap | `{skymap_url}` | `{prov.get('skymap', 'unknown')}` |",
        "| Catalog | CDS VizieR TAP / bundled GLADE cache | `{prov.get('catalog', 'unknown')}` |",
        "| Weather | Open-Meteo API (keyless) | `live` |",
        f"| Event | GCN ({record.source}) | `{prov.get('event', record.source)}` |",
        "",
    ]


def _skymap_stats(record) -> Dict[str, Any]:
    """Extract skymap statistics recorded at parse time (agent state snapshot)."""
    event = record.event or {}
    stats = event.get("skymap_summary") if isinstance(event.get("skymap_summary"), dict) else {}
    return stats or {}


def _classification_lines(event: Dict[str, Any]) -> List[str]:
    """Trigger-classification section shared by all report formats."""
    event_class = event.get("event_class") or "bns"
    profile = get_profile(event_class)
    label = METADATA.get(event_class, METADATA["bns"])["label"]
    return [
        f"**Event class:** `{label}` (`{event_class}`)",
        f"**Ingest verdict:** `{event.get('gate_status', 'unknown')}` — "
        f"{event.get('gate_reason', 'no gate record')} "
        f"(confidence {event.get('gate_confidence', '—')}, subclass `{event.get('gate_subclass', '—')}`)",
        f"**Ranking strategy:** {profile.get('strategy', '')}",
        f"**Scoring formula:** `{profile.get('formula', '')}`",
    ]


def build_report_markdown(record, weights: Optional[Dict[str, float]] = None) -> str:
    """Full v3 Markdown report with provenance and calculation traces."""
    event = record.event or {}
    prov = record.provenance or {}
    sky = _skymap_stats(record)
    event_class = event.get("event_class") or "bns"
    profile = get_profile(event_class)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    lines: List[str] = []
    lines.append("# KilonovaScout Follow-Up Report")
    lines.append("")
    lines.append(f"**Event:** `{event.get('ivorn', 'unknown')}`  ")
    lines.append(f"**Trigger time:** `{event.get('event_time', 'unknown')}`  ")
    lines.append(f"**Run:** `{record.run_id}` ({record.source}) — status `{record.status}`  ")
    lines.append(f"**Generated:** {now}")
    lines.append("")

    lines.append("## Event Summary")
    lines.append("")
    lines.append(f"- Data provenance: skymap = `{prov.get('skymap', 'unknown')}`, "
                 f"catalog = `{prov.get('catalog', 'unknown')}`, event = `{prov.get('event', record.source)}`")
    if (prov.get('event', record.source) or record.source) == "live":
        lines.append("- **Live trigger:** this run processed a real notice from the NASA GCN stream.")
    else:
        lines.append("- **Fallback simulation:** no live trigger was pending at launch, so this run "
                     "replays the archived GW170817 packet as a stand-in. Every downstream data tier "
                     "(skymap / catalog) is labeled per stage — nothing is presented as live sky data.")
    lines.append("")

    lines.append("## Sky Localization")
    lines.append("")
    lines.append("$$P(\\hat{n}) = \\mathrm{PROB}(\\hat{n}), \\quad d_L \\sim \\mathcal{N}(\\mu_{d}, \\sigma_{d}^2)$$")
    lines.append("")
    lines.append("### Calculation Trace: Sky Localization")
    lines.append("")
    lines.append("1. **Input:** FITS skymap, pixels sorted by PROB descending "
                 "(`sorted_idx = argsort(PROB)[::-1]`)")
    lines.append("2. **CDF:** cumulative probability C_k = Σ_{i≤k} P_i")
    lines.append("3. **90% threshold:** select pixels where C_k ≤ 0.90")
    if sky.get("area_sq_deg") is not None:
        lines.append(f"4. **Result:** 90% credible area = **{_fmt(sky.get('area_sq_deg'), 2)} deg²**, "
                     f"{sky.get('pixel_count_90', '?')} pixels at NSIDE {sky.get('nside', '?')}")
    else:
        lines.append("4. **Result:** 90% credible region extracted from the skymap")
    lines.append("5. **Distance:** d̄_L = Σ w_i·μ_i / Σ w_i (probability-weighted), "
                 f"d̄ = {_fmt(sky.get('dist_mean'), 1)} Mpc, σ = {_fmt(sky.get('dist_std'), 1)} Mpc")
    lines.append("")

    lines.append("## Galaxy Candidates")
    lines.append("")
    lines.append("| Name | PGC | d_L (Mpc) | P_overlap | L_K (L_☉) | Score | Source |")
    lines.append("|---|---|---|---|---|---|---|")
    for cand in record.candidates:
        lines.append(
            f"| {cand.get('name', '—')} "
            f"| {cand.get('pgc', '—')} "
            f"| {_fmt(cand.get('distance_mpc'), 2)} "
            f"| {_fmt(cand.get('probability'))} "
            f"| {_sci(cand.get('luminosity_k'))} "
            f"| {_fmt(cand.get('composite_score'), 3)} "
            f"| `{cand.get('catalog_source', 'unknown')}` |"
        )
    lines.append("")
    lines.append("## Trigger Classification")
    lines.append("")
    lines.extend(f"- {line}" for line in _classification_lines(event))
    lines.append("")
    lines.append("### Scoring Formula")
    lines.append("")
    lines.append(f"$${profile.get('formula_tex', profile.get('formula', ''))}$$")
    lines.append("")
    for cand in record.candidates:
        lines.extend(_candidate_trace_markdown(cand, event_class))

    weather = record.weather
    if weather:
        lines.append("## Observatory Conditions")
        lines.append("")
        lines.append(f"- Site: `{weather.get('observatory_name')}` "
                     f"(lat = {weather.get('latitude')}, lon = {weather.get('longitude')})")
        lines.append(f"- Cloud cover: `{weather.get('cloud_cover_percent')}` %")
        lines.append(f"- Humidity: `{weather.get('humidity_pct')}` %")
        lines.append(f"- Dome safe: `{weather.get('dome_safe')}`")
        lines.append(f"- Seeing: `{weather.get('seeing_conditions')}`")
        lines.append("")
        lines.append("### Calculation Trace: Observatory Conditions")
        lines.append("")
        lines.append("1. **Cloud cover:** C = cloudcover/100 from "
                     "`GET api.open-meteo.com/v1/forecast?latitude=…`")
        lines.append("2. **Humidity:** H = relativehumidity_2m (%); dome safe ⟺ H ≤ 85 % and C ≤ 40 %")
        lines.append("3. **Airmass integral:** X̄ = (1/12)·Σ_{k=1..12} sec(z_k) sampled over a 2-hour window")
        lines.append("")

    if record.slew_script:
        lines.append("## Observation Schedule")
        lines.append("")
        lines.append("Slew order optimized with a greedy nearest-neighbor TSP "
                     "heuristic on the local alt/az sphere (PRD M7.2).")
        lines.append("")
        lines.append("```xml")
        lines.append(record.slew_script)
        lines.append("```")
        lines.append("")

    lines.append("## Pipeline Execution Log")
    lines.append("")
    lines.append("| Step | Tool | Status | Attempt | Duration (ms) |")
    lines.append("|---|---|---|---|---|")
    for s in record.steps:
        dur = s.duration_ms if s.duration_ms is not None else "—"
        lines.append(f"| {s.step} | `{s.tool_name}` | {s.status} | {s.attempt} | {dur} |")
    lines.append("")

    lines.append("## Data Sources")
    lines.append("")
    lines.extend(_data_sources_table(record))

    if record.llm_rationale:
        lines.append("## LLM Rationale")
        lines.append("")
        lines.append(record.llm_rationale)
        lines.append("")

    top = record.candidates[0] if record.candidates else None
    if top:
        lines.append("## GCN Circular Draft")
        lines.append("")
        lines.append(f"> **KilonovaScout follow-up of {event.get('ivorn', 'a LVC trigger')}**")
        lines.append(">")
        lines.append(f"> We identified {top.get('name', 'a candidate host')} "
                     f"(PGC {top.get('pgc', '?')}, d_L = {_fmt(top.get('distance_mpc'), 1)} Mpc) "
                     "as the highest-priority host-galaxy candidate through "
                     "autonomous multi-messenger triage (GLADE+ crossmatch, "
                     "windowed airmass and lunar-separation filtering). "
                     f"Composite prioritization score: {_fmt(top.get('composite_score'), 3)}. "
                     "Robotic follow-up is pending human approval.")
        lines.append("")

    if record.observation_header:
        lines.append("## FITS Observation Header")
        lines.append("")
        lines.append("```text")
        lines.append(record.observation_header)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by KilonovaScout v3 — Autonomous Multi-Messenger Targeting Agent — {now}*")
    return "\n".join(lines)

_PRINT_CSS = """
  body { font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a;
         max-width: 820px; margin: 0 auto; padding: 32px 24px; line-height: 1.5; }
  h1 { border-bottom: 2px solid #222; padding-bottom: 8px; font-size: 1.6em; }
  h2 { border-bottom: 1px solid #999; padding-bottom: 4px; margin-top: 28px; font-size: 1.25em; }
  h3 { margin-top: 18px; font-size: 1.05em; }
  h4 { margin-top: 14px; font-size: 0.95em; color: #333; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.85em; }
  th, td { border: 1px solid #bbb; padding: 5px 8px; text-align: left; }
  th { background: #f0f0f0; }
  code, pre { font-family: 'Consolas', 'Menlo', monospace; font-size: 0.82em;
              background: #f5f5f5; padding: 1px 4px; }
  pre { padding: 10px; overflow-x: auto; border: 1px solid #ddd; }
  ol li, ul li { margin: 4px 0; }
  blockquote { border-left: 3px solid #888; margin-left: 0; padding-left: 14px; color: #333; }
  .viz { width: 100%; margin: 10px 0; border: 1px solid #ddd; }
  .provenance-badge { display: inline-block; background: #eee; border: 1px solid #bbb;
                      border-radius: 10px; padding: 1px 8px; font-size: 0.8em;
                      font-family: monospace; margin-right: 6px; }
  footer { margin-top: 32px; font-size: 0.78em; color: #666; border-top: 1px solid #ccc; padding-top: 8px; }
  .titleblock { text-align: center; margin: 8px 0 26px; }
  .tb-app { font-size: 0.8em; letter-spacing: 0.45em; color: #555; margin-bottom: 10px; }
  .tb-title { font-size: 2em; margin: 0 0 10px; border: none; padding: 0; }
  .tb-sub { font-size: 0.85em; color: #555; }
  .math { text-align: center; font-size: 1.05em; background: #f7f7f9;
          border: 1px solid #ddd; border-radius: 6px; padding: 12px 10px; margin: 12px 0; }
  @media print { body { padding: 0; } }
"""


def _md_inline(text: str) -> str:
    """Very small markdown-inline renderer for the HTML report."""
    text = _html.escape(text)
    while "**" in text:
        text = text.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
    return text


def _markdown_table_to_html(md_lines: List[str]) -> str:
    rows = [l for l in md_lines if l.startswith("|")]
    if len(rows) < 2:
        return ""
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    body_rows = rows[2:]  # skip separator row
    out = ["<table>", "<thead><tr>"]
    for h in header:
        out.append(f"<th>{_md_inline(h)}</th>")
    out.append("</tr></thead><tbody>")
    for r in body_rows:
        out.append("<tr>")
        for c in r.strip("|").split("|"):
            out.append(f"<td>{_md_inline(c.strip())}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)

def _math_to_html(tex: str) -> str:
    """Render our small LaTeX vocabulary as human-readable HTML.

    Only the equation lines this writer emits are supported (localization
    law + per-class scoring formula) — enough to read the report without a
    TeX engine, without shipping MathJax to a print stylesheet.
    """
    import re
    text = _html.escape(tex.strip().strip("$").strip())
    text = text.replace("\\\\", "<br>")
    for cmd, char in [
        ("\\hat{n}", "n̂"), ("\\bar{X}", "X̄"),
        ("\\mathrm{PROB}", "PROB"), ("\\mathcal{N}", "N"),
        ("\\alpha", "α"), ("\\beta", "β"), ("\\gamma", "γ"),
        ("\\delta", "δ"), ("\\epsilon", "ε"), ("\\zeta", "ζ"),
        ("\\eta", "η"), ("\\theta", "θ"), ("\\kappa", "κ"),
        ("\\mu", "μ"), ("\\sigma", "σ"),
        ("\\cdot", "·"), ("\\sim", "∼"), ("\\leq", "≤"),
        ("\\quad", " "), ("\\,", " "), ("\\;", " "),
    ]:
        text = text.replace(cmd, char)
    text = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\mathcal\{([^}]*)\}", r"\1", text)
    text = re.sub(r"_\{([^}]*)\}", r"<sub>\1</sub>", text)
    text = re.sub(r"\^\{([^}]*)\}", r"<sup>\1</sup>", text)
    text = re.sub(r"\^([0-9])", r"<sup>\1</sup>", text)
    text = re.sub(r"\b([A-Za-z])_([A-Za-z])\b", r"\1<sub>\2</sub>", text)
    return text


def _title_block_html(record) -> str:
    """Centered academic title block: app name, report title, event line."""
    event = record.event or {}
    event_class = event.get("event_class") or "bns"
    label = METADATA.get(event_class, METADATA["bns"])["label"]
    trigger = event.get("trigger_id") or event.get("ivorn") or record.run_id
    when = event.get("event_time") or ""
    return (
        '<div class="titleblock">'
        '<div class="tb-app">KILONOVASCOUT</div>'
        f"<h1 class=\"tb-title\">{_html.escape(label)} Follow-Up Report</h1>"
        f"<div class=\"tb-sub\">Event {_html.escape(str(trigger))}"
        + (f" · {_html.escape(str(when))}" if when else "")
        + " · Autonomous Multi-Messenger Targeting Pipeline</div>"
        "</div>"
    )


def build_report_html(record, weights: Optional[Dict[str, float]] = None,
                      visualizations: Optional[Dict[str, str]] = None) -> str:
    """Rendered HTML report (print-to-PDF ready) with embedded visualizations.

    ``visualizations`` maps plot names to base64 PNG data (PRD Milestone 8).
    """
    prov = record.provenance or {}
    event = record.event or {}

    badges = "".join(
        f'<span class="provenance-badge">{key}: {_html.escape(str(val))}</span>'
        for key, val in prov.items()
    ) or '<span class="provenance-badge">provenance: unknown</span>'

    # Convert the Markdown report block by block into styled HTML.
    md = build_report_markdown(record, weights)
    body: List[str] = []
    i = 0
    md_lines = md.split("\n")
    while i < len(md_lines):
        line = md_lines[i]
        if line.startswith("| "):
            tbl: List[str] = []
            while i < len(md_lines) and md_lines[i].startswith("|"):
                tbl.append(md_lines[i])
                i += 1
            body.append(_markdown_table_to_html(tbl))
            continue
        if line.startswith("```"):
            lang = line[3:].strip()
            block: List[str] = []
            i += 1
            while i < len(md_lines) and not md_lines[i].startswith("```"):
                block.append(md_lines[i])
                i += 1
            i += 1  # closing fence
            body.append(f"<pre><code class='lang-{_html.escape(lang)}'>"
                        f"{_html.escape(chr(10).join(block))}</code></pre>")
            continue
        if line.startswith("$$"):
            body.append(f"<p class='math'>{_math_to_html(line)}</p>")
        elif line.startswith("#### "):
            body.append(f"<h4>{_md_inline(line[5:])}</h4>")
        elif line.startswith("### "):
            body.append(f"<h3>{_md_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_md_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_md_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            body.append(f"<li>{_md_inline(line[2:])}</li>")
        elif line.startswith("> "):
            body.append(f"<blockquote><p>{_md_inline(line[2:])}</p></blockquote>")
        elif line.startswith("---"):
            body.append("<hr/>")
        elif line.startswith("*") and line.endswith("*") and len(line) > 2:
            body.append(f"<footer>{_html.escape(line.strip('*'))}</footer>")
        elif line.strip():
            body.append(f"<p>{_md_inline(line)}</p>")
        i += 1

    # Visualization figures (Milestone 8), embedded as data URIs
    viz_html = ""
    if visualizations:
        for name, b64 in visualizations.items():
            viz_html += (
                f"<figure><img class='viz' src='data:image/png;base64,{b64}' "
                f"alt='{_html.escape(name)}'/>"
                f"<figcaption style='font-size:0.8em;color:#555'>{_html.escape(name)}</figcaption></figure>"
            )

    # The markdown's own "# ..." title is superseded by the academic title
    # block above — drop it so the report does not print two titles.
    if body and body[0].startswith("<h1>"):
        body = body[1:]
    rest = chr(10).join(body)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>KilonovaScout Follow-Up Report — {_html.escape(str(event.get('ivorn', record.run_id)))}</title>
<style>{_PRINT_CSS}</style>
</head>
<body>
{_title_block_html(record)}
<div style="margin:10px 0">{badges}</div>
{viz_html}
{rest}
<footer>Report ID {_html.escape(record.run_id)} — calculation traces reflect the exact values computed by the pipeline scoring tool.</footer>
</body>
</html>"""

def _tex_escape(s: Any) -> str:
    return (str(s).replace("_", r"\_").replace("$", r"\$")
            .replace("&", r"\&").replace("%", r"\%").replace("#", r"\#"))


def build_report_latex(record, weights: Optional[Dict[str, float]] = None) -> str:
    """LaTeX source for academic-quality rendering (PRD 6.2/6.3).

    Compilable with xelatex/pdflatex when a TeX distribution is available;
    also serves as a human-readable formal artifact in the repo.
    """
    event = record.event or {}
    prov = record.provenance or {}
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    tex: List[str] = []
    tex.append(r"\documentclass[11pt]{article}")
    tex.append(r"\usepackage{amsmath, amssymb, graphicx, hyperref, booktabs}")
    tex.append(r"\title{KilonovaScout Follow-Up Report}")
    tex.append(r"\author{KilonovaScout Autonomous Pipeline v3}")
    tex.append(r"\begin{document}")
    tex.append(r"\maketitle")
    tex.append(r"\section{Event Summary}")
    tex.append(r"\begin{itemize}")
    tex.append(r"  \item Trigger: \texttt{" + _tex_escape(event.get("ivorn", "unknown")) + "}")
    tex.append(r"  \item Time: \texttt{" + _tex_escape(event.get("event_time", "unknown")) + "}")
    tex.append(r"  \item Data provenance: skymap=\texttt{" + _tex_escape(prov.get("skymap", "unknown")) +
               r"}, catalog=\texttt{" + _tex_escape(prov.get("catalog", "unknown")) + "}")
    _ev_class = event.get("event_class") or "bns"
    _prof = get_profile(_ev_class)
    _label = METADATA.get(_ev_class, METADATA["bns"])["label"]
    tex.append(r"  \item Event class: \texttt{" + _tex_escape(_label) + "} (\texttt{" + _tex_escape(_ev_class) + "})")
    tex.append(r"  \item Ingest verdict: \texttt{" + _tex_escape(event.get("gate_status", "unknown")) + "} --- " +
               _tex_escape(event.get("gate_reason", "no gate record")))
    _live = (prov.get("event", record.source) or record.source) == "live"
    if _live:
        tex.append(r"  \item Live trigger: this run processed a real notice from the NASA GCN stream.")
    else:
        tex.append(r"  \item Fallback simulation: no live trigger was pending at launch, so this run "
                   r"replays the archived GW170817 packet as a stand-in. Every downstream data tier "
                   r"is labeled per stage.")
    tex.append(r"\end{itemize}")
    tex.append(r"\section{Sky Localization}")
    tex.append(r"\begin{equation} P(\hat{n}) = \mathrm{PROB}(\hat{n}), \quad"
               r" d_L \sim \mathcal{N}(\mu_{\text{dist}}, \sigma_{\text{dist}}^2) \end{equation}")
    tex.append(r"\subsection*{Calculation Trace: Sky Localization}")
    tex.append(r"\begin{enumerate}")
    tex.append(r"  \item Sort pixels by PROB descending; CDF $C_k = \sum_{i \leq k} P_i$")
    tex.append(r"  \item Select pixels where $C_k \leq 0.90$")
    sky = record.event or {}
    ss = sky.get("skymap_summary") if isinstance(sky.get("skymap_summary"), dict) else {}
    if ss.get("area_sq_deg") is not None:
        tex.append(r"  \item Result: $N_{90} = " + str(ss.get("pixel_count_90", "?")) +
                   r"$ pixels, area $= " + f"{float(ss['area_sq_deg']):.2f}" + r"\,\mathrm{deg}^2$")
    tex.append(r"  \item Distance: $\bar{d}_L = \frac{\sum w_i \mu_i}{\sum w_i}$ (probability-weighted)")
    tex.append(r"\end{enumerate}")

    tex.append(r"\section{Galaxy Candidates}")
    tex.append(r"\begin{table}[h]\centering")
    tex.append(r"\begin{tabular}{@{}lrrrrr@{}}\toprule")
    tex.append(r"Name & PGC & $d_L$ (Mpc) & $P_{\text{overlap}}$ & $L_K/L_\star$ & Score \\ \midrule")
    l_star = float((weights or {}).get("schechter_l_star", 1.0e10))
    for cand in record.candidates:
        lk = float(cand.get("luminosity_k") or 0.0)
        tex.append(
            f"{_tex_escape(cand.get('name', '?'))} & "
            f"{cand.get('pgc') or '--'} & "
            f"{float(cand.get('distance_mpc') or 0):.2f} & "
            f"{float(cand.get('probability') or 0):.4f} & "
            f"{lk / l_star:.2e} & "
            f"{float(cand.get('composite_score') or 0):.3f} \\\\"
        )
    tex.append(r"\bottomrule\end{tabular}")
    tex.append(r"\caption{Ranked host galaxy candidates with composite prioritization scores.}")
    tex.append(r"\end{table}")
    tex.append(r"\subsection{Scoring Formula}")
    tex.append(r"\begin{equation}" + _prof.get("formula_tex", "") + r"\end{equation}")
    _active = set(_prof.get("active_terms", []))
    for cand in record.candidates:
        bd = cand.get("score_breakdown") or {}
        terms = bd.get("terms", {}) or {}
        name = _tex_escape(cand.get("name", "candidate"))
        tex.append(r"\subsection*{Calculation Trace: " + name + "}")
        tex.append(r"\begin{enumerate}")
        tex.append(r"  \item Spatial: $P_{\text{overlap}} = " + f"{float(terms.get('spatial', 0)):.4f}$")
        if "schechter" in _active:
            tex.append(r"  \item Schechter: $w = " + f"{float(terms.get('schechter', 0)):.4f}$")
        tex.append(r"  \item Airmass: $\bar{{X}} = " + f"{float(terms.get('airmass', 0)):.3f}$")
        tex.append(r"  \item Cloud: $C = " + f"{float(terms.get('cloud', 0)):.3f}$")
        if "grb_boost" in _active:
            tex.append(r"  \item GRB boost: $B = " + f"{float(terms.get('grb_boost', 0)):.1f}$")
        if "snr" in _active:
            tex.append(r"  \item SNR proxy: $\text{{SNR}} = " + f"{float(terms.get('snr', 0)):.4f}$")
        if "flux" in _active:
            tex.append(r"  \item Burst flux: $F = " + f"{float(terms.get('flux', 0)):.4f}$")
        if "signalness" in _active:
            tex.append(r"  \item Signalness: $s = " + f"{float(terms.get('signalness', 0)):.4f}$")
        tex.append(r"  \item Lunar: $L = " + f"{float(terms.get('lunar', 0)):.3f}$")
        tex.append(r"  \item Final: $S = " + f"{float(bd.get('total', 0)):.4f}$")
        tex.append(r"\end{enumerate}")

    if record.weather:
        wrec = record.weather
        tex.append(r"\section{Observatory Conditions}")
        tex.append(r"\begin{itemize}")
        tex.append(r"  \item Site: \texttt{" + _tex_escape(wrec.get("observatory_name", "?")) + "}")
        tex.append(r"  \item Cloud cover: " + f"{float(wrec.get('cloud_cover_percent', 0)):.1f}\\%")
        tex.append(r"  \item Humidity: " + f"{float(wrec.get('humidity_pct', 0)):.1f}\\%")
        tex.append(r"  \item Dome safe: " + str(bool(wrec.get("dome_safe"))))
        tex.append(r"\end{itemize}")
    if record.slew_script:
        tex.append(r"\section{Observation Schedule}")
        tex.append(r"\begin{verbatim}")
        tex.append(record.slew_script[:2000])
        tex.append(r"\end{verbatim}")
    if record.llm_rationale:
        tex.append(r"\section{LLM Rationale}")
        tex.append(_tex_escape(record.llm_rationale)[:3000])
    tex.append(r"\section{Data Sources}")
    tex.append(r"\begin{tabular}{@{}lll@{}}\toprule")
    tex.append(r"Component & Source & Provenance \\ \midrule")
    ss_url = (ss or {}).get("url", "bundled bayestar")
    tex.append(r"Skymap & \texttt{" + _tex_escape(ss_url) + r"} & \texttt{" +
               _tex_escape(prov.get("skymap", "unknown")) + r"} \\")
    tex.append(r"Catalog & CDS VizieR TAP & \texttt{" + _tex_escape(prov.get("catalog", "unknown")) + r"} \\")
    tex.append(r"Weather & Open-Meteo API & live \\")
    tex.append(r"Event & GCN & \texttt{" + _tex_escape(prov.get("event", record.source)) + r"} \\")
    tex.append(r"\bottomrule\end{tabular}")
    tex.append(r"\vfill")
    tex.append(r"\footnotesize Generated by KilonovaScout v3 --- " + _tex_escape(now))
    tex.append(r"\end{document}")
    return "\n".join(tex)
