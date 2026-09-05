import json
import os

def load_scoring_weights():
    """Loads scoring weights from the config file."""
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'scoring_weights.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "spatial_prior": 1.0,
            "galaxy_mass_prior": 0.6,
            "airmass_penalty": 0.2,
            "cloud_cover_penalty": 0.5,
            "grb_coincidence_boost": 3.0
        }
