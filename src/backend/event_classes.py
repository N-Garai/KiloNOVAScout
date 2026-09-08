"""event_classes.py - Multi-event-class support for KilonovaScout.

The pipeline used to understand exactly one trigger family (LVC compact-binary
mergers).  This module generalizes it to three cosmic event classes:

  * ``bns``      — neutron-star mergers (BNS/NSBH) via LIGO/Virgo/KAGRA notices.
  * ``grb``      — gamma-ray bursts via Fermi-GBM / Swift-BAT notices.
  * ``neutrino`` — high-energy neutrino alerts via IceCube notices.

Each class declares everything the orchestrator needs to treat it as a
first-class trigger:

  * ``topics``        — GCN Kafka topics to subscribe to (the
                      ``gcn.classic.voevent.<MISSION>_<STREAM>`` convention;
                      subscribing to a quiet/nonexistent topic is harmless —
                      it simply yields no messages).
  * ``gate``          — ingest filter mapping notice parameters to
                      ACCEPTED/REJECTED with a human-readable reason.
  * ``weights``       — per-class scoring profile over the shared composite
                      engine (see scoring_tools.compute_full_score).  Terms a
                      class does not need get weight 0.0 and are skipped in
                      that class's report formula.
  * ``catalog_mode``  — ``"host"`` (rank host-galaxy candidates, kilonova
                      strategy) or ``"field"`` (rank pointings/candidates in
                      the error region without host-mass weighting).
  * ``needs_validator`` — whether the GW↔GRB coincidence stage applies
                      (only meaningful when the trigger itself is a GW).

Design rules:
  * Pure stdlib.  No numpy / astropy / strands imports, so gates and math
    are unit-testable anywhere (see scripts/check_event_classes.py).
  * Gates never crash on missing fields: absent parameters yield a lower
    confidence ACCEPT ("unclassified — proceeding to localization"), never
    a KeyError.  REJECT requires positive evidence (e.g. terrestrial ~ 1).
  * Unknown topics default to the ``bns`` pipeline (backward compatible).
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

# 1/yr expressed in Hz (LVC FAR units).  Anything below this is rarer than
# one false alarm per year of observing time.
FAR_PER_YEAR_HZ = 1.0 / 31557600.0


# ---------------------------------------------------------------------------
# Parameter harvesting
# ---------------------------------------------------------------------------
# Live VOEvent parsing harvests <Param name value> pairs; the bundled BNS
# mock instead nests a "properties" dict; hand-built callers may pass flat
# dicts.  harvest_params() normalizes all three shapes into one
# lowercase-keyed map so gates work identically on live and replay data.

def harvest_params(what: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Flatten a VOEvent ``what`` list into a lowercase parameter map."""
    flat: Dict[str, Any] = {}
    for entry in what or []:
        if not isinstance(entry, dict):
            continue
        if "name" in entry and "value" in entry:
            flat[str(entry["name"]).strip().lower()] = entry["value"]
        if isinstance(entry.get("properties"), dict):
            for k, v in entry["properties"].items():
                flat[str(k).strip().lower()] = v
        # Flat calibration-style dicts, e.g. {"BNS": 0.95, "far": 1.2e-9}.
        for k, v in entry.items():
            if k in ("name", "value", "properties"):
                continue
            flat[str(k).strip().lower()] = v
    return flat


def _fnum(params: Dict[str, Any], *aliases: str) -> Optional[float]:
    """First finite float found under any alias, else None."""
    for a in aliases:
        v = params.get(a.lower())
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            return f
    return None


# ---------------------------------------------------------------------------
# Ingest gates — one per event class
# ---------------------------------------------------------------------------
# Each gate returns (status, reason, confidence, subclass) where status is
# "ACCEPTED" or "REJECTED" and confidence is 0..1.

