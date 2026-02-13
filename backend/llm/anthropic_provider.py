"""
Anthropic LLM provider implementation.
Supports Claude 3, Claude 3.5, and other Anthropic models.
"""

import logging
import json
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from llm.base import LLMProvider, LLMResponse, StreamChunk, ModelInfo

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """
    Anthropic API provider.
    Auto-detects available models via the /models endpoint.
    """
    
    provider_name = "anthropic"
    
    # Known Anthropic models (API doesn't have a list endpoint)
    KNOWN_MODELS = [
        ModelInfo(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-opus-4-20250514", name="Claude Opus 4", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-opus-20240229", name="Claude 3 Opus", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-sonnet-20240229", name="Claude 3 Sonnet", context_length=200000, supports_vision=True),
        ModelInfo(id="claude-3-haiku-20240307", name="Claude 3 Haiku", context_length=200000, supports_vision=True),
    ]
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, base_url)
        # Strip any path suffix users may have pasted (e.g. /v1/messages)
        # so we don't end up with double paths like /v1/messages/v1/messages
        raw = base_url or "https://api.anthropic.com"
        self.base_url = raw.split("/v1")[0] if "/v1" in raw else raw.rstrip("/")
    
    # Delimiter injected by format_messages_with_context() to separate
    # stable (cacheable) prefix from dynamic (per-turn) context.
    _CACHE_BREAK = "<!-- CACHE_BREAK -->"

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

    @staticmethod
    def _build_cached_system(system_content: str) -> list:
        """Split system prompt on CACHE_BREAK and add cache_control markers.

        Anthropic prompt caching is prefix-based: everything before a
        cache_control marker is cached for 5 minutes.  Cache reads cost
        10% of base input price (90% savings).

        The stable prefix (persona + capability instructions) rarely
        changes between turns, so it benefits massively from caching.
        The dynamic suffix (date, retrieval context) changes every
        message and is NOT cached.

        Args:
            system_content: Full system prompt string, optionally
                containing a <!-- CACHE_BREAK --> delimiter.

        Returns:
            List of Anthropic system content blocks with cache_control
            on the stable prefix.
        """
        delimiter = "<!-- CACHE_BREAK -->"
        if delimiter in system_content:
            stable, dynamic = system_content.split(delimiter, 1)
            blocks = []
            stable = stable.strip()
            dynamic = dynamic.strip()
            if stable:
                blocks.append({
                    "type": "text",
                    "text": stable,
                    "cache_control": {"type": "ephemeral"},
                })
            if dynamic:
                blocks.append({"type": "text", "text": dynamic})
            return blocks
        # No delimiter — cache the entire system prompt
        return [{
            "type": "text",
            "text": system_content,
            "cache_control": {"type": "ephemeral"},
        }]
    
    async def list_models(self) -> List[ModelInfo]:
        """
        Fetch available models from Anthropic's /v1/models endpoint.
        Falls back to known models if the endpoint fails.
        """
        if not self.api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model_data in data.get("data", []):
                        model_id = model_data.get("id", "")
                        display_name = model_data.get("display_name", model_id)
                        # Anthropic models typically have 200k context
                        # All Claude 3+ models support vision
                        models.append(ModelInfo(
                            id=model_id,
                            name=display_name,
                            context_length=200000,
                            supports_vision=True,
                        ))
                    if models:
                        logger.info(f"Fetched {len(models)} models from Anthropic API")
                        return models

                # If endpoint fails or returns no models, fall back to known models
                logger.warning(f"Anthropic /v1/models returned {response.status_code}, using fallback")

        except Exception as e:
            logger.warning(f"Failed to fetch Anthropic models: {e}")

        # Fallback: verify API key works and return known models
        if await self.test_connection():
            return self.KNOWN_MODELS.copy()
        return []
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response from Anthropic."""
        if not self.api_key:
            raise ValueError("Anthropic API key is required but not set")

        # Validate model name format
        if not model or not model.startswith("claude"):
            logger.warning(f"Possibly invalid Anthropic model name: {model}")

        # Extract and concatenate all system messages.
        # Multiple system messages can exist when addins (e.g. Skill Voyager)
        # inject additional system instructions. We must preserve them ALL.
        system_parts = []
        chat_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append(msg)
        
        system_content = "\n\n".join(system_parts) if system_parts else None
        
        payload = {
            "model": model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096
        }
        if system_content:
            # Use structured system blocks with cache_control for
            # prompt caching (90% cost reduction on cached prefix).
            payload["system"] = self._build_cached_system(system_content)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{self.base_url}/v1/messages"
            logger.debug(f"Anthropic request to {url} with model {model}")
            response = await client.post(
                url,
                headers=self._get_headers(),
                json=payload
            )
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Anthropic API error {response.status_code}: {error_text}")
                # Try to get detailed error message
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", error_text)
                    raise httpx.HTTPStatusError(
                        f"Anthropic API error: {error_msg}",
                        request=response.request,
                        response=response
                    )
                except:
                    response.raise_for_status()
            data = response.json()
        
        content = data["content"][0]["text"] if data.get("content") else ""
        usage = data.get("usage", {})

        # Log prompt caching metrics when available
        cache_created = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        if cache_created or cache_read:
            logger.info(
                f"Anthropic cache: created={cache_created} read={cache_read} "
                f"input={usage.get('input_tokens', 0)} output={usage.get('output_tokens', 0)}"
            )

        return LLMResponse(
            content=content,
            model=model,
            provider=self.provider_name,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_creation_input_tokens": cache_created,
                "cache_read_input_tokens": cache_read,
            },
            finish_reason=data.get("stop_reason")
        )
    
    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream response chunks from Anthropic."""
        if not self.api_key:
            raise ValueError("Anthropic API key is required but not set")

        # Validate model name format
        if not model or not model.startswith("claude"):
            logger.warning(f"Possibly invalid Anthropic model name: {model}")

        # Extract and concatenate all system messages (see generate() comment)
        system_parts = []
        chat_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append(msg)
        
        system_content = "\n\n".join(system_parts) if system_parts else None
        
        payload = {
            "model": model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
            "stream": True
        }
        if system_content:
            # Use structured system blocks with cache_control for
            # prompt caching (90% cost reduction on cached prefix).
            payload["system"] = self._build_cached_system(system_content)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{self.base_url}/v1/messages"
            logger.debug(f"Anthropic stream request to {url} with model {model}")
            async with client.stream(
                "POST",
                url,
                headers=self._get_headers(),
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_text = error_body.decode()
                    logger.error(f"Anthropic stream error {response.status_code}: {error_text}")
                    try:
                        error_data = json.loads(error_text)
                        error_msg = error_data.get("error", {}).get("message", error_text)
                        raise httpx.HTTPStatusError(
                            f"Anthropic API error: {error_msg}",
                            request=response.request,
                            response=response
                        )
                    except json.JSONDecodeError:
                        response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type")

                        if event_type == "message_start":
                            # Log prompt caching metrics from the initial event
                            usage = data.get("message", {}).get("usage", {})
                            cache_created = usage.get("cache_creation_input_tokens", 0)
                            cache_read = usage.get("cache_read_input_tokens", 0)
                            if cache_created or cache_read:
                                logger.info(
                                    f"Anthropic cache: created={cache_created} read={cache_read} "
                                    f"input={usage.get('input_tokens', 0)}"
                                )
                        elif event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield StreamChunk(content=text)
                        elif event_type == "message_stop":
                            yield StreamChunk(content="", is_done=True)
                            break
                    except Exception as e:
                        logger.warning(f"Failed to parse chunk: {e}")
    
    async def test_connection(self) -> bool:
        """Test Anthropic API connectivity with a minimal request."""
        if not self.api_key:
            logger.error("Anthropic connection test failed: No API key provided")
            return False

        try:
            url = f"{self.base_url}/v1/messages"
            logger.debug(f"Testing Anthropic connection to {url}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json={
                        "model": "claude-3-5-haiku-20241022",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1
                    }
                )
                if response.status_code in (200, 201):
                    return True
                else:
                    logger.error(f"Anthropic test failed with status {response.status_code}: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Anthropic connection test failed: {e}")
            return False
