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
def test_xkiro_script_defaults_pin_gemini_flash_without_model_fallbacks():
    from ytb_pipeline.config.settings import Settings
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    defaults = Settings(_env_file=None)

    assert defaults.xkiro_llm_model == "google/gemini-3.7-flash"
    assert not hasattr(defaults, "xkiro_llm_fallback_models")
    assert XkiroLLMProvider().model_name() == "google/gemini-3.7-flash"


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
    monkeypatch.setattr(settings, "xkiro_llm_model", "google/gemini-3.7-flash", raising=False)
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
    assert request_seen["payload"]["model"] == "google/gemini-3.7-flash"
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
async def test_xkiro_llm_surfaces_server_error_without_changing_model(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        model = json.loads(request.data.decode("utf-8"))["model"]
        calls.append(model)
        raise urllib_error.HTTPError(request.full_url, 500, "Server Error", None, None)

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError, match="HTTP 500"):
        await XkiroLLMProvider().complete("script", json_output=True, response_schema={"type": "object"})
    assert calls == ["model-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_does_not_retry_with_another_model(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        payload = json.loads(request.data.decode("utf-8"))
        model = payload["model"]
        calls.append(model)
        raise urllib_error.HTTPError(request.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError, match="HTTP 403"):
        await XkiroLLMProvider().complete("test")
    assert calls == ["model-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_raises_when_the_pinned_model_fails(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)

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

    def fake_urlopen(request: Request, timeout: float):
        return _fake_response({"choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError):
        await XkiroLLMProvider().complete("test")


async def test_request_timeout_scales_with_the_requested_output_size(monkeypatch):
    """A Long asks for 14k tokens; a flat 60s budget could never deliver it.

    Production 2026-08-24: every model in the cascade "failed" with a read
    timeout while generating a 13k-character Long, so the run wasted 4 minutes
    and fell through to a CLI provider that cannot enforce the JSON schema.
    """
    from ytb_pipeline.providers.llm import xkiro_provider

    short_budget = xkiro_provider.request_timeout_for(max_tokens=4096)
    long_budget = xkiro_provider.request_timeout_for(max_tokens=14000)

    assert short_budget >= xkiro_provider._REQUEST_TIMEOUT_S
    assert long_budget > short_budget * 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_surfaces_invalid_json_without_changing_model(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)

    class _BrokenBodyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"event: ping\n\ndata: not-json-at-all"

    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: float):
        model = json.loads(request.data.decode("utf-8"))["model"]
        calls.append(model)
        return _BrokenBodyResponse()

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderUnavailableError, match="không phải JSON"):
        await XkiroLLMProvider().complete("test")
    assert calls == ["model-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_reports_the_bad_body_when_every_model_returns_invalid_json(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)

    class _BrokenBodyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"not-json-at-all"

    monkeypatch.setattr(
        xkiro_provider.urllib_request, "urlopen", lambda request, timeout: _BrokenBodyResponse()
    )

    with pytest.raises(ProviderUnavailableError, match="not-json-at-all"):
        await XkiroLLMProvider().complete("test")