def gate_bns(params: Dict[str, Any]) -> Tuple[str, str, float, str]:
    """BNS/NSBH merger gate: require a neutron-star component."""
    has_ns = _fnum(params, "hasns", "has_ns")
    bns = _fnum(params, "bns") or 0.0
    nsbh = _fnum(params, "nsbh") or 0.0
    terrestrial = _fnum(params, "terrestrial")
    far = _fnum(params, "far")
    remnant = _fnum(params, "hasremnant", "has_remnant")

    if terrestrial is not None and terrestrial >= 0.5:
        return ("REJECTED", f"terrestrial probability {terrestrial:.2f} ≥ 0.50 — likely noise", 0.95, "terrestrial")
    if far is not None and far > FAR_PER_YEAR_HZ:
        return ("REJECTED", f"false-alarm rate {far:.2e} Hz exceeds 1/yr — not significant", 0.9, "sub-threshold")
    ns_mass = max(bns + nsbh, has_ns or 0.0)
    if (has_ns is not None or bns or nsbh) and ns_mass <= 0.2:
        return ("REJECTED", f"no neutron-star component (BNS+NSBH = {bns + nsbh:.2f}) — likely BBH", 0.85, "bbh")
    if has_ns is not None and has_ns > 0.2:
        sub = "bns" if bns >= nsbh else "nsbh"
        conf = 0.95 if (far is not None and far < FAR_PER_YEAR_HZ) else 0.8
        extra = f", remnant likely" if (remnant or 0) > 0.5 else ""
        return ("ACCEPTED", f"HasNS = {has_ns:.2f}{extra} — neutron-star merger", conf, sub)
    if bns + nsbh > 0.2:
        return ("ACCEPTED", f"BNS+NSBH = {bns + nsbh:.2f} — compact-binary merger", 0.8, "bns" if bns >= nsbh else "nsbh")
    return ("ACCEPTED", "unclassified compact-binary notice — proceeding to localization", 0.5, "unclassified")


def gate_grb(params: Dict[str, Any]) -> Tuple[str, str, float, str]:
    """GRB gate: triage by duration / brightness, never blind-reject.

    Short-hard bursts (T90 ≤ 2 s) are the merger-related population this
    system cares about most; bright long bursts still get bright afterglows.
    Faint unclassified triggers proceed at reduced confidence so the sky is
    still searched rather than silently dropped.
    """
    t90 = _fnum(params, "t90", "burst_t90", "duration", "burst_duration")
    fluence = _fnum(params, "fluence", "burst_fluence")
    peak_flux = _fnum(params, "peak_flux", "peakflux", "flux_peak")
    hardness = _fnum(params, "hardness", "hardness_ratio", "hr")

    hard = f", hardness {hardness:.2f}" if hardness is not None else ""
    if t90 is not None and t90 <= 2.0:
        return ("ACCEPTED", f"short burst (T90 = {t90:.2f} s{hard}) — merger origin possible", 0.9, "short")
    if t90 is not None:
        if (fluence is not None and fluence >= 1e-7) or (peak_flux is not None and peak_flux >= 0.5):
            return ("ACCEPTED", f"bright long burst (T90 = {t90:.1f} s) — afterglow likely", 0.8, "long-bright")
        return ("ACCEPTED", f"long burst (T90 = {t90:.1f} s) — faint afterglow expected", 0.55, "long-faint")
    if fluence is not None or peak_flux is not None:
        return ("ACCEPTED", "duration unreported but flux detected — proceeding", 0.7, "unclassified-bright")
    return ("ACCEPTED", "unclassified GRB notice — proceeding to localization", 0.5, "unclassified")


def gate_neutrino(params: Dict[str, Any]) -> Tuple[str, str, float, str]:
    """IceCube gate: signalness tiers (gold ≥ 0.5, bronze ≥ 0.3)."""
    signalness = _fnum(params, "signalness", "signal_trackness", "p_astro")
    if signalness is not None and signalness < 0.3:
        return ("REJECTED", f"signalness {signalness:.2f} < 0.30 — sub-threshold", 0.85, "sub-threshold")
    if signalness is not None and signalness >= 0.5:
        return ("ACCEPTED", f"signalness {signalness:.2f} — gold-tier astrophysical neutrino", 0.85, "gold")
    if signalness is not None:
        return ("ACCEPTED", f"signalness {signalness:.2f} — bronze-tier neutrino", 0.65, "bronze")
    return ("ACCEPTED", "unclassified neutrino notice — proceeding to localization", 0.5, "unclassified")


