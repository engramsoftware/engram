"""
LLM Provider factory module.
Creates provider instances based on configuration.
"""

import logging
from typing import Optional, Dict, List

from llm.base import LLMProvider, ModelInfo
from llm.openai_provider import OpenAIProvider
from llm.anthropic_provider import AnthropicProvider
from llm.lmstudio_provider import LMStudioProvider
from llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

# ============================================================
# Provider Registry
# ============================================================
PROVIDERS: Dict[str, type] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "lmstudio": LMStudioProvider,
    "ollama": OllamaProvider,
}


def create_provider(
    provider_name: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs
) -> Optional[LLMProvider]:
    """
    Create an LLM provider instance.
    
    Args:
        provider_name: Name of the provider (openai, anthropic, lmstudio, ollama)
        api_key: API key for authentication
        base_url: Custom base URL for the API
        **kwargs: Provider-specific options
        
    Returns:
        LLMProvider instance or None if provider not found
    """
    provider_class = PROVIDERS.get(provider_name.lower())
    
    if not provider_class:
        logger.error(f"Unknown provider: {provider_name}")
        return None
    
    return provider_class(api_key=api_key, base_url=base_url)


def get_available_providers() -> List[str]:
    """Get list of all supported provider names."""
    return list(PROVIDERS.keys())


async def detect_all_models(
    provider_configs: Dict[str, Dict]
) -> Dict[str, List[ModelInfo]]:
    """
    Auto-detect models from all configured providers.
    
    Args:
        provider_configs: Dict mapping provider name to config
            Each config should have 'api_key' and optionally 'base_url'
            
    Returns:
        Dict mapping provider name to list of available models
    """
    results = {}
    
    for provider_name, config in provider_configs.items():
        provider = create_provider(
            provider_name,
            api_key=config.get("api_key"),
            base_url=config.get("base_url")
        )
        
        if provider:
            try:
                models = await provider.list_models()
                results[provider_name] = models
                logger.info(f"Found {len(models)} models for {provider_name}")
            except Exception as e:
                logger.error(f"Failed to detect models for {provider_name}: {e}")
                results[provider_name] = []
    
    return results
