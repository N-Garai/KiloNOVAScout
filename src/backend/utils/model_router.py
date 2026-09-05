import os
from typing import Dict, Any

# LiteLLM is used directly for model calls if needed, but Strands Agent handles this internally.
# This module is now deprecated/empty as Strands Agent manages LLM routing.
def get_llm_config(primary_model: str, fallback_model: str) -> Dict[str, str]:
    """Returns LLM configuration dictionary."""
    return {
        "primary": primary_model,
        "fallback": fallback_model
    }

