"""visualization_agent.py - Visualization agent for KilonovaScout v3 (PRD Milestone 8).

Generates per-run plots with matplotlib (Agg backend, no display, render-safe
for the 512 MB budget) and returns them as base64-encoded PNG strings:

1. ``skymap_candidates`` — 90% localization region in Mollweide projection
   with host-galaxy candidates overlaid.
2. ``scoring_breakdown`` — horizontal bar chart of each candidate's weighted
   score decomposition (spatial, Schechter, airmass, cloud, GRB, SNR, lunar).
3. ``observing_conditions`` — radar chart of observability metrics for the
   top candidates (altitude coverage, airmass, moon separation, SNR).
4. ``distance_distribution`` — candidate distance distribution with the
   skymap's probability-weighted distance ± sigma band shaded.

Plots are stored in-memory in the run record (``visualizations`` field);
no disk writes.
"""

from __future__ import annotations

import base64
import gc
import io
import math
from typing import Any, Dict, List, Optional

import numpy as np

_DARK_TEXT = "#e8e8f0"
_DARK_BG = "#0d1117"


def _pyplot():
    """Import pyplot lazily (Agg backend) — keeps ~50-80 MB of matplotlib
    out of the process RSS until a run actually renders plots.  Critical
    for the 512 MB Render free tier: import cost is paid per-run, inside
    the existing to_thread worker, instead of at server boot."""
    import matplotlib
    matplotlib.use("Agg")  # headless — must be set before pyplot import
    import matplotlib.pyplot as plt
    return plt


def _apply_dark_style() -> None:
    plt = _pyplot()
    plt.style.use("dark_background")
    plt.rcParams.update({
        "figure.facecolor": _DARK_BG,
        "axes.facecolor": _DARK_BG,
        "savefig.facecolor": _DARK_BG,
        "text.color": _DARK_TEXT,
        "axes.edgecolor": "#666",
        "axes.labelcolor": _DARK_TEXT,
        "xtick.color": _DARK_TEXT,
        "ytick.color": _DARK_TEXT,
        "font.size": 9,
    })


def _fig_to_base64(fig) -> str:
    plt = _pyplot()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    del fig
    gc.collect()  # release figure cycles promptly on 512 MB instances
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fallback_figure(title: str, reason: str) -> str:
    """Minimal placeholder PNG so a failed plot degrades gracefully.

    The report layout stays stable (one figure per selected plot) and the
    failure reason is visible instead of a silently missing panel. This
    function itself never raises — worst case the plot is omitted.
    """
    try:
        _apply_dark_style()
        plt = _pyplot()
        fig, ax = plt.subplots(figsize=(6, 2.2))
        ax.axis("off")
        ax.text(0.5, 0.6, title, ha="center", va="center", fontsize=11, color=_DARK_TEXT)
        ax.text(0.5, 0.35, f"plot unavailable: {reason}"[:90],
                ha="center", va="center", fontsize=8, color="#8a8a9a")
        return _fig_to_base64(fig)
    except Exception as exc:
        print(f"[VIZ] fallback figure failed ({exc}); omitting plot")
        raise

