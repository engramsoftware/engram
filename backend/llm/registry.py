"""
Single source of truth for which LLM providers exist and how they behave.

Everything that used to ask "is this a local provider?", "what is the default
URL?" or "which model do I fall back to?" with its own if/elif chain reads a
ProviderSpec from here instead. To add a provider: add a spec below and map it
to a class in llm/factory.py. Nothing else needs to know its name.

The frontend keeps a matching table in frontend/src/utils/providers.ts;
backend/tests/test_llm_registry.py fails if the two drift apart.

This module only holds data and pure helpers, so it never imports a provider
class (no import cycles) and is cheap to import from anywhere.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

# Fallback Claude IDs live next to the provider that uses them
from llm.anthropic_provider import ANTHROPIC_DEFAULT_MODEL, ANTHROPIC_FAST_MODEL

# How a provider wants image attachments shaped (see LLMProvider.inject_images_into_messages)
IMAGE_OPENAI = "openai"        # image_url content blocks with data URIs
IMAGE_ANTHROPIC = "anthropic"  # base64 "source" blocks
IMAGE_OLLAMA = "ollama"        # raw base64 strings in message["images"]

API_KEY_REQUIRED = "required"
API_KEY_OPTIONAL = "optional"
API_KEY_NONE = "none"


@dataclass(frozen=True)
class ProviderSpec:
    """Static facts about one provider."""

    id: str
    name: str
    #: Runs on the user's own machine/network (no cloud account, no per-token cost)
    local: bool
    #: Used when the user saved no URL. Empty = the user must supply one.
    default_url: str
    #: API_KEY_REQUIRED / API_KEY_OPTIONAL / API_KEY_NONE
    api_key: str
    #: Fallback model for chat when none is chosen or cached ("" = pick the first the server lists)
    default_model: str
    #: Cheap model for background work (memory extraction etc.)
    background_model: str
    #: .env settings (config.Settings attribute names) used when the user saved nothing
    env_api_key: Optional[str] = None
    env_base_url: Optional[str] = None
    image_format: str = IMAGE_OPENAI
    key_placeholder: str = ""
    key_url: str = ""

    @property
    def requires_api_key(self) -> bool:
        return self.api_key == API_KEY_REQUIRED

    @property
    def accepts_api_key(self) -> bool:
        return self.api_key != API_KEY_NONE

    @property
    def requires_url(self) -> bool:
        return not self.default_url


# Display order: local first (the setup wizard lists them that way), then cloud, then custom
PROVIDER_SPECS: Dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        ProviderSpec(
            id="lmstudio", name="LM Studio", local=True,
            default_url="http://host.docker.internal:1234/v1",
            api_key=API_KEY_NONE,
            default_model="local-model", background_model="local-model",
            env_base_url="lmstudio_base_url",
        ),
        ProviderSpec(
            id="ollama", name="Ollama", local=True,
            default_url="http://host.docker.internal:11434",
            api_key=API_KEY_NONE,
            default_model="llama3.2", background_model="llama3.2",
            env_base_url="ollama_base_url",
            image_format=IMAGE_OLLAMA,
        ),
        ProviderSpec(
            id="openai", name="OpenAI", local=False,
            default_url="https://api.openai.com/v1",
            api_key=API_KEY_REQUIRED,
            default_model="gpt-4o", background_model="gpt-4o-mini",
            env_api_key="openai_api_key", env_base_url="openai_base_url",
            key_placeholder="sk-...", key_url="https://platform.openai.com/api-keys",
        ),
        ProviderSpec(
            id="anthropic", name="Anthropic", local=False,
            default_url="https://api.anthropic.com",
            api_key=API_KEY_REQUIRED,
            default_model=ANTHROPIC_DEFAULT_MODEL, background_model=ANTHROPIC_FAST_MODEL,
            env_api_key="anthropic_api_key", env_base_url="anthropic_base_url",
            image_format=IMAGE_ANTHROPIC,
            key_placeholder="sk-ant-...", key_url="https://console.anthropic.com/settings/keys",
        ),
        # Any server that speaks the OpenAI chat API: llama.cpp (llama-server), vLLM,
        # text-generation-webui, Groq, Together, OpenRouter, a company gateway...
        ProviderSpec(
            id="custom", name="Custom (OpenAI-compatible)", local=False,
            default_url="",
            api_key=API_KEY_OPTIONAL,
            default_model="", background_model="",
            env_api_key="custom_api_key", env_base_url="custom_base_url",
            key_placeholder="Only if the server asks for one",
        ),
    )
}


#: Used when the user has configured nothing at all
DEFAULT_PROVIDER = "lmstudio"


def provider_ids() -> List[str]:
    """Every supported provider id, in display order."""
    return list(PROVIDER_SPECS)


def get_spec(provider_name: Optional[str]) -> Optional[ProviderSpec]:
    """The spec for a provider id (case-insensitive), or None if unknown."""
    return PROVIDER_SPECS.get((provider_name or "").lower())


def is_local(provider_name: Optional[str]) -> bool:
    spec = get_spec(provider_name)
    return bool(spec and spec.local)


def default_model(provider_name: Optional[str], background: bool = False) -> str:
    """Fallback model for a provider ("" when the server should be asked)."""
    spec = get_spec(provider_name)
    if not spec:
        return ""
    return spec.background_model if background else spec.default_model


def resolve_credentials(
    provider_name: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Fill any missing API key / URL from the .env settings.

    A value the caller already has (the user's saved one) always wins; .env only
    fills gaps. Returns (api_key, base_url); either may still be None, in which
    case the provider class uses its own default URL.
    """
    spec = get_spec(provider_name)
    if not spec or (api_key and base_url):
        return api_key, base_url

    from config import get_settings
    env = get_settings()
    if not api_key and spec.env_api_key:
        api_key = getattr(env, spec.env_api_key, None) or None
    if not base_url and spec.env_base_url:
        base_url = getattr(env, spec.env_base_url, None) or None
    return api_key, base_url


