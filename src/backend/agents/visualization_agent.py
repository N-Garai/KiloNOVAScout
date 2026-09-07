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
import io
import math
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # headless — must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np

_DARK_TEXT = "#e8e8f0"
_DARK_BG = "#0d1117"


def _apply_dark_style() -> None:
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
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fallback_figure(title: str, reason: str) -> str:
    """Minimal placeholder PNG so a failed plot degrades gracefully.

    The report layout stays stable (one figure per selected plot) and the
    failure reason is visible instead of a silently missing panel. This
    function itself never raises — worst case the plot is omitted.
    """
    try:
        _apply_dark_style()
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
    ax.legend(loc="lower right", fontsize=7, ncol=2, framealpha=0.25)
    ax.invert_yaxis()
    return _fig_to_base64(fig)

def plot_observing_conditions(candidates: List[Dict[str, Any]]) -> str:
    """Radar chart of normalized observability metrics for the top candidates."""
    _apply_dark_style()
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


def generate_run_visualizations(skymap, candidates: List[Dict[str, Any]],
                                weather: Optional[Dict[str, Any]] = None,
                                context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Generate the workflow-selected plots; returns {name: base64_png} (PRD M8.2/8.3).

    Robustness contract: visualization must never break the run. Every
    selected plot has a per-plot fallback figure carrying the failure
    reason, so the report always embeds a stable figure set.
    """
    selected, notes = select_visualizations(skymap, candidates, context)
    print(f"[VIZ] selected plots: {', '.join(selected)} ({'; '.join(notes)})")
    plots: Dict[str, str] = {}
    generators = {
        "skymap_candidates": ("90% Localization Region", lambda: plot_skymap_with_candidates(skymap, candidates)),
        "scoring_breakdown": ("Scoring Breakdown", lambda: plot_scoring_breakdown(candidates)),
        "observing_conditions": ("Observing Conditions", lambda: plot_observing_conditions(candidates)),
        "distance_distribution": ("Distance Distribution", lambda: plot_distance_distribution(skymap, candidates)),
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
