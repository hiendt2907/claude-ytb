from __future__ import annotations


def test_segment_cache_key_changes_when_narration_changes(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.voiceover import tts

    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(settings, "tts_provider", "xkiro")
    profile = tts.VOICE_KNOWLEDGE

    first = tts._segment_audio_path("same-title", profile, 0, narration="Nội dung thứ nhất.", voice="vi-VN")
    second = tts._segment_audio_path("same-title", profile, 0, narration="Nội dung đã thay đổi.", voice="vi-VN")

    assert first != second


def test_segment_cache_key_changes_when_provider_changes(monkeypatch, tmp_path):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.voiceover import tts

    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    profile = tts.VOICE_KNOWLEDGE
    monkeypatch.setattr(settings, "tts_provider", "xkiro")
    xkiro = tts._segment_audio_path("same-title", profile, 0, narration="Nội dung.", voice="vi-VN")
    monkeypatch.setattr(settings, "tts_provider", "edge")
    edge = tts._segment_audio_path("same-title", profile, 0, narration="Nội dung.", voice="vi-VN")

    assert xkiro != edge
