import os
from typing import Dict, Any

from strands.llm import LiteLLMClient


def get_llm_client(primary_model: str, fallback_model: str) -> LiteLLMClient:
    """Initializes and returns a LiteLLMClient with primary and fallback models."""
    # LiteLLM client handles model routing and fallbacks based on environment variables
    # and the provided primary/fallback model strings.
    # It will automatically pick up API keys from environment variables (e.g., OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY)
    
    # Basic initialization, LiteLLM handles the routing logic internally.
    # We provide the primary model and the fallback model strings.
    # The actual model choice at runtime depends on API availability and LLM health.
    
    # For demonstration, we'll just initialize with the primary.
    # LiteLLM's routing logic will be implicitly used when calling models.
    # Note: A more advanced implementation might pre-configure LiteLLM providers.
    
    # If you need explicit configuration or to force a provider, you would do it here.
    # Example: client = LiteLLMClient(model=primary_model, fallback_model=fallback_model, api_key=os.getenv("GEMINI_API_KEY"))
    
    # For simplicity and relying on LiteLLM's default env var handling:
    client = LiteLLMClient(model=primary_model, fallback_model=fallback_model)
    
    return client

