"""
Ollama LLM provider implementation.
Supports local models running via Ollama.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from llm.base import LLMProvider, LLMResponse, StreamChunk, ModelInfo

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """
    Ollama provider for local models.
    Auto-detects installed models via /api/tags endpoint.
    """
    
    provider_name = "ollama"
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, base_url)
        # Ollama default port is 11434
        self.base_url = base_url or "http://host.docker.internal:11434"
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {"Content-Type": "application/json"}
    
    async def list_models(self) -> List[ModelInfo]:
        """
        Auto-detect models installed in Ollama.
        Uses /api/tags endpoint to list all available models.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
            
            models = []
            for model in data.get("models", []):
                model_name = model.get("name", "")
                # Extract context length from model details if available
                details = model.get("details", {})
                
                # Ollama vision models typically have "vision" or "llava" in name
                _VISION_KEYWORDS = ("llava", "vision", "bakllava", "moondream")
                has_vision = any(kw in model_name.lower() for kw in _VISION_KEYWORDS)

                models.append(ModelInfo(
                    id=model_name,
                    name=model_name,
                    context_length=details.get("context_length"),
                    supports_streaming=True,
                    supports_functions=False,
                    supports_vision=has_vision,
                ))
            
            return models
            
        except httpx.ConnectError:
            logger.warning("Ollama not running or not reachable")
            return []
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response from Ollama."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
        
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=model,
            provider=self.provider_name,
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0)
            },
            finish_reason="stop" if data.get("done") else None
        )
    
    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream response chunks from Ollama."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature
            }
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                headers=self._get_headers(),
                json=payload
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    try:
                        import json
                        data = json.loads(line)
                        
                        if data.get("done"):
                            yield StreamChunk(content="", is_done=True)
                            break
                        
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield StreamChunk(content=content)
                    except Exception as e:
                        logger.warning(f"Failed to parse chunk: {e}")
    
    async def test_connection(self) -> bool:
        """Test Ollama connectivity."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return False
