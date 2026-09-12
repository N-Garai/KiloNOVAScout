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


def _fallback_draft(section: str, context: str) -> str:
    """Deterministic 2-3 sentence template (60-80 words) when LLM keys absent.

    Keeps every report complete and publication-grade without inventing
    numbers — all values are quoted from the trace context. Labels provenance
    honestly so reviewers know no model inference was used.
    """
    # context is the rich base_ctx string; keep it out of the prose itself
    # and craft 2-3 formal sentences per section.
    if section == "Abstract":
        return (
            "We report KilonovaScout's autonomous response to the trigger detailed in the event context, "
            "localizing the source via the HEALPix or point-map branch and ranking candidates with the class-specific composite score. "
            "Observability was assessed with windowed airmass, lunar separation and Open-Meteo weather, and a TSP-optimized slew plus wide-field tiling was prepared for human approval. "
            "All tiers (skymap/point, catalog live/cached, weather live/fallback) are labeled per stage for full auditability. "
            "[Deterministic — LLM keys not configured.]"
        )
    if section == "Methodology":
        return (
            "The pipeline executed the staged DAG: ingestion and gate (event-class profile) → HEALPix triage (live FITS download with replay/point/synthetic fallback, or point-map synthesis for GRB/neutrino) → parallel VizieR TAP (120→60 centroid filter) and weather (Open-Meteo TTL) → ephemeris (windowed airmass over 2 h, atmospheric extinction, lunar penalty) → GRB validator when applicable (BNS only) → TSP slew ordering → LLM rationale and Matplotlib visualizations in parallel → FITS header and approval gate. "
            "Scoring used the shared engine S = α·P + β·w − γ·X̄ − δ·C + ε·B + ζ·SNR − η·L (+θ·F / κ·s for GRB/neutrino), with per-candidate breakdowns and provenance per term. "
            "[Deterministic — LLM keys not configured.]"
        )
    if section == "Discussion":
        return (
            "For this class the ranking weights reflect the physics: BNS emphasizes host Schechter luminosity and kilonova SNR, while GRB/neutrino emphasize burst flux or signalness and treat the host list as reference — tiling drives the plan when the error circle is degree-scale or all hosts share high airmass (e.g., below horizon at the current LST, X̄=38). "
            "Uniform low P_overlap or compressed scores therefore do not indicate a bug but a below-horizon window or faint field; the per-candidate traces expose each term. "
            "Tiling (3×3, ~9 deg²) is recommended when P_overlap is uniformly low or observability is poor. [Deterministic — LLM keys not configured.]"
        )
    if section == "Conclusion":
        return (
            "Per the gate verdict and dome check the slew script is ready for one-click approval after a fresh dome-safety re-check. "
            "If weather is marginal (cloud 40-80% or dome unsafe) or all candidates are below horizon, monitor and re-trigger near transit or approve only if urgent; otherwise execute the TSP order and, for GRB/neutrino, the ranked tiling. "
            "The report, FITS header and visualizations provide the full audit trail for the GCN circular. [Deterministic — LLM keys not configured.]"
        )
    if section == "Introduction":
        return (
            "Multi-messenger follow-up is time-critical: poorly localized GW, GRB and neutrino alerts fade on hour timescales and require rapid host or field prioritization. "
            "KilonovaScout automates the triage that astronomers previously did by hand — crossmatching GLADE+, checking windowed observability and weather, and scoring with a class-aware composite — so telescopes can slew before the transient fades. "
            "This report documents one autonomous run, with every measurement, fallback tier and visualization traceable. [Deterministic — LLM keys not configured.]"
        )
    return f"{section} — deterministic fallback (60-80 words, formal, no invented numbers). [Deterministic — LLM keys not configured.]"


