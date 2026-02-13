"""
LM Studio LLM provider implementation.
Supports local models running via LM Studio's OpenAI-compatible API.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from llm.base import LLMProvider, LLMResponse, StreamChunk, ModelInfo

logger = logging.getLogger(__name__)


class LMStudioProvider(LLMProvider):
    """
    LM Studio provider for local models.
    Uses OpenAI-compatible API format.
    Auto-detects loaded models via /models endpoint.
    """
    
    provider_name = "lmstudio"
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, base_url)
        # LM Studio default port is 1234
        self.base_url = base_url or "http://host.docker.internal:1234/v1"
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers (no auth needed for local)."""
        return {"Content-Type": "application/json"}
    
    async def list_models(self) -> List[ModelInfo]:
        """
        Auto-detect models loaded in LM Studio.
        LM Studio exposes /models endpoint listing available models.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
            
            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                # LM Studio vision models often have "vision", "llava", "vl" in name
                _VISION_KEYWORDS = ("llava", "vision", "bakllava", "moondream", "-vl", "minicpm-v")
                has_vision = any(kw in model_id.lower() for kw in _VISION_KEYWORDS)

                models.append(ModelInfo(
                    id=model_id,
                    name=model_id,
                    supports_streaming=True,
                    supports_functions=False,
                    supports_vision=has_vision,
                ))
            
            return models
            
        except httpx.ConnectError:
            logger.warning("LM Studio not running or not reachable")
            return []
        except Exception as e:
            logger.error(f"Failed to list LM Studio models: {e}")
            return []
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response from LM Studio."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        async with httpx.AsyncClient(timeout=300.0) as client:
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
        """Stream response chunks from LM Studio."""
        # If no model specified, try to get first available
        if not model:
            models = await self.list_models()
            if models:
                model = models[0].id
                logger.info(f"Auto-selected model: {model}")
            else:
                raise ValueError("No model specified and none available in LM Studio")
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        logger.info(f"LM Studio streaming request to {self.base_url}/chat/completions")
        logger.info(f"Model: {model}, Messages: {len(messages)}")
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"LM Studio error: {response.status_code} - {error_text}")
                        raise httpx.HTTPStatusError(f"LM Studio returned {response.status_code}", request=response.request, response=response)
                    
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:]
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
                            logger.warning(f"Failed to parse chunk: {e} - data: {data_str[:100]}")
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to LM Studio at {self.base_url}: {e}")
            raise ValueError(f"Cannot connect to LM Studio. Is it running at {self.base_url}?")
        except Exception as e:
            logger.error(f"LM Studio stream error: {e}")
            raise
    
    async def test_connection(self) -> bool:
        """Test LM Studio connectivity."""
        try:
            models = await self.list_models()
            return True  # Even empty list means server is running
        except Exception as e:
            logger.error(f"LM Studio connection test failed: {e}")
            return False
