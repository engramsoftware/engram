"""
OpenAI LLM provider implementation.
Supports GPT-4, GPT-3.5, and other OpenAI models.
"""

import logging
from typing import Optional

from llm.base import ModelInfo
from llm.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# Only chat models are offered (the /models list also has embeddings, TTS, ...)
_CHAT_PREFIXES = ("gpt-4", "gpt-3.5", "o1", "o3")

# Model IDs known to support vision (image input)
_VISION_PREFIXES = ("gpt-4o", "gpt-4-turbo", "gpt-4-vision", "o1", "o3")


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI API provider. Auto-detects chat models via the /models endpoint."""

    provider_name = "openai"
    timeout = 120.0

    def _model_info(self, model_id: str) -> Optional[ModelInfo]:
        if not model_id.startswith(_CHAT_PREFIXES):
            return None
        return ModelInfo(
            id=model_id,
            name=model_id,
            supports_streaming=True,
            supports_functions="gpt-4" in model_id or "gpt-3.5" in model_id,
            supports_vision=model_id.startswith(_VISION_PREFIXES),
        )
