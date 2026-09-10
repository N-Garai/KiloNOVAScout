"""skills/ — auto-discovered Skill subclasses (M13).

Ported A.R.I.E.S pattern: any ``skills/*.py`` that defines a ``Skill``
subclass is auto-imported and auto-registered with the pipeline — no manual
wiring in agent.py.  Skills are lightweight advisory enrichments (like tools
but discovered by convention), kept separate so they can be added per-observatory
without touching the DAG.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Type

__all__ = ["Skill", "discover_skills", "SKILLS"]


class Skill:
    """Base class for auto-discovered skills. Override ``name`` and ``run``."""
    name: str = "base-skill"
    description: str = ""

    def run(self, *args, **kwargs):
        raise NotImplementedError


# Populated by discover_skills()
SKILLS: Dict[str, Type[Skill]] = {}


def discover_skills() -> Dict[str, Type[Skill]]:
    """Import every submodule in this package and collect Skill subclasses."""
    global SKILLS
    SKILLS = {}
    try:
        package = __name__
        for mod_info in pkgutil.iter_modules(__path__, package + "."):
            try:
                mod = importlib.import_module(mod_info.name)
            except Exception as e:
                print(f"[SKILLS] import {mod_info.name} failed: {e}")
                continue
            for attr in dir(mod):
                try:
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and issubclass(obj, Skill) and obj is not Skill:
                        SKILLS[obj.name or obj.__name__] = obj
                except Exception:
                    continue
    except Exception as e:
        print(f"[SKILLS] discovery failed: {e}")
    if SKILLS:
        print(f"[SKILLS] discovered {len(SKILLS)} skill(s): {', '.join(SKILLS)}")
    return SKILLS


# Auto-run on import so the DAG and ArchitectureSection can read SKILLS
try:
    discover_skills()
except Exception:
    pass
