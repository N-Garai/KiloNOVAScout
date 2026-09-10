"""tiling.py — Tiling planner skill (M13).

For point tier (GRB/neutrino): ranked pointings, not 5 galaxies.
Wraps the existing suggest_tiling tool as a Skill so it is auto-discovered.
"""

from __future__ import annotations

from . import Skill


class TilingPlannerSkill(Skill):
    name = "tiling_planner"
    description = "Ranked tiling pointings for degree-scale error circles (GRB/neutrino)."

    def run(self, skymap=None, fov_deg: float = 1.0):
        try:
            from ..tools import KilonovaScoutTools
            tools = KilonovaScoutTools()
            if skymap is None:
                return {"error": "no skymap", "tiles": []}
            return tools.suggest_tiling(skymap, fov_deg=fov_deg)
        except Exception as e:
            return {"error": str(e), "tiles": []}
