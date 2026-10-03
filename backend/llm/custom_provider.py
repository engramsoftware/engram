"""
Custom OpenAI-compatible provider.

For any server that speaks the OpenAI chat API: llama.cpp's `llama-server`,
vLLM, text-generation-webui, Groq, Together, OpenRouter, a company gateway.
The user supplies the URL (and a key if the server wants one).
"""

from llm.openai_compatible import OpenAICompatibleProvider


class CustomProvider(OpenAICompatibleProvider):
    """A user-supplied OpenAI-compatible endpoint."""

    provider_name = "custom"
