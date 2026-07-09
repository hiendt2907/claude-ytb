"""Test voiceover — mock edge_tts.Communicate + subprocess (ffmpeg/ffprobe), không gọi thật."""

from __future__ import annotations

import json

import pytest

from ytb_pipeline.content import voiceover as vo
from ytb_pipeline.content.models import Script, ScriptSegment


def _script() -> Script:
    return Script(
        title="Thói quen dậy sớm",
        description="",
        segments=(
            ScriptSegment(narration="Xin chào, hôm nay ta nói về thói quen.", visual_keywords=("sunrise",)),
            ScriptSegment(narration="Dậy sớm giúp bạn tập trung hơn.", visual_keywords=("morning walk",)),
        ),
    )


def test_split_for_pacing_sentence_gets_sentence_pause():
    pieces = vo._split_for_pacing("Xin chào. Tạm biệt.")
    assert pieces[0] == ("Xin chào.", vo.SENTENCE_PAUSE_SEC)
    assert pieces[-1][1] == 0.0


def test_split_for_pacing_empty_returns_empty():
    assert vo._split_for_pacing("") == []


def test_prepare_narration_collapses_whitespace():
    assert vo._prepare_narration("  a   b  \n c ") == "a b c"


def test_slugify_strips_accents_and_spaces():
    assert vo._slugify("Thói Quen Dậy Sớm!") == "thoi-quen-day-som"


@pytest.fixture(autouse=True)
def _fake_edge_and_ffmpeg(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            self.text = text

        async def save(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"fake-audio")

    monkeypatch.setattr(vo.edge_tts, "Communicate", FakeCommunicate)

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""

        # ffprobe: trả duration cố định qua stdout JSON
        if cmd[0] == "ffprobe":
            Result.stdout = json.dumps({"format": {"duration": "1.5"}})
        else:
            # ffmpeg -y ... <output cuối cùng> — tạo file rỗng để .exists() = True
            out = cmd[-1]
            from pathlib import Path

            Path(out).write_bytes(b"fake")
        return Result()

    monkeypatch.setattr(vo.subprocess, "run", fake_run)


def test_synthesize_produces_combined_voice_and_segment_durations(tmp_path):
    script = _script()

    result = vo.synthesize(script, tmp_path, slug="test-slug")

    assert result.title == "Thói quen dậy sớm"
    assert len(result.segments) == 2
    assert all(s.duration_sec == pytest.approx(1.5) for s in result.segments)
    assert result.duration_sec == pytest.approx(3.0)
    assert result.audio_path == tmp_path / "test-slug_voice.mp3"
    assert result.segments[0].visual_keywords == ("sunrise",)


def test_synthesize_resumes_when_segment_audio_already_exists(tmp_path, monkeypatch):
    script = _script()
    existing = vo._segment_audio_path(tmp_path, "test-slug", 0)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"already-there")

    calls = []
    original_work_target = vo._synth_segment

    def spy(text, out_mp3, **kwargs):
        calls.append(out_mp3)
        return original_work_target(text, out_mp3, **kwargs)

    monkeypatch.setattr(vo, "_synth_segment", spy)

    vo.synthesize(script, tmp_path, slug="test-slug")

    assert existing not in calls


def test_synthesize_skips_trailing_pause_only_on_last_segment(tmp_path, monkeypatch):
    """assembler/duration.py (VoiceSilenceDurationStrategy) đếm N khoảng lặng
    giữa N cảnh — nếu đoạn CUỐI cũng có khoảng lặng cuối, ghép audio sẽ tạo ra
    N+1 khoảng lặng, đếm lệch so với số cảnh (bug thật đã gặp khi test UI)."""
    script = _script()  # 2 segments

    calls: dict[str, bool] = {}
    original = vo._synth_segment

    def spy(text, out_mp3, *, trailing_pause=True):
        calls[text] = trailing_pause
        return original(text, out_mp3, trailing_pause=trailing_pause)

    monkeypatch.setattr(vo, "_synth_segment", spy)

    vo.synthesize(script, tmp_path, slug="test-slug")

    assert calls[script.segments[0].narration] is True
    assert calls[script.segments[1].narration] is False
