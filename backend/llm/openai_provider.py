"""
OpenAI LLM provider implementation.
Supports GPT-4, GPT-3.5, and other OpenAI models.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from llm.base import LLMProvider, LLMResponse, StreamChunk, ModelInfo

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    OpenAI API provider.
    Auto-detects available models via the /models endpoint.
    """
    
    provider_name = "openai"
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, base_url)
        self.base_url = base_url or "https://api.openai.com/v1"
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def list_models(self) -> List[ModelInfo]:
        """
        Fetch available models from OpenAI API.
        Filters to only include chat-capable models.
        """
        if not self.api_key:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
            
            models = []
            # Filter for GPT models that support chat
            chat_prefixes = ("gpt-4", "gpt-3.5", "o1", "o3")
            
            # Model IDs known to support vision (image input)
            _VISION_PATTERNS = ("gpt-4o", "gpt-4-turbo", "gpt-4-vision", "o1", "o3")

            for model in data.get("data", []):
                model_id = model.get("id", "")
                if any(model_id.startswith(p) for p in chat_prefixes):
                    has_vision = any(model_id.startswith(v) for v in _VISION_PATTERNS)
                    models.append(ModelInfo(
                        id=model_id,
                        name=model_id,
                        supports_streaming=True,
                        supports_functions="gpt-4" in model_id or "gpt-3.5" in model_id,
                        supports_vision=has_vision,
                    ))
            
            # Sort by name for consistent ordering
            models.sort(key=lambda m: m.id)
            return models
            
        except Exception as e:
            logger.error(f"Failed to list OpenAI models: {e}")
            return []
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response from OpenAI."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
        
        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=model,
            provider=self.provider_name,
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason")
        )
    
    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream response chunks from OpenAI."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str == "[DONE]":
                        yield StreamChunk(content="", is_done=True)
                        break
                    
                    try:
                        import json
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield StreamChunk(content=content)
                    except Exception as e:
                        logger.warning(f"Failed to parse chunk: {e}")
    
    async def test_connection(self) -> bool:
        """Test OpenAI API connectivity."""
        try:
            models = await self.list_models()
            return len(models) > 0
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False
