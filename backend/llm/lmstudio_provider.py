"""
LM Studio LLM provider implementation.
Supports local models running via LM Studio's OpenAI-compatible API.
"""

from llm.openai_compatible import OpenAICompatibleProvider


class LMStudioProvider(OpenAICompatibleProvider):
    """LM Studio: local models, no API key. Lists whatever is loaded in the app."""

    provider_name = "lmstudio"