_GATES = {"bns": gate_bns, "grb": gate_grb, "neutrino": gate_neutrino}


def evaluate_trigger(event_class: str, what: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Run the ingest gate for an event class over a VOEvent ``what`` list."""
    key = event_class if event_class in _GATES else "bns"
    params = harvest_params(what)
    status, reason, confidence, subclass = _GATES[key](params)
    return {
        "status": status,
        "reason": reason,
        "confidence": round(float(confidence), 3),
        "subclass": subclass,
        "class_key": key,
        "params_used": {k: params[k] for k in sorted(params) if not k.startswith("_")},
    }


# ---------------------------------------------------------------------------
# Per-class scoring profiles over the shared composite engine
# ---------------------------------------------------------------------------
# Engine terms: spatial, schechter, airmass, cloud, grb_boost, snr, lunar,
# plus flux (GRB brightness proxy) and signalness (neutrino confidence).
# A weight of 0.0 disables a term the class does not need — e.g. host-galaxy
# mass is meaningless for a bright GRB afterglow, and the kilonova SNR proxy
# is meaningless outside mergers — so not every measurement runs every time.

PROFILES: Dict[str, Dict[str, Any]] = {
    "bns": {
        "weights": {"alpha": 1.0, "beta": 0.5, "gamma": 0.3, "delta": 0.2,
                    "epsilon": 3.0, "zeta": 0.15, "eta": 0.1,
                    "theta": 0.0, "kappa": 0.0},
        "formula": "S = α·P + β·w − γ·X̄ − δ·C + ε·B + ζ·SNR − η·L",
        "formula_tex": r"S_i = \alpha \cdot P + \beta \cdot w - \gamma \cdot \bar{X} - \delta \cdot C + \epsilon \cdot B + \zeta \cdot \text{SNR} - \eta \cdot L",
        "active_terms": ["spatial", "schechter", "airmass", "cloud", "grb_boost", "snr", "lunar"],
        "catalog_mode": "host",
        "needs_validator": True,
        "strategy": "Host-galaxy ranking: the kilonova is faint, so candidates are nearby GLADE+ galaxies weighted by Schechter luminosity.",
    },
    "grb": {
        "weights": {"alpha": 1.0, "beta": 0.0, "gamma": 0.3, "delta": 0.25,
                    "epsilon": 0.0, "zeta": 0.0, "eta": 0.15,
                    "theta": 0.6, "kappa": 0.0},
        "formula": "S = α·P + θ·F − γ·X̄ − δ·C − η·L",
        "formula_tex": r"S_i = \alpha \cdot P + \theta \cdot F - \gamma \cdot \bar{X} - \delta \cdot C - \eta \cdot L",
        "active_terms": ["spatial", "flux", "airmass", "cloud", "lunar"],
        "catalog_mode": "field",
        "needs_validator": False,
        "strategy": "Afterglow ranking: the optical transient outshines any host, so host mass (β) and kilonova SNR (ζ) are disabled and burst flux (θ) drives priority.",
    },
    "neutrino": {
        "weights": {"alpha": 1.2, "beta": 0.0, "gamma": 0.3, "delta": 0.25,
                    "epsilon": 0.0, "zeta": 0.0, "eta": 0.15,
                    "theta": 0.0, "kappa": 1.5},
        "formula": "S = α·P + κ·s − γ·X̄ − δ·C − η·L",
        "formula_tex": r"S_i = \alpha \cdot P + \kappa \cdot s - \gamma \cdot \bar{X} - \delta \cdot C - \eta \cdot L",
        "active_terms": ["spatial", "signalness", "airmass", "cloud", "lunar"],
        "catalog_mode": "field",
        "needs_validator": False,
        "strategy": "Region ranking over a degree-scale error circle: containment and signalness dominate; listed galaxies are reference only — wide-field tiling recommended.",
    },
}


def get_profile(event_class: str) -> Dict[str, Any]:
    """Return the scoring profile for a class (unknown → bns defaults)."""
    return PROFILES.get(event_class, PROFILES["bns"])


def flux_proxy(fluence: Optional[float] = None, peak_flux: Optional[float] = None) -> float:
    """GRB brightness proxy on a ~0..3 scale from notice energetics.

    Anchored so 1e-6 erg/cm² fluence (or 1 ph/cm²/s peak flux) scores 1.0,
    gaining/losing 0.5 per decade — bright bursts outrank faint ones without
    unbounded dominance.
    """
    score = 0.0
    try:
        if fluence is not None and fluence > 0:
            score = max(score, 1.0 + 0.5 * math.log10(fluence / 1e-6))
        if peak_flux is not None and peak_flux > 0:
            score = max(score, 1.0 + 0.5 * math.log10(peak_flux / 1.0))
    except (TypeError, ValueError):
        return 0.0
    return round(min(3.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Topics, class detection, enablement
# ---------------------------------------------------------------------------

CLASS_TOPICS: Dict[str, List[str]] = {
    "bns": [
        "gcn.classic.voevent.LVC_INITIAL",
        "gcn.classic.voevent.LVC_PRELIMINARY",
        "gcn.classic.voevent.LVC_UPDATE",
    ],
    "grb": [
        "gcn.classic.voevent.FERMI_GBM_ALERT",
        "gcn.classic.voevent.FERMI_GBM_FIN_POS",
        "gcn.classic.voevent.SWIFT_BAT_ALERT",
    ],
    "neutrino": [
        "gcn.classic.voevent.ICECUBE_ASTROTRACK_GOLD",
        "gcn.classic.voevent.ICECUBE_ASTROTRACK_BRONZE",
    ],
}

ALL_CLASSES = ["bns", "grb", "neutrino"]


def class_for_topic(topic: str) -> str:
    """Map a Kafka topic to its event class (unknown → bns pipeline)."""
    t = (topic or "").upper()
    if "LVC" in t:
        return "bns"
    if any(k in t for k in ("GBM", "FERMI", "SWIFT", "BAT", "INTEGRAL")):
        return "grb"
    if any(k in t for k in ("ICECUBE", "AMON", "NEUTRINO")):
        return "neutrino"
    return "bns"


def enabled_classes(raw: Optional[str] = None) -> List[str]:
    """Parse the ALERT_CLASSES env (comma-separated); default: all three."""
    if raw is None:
        raw = os.getenv("ALERT_CLASSES", "bns,grb,neutrino")
    out = [c.strip().lower() for c in (raw or "").split(",") if c.strip().lower() in ALL_CLASSES]
    return out or ["bns"]


def topics_for(classes: List[str]) -> List[str]:
    """Flatten registry topics for the enabled classes (deduped, ordered)."""
    seen: List[str] = []
    for c in classes:
        for t in CLASS_TOPICS.get(c, []):
            if t not in seen:
                seen.append(t)
    return seen


METADATA: Dict[str, Dict[str, str]] = {
    "bns": {
        "key": "bns",
        "label": "Neutron-star merger",
        "blurb": "LIGO/Virgo/KAGRA compact-binary notices; kilonova host-galaxy ranking.",
    },
    "grb": {
        "key": "grb",
        "label": "Gamma-ray burst",
        "blurb": "Fermi-GBM / Swift-BAT notices; afterglow flux-weighted ranking.",
    },
    "neutrino": {
        "key": "neutrino",
        "label": "High-energy neutrino",
        "blurb": "IceCube track alerts; degree-scale region ranking with tiling guidance.",
    },
}
