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
def test_xkiro_script_defaults_pin_deepseek_v4_pro_without_model_fallbacks():
    from ytb_pipeline.config.settings import Settings
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    defaults = Settings(_env_file=None)

    assert defaults.xkiro_llm_model == "deepseek/deepseek-v4-pro"
    assert not hasattr(defaults, "xkiro_llm_fallback_models")
    assert XkiroLLMProvider().model_name() == "deepseek/deepseek-v4-pro"


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
    monkeypatch.setattr(settings, "xkiro_llm_model", "deepseek/deepseek-v4-pro", raising=False)
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
    assert request_seen["payload"]["model"] == "deepseek/deepseek-v4-pro"
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
async def test_xkiro_llm_retries_same_model_without_response_format_when_gateway_500s(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_model", "model-a", raising=False)
    calls: list[tuple[str, object]] = []

    def fake_urlopen(request: Request, timeout: float):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((payload["model"], payload.get("response_format")))
        if "response_format" in payload:
            raise urllib_error.HTTPError(request.full_url, 500, "Server Error", None, None)
        return _fake_response({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    assert await XkiroLLMProvider().complete(
        "script", json_output=True, response_schema={"type": "object"}
    ) == "{}"
    assert calls == [
        ("model-a", {"type": "json_schema", "json_schema": {
            "name": "youtube_script", "strict": True, "schema": {"type": "object"},
        }}),
        ("model-a", None),
    ]


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
    long_budget = xkiro_provider.request_timeout_for(max_tokens=60_000)

    assert short_budget >= xkiro_provider._REQUEST_TIMEOUT_S
    assert long_budget > short_budget * 2


async def test_request_timeout_floor_covers_a_small_output_call_with_a_large_input(monkeypatch):
    """A small max_tokens ask (e.g. editorial_review's 1024-token verdict) can
    still take a long time to *start* responding when the INPUT is large (a
    full Long script + rubric) — the formula only scales with requested
    OUTPUT size, so the floor alone must be generous enough to cover that
    prefill latency.

    Production 2026-08-27: `run_editorial_review()` (max_tokens=1024) timed
    out twice in a row against real xKiro at the previous 60s floor, both
    times on a full Long script payload.
    """
    from ytb_pipeline.providers.llm import xkiro_provider

    assert xkiro_provider.request_timeout_for(max_tokens=1024) >= 600.0


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_retries_a_response_with_broken_utf8_bytes(monkeypatch):
    """Gateway cắt ký tự nhiều byte giữa chừng; một lượt sinh không nên chết vì thế.

    Đo trên production: hai lượt sinh Long liên tiếp hỏng vì đúng lỗi này, với
    'câu trả l\\ufffd\\ufffd\\ufffdi' và 'gi\\ufffd\\ufffd này' trong voiceover —
    tiếng Việt nhiều byte bị truncate trên đường truyền. Cổng encoding bắt đúng
    và fail closed (giữ nguyên), nhưng mỗi lần như vậy mất trọn một lượt sinh
    vài phút, trong khi lời gọi lại thường sạch.

    Retry ngay tại ranh giới provider, có TRẦN. Không nới cổng, không vá text:
    byte đã mất thì không đoán lại được, chỉ hỏi lại provider.
    """
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_url", "https://voice.example/v1/chat", raising=False)
    calls = {"n": 0}

    class _Corrupt:
        """Body có byte UTF-8 hỏng: 'lời' bị cắt mất byte cuối."""

        def read(self):
            payload = '{"choices":[{"message":{"content":"câu trả lời"}}]}'.encode("utf-8")
            return payload[:-14] + b"\xe1\xbb" + payload[-13:]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request: Request, timeout: float):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Corrupt()
        return _fake_response({"choices": [{"message": {"content": "câu trả lời"}}]})

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)

    result = await XkiroLLMProvider().complete("hỏi gì đó")

    assert calls["n"] == 2, "phải hỏi lại provider khi byte hỏng"
    assert "�" not in result
    assert result == "câu trả lời"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_llm_gives_up_after_bounded_retries_on_broken_bytes(monkeypatch):
    """Hỏng mãi thì phải dừng, không quay vòng vô hạn."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.llm import xkiro_provider
    from ytb_pipeline.providers.llm.xkiro_provider import (
        MAX_CORRUPT_RESPONSE_RETRIES, XkiroLLMProvider,
    )
    from ytb_pipeline.providers.errors import ProviderUnavailableError

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_llm_url", "https://voice.example/v1/chat", raising=False)
    calls = {"n": 0}

    class _AlwaysCorrupt:
        def read(self):
            calls["n"] += 1
            return b'{"choices":[{"message":{"content":"c\xe1\xbb'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        xkiro_provider.urllib_request, "urlopen",
        lambda request, timeout: _AlwaysCorrupt(),
    )

    with pytest.raises(ProviderUnavailableError):
        await XkiroLLMProvider().complete("hỏi gì đó")

    assert calls["n"] == MAX_CORRUPT_RESPONSE_RETRIES + 1
