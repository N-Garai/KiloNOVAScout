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
    "spatial_prior": 1.0,
    "galaxy_mass_prior": 0.6,
    "airmass_penalty": 0.2,
    "cloud_cover_penalty": 0.5,
    "grb_coincidence_boost": 3.0
}