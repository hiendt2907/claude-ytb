"""Retry ở ranh giới transport của Vision, giống hệt đã làm cho LLM.

Một video Long gọi Judge khoảng 250 lần. Trước bản sửa này, ĐÚNG MỘT lần
read-timeout trong 250 lần giết cả node `visual_assets` sau khi đã sinh xong
ảnh — mất toàn bộ công của node. Đã xảy ra thật trong session 2026-09-01.

Cùng lớp với ba lỗi transport của LLM đã sửa (`18fee34`, `fd558ed`,
`b142e55`): gateway trả về thứ không phải câu trả lời của model. Cách xử lý
đúng là hỏi lại, không phải nới cổng.

Ranh giới phải giữ: chỉ retry lỗi THOÁNG QUA. 401/403 (sai khoá) và 413
(payload quá lớn) là lỗi vĩnh viễn — retry chỉ làm chậm rồi vẫn hỏng, và che
mất nguyên nhân thật.
"""

from __future__ import annotations

import urllib.error as urllib_error
from io import BytesIO

import pytest

from ytb_pipeline.render.visual_judge import JudgeInfrastructureError


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


_OK_BODY = b'{"choices":[{"message":{"content":"{\\"verdict\\":\\"pass\\"}"}}]}'


def _flaky_urlopen(errors: list[BaseException]):
    """urlopen ném lần lượt các lỗi đã cho, rồi trả về một phản hồi hợp lệ."""
    calls: list[int] = []

    def _open(*_args: object, **_kwargs: object) -> _Response:
        calls.append(1)
        if errors:
            raise errors.pop(0)
        return _Response(_OK_BODY)

    return _open, calls


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        urllib_error.URLError("connection reset"),
        urllib_error.HTTPError("https://api.xkiro.com/v1/chat/completions", 503, "unavailable", {}, BytesIO(b"{}")),
        urllib_error.HTTPError("https://api.xkiro.com/v1/chat/completions", 429, "rate limit", {}, BytesIO(b"{}")),
    ],
)
def test_transient_transport_fault_is_retried_not_fatal(monkeypatch, error):
    from ytb_pipeline.providers.vision import xkiro_provider

    opener, calls = _flaky_urlopen([error])
    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", opener)
    monkeypatch.setattr(xkiro_provider.time, "sleep", lambda _s: None)

    transport = xkiro_provider.XkiroVisionTransport(api_key="test-key")
    text = transport.complete(
        model="qwen/qwen3.8-max:free",
        system="system",
        content=({"type": "text", "text": "prompt"},),
    )

    assert '"verdict"' in text
    assert len(calls) == 2, "phải hỏi lại đúng một lần sau lỗi thoáng qua"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "authentication"), (403, "authentication"), (413, "payload too large")],
)
def test_permanent_fault_is_not_retried(monkeypatch, status, message):
    """Sai khoá hay payload quá lớn: hỏi lại 3 lần vẫn sai, chỉ tốn thời gian
    và làm mờ nguyên nhân. Phải hỏng ngay ở lần đầu."""
    from ytb_pipeline.providers.vision import xkiro_provider

    error = urllib_error.HTTPError(
        "https://api.xkiro.com/v1/chat/completions", status, "error", {}, BytesIO(b"{}")
    )
    opener, calls = _flaky_urlopen([error, error, error])
    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", opener)
    monkeypatch.setattr(xkiro_provider.time, "sleep", lambda _s: None)

    transport = xkiro_provider.XkiroVisionTransport(api_key="test-key")
    with pytest.raises(JudgeInfrastructureError, match=message):
        transport.complete(
            model="qwen/qwen3.8-max:free",
            system="system",
            content=({"type": "text", "text": "prompt"},),
        )

    assert len(calls) == 1, "lỗi vĩnh viễn không được retry"


def test_retry_budget_is_bounded(monkeypatch):
    """Gateway chết hẳn thì vẫn phải dừng, không quay vòng vô hạn."""
    from ytb_pipeline.providers.vision import xkiro_provider

    opener, calls = _flaky_urlopen([TimeoutError("timed out")] * 50)
    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", opener)
    monkeypatch.setattr(xkiro_provider.time, "sleep", lambda _s: None)

    transport = xkiro_provider.XkiroVisionTransport(api_key="test-key")
    with pytest.raises(JudgeInfrastructureError):
        transport.complete(
            model="qwen/qwen3.8-max:free",
            system="system",
            content=({"type": "text", "text": "prompt"},),
        )

    assert len(calls) == xkiro_provider.MAX_TRANSPORT_ATTEMPTS
    assert xkiro_provider.MAX_TRANSPORT_ATTEMPTS <= 4