def normalize_base_url(provider_name: str, url: Optional[str]) -> str:
    """Tidy a user-typed server URL so every provider can append its own paths.

    - Trailing slashes are dropped.
    - OpenAI-style servers get "/v1" when the URL is just a host
      ("http://host:8080" -> "http://host:8080/v1"); a URL that already has a
      path (".../openai/v1", ".../api/v1") is left alone.
    - Ollama's native API has no "/v1", so one pasted from its OpenAI-compatible
      address is trimmed.
    - An empty URL falls back to the provider's default.
    """
    spec = get_spec(provider_name)
    url = (url or "").strip().rstrip("/")
    if not url:
        return spec.default_url if spec else ""
    if provider_name == "ollama":
        return url[:-3].rstrip("/") if url.endswith("/v1") else url
    if provider_name in ("lmstudio", "openai", "custom") and not urlsplit(url).path:
        return f"{url}/v1"
    return url


def _split_prefix(model: str) -> Tuple[Optional[str], str]:
    """Split "ollama:llama3.1:8b" into ("ollama", "llama3.1:8b").

    Only a known provider id counts as a prefix, so Ollama tags like
    "llama3.1:8b" pass through untouched.
    """
    head, sep, rest = model.partition(":")
    if sep and rest and head.lower() in PROVIDER_SPECS:
        return head.lower(), rest
    return None, model


def route_model(
    model: str,
    providers: Optional[Mapping[str, Mapping[str, Any]]] = None,
    default_provider: Optional[str] = None,
) -> Tuple[str, str]:
    """Pick the provider for a bare model name (the /v1/chat/completions endpoint).

    External clients only send a model string, so the provider has to be inferred.
    In order:
      1. an explicit "provider:model" prefix (the prefix is stripped from the model);
      2. a provider whose saved model list contains exactly this model (enabled or not);
      3. the well-known cloud prefixes (claude* -> Anthropic, gpt*/o1/o3/o4 -> OpenAI);
      4. the user's default provider;
      5. the first enabled provider, then OpenAI.

    Returns (provider_id, model_to_send).
    """
    prefixed, bare = _split_prefix(model)
    if prefixed:
        return prefixed, bare

    providers = providers or {}
    for pid in PROVIDER_SPECS:
        cfg = providers.get(pid) or {}
        if model in (cfg.get("availableModels") or []):
            return pid, model

    lowered = model.lower()
    if lowered.startswith("claude"):
        return "anthropic", model
    if lowered.startswith(("gpt-", "chatgpt", "o1", "o3", "o4")):
        return "openai", model

    if default_provider in PROVIDER_SPECS:
        return default_provider, model
    for pid in PROVIDER_SPECS:
        if (providers.get(pid) or {}).get("enabled"):
            return pid, model
    return "openai", model
