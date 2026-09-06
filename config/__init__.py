import json
import os


def _config_root() -> str:
    """Locate the repository config/ directory regardless of CWD or PYTHONPATH."""
    # Searches: this file's dir/.. (config/.), cwd/config, src/backend/config
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'),          # config/__init__.py -> repo root
        os.path.join(os.getcwd(), 'config'),
        os.path.join(os.path.dirname(os.path.abspath(__file__))),                # config itself
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config'),
    ]
    for base in candidates:
        p = os.path.join(base, 'scoring_weights.json')
        if os.path.exists(p):
            return base
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def load_scoring_weights() -> dict:
    """Loads scoring weights from config/scoring_weights.json.

    Falls back to the PRD-standard defaults if the file is missing.
    """
    root = _config_root()
    config_path = os.path.join(root, 'scoring_weights.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_WEIGHTS


_DEFAULT_WEIGHTS = {
    "spatial_weight_alpha": 1.0,
    "mass_weight_beta": 0.5,
    "extinction_gamma": 0.3,
    "weather_delta": 0.2,
    "coincidence_boost": 3.0,
    "snr_weight_zeta": 0.15,
    "lunar_penalty_eta": 0.1,
    "schechter_l_star": 1.0e10,
    "schechter_alpha": 1.0,
    "zenith_extinction": 0.12,
    "peak_kilonova_mag": 17.5,
    "probability_threshold": 0.01,
}