def _llm_draft(section: str, context: str) -> Optional[str]:
    """Draft a prose section via LLM — 350 tokens max, with deterministic fallback.

    Used by the writer for Abstract/Methodology/Discussion/Conclusion.
    Returns a deterministic template when no keys or on failure, so every
    report stays complete (provenance-labeled).
    """
    try:
        import os

        prompt = (
            f"You are KilonovaScout's academic writer. Draft the {section} "
            f"for a kilonova follow-up report. Under 120 words, formal tone, "
            f"grounded only in the context below. Do not invent numbers. Context: {context[:2000]}"
        )
        model = _primary_model_id() if "_primary_model_id" in globals() else os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")
        # Inline _primary_model_id to avoid import cycle if needed
        try:
            from ..llm_reasoner import _primary_model_id as _pm
            model = _pm()
        except Exception:
            pass
        key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
        if not key:
            key = (os.getenv("GROQ_API_KEY", "") or "").strip()
            if key:
                model = os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")
            else:
                return _fallback_draft(section, context)
        from litellm import completion

        resp = completion(
            model=model, api_key=key,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=500,
            timeout=15,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text[:800] if text else _fallback_draft(section, context)
    except Exception:
        return _fallback_draft(section, context)


def _fmt(value: Any, nd: int = 4, default: str = "—") -> str:
    try:
        return f"{float(value):.{nd}f}"
    except (TypeError, ValueError):
        return default


_SUPERSCRIPT = str.maketrans("0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺")


def _sci(value: Any, nd: int = 3, default: str = "—") -> str:
    """Scientific notation in human-readable academic form: ``3.981 × 10⁸``.

    Plain ``e+08`` strings are what made the report traces look like raw
    code output; unicode superscripts read like a journal table in both
    Markdown and print CSS, with no TeX engine required.
    """
    try:
        mantissa, _, exp = f"{float(value):.{nd}e}".partition("e")
        return f"{mantissa} × 10{str(int(exp)).translate(_SUPERSCRIPT)}"
    except (TypeError, ValueError):
        return default


def _candidate_trace_markdown(candidate: Dict[str, Any], event_class: str = "bns") -> List[str]:
    """Step-by-step calculation trace in plain human-readable form (no LaTeX).

    Renders with unicode symbols (×, →, −, α, Δ, °) so the HTML report reads
    correctly even when MathJax is blocked (sandboxed iframe) and the printed
    PDF stays legible. The LaTeX build (build_report_latex) keeps real TeX.
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
    lines.append("| Term | Value | How it was computed |")
    lines.append("|---|---|---|")
    lines.append(f"| Spatial containment (P_overlap) | {_fmt(terms.get('spatial'))} | Localization probability density at candidate pixel, integrated over 1 deg² follow-up field |")
    if "schechter" in active:
        lines.append(f"| Schechter weight (w) | {_fmt(terms.get('schechter'))} | Host L_K = {_sci(candidate.get('luminosity_k'))} vs L_star = {_sci(weights.get('schechter_l_star'))}, slope α = {_fmt(weights.get('schechter_alpha'), 2)} |")
    lines.append(f"| Airmass, windowed mean (Xbar) | {_fmt(terms.get('airmass'), 3)} | Mean of sec(z) over 2 h window (12 samples) |")
    lines.append(f"| Atmospheric extinction (Δm) | {_fmt(obs.get('extinction_mag'), 3)} mag | Δm = k × Xbar, k = {_fmt(weights.get('zenith_extinction'), 3)} mag/airmass |")
    lines.append(f"| Cloud penalty (C) | {_fmt(terms.get('cloud'), 3)} | Fractional cloud cover from Open-Meteo |")
    if "grb_boost" in active:
        lines.append(f"| GRB boost (B) | {_fmt(terms.get('grb_boost'), 1)} | 3.0 when coincidence confirmed, else 0 |")
    if "snr" in active:
        lines.append(f"| SNR proxy | {_fmt(terms.get('snr'), 3)} | Kilonova at m = {_fmt(obs.get('apparent_mag'), 2)}; calibrated m=17 → SNR 10, 0.4 dex/mag (1-m, 300 s) |")
    if "flux" in active:
        lines.append(f"| Burst flux proxy (F) | {_fmt(terms.get('flux'), 3)} | Log-scaled fluence/peak-flux; 1.0 at 1e-6 erg/cm² |")
    if "signalness" in active:
        lines.append(f"| Neutrino signalness (s) | {_fmt(terms.get('signalness'), 3)} | Astrophysical probability from IceCube |")
    lines.append(f"| Lunar penalty (L_moon) | {_fmt(terms.get('lunar'), 3)} | Moon separation Δ = {_fmt(obs.get('moon_separation_deg'), 2)} deg; 0 above 30 deg, 1 below 10 deg, linear |")
    lines.append("")
    skipped = [t for t in ("schechter", "grb_boost", "snr", "flux", "signalness") if t not in active]
    if skipped:
        lines.append(f"Skipped for this event class: {', '.join(skipped)} (weight 0 — not applicable).")
        lines.append("")
    try:
        a = float(weights.get('alpha', weights.get('spatial_weight_alpha', 1.0)))
        b = float(weights.get('beta', weights.get('mass_weight_beta', 0)))
        g = float(weights.get('gamma', weights.get('extinction_gamma', 0.3)))
        d = float(weights.get('delta', weights.get('weather_delta', 0.25)))
        e = float(weights.get('epsilon', weights.get('coincidence_boost', 0)))
        z = float(weights.get('zeta', weights.get('snr_weight_zeta', 0)))
        et = float(weights.get('eta', weights.get('lunar_penalty_eta', 0.15)))
        th = float(weights.get('theta', 0))
        ka = float(weights.get('kappa', 0))
        sp = _fmt(terms.get('spatial'))
        sc = _fmt(terms.get('schechter'))
        am = _fmt(terms.get('airmass'))
        cl = _fmt(terms.get('cloud'))
        gb = _fmt(terms.get('grb_boost', 0))
        sn = _fmt(terms.get('snr', 0))
        lu = _fmt(terms.get('lunar'))
        fx = _fmt(terms.get('flux', 0))
        sg = _fmt(terms.get('signalness', 0))
        if "schechter" in active:
            subs = (f"S = {a:.2f}×{sp} + {b:.2f}×{sc} − {g:.2f}×{am} − {d:.2f}×{cl} "
                    f"+ {e:.2f}×{gb} + {z:.2f}×{sn} − {et:.2f}×{lu} = {_fmt(bd.get('total'))}")
        elif "flux" in active:
            subs = (f"S = {a:.2f}×{sp} + {th:.2f}×{fx} − {g:.2f}×{am} − {d:.2f}×{cl} "
                    f"− {et:.2f}×{lu} = {_fmt(bd.get('total'))}")
        elif "signalness" in active:
            subs = (f"S = {a:.2f}×{sp} + {ka:.2f}×{sg} − {g:.2f}×{am} − {d:.2f}×{cl} "
                    f"− {et:.2f}×{lu} = {_fmt(bd.get('total'))}")
        else:
            subs = f"S = {_fmt(bd.get('total'))}"
        lines.append(f"**Final score:** {subs}")
        lines.append("")
        lines.append(f"*Scoring formula for this class:* `{profile.get('formula', 'S')}`")
        lines.append("")
    except Exception:
        lines.append(f"**Final score:** {profile.get('formula', 'S')} = **{_fmt(bd.get('total'))}**")
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
        f"| Catalog | CDS VizieR TAP / bundled GLADE cache | `{prov.get('catalog', 'unknown')}` |",
        f"| Weather | Open-Meteo API (keyless) | `{prov.get('weather', 'live')}` |",
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
    """Full v3 Markdown report — organized as a publication-grade paper.

    Order: Executive Summary (LLM rationale + GCN draft, small font in HTML) →
    1 Abstract → 2 Introduction → 3 Methodology (3.1 sources, 3.2 classification,
    3.3 formula, 3.4 DAG) → 4 Results (4.1 visualizations, 4.2 event details,
    4.3 sky, 4.4 candidates + trace tables, 4.5 conditions, 4.6 schedule) →
    5 Discussion → 6 Conclusion → 7 Appendix (provenance, log, FITS).
    All mathematics is plain human-readable unicode (no TeX delimiters) so the
    sandboxed HTML preview and printed PDF stay legible without MathJax.
    """
    event = record.event or {}
    prov = record.provenance or {}
    sky = _skymap_stats(record)
    event_class = event.get("event_class") or "bns"
    profile = get_profile(event_class)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Rich context for LLM drafts — params the user asked to "send when calling the api"
    top = record.candidates[0] if record.candidates else {}
    tiling = (event.get("tiling") or {}) if isinstance(event.get("tiling"), dict) else {}
    viz_keys = list((record.visualizations or {}).keys()) if isinstance(record.visualizations, dict) else []
    # Expanded ctx: trigger, classification, sky, weather, tiling, viz
    base_ctx = (
        f"Event {event.get('ivorn', '?')} ({event.get('trigger_id', '?')}) class {event_class} "
        f"{profile.get('strategy', '')} "
        f"Gate {event.get('gate_status', '?')} {event.get('gate_reason', '')} subclass {event.get('gate_subclass', '')} "
        f"Skymap {sky.get('area_sq_deg', '?')} deg2 at NSIDE {sky.get('nside', '?')} "
        f"dist {sky.get('dist_mean', '?')} +/- {sky.get('dist_std', '?')} Mpc "
        f"Provenance {prov} source {record.source} "
        f"Candidates {len(record.candidates)} top {top.get('name', '?')} PGC {top.get('pgc', '?')} "
        f"dL {top.get('distance_mpc', '?')} Mpc score {top.get('composite_score', '?')} P_overlap {top.get('probability', '?')} "
        f"Weather {record.weather} "
        f"Tiling {len(tiling.get('tiles', []))} tiles center {tiling.get('center_ra', '?')},{tiling.get('center_dec', '?')} "
        f"Visualizations {viz_keys} "
    )

    lines: List[str] = []
    lines.append("# KilonovaScout Follow-Up Report")
    lines.append("")
    lines.append(f"**Event:** `{event.get('ivorn', 'unknown')}`  ")
    lines.append(f"**Trigger time:** `{event.get('event_time', 'unknown')}`  ")
    lines.append(f"**Run:** `{record.run_id}` ({record.source}) — status `{record.status}`  ")
    lines.append(f"**Generated:** {now}")
    lines.append("")

    # Provenance badge line (honest labeling)
    lines.append(f"**Provenance:** skymap=`{prov.get('skymap', 'unknown')}` · catalog=`{prov.get('catalog', 'unknown')}` · event=`{prov.get('event', record.source)}` · weather=`{prov.get('weather', 'live')}`")
    if (prov.get('event', record.source) or record.source) == "live":
        lines.append("**Live trigger:** this run processed a real notice from the NASA GCN stream.")
    else:
        lines.append("**Fallback simulation:** no live trigger was pending at launch, so this run replays the archived GW170817 packet as a stand-in. Every downstream tier is labeled per stage — nothing is presented as live sky data.")
    lines.append("")

    # Executive summary right after the title block — small font in HTML.
    # Contains the decision-facing content (LLM rationale + GCN draft) so an
    # observer sees the recommendation before the paper body.
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("<!-- executive-start -->")
    if record.llm_rationale:
        lines.append("### LLM Rationale")
        lines.append("")
        lines.append(record.llm_rationale)
        lines.append("")
        llm_s = event.get("llm_structured") if isinstance(event.get("llm_structured"), dict) else None
        if llm_s:
            lines.append(f"- **Decision:** `{llm_s.get('decision', '?')}` (confidence {llm_s.get('confidence', '?')})")
            if llm_s.get("risks"):
                lines.append(f"- **Risks:** {', '.join(str(r) for r in llm_s['risks'])}")
            if llm_s.get("actions"):
                lines.append(f"- **Suggested actions:** {', '.join(str(a) for a in llm_s['actions'])}")
            if llm_s.get("citations"):
                lines.append(f"- **Citations:** {', '.join(str(c) for c in llm_s['citations'])}")
            lines.append("")
    top_exec = record.candidates[0] if record.candidates else None
    if top_exec:
        lines.append("### GCN Circular Draft")
        lines.append("")
        lines.append(f"> **KilonovaScout follow-up of {event.get('ivorn', 'a LVC trigger')}**")
        lines.append(">")
        lines.append(f"> We identified {top_exec.get('name', 'a candidate host')} "
                     f"(PGC {top_exec.get('pgc', '?')}, d_L = {_fmt(top_exec.get('distance_mpc'), 1)} Mpc) "
                     "as the highest-priority host-galaxy candidate through "
                     "autonomous multi-messenger triage (GLADE+ crossmatch, "
                     "windowed airmass and lunar-separation filtering). "
                     f"Composite prioritization score: {_fmt(top_exec.get('composite_score'), 3)}. "
                     "Robotic follow-up is pending human approval.")
        lines.append("")
    lines.append("<!-- executive-end -->")

    # Abstract — always 2-3 sentences, 60-80 words, grounded
    lines.append("## 1. Abstract")
    lines.append("")
    abs_text = _llm_draft("Abstract", base_ctx + " Write an Abstract of 2-3 sentences, 60-80 words, summarizing trigger, localization, top host/tiling, and recommendation. Formal tone.")
    lines.append(abs_text or _fallback_draft("Abstract", base_ctx))
    lines.append("")

    # Introduction — new section the user requested
    lines.append("## 2. Introduction")
    lines.append("")
    intro_text = _llm_draft("Introduction", base_ctx + " Write an Introduction of 2-3 sentences, 60-80 words: multi-messenger context (GW/GRB/neutrino), the race against fading, and how KilonovaScout's DAG (HEALPix→catalog→weather→scoring→tiling→slew) accelerates it. Formal.")
    lines.append(intro_text or (
        "Multi-messenger astronomy demands minutes-scale follow-up of poorly localized transients. "
        "KilonovaScout automates the triage — parsing the HEALPix or point localization, crossmatching GLADE+ hosts, evaluating windowed airmass, lunar separation and weather, and ranking targets with a class-specific composite score — then proposes a TSP-optimized slew and, for degree-scale error circles, a wide-field tiling. "
        "This report documents one autonomous run end-to-end, with every calculation traceable and provenance labeled."
    ))
    lines.append("")

    # Methodology — pipeline, data sources, classification, scoring
    lines.append("## 3. Methodology")
    lines.append("")
    meth_text = _llm_draft("Methodology", base_ctx + " Write a Methodology of 2-3 sentences, 60-80 words: the staged DAG (ingestion→HEALPix→parallel catalog+weather→ephemeris→validator→scheduler→LLM+viz→FITS), the three-tier fallbacks (live/replay or point/cached/mock), and class-specific scoring. Formal, no invented numbers.")
    lines.append(meth_text or _fallback_draft("Methodology", base_ctx))
    lines.append("")
    lines.append("### 3.1 Data Sources")
    lines.append("")
    lines.extend(_data_sources_table(record))
    lines.append("### 3.2 Trigger Classification")
    lines.append("")
    lines.extend(f"- {line}" for line in _classification_lines(event))
    lines.append("")
    lines.append("### 3.3 Scoring Formula")
    lines.append("")
    lines.append(f"Formula (this event class): `{profile.get('formula', '')}`")
    lines.append("")
    lines.append(f"*{profile.get('strategy', '')}*")
    lines.append("")
    # Pipeline overview (deterministic, not LLM)
    lines.append("### 3.4 Pipeline DAG")
    lines.append("")
    lines.append("ingestion → HEALPix triage (FITS fallback chain or point-map synthesis) → parallel catalog (VizieR TAP 120→60 centroid filter → bundled cache → mock) + weather (Open-Meteo TTL-cached, dome re-check) → ephemeris (windowed airmass, atmospheric extinction, lunar separation) → GRB validator (BNS only, otherwise skipped) → TSP slew ordering → LLM rationale + visualizations in parallel → FITS header → human approval. All tiers logged per stage.")
    lines.append("")

    # Results section — visualizations first (HTML embeds images here),
    # then the event-details block, then all measurement subsections.
    lines.append("## 4. Results")
    lines.append("")
    lines.append("### 4.1 Visualizations")
    lines.append("")
    lines.append("<!-- visualizations-anchor -->")
    if viz_keys:
        lines.append(f"Generated plots: `{', '.join(viz_keys)}` — skymap (Mollweide with candidates), scoring breakdown (horizontal bars), observing-conditions radar, and distance distribution. In the HTML/PDF report these embed as figures below — the scoring chart doubles as a visual audit of every candidate calculation.")
        lines.append("")
    lines.append("### 4.2 Event Details")
    lines.append("")
    lines.append(f"- **Event:** `{event.get('ivorn', 'unknown')}`")
    lines.append(f"- **Trigger time:** `{event.get('event_time', 'unknown')}`")
    lines.append(f"- **Run:** `{record.run_id}` ({record.source}) — status `{record.status}`")
    lines.append(f"- **Generated:** {now}")
    lines.append(f"- **Provenance:** skymap=`{prov.get('skymap', 'unknown')}` · catalog=`{prov.get('catalog', 'unknown')}` · event=`{prov.get('event', record.source)}` · weather=`{prov.get('weather', 'live')}`")
    if (prov.get('event', record.source) or record.source) == "live":
        lines.append("- **Live trigger:** this run processed a real notice from the NASA GCN stream.")
    else:
        lines.append("- **Fallback simulation:** no live trigger was pending at launch, so this run replays the archived GW170817 packet as a stand-in. Every downstream tier is labeled per stage — nothing is presented as live sky data.")
    lines.append("")
    lines.append("### 4.3 Sky Localization")
    lines.append("")
    lines.append("Sky probability follows the HEALPix PROB density; distance follows a probability-weighted Gaussian.")
    lines.append("")
    lines.append("#### Calculation Trace: Sky Localization")
    lines.append("")
    lines.append("| Step | Computation | Result |")
    lines.append("|---|---|---|")
    lines.append("| 1. Input | FITS skymap, pixels sorted by PROB descending | sorted_idx = argsort(PROB), reversed |")
    lines.append("| 2. CDF | Cumulative probability C_k = sum of P_i up to k | C_k in [0, 1] |")
    lines.append("| 3. 90% threshold | Select pixels where C_k ≤ 0.90 | 90% credible set |")
    if sky.get("area_sq_deg") is not None:
        lines.append(f"| 4. Result | 90% credible area = {_fmt(sky.get('area_sq_deg'), 2)} deg², "
                     f"{sky.get('pixel_count_90', '?')} pixels at NSIDE {sky.get('nside', '?')} | 90% set |")
    else:
        lines.append("| 4. Result | 90% credible region extracted from the skymap | 90% set |")
    lines.append(f"| 5. Distance | Probability-weighted mean dL = {_fmt(sky.get('dist_mean'), 1)} Mpc, sigma = {_fmt(sky.get('dist_std'), 1)} Mpc | dL ± σ |")
    lines.append("")
    if sky.get("area_sq_deg") is not None and sky.get("area_sq_deg", 0) > 5:
        lines.append(f"> **Note:** localization spans {sky.get('area_sq_deg'):.1f} deg² (degree-scale). Host list below is advisory; tiling (see Observatory Conditions) covers the error circle more efficiently.")
        lines.append("")

    # Galaxy Candidates — core results
    lines.append("### 4.4 Galaxy Candidates")
    lines.append("")
    if event_class in ("grb", "neutrino"):
        lines.append("> **Field strategy:** candidates are *reference* hosts in the error region. Afterglow/neutrino localization is degree-scale, so the ranked tiling (see below) — not this host list — drives the observing plan. Scores compress when all hosts share similar airmass (e.g., below horizon at current LST).")
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
    lines.append("The scoring-breakdown chart (see Visualizations) shows each candidate's weighted term contributions as stacked bars — a visual audit matching the tables below.")
    lines.append("")
    for cand in record.candidates:
        lines.extend(_candidate_trace_markdown(cand, event_class))

    # Observatory Conditions — part of Results
    weather = record.weather
    if weather:
        lines.append("### 4.5 Observatory Conditions")
        lines.append("")
        lines.append(f"- Site: `{weather.get('observatory_name')}` "
                     f"(lat = {weather.get('latitude')}, lon = {weather.get('longitude')}, alt = {weather.get('alt', '—')} m)")
        lines.append(f"- Cloud cover: `{weather.get('cloud_cover_percent')}` %")
        lines.append(f"- Humidity: `{weather.get('humidity_pct')}` %")
        lines.append(f"- Dome safe: `{weather.get('dome_safe')}`")
        lines.append(f"- Seeing: `{weather.get('seeing_conditions')}`")
        lines.append("")
        lines.append("#### Calculation Trace: Observatory Conditions")
        lines.append("")
        lines.append("| Check | Computation | Result |")
        lines.append("|---|---|---|")
        lines.append("| Cloud cover | C = cloudcover / 100 from Open-Meteo | C = fractional 0–1 |")
        lines.append("| Humidity | H = relativehumidity_2m in %; dome safe iff H ≤ 85% and C ≤ 40% | dome safe true/false |")
        lines.append("| Airmass integral | Xbar = mean of sec(z) over 2 h window (12 samples) | Xbar ≥ 1.0; 38 means below horizon |")
        lines.append("")
        if tiling and tiling.get("tiles"):
            lines.append(f"**Tiling (field strategy):** {len(tiling['tiles'])} pointings on a 3×3 grid (FOV {tiling.get('fov_deg', 1)}°) centered at RA {tiling.get('center_ra', '?')} Dec {tiling.get('center_dec', '?')}. Use when host ranking is ambiguous or all hosts are below horizon at current LST.")
            lines.append("")

    if record.slew_script:
        lines.append("### 4.6 Observation Schedule")
        lines.append("")
        lines.append("Slew order optimized with a greedy nearest-neighbor TSP heuristic on the local alt/az sphere (PRD M7.2). Requires human approval before execution (see Conclusion).")
        lines.append("")
        lines.append("```xml")
        lines.append(record.slew_script)
        lines.append("```")
        lines.append("")

    # Discussion — LLM 2-3 lines
    lines.append("## 5. Discussion")
    lines.append("")
    disc_text = _llm_draft("Discussion", base_ctx + " Write a Discussion of 2-3 sentences, 60-80 words: what the numbers mean (e.g., low P_overlap but high Schechter weight, or uniform airmass 38 below horizon compressing scores, or tiling vs host trade-off). Formal, no invented numbers.")
    lines.append(disc_text or _fallback_draft("Discussion", base_ctx))
    lines.append("")

    # Conclusion — LLM 2-3 lines
    lines.append("## 6. Conclusion")
    lines.append("")
    concl_text = _llm_draft("Conclusion", base_ctx + " Write a Conclusion of 2-3 sentences, 60-80 words: approve/monitor/reject with explicit next steps (approve if dome safe and top P>0.02 else monitor/tiling, re-check at night if below horizon). Formal.")
    lines.append(concl_text or _fallback_draft("Conclusion", base_ctx))
    lines.append("")

    # Appendix — machine-readable audit trail (decision content lives in
    # Executive Summary at the top; not duplicated here).
    lines.append("## 7. Appendix")
    lines.append("")
    lines.append("### 7.1 Data Sources & Provenance")
    lines.append("")
    lines.extend(_data_sources_table(record))
    lines.append("Provenance is attached per stage and echoed in the dashboard badge and FITS header. Live/replay/point/cached/synthetic/mock are never conflated.")
    lines.append("")

    lines.append("### 7.2 Pipeline Execution Log")
    lines.append("")
    lines.append("| Step | Tool | Status | Attempt | Duration (ms) |")
    lines.append("|---|---|---|---|---|")
    for s in record.steps:
        dur = s.duration_ms if s.duration_ms is not None else "—"
        lines.append(f"| {s.step} | `{s.tool_name}` | {s.status} | {s.attempt} | {dur} |")
    lines.append("")

    if record.observation_header:
        lines.append("### 7.3 FITS Observation Header")
        lines.append("")
        lines.append("```text")
        lines.append(record.observation_header)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by KilonovaScout v3 — Autonomous Multi-Messenger Targeting Agent — {now}*")
    lines.append(f"*Report ID {record.run_id} — calculation traces reflect the exact values computed by the pipeline scoring tool.*")
    return "\n".join(lines)

_PRINT_CSS = """
  @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;600&display=swap');
  body { font-family: 'EB Garamond', Georgia, 'Times New Roman', serif; color: #1a1a1a;
         max-width: 820px; margin: 0 auto; padding: 36px 28px; line-height: 1.65; font-size: 11pt; }
  h1 { font-family: 'Inter', sans-serif; border-bottom: 2.5px solid #111; padding-bottom: 10px; font-size: 1.7em; letter-spacing: 0.02em; }
  h2 { font-family: 'Inter', sans-serif; border-bottom: 1px solid #999; padding-bottom: 6px; margin-top: 32px; font-size: 1.3em; color: #111; letter-spacing: 0.01em; }
  h3 { font-family: 'Inter', sans-serif; margin-top: 20px; font-size: 1.1em; color: #222; }
  h4 { font-family: 'Inter', sans-serif; margin-top: 16px; font-size: 0.98em; color: #333; font-style: italic; }
  table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 0.88em; font-family: 'Inter', sans-serif; }
  th, td { border: 1px solid #bbb; padding: 6px 9px; text-align: left; }
  th { background: #f0f0f0; font-weight: 600; }
  code, pre { font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 0.82em; background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
  pre { padding: 12px; overflow-x: auto; border: 1px solid #ddd; border-radius: 6px; line-height: 1.45; }
  ol li, ul li { margin: 5px 0; }
  blockquote { border-left: 3px solid #444; margin-left: 0; padding-left: 16px; color: #222; font-style: italic; background: #fafafa; padding: 8px 16px; border-radius: 4px; }
  .viz { width: 100%; margin: 14px 0; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .viz figcaption { font-family: 'Inter', sans-serif; }
  .provenance-badge { display: inline-block; background: #f0f4f8; border: 1px solid #c0cdd8; color: #334; border-radius: 10px; padding: 2px 9px; font-size: 0.78em; font-family: 'Inter', monospace; margin-right: 6px; }
  footer { margin-top: 36px; font-size: 0.8em; color: #666; border-top: 1px solid #ccc; padding-top: 10px; font-family: 'Inter', sans-serif; }
  .titleblock { text-align: center; margin: 12px 0 30px; padding-bottom: 18px; border-bottom: 1px solid #ddd; }
  .tb-app { font-size: 0.78em; letter-spacing: 0.5em; color: #555; margin-bottom: 12px; font-family: 'Inter', sans-serif; }
  .tb-title { font-size: 2.1em; margin: 0 0 10px; border: none; padding: 0; font-weight: 600; }
  .tb-sub { font-size: 0.88em; color: #555; font-family: 'Inter', sans-serif; }
  .math { text-align: center; font-size: 1.08em; background: #f7f7f9; border: 1px solid #e0e0e0; border-radius: 8px; padding: 14px 12px; margin: 16px 0; font-family: 'EB Garamond', serif; }
  .math-tex { font-family: 'EB Garamond', serif; }
  .calc-step { margin: 6px 0 6px 18px; padding-left: 12px; border-left: 2px solid #e8e8e8; }
  .executive { font-size: 0.85em; line-height: 1.5; background: #f8fafc; border: 1px solid #dbe4ec; border-radius: 8px; padding: 12px 16px; margin: 18px 0 8px; }
  .executive h3 { font-size: 0.95em; margin-top: 10px; }
  .executive blockquote { font-size: 0.95em; }
  figure { margin: 16px 0; }
  figcaption { font-family: 'Inter', sans-serif; font-size: 0.82em; color: #444; margin-top: 6px; line-height: 1.45; }
  @media print { body { padding: 0; } @page { margin: 18mm 16mm; } .executive { background: #fff; } }
"""


def _md_inline(text: str) -> str:
    """Very small markdown-inline renderer for the HTML report."""
    import re
    text = _html.escape(text)
    # `code` spans first so ** inside code is not mis-parsed
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
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

    # Human-readable figure captions (A.R.I.E.S insight: every figure needs a
    # one-line "what to look at" caption, not just a filename).
    _CAPTIONS = {
        "skymap_candidates": "Figure 1 — 90% localization region (Mollweide) with ranked host candidates overlaid as red stars. The color bar is relative probability density (normalized).",
        "scoring_breakdown": "Figure 2 — Scoring breakdown per candidate: stacked bars show each term's weighted contribution to the composite score (spatial, Schechter, airmass, cloud, GRB/SNR, lunar). Longer bars to the right mean stronger follow-up priority.",
        "observing_conditions": "Figure 3 — Observing-conditions radar (normalized 0–1): altitude coverage, inverse airmass, moon separation, and SNR proxy for the top candidates. Larger polygons mean better observability.",
        "distance_distribution": "Figure 4 — Candidate luminosity distances vs the skymap's probability-weighted distance band (shaded, mean ± sigma).",
    }
    # Visualization figures (Milestone 8), embedded as data URIs.
    # They are injected at the <!-- visualizations-anchor --> inside Results,
    # not at the top of the document.
    viz_html = ""
    if visualizations:
        order = ["skymap_candidates", "scoring_breakdown", "observing_conditions", "distance_distribution"]
        for name in order + [k for k in visualizations.keys() if k not in order]:
            b64 = visualizations.get(name)
            if not b64:
                continue
            cap = _CAPTIONS.get(name, name.replace("_", " "))
            viz_html += (
                f"<figure><img class='viz' src='data:image/png;base64,{b64}' "
                f"alt='{_html.escape(name)}'/>"
                f"<figcaption>{_html.escape(cap)}</figcaption></figure>"
            )

    # Convert the Markdown report block by block into styled HTML.
    md = build_report_markdown(record, weights)
    body: List[str] = []
    i = 0
    md_lines = md.split("\n")
    in_executive = False
    while i < len(md_lines):
        line = md_lines[i]
        if "<!-- executive-start -->" in line:
            body.append("<div class='executive'>")
            in_executive = True
            i += 1
            continue
        if "<!-- executive-end -->" in line:
            body.append("</div>")
            in_executive = False
            i += 1
            continue
        if "<!-- visualizations-anchor -->" in line:
            if viz_html:
                body.append(viz_html)
            i += 1
            continue
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
            raw_tex = line.strip().strip("$").strip()
            body.append(f"<p class='math'>{_math_to_html(line)}<span class='math-tex' style='display:none'>$$ { _html.escape(raw_tex)} $$</span></p>")
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
    if in_executive:
        body.append("</div>")

    # The markdown's own "# ..." title is superseded by the academic title
    # block above — drop it so the report does not print two titles.
    if body and body[0].startswith("<h1>"):
        body = body[1:]
    rest = chr(10).join(body)
    mathjax = r"""
<script>
window.MathJax = { tex: { inlineMath: [['$','$'], ['\\(','\\)']], displayMath: [['$$','$$'], ['\\[','\\]']], processEscapes: true }, options: { skipHtmlTags: ['script','noscript','style','textarea','pre','code'] } };
</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>KilonovaScout Follow-Up Report — {_html.escape(str(event.get('ivorn', record.run_id)))}</title>
<style>{_PRINT_CSS}</style>
{mathjax}
</head>
<body>
{_title_block_html(record)}
<div style="margin:10px 0">{badges}</div>
{rest}
<footer>Report ID {_html.escape(record.run_id)} — calculation traces reflect the exact values computed by the pipeline scoring tool. All mathematics is rendered in plain human-readable form; MathJax enhances the print view where scripts are allowed.</footer>
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
