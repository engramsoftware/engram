"""The provider registry: the one list every other module reads."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from llm import registry
from llm.factory import PROVIDERS, create_provider, get_available_providers
from llm.registry import (
    default_model, get_spec, is_local, normalize_base_url, resolve_credentials, route_model,
)


def test_every_provider_has_spec_and_class():
    assert set(PROVIDERS) == set(registry.PROVIDER_SPECS)
    assert get_available_providers() == registry.provider_ids()
    for pid, cls in PROVIDERS.items():
        assert cls.provider_name == pid


def test_spec_facts():
    assert get_spec("OpenAI").requires_api_key
    assert not get_spec("lmstudio").accepts_api_key
    custom = get_spec("custom")
    assert custom.requires_url and custom.accepts_api_key and not custom.requires_api_key
    assert is_local("ollama") and not is_local("openai") and not is_local("nope")
    assert get_spec("nope") is None


def test_default_models():
    assert default_model("openai") == "gpt-4o"
    assert default_model("openai", background=True) == "gpt-4o-mini"
    assert default_model("custom") == ""      # ask the server
    assert default_model("nope") == ""


@pytest.mark.parametrize("provider,url,expected", [
    ("lmstudio", None, "http://host.docker.internal:1234/v1"),
    ("lmstudio", "http://h:1234", "http://h:1234/v1"),          # host only -> /v1 added
    ("lmstudio", "http://h:1234/", "http://h:1234/v1"),
    ("lmstudio", "http://h:1234/v1/", "http://h:1234/v1"),
    ("custom", "http://h:8080", "http://h:8080/v1"),
    ("custom", "https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1"),  # has a path
    ("custom", "https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1"),
    ("custom", "", ""),                                          # no default for Custom
    ("ollama", "http://h:11434/v1", "http://h:11434"),           # Ollama's native API has no /v1
    ("ollama", "http://h:11434/", "http://h:11434"),
    ("anthropic", "https://proxy.example/anthropic/", "https://proxy.example/anthropic"),
])
def test_normalize_base_url(provider, url, expected):
    assert normalize_base_url(provider, url) == expected


MODELS = {
    "lmstudio": {"enabled": False, "availableModels": ["qwen/qwen3-8b"]},
    "ollama": {"enabled": True, "availableModels": ["llama3.1:8b"]},
}


@pytest.mark.parametrize("model,default,expected", [
    ("ollama:llama3.1:8b", None, ("ollama", "llama3.1:8b")),     # explicit prefix is stripped
    ("custom:my-model", None, ("custom", "my-model")),
    ("llama3.1:8b", "openai", ("ollama", "llama3.1:8b")),        # a tag is not a prefix; found in a list
    ("qwen/qwen3-8b", "openai", ("lmstudio", "qwen/qwen3-8b")),  # listed by a disabled provider too
    ("claude-sonnet-5-5", "ollama", ("anthropic", "claude-sonnet-5-5")),
    ("gpt-4o-mini", "ollama", ("openai", "gpt-4o-mini")),
    ("mystery-model", "custom", ("custom", "mystery-model")),    # falls to the user's default
    ("mystery-model", None, ("ollama", "mystery-model")),        # then the first enabled provider
])
def test_route_model(model, default, expected):
    assert route_model(model, MODELS, default) == expected


def test_route_model_with_nothing_configured():
    assert route_model("mystery-model") == ("openai", "mystery-model")


def test_resolve_credentials_fills_gaps_only(monkeypatch):
    env = SimpleNamespace(openai_api_key="env-key", openai_base_url=None,
                          lmstudio_base_url="http://env:1234", custom_api_key=None, custom_base_url=None)
    monkeypatch.setattr(config, "get_settings", lambda: env)
    assert resolve_credentials("openai") == ("env-key", None)
    assert resolve_credentials("openai", api_key="user-key") == ("user-key", None)  # user's wins
    assert resolve_credentials("lmstudio", base_url="http://user:1") == (None, "http://user:1")
    assert resolve_credentials("lmstudio") == (None, "http://env:1234")
    assert resolve_credentials("custom") == (None, None)
    assert resolve_credentials("nope", "k", None) == ("k", None)


def test_create_provider_env_fallback_is_opt_in(monkeypatch):
    env = SimpleNamespace(openai_api_key="env-key", openai_base_url=None)
    monkeypatch.setattr(config, "get_settings", lambda: env)
    assert create_provider("openai").api_key is None
    assert create_provider("openai", use_env_fallback=True).api_key == "env-key"
    assert create_provider("nope") is None


# ── Frontend table (frontend/src/utils/providers.ts) must match the registry ──

TS_FILE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "providers.ts"


def _frontend_meta():
    """Parse PROVIDER_META out of providers.ts: {id: {field: value}}."""
    src = TS_FILE.read_text()
    block = src[src.index("export const PROVIDER_META"):src.index("export const PROVIDER_IDS")]
    meta = {}
    for match in re.finditer(r"^  (\w+): \{\n(.*?)^  \},", block, re.S | re.M):
        fields = {}
        for line in match.group(2).splitlines():
            m = re.match(r"\s+(\w+): (.+),$", line)
            if m:
                raw = m.group(2)
                fields[m.group(1)] = (raw == "true") if raw in ("true", "false") else raw.strip("'")
        meta[match.group(1)] = fields
    return meta


def test_frontend_table_matches_registry():
    meta = _frontend_meta()
    assert list(meta) == registry.provider_ids()          # same providers, same order
    for pid, spec in registry.PROVIDER_SPECS.items():
        fe = meta[pid]
        assert fe["name"] == spec.name, pid
        assert fe["defaultUrl"] == spec.default_url, pid
        assert fe["needsApiKey"] == spec.requires_api_key, pid
        assert fe["acceptsApiKey"] == spec.accepts_api_key, pid
        assert fe["requiresUrl"] == spec.requires_url, pid
        assert fe["local"] == spec.local, pid
        assert fe.get("keyPlaceholder", "") == spec.key_placeholder, pid
        assert fe.get("keyUrl", "") == spec.key_url, pid
