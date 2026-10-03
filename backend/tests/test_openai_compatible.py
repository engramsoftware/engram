"""OpenAI-compatible providers (OpenAI, LM Studio, Custom) against a fake server."""
import asyncio
import json

import httpx
import pytest

from llm import openai_compatible
from llm.factory import create_provider


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def server(monkeypatch):
    """Route the providers' HTTP calls to a handler; records every request."""
    state = {"handler": None, "requests": []}
    real = httpx.AsyncClient

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(
        openai_compatible.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    return state


def sse(*events):
    body = "".join(f"data: {e}\n\n" for e in events)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def chunk(text):
    return json.dumps({"choices": [{"delta": {"content": text}}]})


def test_lists_models_sorted_and_hides_non_chat_for_openai(server):
    server["handler"] = lambda r: httpx.Response(200, json={"data": [
        {"id": "text-embedding-3-small"}, {"id": "gpt-4o"}, {"id": "gpt-4"}, {"id": "whisper-1"}]})
    models = run(create_provider("openai", api_key="k").list_models())
    assert [m.id for m in models] == ["gpt-4", "gpt-4o"]
    assert models[1].supports_vision and not models[0].supports_vision


def test_custom_lists_everything_and_sends_key_only_when_set(server):
    server["handler"] = lambda r: httpx.Response(200, json={"data": [{"id": "llava-1.6"}, {"id": "llama-3.1-8b"}]})
    models = run(create_provider("custom", base_url="http://h:8080").list_models())
    assert [m.id for m in models] == ["llama-3.1-8b", "llava-1.6"]
    assert models[1].supports_vision
    req = server["requests"][-1]
    assert str(req.url) == "http://h:8080/v1/models" and "authorization" not in req.headers

    run(create_provider("custom", api_key="secret", base_url="http://h:8080/v1").list_models())
    assert server["requests"][-1].headers["authorization"] == "Bearer secret"


def test_openai_without_key_or_custom_without_url_never_calls_out(server):
    server["handler"] = lambda r: pytest.fail("should not be called")
    assert run(create_provider("openai").list_models()) == []
    assert run(create_provider("openai").test_connection()) is False
    assert run(create_provider("custom").list_models()) == []
    assert run(create_provider("custom").test_connection()) is False
    with pytest.raises(ValueError, match="server URL"):
        run(create_provider("custom").generate([{"role": "user", "content": "hi"}], "m"))


def test_connection_reflects_reachability_not_model_count(server):
    server["handler"] = lambda r: httpx.Response(200, json={"data": []})
    assert run(create_provider("lmstudio").test_connection()) is True   # running, nothing loaded

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    server["handler"] = refuse
    assert run(create_provider("lmstudio").test_connection()) is False  # used to say True
    assert run(create_provider("lmstudio").list_models()) == []

    server["handler"] = lambda r: httpx.Response(401, json={"error": "bad key"})
    assert run(create_provider("custom", base_url="http://h:1").test_connection()) is False

    # A gateway with no /models route is still up; it must not be reported as down
    server["handler"] = lambda r: httpx.Response(404, json={"error": "not found"})
    assert run(create_provider("custom", base_url="http://h:1").test_connection()) is True
    assert run(create_provider("custom", base_url="http://h:1").list_models()) == []


def test_stream_yields_text_and_done(server):
    server["handler"] = lambda r: sse(chunk("Hel"), chunk("lo"), json.dumps({"choices": [{"delta": {}}]}), "[DONE]")

    async def collect():
        return [c async for c in create_provider("lmstudio").stream([{"role": "user", "content": "hi"}], "m")]

    chunks = run(collect())
    assert "".join(c.content for c in chunks) == "Hello"
    assert chunks[-1].is_done
    body = json.loads(server["requests"][-1].content)
    assert body["stream"] is True and body["model"] == "m"


def test_stream_without_model_uses_first_listed(server):
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})
        return sse(chunk("ok"), "[DONE]")
    server["handler"] = handler

    async def collect():
        return [c async for c in create_provider("custom", base_url="http://h:1").stream([], "")]

    run(collect())
    assert json.loads(server["requests"][-1].content)["model"] == "a-model"


def test_stream_error_carries_the_server_message(server):
    server["handler"] = lambda r: httpx.Response(404, json={"error": "model 'x' not found"})

    async def collect():
        return [c async for c in create_provider("lmstudio").stream([], "x")]

    with pytest.raises(httpx.HTTPStatusError, match="model 'x' not found"):
        run(collect())


def test_stream_unreachable_server_says_where(server):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    server["handler"] = refuse

    async def collect():
        return [c async for c in create_provider("lmstudio", base_url="http://h:1234").stream([], "m")]

    with pytest.raises(ValueError, match=r"Cannot connect to LM Studio.*http://h:1234/v1"):
        run(collect())


def test_generate_returns_text_and_tolerates_null_content(server):
    server["handler"] = lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": None}, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 3}})
    response = run(create_provider("openai", api_key="k").generate([{"role": "user", "content": "hi"}], "gpt-4o"))
    assert response.content == "" and response.provider == "openai" and response.finish_reason == "tool_calls"
