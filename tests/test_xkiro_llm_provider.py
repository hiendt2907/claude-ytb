"""Tests cho XkiroLLMProvider — chat completions OpenAI-compatible của xKiro."""

from __future__ import annotations

import json

import pytest
from urllib import error as urllib_error
from urllib.request import Request

from ytb_pipeline.providers.errors import ProviderUnavailableError


def _fake_response(body: dict):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(body).encode("utf-8")

    return _Response()


@pytest.mark.unit
def test_xkiro_llm_provider_registers_and_satisfies_protocol():
    from ytb_pipeline.providers.base import LLMProvider
    from ytb_pipeline.providers.registry import get_llm_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    provider = get_llm_provider("xkiro")

    assert isinstance(provider, XkiroLLMProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.name == "xkiro"


@pytest.mark.unit
def test_xkiro_llm_unavailable_without_api_key(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "", raising=False)
    assert XkiroLLMProvider().is_available() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_sends_openai_compatible_chat_request(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_url", "https://voice.example/v1/chat/completions", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "deepseek/deepseek-v4-flash", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "", raising=False)
    request_seen: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        request_seen["url"] = request.full_url
        request_seen["authorization"] = request.get_header("Authorization")
        request_seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _fake_response({"choices": [{"message": {"content": "xin chào"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    result = await XkiroLLMProvider().complete("hỏi gì đó", system="bạn là trợ lý")

    assert result == "xin chào"
    assert request_seen["url"] == "https://voice.example/v1/chat/completions"
    assert request_seen["authorization"] == "Bearer test-key"
    assert request_seen["payload"]["model"] == "deepseek/deepseek-v4-flash"
    assert request_seen["payload"]["messages"] == [
        {"role": "system", "content": "bạn là trợ lý"},
        {"role": "user", "content": "hỏi gì đó"},
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_sends_json_schema_when_structured_output_is_requested(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "", raising=False)
    seen: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _fake_response({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    await XkiroLLMProvider().complete("script", json_output=True, response_schema=schema)

    assert seen["payload"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "youtube_script", "strict": True, "schema": schema},
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_omits_response_format_when_json_is_not_requested(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "", raising=False)
    seen: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _fake_response({"choices": [{"message": {"content": "plain text"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    await XkiroLLMProvider().complete("script", json_output=False)

    assert "response_format" not in seen["payload"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_downgrades_schema_400_to_json_object_on_same_model(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "model-b", raising=False)
    calls: list[tuple[str, str]] = []

    def fake_urlopen(request: Request, timeout: float):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((payload["model"], payload["response_format"]["type"]))
        if payload["response_format"]["type"] == "json_schema":
            raise urllib_error.HTTPError(request.full_url, 400, "Bad Request", None, None)
        return _fake_response({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    assert await XkiroLLMProvider().complete("script", json_output=True, response_schema={"type": "object"}) == "{}"
    assert calls == [("model-a", "json_schema"), ("model-a", "json_object")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_does_not_hide_an_unsupported_response_format_by_changing_model(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "model-b", raising=False)
    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        calls.append(json.loads(request.data.decode("utf-8"))["model"])
        raise urllib_error.HTTPError(request.full_url, 400, "Bad Request", None, None)

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError, match="response_format"):
        await XkiroLLMProvider().complete("script", json_output=True, response_schema={"type": "object"})
    assert calls == ["model-a", "model-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_uses_next_model_for_a_real_server_error(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "model-b", raising=False)
    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        model = json.loads(request.data.decode("utf-8"))["model"]
        calls.append(model)
        if model == "model-a":
            raise urllib_error.HTTPError(request.full_url, 500, "Server Error", None, None)
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    assert await XkiroLLMProvider().complete("script", json_output=True, response_schema={"type": "object"}) == "ok"
    assert calls == ["model-a", "model-b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_falls_back_to_next_model_on_error(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "model-b,model-c", raising=False)

    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        payload = json.loads(request.data.decode("utf-8"))
        model = payload["model"]
        calls.append(model)
        if model != "model-b":
            raise urllib_error.HTTPError(request.full_url, 403, "Forbidden", None, None)
        return _fake_response({"choices": [{"message": {"content": "ok tu model-b"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    result = await XkiroLLMProvider().complete("test")

    assert result == "ok tu model-b"
    assert calls == ["model-a", "model-b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_raises_when_all_models_fail(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "model-b", raising=False)

    def fake_urlopen(request: Request, timeout: float):
        raise urllib_error.HTTPError(request.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError):
        await XkiroLLMProvider().complete("test")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_raises_on_empty_content(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_fallback_models", "", raising=False)

    def fake_urlopen(request: Request, timeout: float):
        return _fake_response({"choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError):
        await XkiroLLMProvider().complete("test")
