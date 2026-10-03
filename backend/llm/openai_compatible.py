"""
Shared implementation for every server that speaks the OpenAI chat API.

OpenAI itself, LM Studio and the "Custom" provider (llama.cpp's llama-server,
vLLM, Groq, Together, OpenRouter, ...) differ only in defaults and in how they
filter the model list, so they are thin subclasses of this class.
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from llm.base import LLMProvider, LLMResponse, ModelInfo, StreamChunk
from llm.registry import get_spec, normalize_base_url

logger = logging.getLogger(__name__)

# Model IDs that usually mean "accepts images", for servers that don't say
_VISION_KEYWORDS = ("llava", "vision", "bakllava", "moondream", "-vl", "minicpm-v")


class OpenAICompatibleProvider(LLMProvider):
    """Chat + model listing over `{base_url}/chat/completions` and `{base_url}/models`."""

    provider_name = "openai-compatible"
    #: Seconds allowed for a chat request (local models can be slow to start)
    timeout = 300.0

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key, base_url)
        self.base_url = normalize_base_url(self.provider_name, base_url)

    # ── Hooks for subclasses ─────────────────────────────────────

    @property
    def display_name(self) -> str:
        spec = get_spec(self.provider_name)
        return spec.name if spec else self.provider_name

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _model_info(self, model_id: str) -> Optional[ModelInfo]:
        """Describe one listed model, or None to hide it."""
        return ModelInfo(
            id=model_id,
            name=model_id,
            supports_streaming=True,
            supports_functions=False,
            supports_vision=any(kw in model_id.lower() for kw in _VISION_KEYWORDS),
        )

    # ── Models ───────────────────────────────────────────────────

    def _missing_credentials(self) -> bool:
        """No URL to talk to (Custom has no default), or a required key is absent."""
        spec = get_spec(self.provider_name)
        return not self.base_url or bool(spec and spec.requires_api_key and not self.api_key)

    def _require_url(self) -> None:
        if not self.base_url:
            raise ValueError(f"{self.display_name} needs a server URL. Add one in Settings > Models.")

    async def _fetch_models(self, timeout: float) -> List[ModelInfo]:
        """GET /models. Raises when the server is unreachable or refuses us."""
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._get_headers())
            response.raise_for_status()
            data = response.json()
        models = [self._model_info(m.get("id", "")) for m in data.get("data", []) if m.get("id")]
        return sorted((m for m in models if m), key=lambda m: m.id)

    async def list_models(self) -> List[ModelInfo]:
        """Models the server reports; an empty list when it can't be reached."""
        if self._missing_credentials():
            return []
        try:
            return await self._fetch_models(timeout=30.0)
        except httpx.ConnectError:
            logger.warning(f"{self.display_name} not reachable at {self.base_url}")
        except Exception as e:
            logger.error(f"Failed to list {self.display_name} models: {e}")
        return []

    async def test_connection(self, timeout: float = 10.0) -> bool:
        """True when the server answers /models with these credentials.

        An empty model list still counts (a local server with nothing loaded is
        running), and so does a server with no /models route at all, but an
        unreachable server or a rejected key does not.
        """
        if self._missing_credentials():
            return False
        try:
            await self._fetch_models(timeout=timeout)
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 405):
                return True  # up, just no model list (some gateways); chat may still work
            logger.error(f"{self.display_name} connection test failed: {e}")
            return False
        except Exception as e:
            logger.error(f"{self.display_name} connection test failed: {e}")
            return False

    # ── Chat ─────────────────────────────────────────────────────

    async def _resolve_model(self, model: str) -> str:
        """The model to send: the one asked for, else the first the server lists."""
        self._require_url()
        if model:
            return model
        models = await self.list_models()
        if not models:
            raise ValueError(f"No model specified and none available in {self.display_name}")
        logger.info(f"Auto-selected model: {models[0].id}")
        return models[0].id

    def _payload(
        self, messages: List[Dict[str, Any]], model: str, temperature: float,
        max_tokens: Optional[int], stream: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if stream:
            payload["stream"] = True
        if max_tokens:
            payload["max_tokens"] = max_tokens
        return payload

    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a complete response."""
        model = await self._resolve_model(model)
        payload = self._payload(messages, model, temperature, max_tokens)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", headers=self._get_headers(), json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"].get("content") or "",
            model=model,
            provider=self.provider_name,
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason"),
        )

    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream response chunks."""
        model = await self._resolve_model(model)
        payload = self._payload(messages, model, temperature, max_tokens, stream=True)
        logger.info(f"{self.display_name} streaming to {self.base_url}/chat/completions "
                    f"(model={model}, messages={len(messages)})")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions",
                    headers=self._get_headers(), json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", "replace")[:300]
                        logger.error(f"{self.display_name} error {response.status_code}: {body}")
                        raise httpx.HTTPStatusError(
                            f"{self.display_name} returned {response.status_code}: {body}",
                            request=response.request, response=response,
                        )

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            yield StreamChunk(content="", is_done=True)
                            break
                        try:
                            delta = json.loads(data_str)["choices"][0].get("delta", {})
                        except Exception as e:
                            logger.warning(f"Failed to parse chunk: {e} - data: {data_str[:100]}")
                            continue
                        content = delta.get("content")
                        if content:
                            yield StreamChunk(content=content)
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to {self.display_name} at {self.base_url}: {e}")
            raise ValueError(f"Cannot connect to {self.display_name}. Is it running at {self.base_url}?")