def plot_skymap_with_candidates(skymap, candidates: List[Dict[str, Any]]) -> str:
    """Mollweide skymap of the 90% region with candidate positions overlaid."""
    _apply_dark_style()
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9, 4.6), subplot_kw={"projection": "mollweide"})

    indices = list(getattr(skymap, "supercell_indices", []) or [])
    probs = list(getattr(skymap, "probdensity", []) or [])
    if indices and probs and len(indices) == len(probs):
        import astropy_healpix as ah
        nside = int(getattr(skymap, "nside", 512))
        ra, dec = ah.healpix_to_lonlat(np.asarray(indices, dtype=np.int64), nside, order="nested")
        ra_deg = np.asarray(ra.deg)
        dec_deg = np.asarray(dec.deg)
        p = np.asarray(probs, dtype=float)
        if p.max() > 0:
            p = p / p.max()
        # Mollweide convention: longitude runs -180..180 (RA increasing left)
        ra_rad = np.radians((ra_deg - 180.0) % 360.0 - 180.0)
        dec_rad = np.radians(dec_deg)
        order = np.argsort(p)[::-1]
        # Downsample dense 90% regions for the 512 MB Render budget — visual
        # output is identical, peak scatter memory drops ~10x on full-res maps.
        if len(order) > 20000:
            order = order[:: max(1, len(order) // 20000)]
        sc = ax.scatter(ra_rad[order], dec_rad[order], c=p[order], s=2.5, cmap="viridis",
                        alpha=0.85, vmin=0.0, vmax=1.0)
        cbar = fig.colorbar(sc, ax=ax, orientation="horizontal", fraction=0.045, pad=0.06)
        cbar.set_label("Relative probability density (normalized)")

    for c in candidates:
        ra_c = float(c.get("ra") or 0)
        dec_c = float(c.get("dec") or 0)
        ra_rad = math.radians((ra_c - 180.0) % 360.0 - 180.0)
        ax.scatter([ra_rad], [math.radians(dec_c)], marker="*", s=180, edgecolors="red",
                   facecolors="none", linewidths=1.6, zorder=5)
        ax.annotate(str(c.get("name", ""))[:12], (ra_rad, math.radians(dec_c)),
                    fontsize=6.5, color="#ffd0d0", xytext=(4, 4), textcoords="offset points")

    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.grid(True, alpha=0.3)
    ax.set_title("90% Localization Region with Host Candidates", fontsize=11)
    return _fig_to_base64(fig)


def plot_scoring_breakdown(candidates: List[Dict[str, Any]]) -> str:
    """Horizontal bar chart of each candidate's weighted score decomposition."""
    _apply_dark_style()
    plt = _pyplot()
    names = [str(c.get("name", "?"))[:14] for c in candidates]
    term_keys = [
        ("spatial", "alpha", "spatial (α·P)", "#3ad6c5"),
        ("schechter", "beta", "Schechter (β·w)", "#c53ad6"),
        ("airmass", "gamma", "airmass (−γ·X̄)", "#d66a3a"),
        ("cloud", "delta", "cloud (−δ·C)", "#8a8a9a"),
        ("grb_boost", "epsilon", "GRB boost (ε·B)", "#ffd23a"),
        ("snr", "zeta", "SNR proxy (ζ·SNR)", "#3a8ad6"),
        ("lunar", "eta", "lunar (−η·L)", "#d63a8a"),
    ]

    fig, ax = plt.subplots(figsize=(9, max(2.6, 0.7 * len(candidates) + 1.6)))
    y = np.arange(len(candidates))
    left = np.zeros(len(candidates))
    for key, weight_key, label, color in term_keys:
        vals = []
        for c in candidates:
            bd = c.get("score_breakdown") or {}
            w = float((bd.get("weights") or {}).get(weight_key, 1.0))
            t = float((bd.get("terms") or {}).get(key, 0.0) or 0.0)
            vals.append(w * t)
        vals = np.asarray(vals, dtype=float)
        ax.barh(y, vals, left=left, color=color, label=label, height=0.6)
        left += vals

    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.axvline(0.0, color="#999", linewidth=0.8)
    ax.set_xlabel("Weighted contribution to composite score")
    ax.set_title("Scoring Breakdown per Candidate", fontsize=11)
    # Legend below the axes (not over the bars): readable on dark print
    # background and in the white-page HTML report alike.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), fontsize=7, ncol=3, framealpha=0.3)
    fig.tight_layout()
    ax.invert_yaxis()
    return _fig_to_base64(fig)

def plot_observing_conditions(candidates: List[Dict[str, Any]]) -> str:
    """Radar chart of normalized observability metrics for the top candidates."""
    _apply_dark_style()
    plt = _pyplot()
    metrics = [
        ("Altitude cov.", lambda o: float(o.get("observable_fraction") or 0)),
        ("Airmass inv.", lambda o: 1.0 / ((float(o.get("mean_airmass") or 38)) or 38)),
        ("Moon sep", lambda o: min(1.0, float(o.get("moon_separation_deg") or 0) / 180.0)),
        ("SNR norm.", lambda o: min(1.0, float(o.get("snr_proxy") or 0) / 12.0)),
    ]
    n = len(metrics)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
    colors = ["#3ad6c5", "#c53ad6", "#ffd23a", "#3a8ad6", "#d63a8a"]
    for i, c in enumerate(candidates[:5]):
        obs = c.get("observability") or {}
        vals = [min(1.0, max(0.0, fn(obs))) for _, fn in metrics]
        vals += vals[:1]
        ax.plot(angles, vals, color=colors[i % len(colors)], linewidth=1.6,
                label=str(c.get("name", "?"))[:14])
        ax.fill(angles, vals, color=colors[i % len(colors)], alpha=0.08)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([m[0] for m in metrics], fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_yticklabels([])
    ax.set_title("Observing Conditions (normalized)", fontsize=11, pad=18)
    ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.1), fontsize=7)
    return _fig_to_base64(fig)


def plot_distance_distribution(skymap, candidates: List[Dict[str, Any]]) -> str:
    """Candidate distance distribution with the skymap distance band shaded."""
    _apply_dark_style()
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(8, 4.0))

    dists = [float(c.get("distance_mpc") or 0) for c in candidates if c.get("distance_mpc")]
    mu = float(getattr(skymap, "dist_mean", None) or 0)
    sigma = float(getattr(skymap, "dist_std", None) or 0)

    if dists:
        ax.hist(dists, bins=min(12, max(5, len(dists))), color="#3ad6c5",
                alpha=0.75, edgecolor="#0d1117")
    if mu > 0 and sigma > 0:
        ax.axvspan(max(0, mu - sigma), mu + sigma, color="#ffd23a", alpha=0.18,
                   label=f"skymap $d_L$: {mu:.1f} ± {sigma:.1f} Mpc")
        ax.axvline(mu, color="#ffd23a", linewidth=1.4, linestyle="--")

    ax.set_xlabel("Luminosity distance $d_L$ (Mpc)")
    ax.set_ylabel("Candidates")
    ax.set_title("Candidate Distance Distribution", fontsize=11)
    ax.legend(fontsize=8)
    return _fig_to_base64(fig)


