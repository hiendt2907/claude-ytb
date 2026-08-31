"""Contract tests for the xKiro OpenAI-compatible TTS adapter."""

import json
from pathlib import Path
from urllib.request import Request

import pytest

from ytb_pipeline.pkg.models import Script, Segment
from ytb_pipeline.voiceover.tts import _slugify


def _script() -> Script:
    return Script(
        topic="t",
        title="xKiro demo",
        description="d",
        segments=(
            Segment(caption="mở đầu", narration="Đây là câu đầu tiên."),
            Segment(caption="tiếp", narration="Đây là câu thứ hai."),
        ),
    )


@pytest.mark.unit
def test_xkiro_uses_its_own_measured_planning_speed():
    """xKiro must never silently inherit F5's unrelated calibration."""
    from ytb_pipeline.content_contract import XKIRO_CHARS_PER_MIN, chars_per_min_for_provider

    assert chars_per_min_for_provider("xkiro") == XKIRO_CHARS_PER_MIN


@pytest.mark.unit
def test_xkiro_cache_key_changes_when_endpoint_changes(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    provider = XkiroVoiceProvider()
    script = _script()
    monkeypatch.setattr(settings, "xkiro_tts_url", "https://one.example/v1/audio/speech", raising=False)
    first = provider._segment_path(script, script.segments[0], 0, tmp_path)
    monkeypatch.setattr(settings, "xkiro_tts_url", "https://two.example/v1/audio/speech", raising=False)
    second = provider._segment_path(script, script.segments[0], 0, tmp_path)

    assert first != second


@pytest.mark.unit
def test_xkiro_cache_key_changes_when_chunking_strategy_changes(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    provider = XkiroVoiceProvider()
    script = Script(
        topic="t",
        title="xKiro demo",
        description="d",
        segments=(Segment(caption="c", narration="Một câu rất dài cần được chia nhỏ để đọc rõ hơn."),),
    )
    monkeypatch.setattr(settings, "xkiro_max_chars_per_piece", 48, raising=False)
    first = provider._segment_path(script, script.segments[0], 0, tmp_path)
    monkeypatch.setattr(settings, "xkiro_max_chars_per_piece", 32, raising=False)
    second = provider._segment_path(script, script.segments[0], 0, tmp_path)

    assert first != second


@pytest.mark.unit
def test_xkiro_provider_registers_and_satisfies_voice_protocol():
    from ytb_pipeline.providers.base import VoiceProvider
    from ytb_pipeline.providers.registry import get_voice_provider
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    provider = get_voice_provider("xkiro")

    assert isinstance(provider, XkiroVoiceProvider)
    assert isinstance(provider, VoiceProvider)
    assert provider.name == "xkiro"


def test_artifact_slug_preserves_vietnamese_d_and_uses_project_id(tmp_path):
    """New pipeline artifacts must be addressable by their project slug, not title."""
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    script = Script(
        topic="t",
        title="Đã đổi tiêu đề",
        description="d",
        project_id="slug-da-duyet",
        segments=(Segment(caption="c", narration="Một câu."),),
    )

    assert _slugify("Đã đến") == "da-den"
    assert XkiroVoiceProvider()._segment_path(script, script.segments[0], 0, tmp_path).name.startswith(
        "slug-da-duyet_xkiro_"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_sends_openai_compatible_request(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_tts_url", "https://voice.example/v1/audio/speech", raising=False)
    monkeypatch.setattr(settings, "xkiro_voice", "confident-male-vietnamese", raising=False)
    monkeypatch.setattr(settings, "xkiro_model", "xkiro-voice", raising=False)
    request_seen: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"mp3-bytes"

    def fake_urlopen(request: Request, timeout: float):
        request_seen["url"] = request.full_url
        request_seen["timeout"] = timeout
        request_seen["authorization"] = request.get_header("Authorization")
        request_seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(xkiro_provider.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 1.25)
    monkeypatch.setattr(
        xkiro_provider,
        "_to_mp3",
        lambda src, dst: dst.write_bytes(src.read_bytes()),
    )
    monkeypatch.setattr(
        xkiro_provider,
        "_concat_audio",
        lambda _parts, output: output.write_bytes(b"combined"),
    )

    voiceover = await XkiroVoiceProvider().synthesise(_script(), tmp_path)

    assert request_seen["url"] == "https://voice.example/v1/audio/speech"
    assert request_seen["authorization"] == "Bearer test-key"
    assert request_seen["payload"] == {
        "model": "xkiro-voice",
        "input": "Đây là câu thứ hai.",
        "voice": "confident-male-vietnamese",
        "response_format": "mp3",
        "stream": False,
    }
    assert [segment.duration_sec for segment in voiceover.segments] == [1.25, 1.25]
    assert voiceover.audio_path == tmp_path / "xkiro-demo_xkiro.mp3"
    assert voiceover.audio_path.read_bytes() == b"combined"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_normalizes_raw_audio_before_concat(monkeypatch, tmp_path):
    """xKiro trả mp3 24kHz mono; concat với silence 44100/stereo không qua
    chuẩn hoá từng làm ffmpeg/libmp3lame abort giữa chừng (loudnorm reconfigure)."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider
    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(XkiroVoiceProvider, "_request_audio", lambda _self, _text: b"raw-24khz-mono")
    normalize_calls: list[tuple[bytes, str]] = []

    def fake_to_mp3(src: Path, dst: Path) -> None:
        normalize_calls.append((src.read_bytes(), dst.suffix))
        dst.write_bytes(b"normalized-44100-stereo")

    monkeypatch.setattr(xkiro_provider, "_to_mp3", fake_to_mp3)
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 2.0)
    monkeypatch.setattr(xkiro_provider, "_concat_audio", lambda _parts, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(xkiro_provider, "_silence_mp3", lambda _seconds, output: output.write_bytes(b"silence"))

    await XkiroVoiceProvider().synthesise(_script(), tmp_path)

    assert normalize_calls, "xKiro phải chuẩn hoá mỗi mảnh audio thô qua _to_mp3 trước khi concat"
    for src_bytes, dst_suffix in normalize_calls:
        assert src_bytes == b"raw-24khz-mono"
        assert dst_suffix == ".mp3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_removes_stage_direction_and_preserves_pacing(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider
    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    requests: list[str] = []
    monkeypatch.setattr(XkiroVoiceProvider, "_request_audio", lambda _self, text: requests.append(text) or b"new")
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 2.0)
    monkeypatch.setattr(xkiro_provider, "_to_mp3", lambda src, dst: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(xkiro_provider, "_concat_audio", lambda _parts, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(xkiro_provider, "_silence_mp3", lambda _seconds, output: output.write_bytes(b"silence"))
    script = _script()
    script = Script(**{**vars(script), "segments": (Segment(caption="c", narration="Cú hình tiếp theo: Một, hai."),)})

    await XkiroVoiceProvider().synthesise(script, tmp_path)

    assert requests == ["Một,", "hai."]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_reuses_only_matching_cache(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider
    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    provider = XkiroVoiceProvider()
    cached = provider._segment_path(_script(), _script().segments[0], 0, tmp_path)
    cached.write_bytes(b"cached")
    requests: list[str] = []
    monkeypatch.setattr(XkiroVoiceProvider, "_request_audio", lambda _self, text: requests.append(text) or b"new")
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 2.0)
    monkeypatch.setattr(xkiro_provider, "_to_mp3", lambda src, dst: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(xkiro_provider, "_concat_audio", lambda _parts, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(xkiro_provider, "_silence_mp3", lambda _seconds, output: output.write_bytes(b"silence"))

    voiceover = await provider.synthesise(_script(), tmp_path)

    assert requests == ["Đây là câu thứ hai."]
    assert voiceover.segments[0].audio_path == cached


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_splits_long_clause_before_request(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider
    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "xkiro_max_chars_per_piece", 32, raising=False)
    requests: list[str] = []
    monkeypatch.setattr(XkiroVoiceProvider, "_request_audio", lambda _self, text: requests.append(text) or b"new")
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 2.0)
    monkeypatch.setattr(xkiro_provider, "_to_mp3", lambda src, dst: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(xkiro_provider, "_concat_audio", lambda _parts, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(xkiro_provider, "_silence_mp3", lambda _seconds, output: output.write_bytes(b"silence"))
    script = Script(
        topic="t",
        title="xKiro demo",
        description="d",
        segments=(
            Segment(
                caption="c",
                narration="Đây là một câu rất dài không có dấu phẩy nhưng cần được chia nhỏ để xKiro đọc rõ ràng hơn và không nuốt mất phần cuối",
            ),
        ),
    )

    await XkiroVoiceProvider().synthesise(script, tmp_path)

    assert len(requests) > 1
    assert all(len(part) <= 32 for part in requests)
    assert " ".join(requests).replace("  ", " ") == (
        "Đây là một câu rất dài không có dấu phẩy nhưng cần được chia nhỏ để "
        "xKiro đọc rõ ràng hơn và không nuốt mất phần cuối"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_xkiro_provider_pads_a_small_runtime_shortfall(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider
    from ytb_pipeline.providers.voice import xkiro_provider

    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)
    monkeypatch.setattr(XkiroVoiceProvider, "_request_audio", lambda _self, _text: b"new")
    monkeypatch.setattr(xkiro_provider, "_probe_duration", lambda _path: 59.0)
    monkeypatch.setattr(xkiro_provider, "_to_mp3", lambda src, dst: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(xkiro_provider, "_concat_audio", lambda _parts, output: output.write_bytes(b"combined"))
    monkeypatch.setattr(xkiro_provider, "_silence_mp3", lambda _seconds, output: output.write_bytes(b"silence"))
    padded: list[tuple[Path, float]] = []
    monkeypatch.setattr(xkiro_provider, "_pad_audio", lambda path, seconds: padded.append((path, seconds)))
    script = Script(topic="t", title="Short sát ngưỡng", description="d", segments=(Segment(caption="c", narration="Một câu."),))

    voiceover = await XkiroVoiceProvider().synthesise(script, tmp_path)

    assert padded == [(voiceover.segments[-1].audio_path, 1.0)]
    assert voiceover.duration_sec == 60.0


@pytest.mark.unit
def test_split_long_clause_never_orphans_a_tail_fragment():
    """Đo được trên xKiro: mảnh cụt do cắt tham lam làm TTS đọc ra nội dung khác.

    Câu "Tách cà phê nguội rồi mà cậu chưa uống một ngụm nào." dài 52 ký tự,
    chỉ hơn trần 48 một chút. Cắt tham lam cho ra 47 + "nào." — và CẢ HAI nửa
    đều hỏng: nửa đầu nghe ra "Cảm ơn các bạn đã theo dõi và hẹn gặp lại."
    (0.21), mảnh "nào." nghe ra "Hãy đăng ký kênh..." (0.08). Đọc nguyên câu
    thì đạt 0.98. Cắt cân bằng giữ mỗi mảnh đủ dài để còn là lời nói.
    """
    from ytb_pipeline.providers.voice.xkiro_provider import _split_long_clause

    text = "Tách cà phê nguội rồi mà cậu chưa uống một ngụm nào."
    chunks = _split_long_clause(text, max_chars=48)

    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")
    assert all(len(chunk) <= 48 for chunk in chunks), chunks
    assert min(len(chunk) for chunk in chunks) >= 12, chunks


@pytest.mark.unit
def test_split_long_clause_keeps_short_text_whole():
    from ytb_pipeline.providers.voice.xkiro_provider import _split_long_clause

    assert _split_long_clause("Em gọi.", max_chars=48) == ["Em gọi."]


@pytest.mark.unit
def test_split_long_clause_balances_every_length_near_the_cap():
    """Không được có mảnh cụt ở BẤT KỲ độ dài nào, không chỉ ở ca đã gặp."""
    from ytb_pipeline.providers.voice.xkiro_provider import _split_long_clause

    words = "cà phê nguội rồi mà cậu chưa uống một ngụm nào thêm lần nữa sáng nay".split()
    for count in range(2, len(words) + 1):
        text = " ".join(words[:count]) + "."
        chunks = _split_long_clause(text, max_chars=48)
        assert all(len(chunk) <= 48 for chunk in chunks), (text, chunks)
        if len(chunks) > 1:
            assert min(len(chunk) for chunk in chunks) >= 12, (text, chunks)
