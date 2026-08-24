"""Test resume voiceover (edge-tts): segment đã có audio hợp lệ -> bỏ qua, không gọi lại TTS."""

from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.pkg.models import Script, Segment
from ytb_pipeline.voiceover import tts


@pytest.fixture(autouse=True)
def _isolate_audio_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(settings, "tts_provider", "edge")
    yield


def _script() -> Script:
    return Script(
        topic="t", title="Video Demo", description="d", voice="vi-VN-NamMinhNeural",
        segments=(
            Segment(caption="c1", narration="đoạn một"),
            Segment(caption="c2", narration="đoạn hai"),
        ),
    )


@pytest.mark.unit
def test_synthesize_skips_segment_with_existing_valid_audio(monkeypatch, tmp_path):
    script = _script()
    slug = tts._slugify(script.title)
    profile = tts._voice_profile(script)
    seg0_profile = tts._segment_profile(script.segments[0], profile, 0, len(script.segments))
    seg1_profile = tts._segment_profile(script.segments[1], profile, 1, len(script.segments))
    seg0_path = tts._segment_audio_path(slug, seg0_profile, 0, narration=script.segments[0].narration, voice=script.voice)
    seg0_path.write_bytes(b"fake-but-present")  # nội dung không quan trọng, ffprobe bị mock

    synth_calls = []
    monkeypatch.setattr(tts, "_synth_segment", lambda text, voice, out, profile=None: synth_calls.append(out))

    def _fake_probe(path: Path) -> float:
        if path == seg0_path:
            return 3.5  # segment 0 coi như đã render hợp lệ ở lần chạy trước
        return 2.0

    monkeypatch.setattr(tts, "_probe_duration", _fake_probe)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out: None)

    tts.synthesize(script)

    # Segment 0 đã có audio hợp lệ -> KHÔNG gọi lại _synth_segment cho nó.
    assert seg0_path not in synth_calls
    # Segment 1 chưa có file -> phải synth.
    assert tts._segment_audio_path(slug, seg1_profile, 1, narration=script.segments[1].narration, voice=script.voice) in synth_calls


@pytest.mark.unit
def test_synthesize_resynths_segment_with_corrupt_existing_audio(monkeypatch, tmp_path):
    script = _script()
    slug = tts._slugify(script.title)
    profile = tts._voice_profile(script)
    seg0_profile = tts._segment_profile(script.segments[0], profile, 0, len(script.segments))
    seg0_path = tts._segment_audio_path(slug, seg0_profile, 0, narration=script.segments[0].narration, voice=script.voice)
    seg0_path.write_bytes(b"corrupt")

    synth_calls = []
    monkeypatch.setattr(tts, "_synth_segment", lambda text, voice, out, profile=None: synth_calls.append(out))

    import subprocess

    probe_calls = []

    def _fake_probe(path: Path) -> float:
        probe_calls.append(path)
        # Lần đầu kiểm tra file cũ (corrupt) -> raise, coi như chưa xong -> resynth.
        # Lần sau (sau khi resynth) -> trả duration thật bình thường.
        if path == seg0_path and probe_calls.count(path) == 1:
            raise subprocess.CalledProcessError(1, "ffprobe")
        return 2.0

    monkeypatch.setattr(tts, "_probe_duration", _fake_probe)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out: None)

    tts.synthesize(script)

    # File cũ hỏng -> coi như chưa xong -> phải resynth.
    assert seg0_path in synth_calls


@pytest.mark.unit
def test_synthesize_f5_skips_batch_when_all_segments_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "tts_provider", "f5")
    script = _script()
    slug = tts._slugify(script.title)
    profile = tts._voice_profile(script)
    seg_profiles = [
        tts._segment_profile(seg, profile, i, len(script.segments))
        for i, seg in enumerate(script.segments)
    ]
    for i in range(len(script.segments)):
        tts._segment_audio_path(slug, seg_profiles[i], i, narration=script.segments[i].narration, voice=script.voice).write_bytes(b"cached")

    def _fake_probe(path: Path) -> float:
        if path.name.endswith(".mp3"):
            return 4.0
        return 0.0

    monkeypatch.setattr(tts, "_probe_duration", _fake_probe)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out: None)

    # Resume từ cache F5 không được phép nạp model hay gửi bất kỳ job TTS nào.
    from ytb_pipeline.voiceover import f5_provider

    monkeypatch.setattr(
        f5_provider,
        "run_batch",
        lambda jobs: pytest.fail(f"F5 không được gọi lại khi đã có cache: {jobs}"),
    )

    voiceover = tts.synthesize(script)

    assert [s.audio_path for s in voiceover.segments] == [
        tts._segment_audio_path(slug, seg_profiles[0], 0, narration=script.segments[0].narration, voice=script.voice),
        tts._segment_audio_path(slug, seg_profiles[1], 1, narration=script.segments[1].narration, voice=script.voice),
    ]
    assert voiceover.duration_sec == 8.0


@pytest.mark.unit
def test_tiny_runtime_heal_pads_final_segment_before_combining(monkeypatch, tmp_path):
    script = _script()
    paths = [tmp_path / "first.mp3", tmp_path / "last.mp3"]
    for path in paths:
        path.write_bytes(b"audio")
    voiced = [
        Segment(caption="c1", narration="đoạn một", audio_path=paths[0], duration_sec=30.0),
        Segment(caption="c2", narration="đoạn hai", audio_path=paths[1], duration_sec=30.0),
    ]
    monkeypatch.setattr(tts, "_synth_all_edge_parallel", lambda *_args: voiced)
    padded: list[tuple[Path, float]] = []
    combined_parts: list[Path] = []
    monkeypatch.setattr(tts, "_pad_audio", lambda path, seconds: padded.append((path, seconds)))
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, _out: combined_parts.extend(parts))

    voiceover = tts.synthesize(script)

    assert padded and padded[0][0] == paths[-1]
    assert voiceover.segments[-1].duration_sec > 30.0
    assert combined_parts[-1] == paths[-1]