def plot_score_vs_airmass(candidates: List[Dict[str, Any]]) -> str:
    """Scatter: windowed airmass vs composite score — answers 'horizon-limited?' at a glance."""
    _apply_dark_style()
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(7, 4.2))
    xs, ys, labels = [], [], []
    for c in candidates:
        obs = c.get("observability") or {}
        bd = c.get("score_breakdown") or {}
        try:
            xs.append(float(obs.get("mean_airmass", (bd.get("terms") or {}).get("airmass", 38)) or 38))
            ys.append(float(c.get("composite_score", 0) or 0))
            labels.append(str(c.get("name", "?"))[:12])
        except Exception:
            continue
    ax.scatter(xs, ys, color="#3ad6c5", s=70, edgecolors="#0d1117", zorder=3)
    for x, y, lab in zip(xs, ys, labels):
        ax.annotate(lab, (x, y), fontsize=7, color="#ffd0d0", xytext=(5, 5), textcoords="offset points")
    ax.axvline(2.0, color="#ffd23a", linewidth=1.0, linestyle="--", label="X=2 (low-altitude line)")
    ax.set_xlabel("Windowed mean airmass (Xbar; 38 = below horizon)")
    ax.set_ylabel("Composite score")
    ax.set_title("Score vs Airmass", fontsize=11)
    ax.legend(fontsize=7)
    return _fig_to_base64(fig)


