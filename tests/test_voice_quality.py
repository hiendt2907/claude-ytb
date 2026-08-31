"""Local-first regression tests for the post-TTS audio quality report."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from dataclasses import replace
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
    # The gate now measures against the contract's own audio window, the same
    # one the voiceover node enforces, instead of `target_minutes * 60`.  A
    # single-segment Short accepts 60-90s, so the deviation has to be real:
    # 30s is half the contract floor.
    voiceover = _voiceover(tmp_path, target_minutes=2.0)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 30.0)
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


def test_profile_runtime_tolerance_is_shared_by_audio_quality_gate(monkeypatch, tmp_path):
    """A profile-approved audio boundary must not fail a later audio gate.

    `ban-so-6` calibrates a three-second Long tolerance for its multi-voice
    xKiro delivery.  The audio contract accepts 297s for its 300s lower bound;
    audio quality must use that same tolerance rather than reject it against a
    mathematically exact midpoint/window calculation.
    """
    base = _voiceover(tmp_path, target_minutes=5.0)
    segments = tuple(
        replace(base.segments[0], duration_sec=13.5)
        for _ in range(22)
    )
    voiceover = replace(
        base,
        video_type="long",
        segments=segments,
        content_profile_id="ban-so-6",
        content_profile_version="1.6.0",
    )
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 297.1)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_UnavailableStt(),
        duration_tolerance_sec=15.0,
    )

    assert "DURATION_TARGET_DEVIATION" not in [issue.code for issue in result.issues]


def test_gate_requires_local_transcript_when_e2e_requests_it(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_UnavailableStt(),
        require_transcript=True,
    )

    assert result.passed is False
    assert result.issues[0].code == "STT_UNAVAILABLE"
    assert result.issues[0].severity == "error"


def test_gate_compares_transcript_and_detects_repeated_phrase(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path, narration="Bạn có thể bắt đầu từ việc nhỏ hôm nay.")
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {"mean_volume_db": -19.0})

    result = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_TranscriptStt("Bạn có thể bắt đầu từ việc nhỏ hôm nay. Bạn có thể bắt đầu từ việc nhỏ hôm nay."),
    )

    assert result.passed is False
    # The gate now also scores each segment that kept its own audio, so a
    # whole-script mismatch is reported alongside the worst single segment.
    assert [issue.code for issue in result.issues] == [
        "TRANSCRIPT_MISMATCH", "SEGMENT_TRANSCRIPT_MISMATCH", "TRANSCRIPT_REPEAT",
    ]
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


def test_gate_accepts_expected_local_f5_transcription_noise(monkeypatch, tmp_path):
    expected = (
        "Đây là bài kiểm tra giọng đọc tiếng Việt ở nhịp tự nhiên. "
        "Não bộ không cần bị ép chạy quá nhanh để người nghe hiểu được ý chính. "
        "Một câu rõ ràng giúp cả người xem và bộ nhận dạng giọng nói theo kịp nội dung."
    )
    local_stt = (
        "Với là bài kiểm tra giọng đọc tiếng Việt ở nhịp tự nhiên. "
        "Náo bộ không cần bị ép chạy quá nhanh để người nghe hiểu được ý chính. "
        "Một câu giao thẳng giúp cả người xem và bộ nhận dạng sọng nói theo kết nội dung."
    )
    voiceover = _voiceover(tmp_path, narration=expected)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 60.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {})

    result = quality.run_audio_quality_gate(voiceover, stt_adapter=_TranscriptStt(local_stt))

    assert result.passed is True


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
    # One pass over the merged audio plus one per segment that kept its own
    # file: a whole-script average hid a name read as a different word.
    assert stt.calls == 2


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
    # Two gate runs, each transcribing the merged audio and one segment file.
    assert stt.calls == 4


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


def test_settings_exposes_explicit_cpu_int8_stt_runtime_configuration(tmp_path):
    from ytb_pipeline.config.settings import Settings

    settings = Settings(
        _env_file=None,
        quality_stt_model_path=tmp_path,
        quality_stt_device="cpu",
        quality_stt_compute_type="int8",
        quality_stt_cpu_threads=4,
    )

    assert (settings.quality_stt_device, settings.quality_stt_compute_type, settings.quality_stt_cpu_threads) == (
        "cpu", "int8", 4,
    )


def test_settings_rejects_cpu_only_unsupported_stt_compute_types():
    from pydantic import ValidationError
    from ytb_pipeline.config.settings import Settings

    for compute_type in ("float16", "int8_float16"):
        try:
            Settings(_env_file=None, quality_stt_device="cpu", quality_stt_compute_type=compute_type)
        except ValidationError as exc:
            assert "quality_stt_compute_type" in str(exc)
        else:
            raise AssertionError(f"CPU must reject {compute_type}")


def test_faster_whisper_adapter_passes_explicit_cpu_int8_runtime(monkeypatch, tmp_path):
    calls = []

    class FakeModel:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))

        def transcribe(self, _audio_path, **_options):
            return iter((SimpleNamespace(text="xin chào"),)), None

    fake_module = ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    adapter = quality.FasterWhisperSttAdapter(
        model_path=model_dir,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        module_available=lambda _name: True,
    )

    assert adapter.transcribe(tmp_path / "audio.mp3") == "xin chào"
    assert calls == [(str(model_dir), {"device": "cpu", "compute_type": "int8", "cpu_threads": 4})]


def test_faster_whisper_adapter_runtime_changes_cache_context(tmp_path):
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"model")
    cpu_int8 = quality.FasterWhisperSttAdapter(
        model_path=model_dir, device="cpu", compute_type="int8", cpu_threads=4,
        module_available=lambda _name: True,
    )
    cpu_float32 = quality.FasterWhisperSttAdapter(
        model_path=model_dir, device="cpu", compute_type="float32", cpu_threads=4,
        module_available=lambda _name: True,
    )

    assert cpu_int8.cache_context() != cpu_float32.cache_context()


def test_adjacent_repeat_ignores_a_term_defined_across_a_sentence_boundary():
    """Naming a term then defining it is exposition, not a TTS stutter.

    Production 2026-08-24: "...thường được gọi là chi phí chìm. Chi phí chìm là
    tiền, thời gian..." blocked a rendered Long, because the detector strips
    punctuation and so could not tell a sentence boundary from a duplicated
    audio segment — the artifact it exists to catch.
    """
    definition = "Cơ chế đó thường được gọi là chi phí chìm. Chi phí chìm là tiền và thời gian đã bỏ ra."
    stutter = "Cơ chế đó là chi phí chìm chi phí chìm và bạn không lấy lại được."

    assert quality._adjacent_repeated_phrase(definition) is None
    assert quality._adjacent_repeated_phrase(stutter) == "chi phí chìm"


def test_repeat_gate_only_flags_a_repetition_the_script_did_not_author(monkeypatch, tmp_path):
    """The rule exists to catch a duplicated TTS segment, not authored repetition.

    Production 2026-08-24: the script names a term then defines it — "...gọi là
    chi phí chìm. Chi phí chìm là tiền..." — so the audio says it twice on
    purpose.  Judging the transcript alone made Whisper's punctuation the
    arbiter of a TTS defect, and blocked a correct 14-minute Long twice.
    """
    narration = "Cơ chế đó thường được gọi là chi phí chìm. Chi phí chìm là tiền đã bỏ ra."
    voiceover = _voiceover(tmp_path, narration=narration)
    monkeypatch.setattr(quality, "probe_audio_duration", lambda _path: 75.0)
    monkeypatch.setattr(quality, "analyze_local_audio", lambda _path, _duration: {"mean_volume_db": -19.0})

    # Whisper drops the sentence stop, so the transcript looks like a stutter.
    authored = quality.run_audio_quality_gate(
        voiceover,
        stt_adapter=_TranscriptStt(
            "Cơ chế đó thường được gọi là chi phí chìm chi phí chìm là tiền đã bỏ ra."
        ),
        cache_dir=tmp_path / "authored",
    )
    # The same phrase, but the script never said it twice: a real TTS duplicate.
    invented = quality.run_audio_quality_gate(
        _voiceover(tmp_path, narration="Cơ chế đó thường được gọi là chi phí chìm."),
        stt_adapter=_TranscriptStt(
            "Cơ chế đó thường được gọi là chi phí chìm chi phí chìm."
        ),
        cache_dir=tmp_path / "invented",
    )

    assert "TRANSCRIPT_REPEAT" not in [i.code for i in authored.issues]
    assert "TRANSCRIPT_REPEAT" in [i.code for i in invented.issues]


def test_faster_whisper_adapter_does_not_steer_the_decoder_with_a_topic_prompt(
    monkeypatch, tmp_path
):
    """`initial_prompt` lái decoder sang boilerplate YouTube trên chính audio đúng.

    Đo trên 12 segment của một Long đã render, cùng file audio, chỉ đổi
    `initial_prompt`: 2 segment nhảy 0.18 -> 0.99 và 0.13 -> 0.98 khi bỏ prompt,
    10 segment còn lại không đổi, không segment nào kém đi. Với prompt, cả hai
    segment hỏng đều phiên ra đúng một câu "Hãy subscribe cho kênh Ghiền Mì Gõ
    Để không bỏ lỡ những video hấp dẫn" — audio thật đọc đúng lời, đo từng lát
    3 giây đều khớp. Cổng chất lượng audio dùng adapter này để CHẶN publish, nên
    một prompt làm nó báo sai là chặn nhầm bản dựng tốt.
    """
    options = []

    class FakeModel:
        def __init__(self, path, **kwargs):
            pass

        def transcribe(self, _audio_path, **opts):
            options.append(opts)
            return iter((SimpleNamespace(text="xin chào"),)), None

    fake_module = ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    adapter = quality.FasterWhisperSttAdapter(
        model_path=model_dir, module_available=lambda _name: True,
    )

    adapter.transcribe(tmp_path / "audio.mp3")

    assert options, "adapter phải gọi transcribe"
    assert not options[0].get("initial_prompt")
    assert options[0]["language"] == "vi"
