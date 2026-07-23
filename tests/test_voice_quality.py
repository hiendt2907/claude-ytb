"""Local-first regression tests for the post-TTS audio quality report."""

from __future__ import annotations

from pathlib import Path

from ytb_pipeline.pkg.models import Segment, Voiceover
from ytb_pipeline.voiceover import quality


def _voiceover(tmp_path: Path, *, narration: str = "Xin chào bạn.", target_minutes: float | None = None) -> Voiceover:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio-one")
    segment = Segment(caption="c", narration=narration, audio_path=audio, duration_sec=60.0)
    return Voiceover(
        topic="topic",
        title="title",
        description="description",
        target_minutes=target_minutes,
        segments=(segment,),
        audio_path=audio,
        duration_sec=60.0,
    )


class _UnavailableStt:
    name = "local-test"

    def availability(self) -> quality.SttAvailability:
        return quality.SttAvailability(False, "local-test", "binary is not installed")

    def transcribe(self, audio_path: Path) -> str:  # pragma: no cover - must never run
        raise AssertionError(f"STT must not run for {audio_path}")


class _TranscriptStt:
    name = "local-test"

    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls = 0

    def availability(self) -> quality.SttAvailability:
        return quality.SttAvailability(True, "local-test")

    def transcribe(self, audio_path: Path) -> str:
        self.calls += 1
        return self.transcript


def test_cache_key_changes_when_audio_or_script_changes(tmp_path):
    voiceover = _voiceover(tmp_path)
    first = quality.quality_cache_key(voiceover)

    voiceover.audio_path.write_bytes(b"audio-two")
    assert quality.quality_cache_key(voiceover) != first

    changed_script = _voiceover(tmp_path, narration="Một kịch bản khác.")
    assert quality.quality_cache_key(changed_script) != first


def test_gate_reports_duration_deviation_and_stt_unavailable(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path, target_minutes=2.0)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_UnavailableStt(),
        duration_tolerance_sec=15.0,
    )

    assert result.passed is False
    assert [issue.code for issue in result.issues] == ["DURATION_TARGET_DEVIATION", "STT_UNAVAILABLE"]
    assert result.repair_payload["DURATION_TARGET_DEVIATION"]["target"] == "script.target_minutes"
    assert result.repair_payload["STT_UNAVAILABLE"]["action"] == "configure_local_stt"


def test_gate_compares_transcript_and_detects_repeated_phrase(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path, narration="Bạn có thể bắt đầu từ việc nhỏ hôm nay.")
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {"mean_volume_db": -19.0})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_TranscriptStt("Bạn có thể bắt đầu từ việc nhỏ hôm nay. Bạn có thể bắt đầu từ việc nhỏ hôm nay."),
    )

    assert result.passed is False
    assert [issue.code for issue in result.issues] == ["TRANSCRIPT_MISMATCH", "TRANSCRIPT_REPEAT"]
    assert result.metrics["prosody"]["mean_volume_db"] == -19.0
    assert result.repair_payload["TRANSCRIPT_REPEAT"]["target"] == "audio_or_segment"


def test_gate_honours_transcript_similarity_threshold(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path, narration="Kịch bản gốc có nhiều từ.")
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_TranscriptStt("Bản đọc khác hoàn toàn."),
        transcript_similarity_threshold=0.0,
    )

    assert result.passed is True
    assert result.issues == ()


def test_gate_reports_missing_audio_without_throwing(tmp_path):
    voiceover = _voiceover(tmp_path)
    voiceover.audio_path.unlink()

    result = quality.run_audio_quality_gate(voiceover, stt_adapter=_UnavailableStt())

    assert result.passed is False
    assert result.issues[0].code == "AUDIO_MISSING"


def test_local_audio_analysis_exposes_silence_and_volume(monkeypatch, tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(quality.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(
        quality.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {
            "stderr": "mean_volume: -20.1 dB\\nmax_volume: -1.0 dB\\nsilence_duration: 2.5",
        })(),
    )

    assert quality.analyze_local_audio(audio, 10.0) == {
        "silence_duration_sec": 2.5,
        "silence_ratio": 0.25,
        "mean_volume_db": -20.1,
        "max_volume_db": -1.0,
    }


def test_gate_cache_reuses_report_without_running_stt(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})
    stt = _TranscriptStt("Xin chào bạn.")

    first = quality.run_audio_quality_gate(voiceover, stt_adapter=stt, cache_dir=tmp_path / "cache")
    second = quality.run_audio_quality_gate(voiceover, stt_adapter=stt, cache_dir=tmp_path / "cache")

    assert first.cached is False
    assert second.cached is True
    assert stt.calls == 1


def test_faster_whisper_adapter_reports_missing_dependency_without_importing_it(monkeypatch):
    adapter = quality.FasterWhisperSttAdapter(module_available=lambda _name: False)

    assert adapter.availability() == quality.SttAvailability(
        False,
        "faster-whisper",
        "optional Python package 'faster_whisper' is not installed",
    )


def test_faster_whisper_adapter_cache_context_changes_when_local_model_changes(tmp_path):
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    model_file = model_dir / "model.bin"
    model_file.write_bytes(b"first-model")
    adapter = quality.FasterWhisperSttAdapter(
        model_path=model_dir,
        module_available=lambda _name: True,
    )

    first = adapter.cache_context()
    model_file.write_bytes(b"second-model")

    assert adapter.cache_context() != first


def test_faster_whisper_adapter_rejects_a_file_not_a_local_model_directory(tmp_path):
    model_file = tmp_path / "model.bin"
    model_file.write_bytes(b"not-a-directory")
    adapter = quality.FasterWhisperSttAdapter(
        model_path=model_file,
        module_available=lambda _name: True,
    )

    assert adapter.availability() == quality.SttAvailability(
        False,
        "faster-whisper",
        "local STT model path is not a directory: " + str(model_file),
    )


def test_cache_key_changes_when_quality_policy_or_local_stt_context_changes(tmp_path):
    voiceover = _voiceover(tmp_path)
    base = quality.quality_cache_key(
        voiceover,
        cache_context={"stt": {"available": False}, "thresholds": {"similarity": 0.94}},
    )

    assert quality.quality_cache_key(
        voiceover,
        cache_context={"stt": {"available": True}, "thresholds": {"similarity": 0.94}},
    ) != base
    assert quality.quality_cache_key(
        voiceover,
        cache_context={"stt": {"available": False}, "thresholds": {"similarity": 0.90}},
    ) != base


def test_audio_gate_cache_misses_when_policy_context_changes(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})
    stt = _TranscriptStt("Xin chào bạn.")

    first = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=stt,
        cache_dir=tmp_path / "cache",
        transcript_similarity_threshold=0.94,
    )
    second = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=stt,
        cache_dir=tmp_path / "cache",
        transcript_similarity_threshold=0.90,
    )

    assert first.cached is False
    assert second.cached is False
    assert stt.calls == 2


def test_settings_exposes_an_opt_in_local_stt_model_path(tmp_path):
    from ytb_pipeline.config.settings import Settings

    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    settings = Settings(_env_file=None, quality_stt_model_path=model_dir)

    assert settings.quality_stt_model_path == model_dir


def test_settings_treats_blank_local_stt_model_path_as_disabled(monkeypatch):
    from ytb_pipeline.config.settings import Settings

    monkeypatch.setenv("QUALITY_STT_MODEL_PATH", "   ")

    settings = Settings(_env_file=None)

    assert settings.quality_stt_model_path is None
