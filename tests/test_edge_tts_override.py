"""Regression coverage for explicit, opt-in Edge narration pacing."""

import pytest
from pydantic import ValidationError

from ytb_pipeline.config.settings import Settings
from ytb_pipeline.pkg.models import Script, Segment
from ytb_pipeline.voiceover import tts


async def test_edge_tts_uses_explicit_rate_override(monkeypatch, tmp_path):
    calls = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            calls.append((text, voice, kwargs))

        async def save(self, path):
            tmp_path.joinpath("saved").write_text(path, encoding="utf-8")

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(tts.settings, "edge_tts_rate_override", "+40%", raising=False)

    await tts._tts("Xin chào", "vi-VN-NamMinhNeural", tmp_path / "out.mp3", tts.VOICE_ENTERTAINMENT)

    assert calls[0][2]["rate"] == "+40%"
    assert calls[0][2]["pitch"] == tts.VOICE_ENTERTAINMENT.edge_pitch


def test_edge_rate_override_rejects_invalid_format():
    with pytest.raises(ValidationError, match="EDGE_TTS_RATE_OVERRIDE"):
        Settings(_env_file=None, edge_tts_rate_override="faster")


def test_edge_segment_cache_key_changes_for_explicit_rate_override(monkeypatch):
    monkeypatch.setattr(tts.settings, "tts_provider", "edge")
    monkeypatch.setattr(tts.settings, "edge_tts_rate_override", "", raising=False)
    default = tts._segment_audio_path("demo", tts.VOICE_KNOWLEDGE, 0, narration="nội dung", voice="vi-VN")

    monkeypatch.setattr(tts.settings, "edge_tts_rate_override", "+40%", raising=False)
    slower = tts._segment_audio_path("demo", tts.VOICE_KNOWLEDGE, 0, narration="nội dung", voice="vi-VN")

    assert slower != default
    assert "edgep40" in slower.name


def test_parallel_edge_workers_receive_each_segments_own_profile(monkeypatch, tmp_path):
    received_profiles = []
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(tts.settings, "edge_tts_workers", 1)
    monkeypatch.setattr(
        tts,
        "_synth_segment",
        lambda text, voice, path, profile: received_profiles.append(profile.name) or path.write_bytes(b"x"),
    )
    monkeypatch.setattr(tts, "_probe_duration", lambda _path: 1.0)
    script = Script(
        topic="t", title="Profile Per Segment", description="d", tags=(),
        segments=(
            Segment(caption="c0", narration="n0", hook=True),
            Segment(caption="c1", narration="n1"),
            Segment(caption="c2", narration="n2"),
        ),
    )

    tts._synth_all_edge_parallel(script, "slug", tts.VOICE_KNOWLEDGE)

    assert received_profiles == ["hook", "knowledge", "conclusion"]