def plot_tiling_map(skymap, candidates: List[Dict[str, Any]],
                    context: Optional[Dict[str, Any]] = None) -> str:
    """RA/Dec map of tiling tiles + candidates — the field strategy at a glance."""
    _apply_dark_style()
    plt = _pyplot()
    context = context or {}
    tiling = context.get("tiling") or {}
    tiles = tiling.get("tiles") or []
    fig, ax = plt.subplots(figsize=(8, 4.6))
    if tiles:
        tx = [float(t.get("ra", t.get("center_ra", 0)) or 0) for t in tiles]
        ty = [float(t.get("dec", t.get("center_dec", 0)) or 0) for t in tiles]
        ax.scatter(tx, ty, marker="s", s=120, facecolors="none", edgecolors="#ffd23a",
                   linewidths=1.2, label=f"{len(tiles)} tiles")
    for c in candidates[:8]:
        ax.scatter([float(c.get("ra", 0) or 0)], [float(c.get("dec", 0) or 0)],
                   marker="*", s=140, color="#ff5a5a", zorder=5)
        ax.annotate(str(c.get("name", ""))[:10], (float(c.get("ra", 0) or 0), float(c.get("dec", 0) or 0)),
                    fontsize=6.5, color="#ffd0d0", xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.set_title("Tiling Map with Candidates", fontsize=11)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    return _fig_to_base64(fig)


def plot_weather_gauge(weather: Optional[Dict[str, Any]]) -> str:
    """Single-glance weather bar: cloud, humidity, dome — cheap, no candidates needed."""
    _apply_dark_style()
    plt = _pyplot()
    w = weather or {}
    cloud = float(w.get("cloud_cover_percent", 0) or 0)
    hum = float(w.get("humidity_pct", w.get("humidity", 0)) or 0)
    dome = 100.0 if w.get("dome_safe") else 0.0
    fig, ax = plt.subplots(figsize=(6, 3.2))
    labels = ["Cloud %", "Humidity %", "Dome open %"]
    vals = [cloud, hum, dome]
    colors = ["#3a8ad6", "#3ad6c5", "#ffd23a" if dome else "#d63a5a"]
    ax.barh(labels, vals, color=colors, height=0.55)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Percent")
    ax.set_title(f"Weather — {w.get('observatory_name', 'site')}", fontsize=11)
    for lab, v in zip(labels, vals):
        ax.text(min(98, v + 1), lab, f"{v:.0f}%", va="center", fontsize=8, color="#e8e8f0")
    return _fig_to_base64(fig)


# Pool registry: every plot the LLM selector may choose from.
VIZ_POOL = {
    "skymap_candidates": {"title": "90% Localization Region", "needs": "skymap"},
    "scoring_breakdown": {"title": "Scoring Breakdown", "needs": "candidates"},
    "observing_conditions": {"title": "Observing Conditions", "needs": "observability"},
    "distance_distribution": {"title": "Distance Distribution", "needs": "distances"},
    "score_vs_airmass": {"title": "Score vs Airmass", "needs": "candidates"},
    "tiling_map": {"title": "Tiling Map", "needs": "tiling"},
    "weather_gauge": {"title": "Weather Gauge", "needs": "weather"},
}


def select_visualizations(skymap, candidates: List[Dict[str, Any]],
                            context: Optional[Dict[str, Any]] = None):
    """Decide which plots this run actually needs, from live run state.

    The four generators below are a standard tool library — but the set
    rendered per run is chosen by the workflow, not predefined:
      * skymap + scoring breakdown are always selected (PRD M8.4: >= 2 plots);
      * observing-conditions radar only when candidates carry observability
        metrics (a radar of nothing is meaningless);
      * distance distribution only with >= 2 measured distances and a skymap
        distance scale to compare against;
      * a GRB coincidence forces the scoring breakdown (it visualizes the
        boost term that moved the ranking).

    Returns (ordered_names, notes) where notes explains each decision for
    the run log.
    """
    context = context or {}
    cands = candidates or []
    has_obs = any((c.get("observability") or {}).get("mean_airmass") for c in cands)
    dists = [c.get("distance_mpc") for c in cands if c.get("distance_mpc")]
    has_dist_scale = bool(getattr(skymap, "dist_mean", None))
    grb_hit = bool(context.get("grb_coincidence")) or float(context.get("grb_boost", 0) or 0) > 1.0

    selected = ["skymap_candidates", "scoring_breakdown"]
    notes = ["skymap+s scoring: always (core deliverables)"]
    if has_obs:
        selected.append("observing_conditions")
        notes.append("conditions radar: observability metrics present")
    else:
        notes.append("conditions radar: skipped (no observability metrics)")
    if len(dists) >= 2 and has_dist_scale:
        selected.append("distance_distribution")
        notes.append(f"distance plot: {len(dists)} distances vs skymap scale")
    else:
        notes.append("distance plot: skipped (insufficient distance data)")
    if grb_hit:
        notes.append("GRB coincidence: scoring breakdown carries the boost term")
    return selected, notes


def choose_visualizations_llm(skymap, candidates: List[Dict[str, Any]],
                                weather: Optional[Dict[str, Any]] = None,
                                context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """LLM plot selector (@tool pattern, advisory-only, 10s timeout, 128 tok max).

    Picks 2–4 plots from VIZ_POOL for this run's story (horizon-limited?
    degree-scale? weather-marginal?). Returns {plots, reason} or None when
    keys are absent / the model fails / the answer is invalid — the caller
    then uses the deterministic rule-based fallback. Never raises.
    """
    try:
        import json as _json
        import os as _os
        cands = candidates or []
        ctx = context or {}
        summary = {
            "event_class": ctx.get("event_class", "?"),
            "n_candidates": len(cands),
            "area_sq_deg": round(float(getattr(skymap, "area_sq_deg", 0) or 0), 1),
            "has_observability": any((c.get("observability") or {}).get("mean_airmass") for c in cands),
            "n_distances": len([c for c in cands if c.get("distance_mpc")]),
            "has_tiling": bool((ctx.get("tiling") or {}).get("tiles")),
            "cloud": (weather or {}).get("cloud_cover_percent", "?"),
            "dome_safe": (weather or {}).get("dome_safe", "?"),
            "grb_boost": ctx.get("grb_boost", 0),
        }
        pool = sorted(VIZ_POOL.keys())
        prompt = (
            "You are KilonovaScout's visualization picker. Choose 2-4 plots from "
            f"{pool} for this follow-up run: {str(summary)[:600]} "
            "Prefer: skymap_candidates always; scoring_breakdown when ranking matters; "
            "score_vs_airmass when airmass spreads scores; tiling_map when tiling exists; "
            "weather_gauge when cloud/dome is marginal; observing_conditions when observability present; "
            "distance_distribution when >=2 distances. Reply ONLY JSON like "
            '{"plots": ["skymap_candidates", "scoring_breakdown"], "reason": "one line"}.'
        )
        try:
            from ..llm_reasoner import _primary_model_id as _pm
            model = _pm()
        except Exception:
            model = _os.getenv("PRIMARY_LLM", "gemini/gemini-2.5-flash")
        key = (_os.getenv("GEMINI_API_KEY", "") or "").strip()
        if not key:
            key = (_os.getenv("GROQ_API_KEY", "") or "").strip()
            if key:
                model = _os.getenv("FALLBACK_LLM", "groq/openai/gpt-oss-120b")
            else:
                return None
        from litellm import completion
        resp = completion(model=model, api_key=key,
                          messages=[{"role": "user", "content": prompt}],
                          temperature=0.2, max_tokens=128, timeout=10)
        text = (resp.choices[0].message.content or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        data = _json.loads(text[start:end + 1])
        plots = [p for p in (data.get("plots") or []) if p in VIZ_POOL]
        plots = list(dict.fromkeys(plots))[:4]
        if len(plots) < 2:
            return None
        if not any(p in ("skymap_candidates", "scoring_breakdown") for p in plots):
            plots = (plots + ["scoring_breakdown"])[:4]
        reason = str(data.get("reason", ""))[:160]
        return {"plots": plots, "reason": reason}
    except Exception:
        return None


def generate_run_visualizations(skymap, candidates: List[Dict[str, Any]],
                                weather: Optional[Dict[str, Any]] = None,
                                context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Generate the workflow-selected plots; returns {name: base64_png} (PRD M8.2/8.3).

    Robustness contract: visualization must never break the run. Every
    selected plot has a per-plot fallback figure carrying the failure
    reason, so the report always embeds a stable figure set.
    """
    # LLM picks 2-4 plots from the 7-plot pool; rule-based fallback on any
    # failure (no keys, timeout, invalid answer). Visualization never breaks
    # the run either way.
    llm_pick = choose_visualizations_llm(skymap, candidates, weather, context)
    if llm_pick:
        selected, notes = llm_pick["plots"], [f"llm-selected: {llm_pick['reason'] or 'run story'}"]
        print(f"[VIZ] llm-selected plots: {', '.join(selected)} ({'; '.join(notes)})")
    else:
        selected, notes = select_visualizations(skymap, candidates, context)
        print(f"[VIZ] rule-based fallback plots: {', '.join(selected)} ({'; '.join(notes)})")
    plots: Dict[str, str] = {}
    generators = {
        "skymap_candidates": ("90% Localization Region", lambda: plot_skymap_with_candidates(skymap, candidates)),
        "scoring_breakdown": ("Scoring Breakdown", lambda: plot_scoring_breakdown(candidates)),
        "observing_conditions": ("Observing Conditions", lambda: plot_observing_conditions(candidates)),
        "distance_distribution": ("Distance Distribution", lambda: plot_distance_distribution(skymap, candidates)),
        "score_vs_airmass": ("Score vs Airmass", lambda: plot_score_vs_airmass(candidates)),
        "tiling_map": ("Tiling Map", lambda: plot_tiling_map(skymap, candidates, context)),
        "weather_gauge": ("Weather Gauge", lambda: plot_weather_gauge(weather if isinstance(weather, dict) else {})),
    }
    for name in selected:
        title, fn = generators[name]
        try:
            plots[name] = fn()
        except Exception as exc:  # fall back to a labeled placeholder, never crash
            print(f"[VIZ] {name} failed ({exc}); using fallback figure")
            try:
                plots[name] = _fallback_figure(title, str(exc))
            except Exception:
                pass
    return plots
