"""Local-first audio/STT quality report for synthesized narration.

This module deliberately does not call an LLM, download an STT model, or alter a
``Voiceover``.  It gives callers a cacheable, structured report they can attach
to their own review or repair workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata
from typing import Any, Callable, Mapping, Protocol

from ..config.settings import settings
from ..content_contract import contract_for

from ..pkg.models import Voiceover

# Bump whenever a check's verdict logic changes, or a cached pass/fail decided
# by the old rules is replayed forever.  v4: the duration target moved from
# `target_minutes * 60` to the contract's own audio window.
# Bump whenever a detector's verdict logic changes, or cached verdicts from the
# old logic keep blocking runs the new logic would pass.  v6: an adjacent
# repeat is only a TTS artifact when the script did not author it.
_CACHE_VERSION = 8  # bumped: profile runtime tolerance is part of duration acceptance
TRANSCRIPT_SIMILARITY_ALGORITHM = "sequence-matcher-no-autojunk-v1"
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;:\n]+")
_WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)
_TIME_SHORTHAND_RE = re.compile(r"\b(\d{1,2})h(\d{1,2})\b")
# Measured with the local Faster-Whisper small model against natural-tempo F5
# Vietnamese speech.  0.82 tolerates predictable ASR spelling substitutions;
# an omitted/mismatched narration remains far below it (the 2x-tempo failure
# was 0.98%).
LOCAL_TTS_TRANSCRIPT_SIMILARITY_THRESHOLD = 0.82
_VIETNAMESE_NUMBERS = {
    "khong": 0,
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "lam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
}


@dataclass(frozen=True)
class SttAvailability:
    """Whether a local-only transcript implementation can run now."""

    available: bool
    adapter: str
    reason: str = ""


class TranscriptAdapter(Protocol):
    """Small local-STT seam; adapters must never invoke a cloud service."""

    name: str

    def availability(self) -> SttAvailability: ...

    def transcribe(self, audio_path: Path) -> str: ...


@dataclass(frozen=True)
class FasterWhisperSttAdapter:
    """Optional faster-whisper adapter, restricted to an existing local model path."""

    model_path: Path | None = None
    device: str | None = None
    compute_type: str | None = None
    cpu_threads: int | None = None
    module_available: Callable[[str], bool] | None = None
    name: str = "faster-whisper"

    def availability(self) -> SttAvailability:
        finder = self.module_available or _module_available
        if not finder("faster_whisper"):
            return SttAvailability(
                False,
                self.name,
                "optional Python package 'faster_whisper' is not installed",
            )
        if self.model_path is None:
            return SttAvailability(False, self.name, "local STT model path is not configured")
        if not self.model_path.exists():
            return SttAvailability(False, self.name, f"local STT model is missing: {self.model_path}")
        if not self.model_path.is_dir():
            return SttAvailability(False, self.name, f"local STT model path is not a directory: {self.model_path}")
        return SttAvailability(True, self.name)

    def transcribe(self, audio_path: Path) -> str:
        status = self.availability()
        if not status.available:
            raise RuntimeError(status.reason)
        # Import happens only after dependency and local-model checks. Passing a
        # filesystem path prevents faster-whisper from resolving a remote model.
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        model_kwargs: dict[str, object] = {}
        if self.device is not None:
            model_kwargs["device"] = self.device
        if self.compute_type is not None:
            model_kwargs["compute_type"] = self.compute_type
        if self.cpu_threads is not None:
            model_kwargs["cpu_threads"] = self.cpu_threads
        model = WhisperModel(str(self.model_path), **model_kwargs)
        # KHÔNG đặt `initial_prompt`.  Prompt chủ đề lái decoder sang boilerplate
        # YouTube: đo trên 12 segment của một Long đã render, cùng file audio,
        # chỉ đổi prompt — 2 segment nhảy 0.18 -> 0.99 và 0.13 -> 0.98 khi bỏ
        # prompt, 10 segment không đổi, không segment nào kém đi.  Hai segment
        # hỏng đều phiên ra đúng một câu "Hãy subscribe cho kênh Ghiền Mì Gõ..."
        # trong khi audio thật đọc đúng lời (cắt từng lát 3 giây đều khớp).
        # `language="vi"` đã ghim ngôn ngữ; prompt không thêm gì ngoài rủi ro.
        options = {
            "language": "vi",
            "vad_filter": True,
            "condition_on_previous_text": False,
        }
        segments, _info = model.transcribe(str(audio_path), **options)
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        # Very quiet or heavily paused narration can be removed entirely by
        # VAD. Retry the same local model without VAD before declaring a real
        # transcript mismatch; this is deterministic and never calls an LLM.
        if not text:
            options["vad_filter"] = False
            segments, _info = model.transcribe(str(audio_path), **options)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return text

    def cache_context(self) -> dict[str, object]:
        """Local model identity for cache invalidation, without reading model bytes.

        The model path is always a filesystem path.  A compact manifest catches
        the usual in-place model/config updates while keeping per-video cache
        lookup cheap for multi-gigabyte local models.
        """
        status = self.availability()
        return {
            "adapter": self.name,
            "available": status.available,
            "model": _local_model_identity(self.model_path),
            "runtime": {
                "device": self.device,
                "compute_type": self.compute_type,
                "cpu_threads": self.cpu_threads,
            },
            "package_version": _package_version("faster-whisper") if status.available else "",
        }


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    repair: dict[str, str]


@dataclass(frozen=True)
class AudioQualityResult:
    """Serializable gate result.  Warnings do not block a downstream render."""

    passed: bool
    cache_key: str
    cached: bool
    issues: tuple[QualityIssue, ...]
    metrics: dict[str, object]
    repair_payload: dict[str, dict[str, str]]


def quality_cache_key(
    voiceover: Voiceover,
    *,
    cache_context: Mapping[str, object] | None = None,
) -> str:
    """Content checksum for exactly one audio artifact and its expected narration."""
    audio_digest = _sha256_file(voiceover.audio_path)
    script_payload = {
        "target_minutes": voiceover.target_minutes,
        "narration": [segment.narration for segment in voiceover.segments],
        "cache_context": dict(cache_context or {}),
    }
    script_digest = hashlib.sha256(
        json.dumps(script_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return hashlib.sha256(f"audio:{audio_digest}|script:{script_digest}|v:{_CACHE_VERSION}".encode("utf-8")).hexdigest()


def run_audio_quality_gate(
    voiceover: Voiceover,
    *,
    stt_adapter: TranscriptAdapter | None = None,
    cache_dir: Path | None = None,
    duration_tolerance_sec: float = 30.0,
    transcript_similarity_threshold: float = LOCAL_TTS_TRANSCRIPT_SIMILARITY_THRESHOLD,
    max_silence_ratio: float = 0.65,
    require_transcript: bool = False,
) -> AudioQualityResult:
    """Analyze an audio file with deterministic local checks and optional local STT.

    ``STT_UNAVAILABLE`` is deliberately a warning: installation is optional and
    a missing local dependency must not make a cloud call or crash a batch.
    """
    if duration_tolerance_sec < 0:
        raise ValueError("duration_tolerance_sec must be >= 0")
    if not 0 <= transcript_similarity_threshold <= 1:
        raise ValueError("transcript_similarity_threshold must be between 0 and 1")

    adapter = stt_adapter or FasterWhisperSttAdapter()
    availability = adapter.availability()
    cache_context = _gate_cache_context(
        adapter,
        availability,
        duration_tolerance_sec=duration_tolerance_sec,
        transcript_similarity_threshold=transcript_similarity_threshold,
        max_silence_ratio=max_silence_ratio,
        require_transcript=require_transcript,
    )
    cache_key = quality_cache_key(voiceover, cache_context=cache_context)
    cached = _load_cached(cache_dir, cache_key, cache_context=cache_context)
    if cached is not None:
        return replace(cached, cached=True)

    issues: list[QualityIssue] = []
    audio_path = voiceover.audio_path
    metrics: dict[str, object] = {"duration": {}, "prosody": {}}
    if audio_path is None or not audio_path.is_file():
        issues.append(_issue(
            "AUDIO_MISSING", "error", "Audio voiceover không tồn tại để kiểm tra.",
            target="audio_path", action="render_or_restore_audio",
        ))
        return _finish(cache_dir, cache_key, issues, metrics, cache_context=cache_context)

    actual_duration = probe_audio_duration(audio_path)
    target_duration = _target_duration(voiceover)
    metrics["duration"] = {
        "actual_sec": actual_duration,
        "target_sec": target_duration,
        "deviation_sec": abs(actual_duration - target_duration) if target_duration is not None else None,
    }
    if actual_duration <= 0:
        issues.append(_issue(
            "AUDIO_DURATION_UNAVAILABLE", "error", "Không đo được thời lượng audio bằng công cụ local.",
            target="audio_path", action="repair_or_reencode_audio",
        ))
    elif target_duration is not None and abs(actual_duration - target_duration) > _duration_tolerance(
        voiceover, duration_tolerance_sec
    ):
        issues.append(_issue(
            "DURATION_TARGET_DEVIATION", "error",
            f"Audio lệch mục tiêu {abs(actual_duration - target_duration):.1f}s (audio={actual_duration:.1f}s, target={target_duration:.1f}s).",
            target="script.target_minutes", action="adjust_narration_or_tts_pacing",
        ))

    local_metrics = analyze_local_audio(audio_path, actual_duration)
    metrics["prosody"] = local_metrics
    silence_ratio = _number(local_metrics.get("silence_ratio"))
    if silence_ratio is not None and silence_ratio > max_silence_ratio:
        issues.append(_issue(
            "EXCESSIVE_SILENCE", "error", f"Audio có silence ratio {silence_ratio:.0%}.",
            target="audio_or_segment", action="trim_silence_or_resynthesise_segment",
        ))
    mean_volume = _number(local_metrics.get("mean_volume_db"))
    if mean_volume is not None and mean_volume < -35.0:
        issues.append(_issue(
            "LOW_VOLUME", "error", f"Mức âm lượng trung bình quá nhỏ: {mean_volume:.1f} dB.",
            target="audio_or_segment", action="increase_gain_or_resynthesise_segment",
        ))

    _append_transcript_issues(
        issues,
        metrics,
        voiceover,
        audio_path,
        adapter,
        availability,
        similarity_threshold=transcript_similarity_threshold,
        require_transcript=require_transcript,
    )
    return _finish(cache_dir, cache_key, issues, metrics, cache_context=cache_context)


def probe_audio_duration(audio_path: Path) -> float:
    """Return duration from ffprobe, or zero when the local binary cannot inspect it."""
    if shutil.which("ffprobe") is None:
        return 0.0
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio_path)],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(proc.stdout).get("format", {}).get("duration") or 0.0)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return 0.0


def analyze_local_audio(audio_path: Path, duration_sec: float) -> dict[str, object]:
    """Return silence and volume metadata when ffmpeg is available; otherwise empty."""
    if duration_sec <= 0 or shutil.which("ffmpeg") is None:
        return {}
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path), "-af",
                "volumedetect,silencedetect=noise=-38dB:d=0.5", "-f", "null", "-",
            ],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return {}
    output = proc.stderr
    silence_sec = sum(float(value) for value in re.findall(r"silence_duration:\s*(\d+(?:\.\d+)?)", output))
    result: dict[str, object] = {
        "silence_duration_sec": silence_sec,
        "silence_ratio": silence_sec / duration_sec,
    }
    for name in ("mean", "max"):
        match = re.search(rf"{name}_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
        if match:
            result[f"{name}_volume_db"] = float(match.group(1))
    return result


def _append_transcript_issues(
    issues: list[QualityIssue],
    metrics: dict[str, object],
    voiceover: Voiceover,
    audio_path: Path,
    adapter: TranscriptAdapter,
    status: SttAvailability,
    *,
    similarity_threshold: float,
    require_transcript: bool,
) -> None:
    transcript_metrics: dict[str, object] = {"adapter": status.adapter, "available": status.available}
    metrics["transcript"] = transcript_metrics
    if not status.available:
        transcript_metrics["reason"] = status.reason
        issues.append(_issue(
            "STT_UNAVAILABLE", "error" if require_transcript else "warning",
            f"Không chạy transcript diff: {status.reason}",
            target="local_stt", action="configure_local_stt",
        ))
        return
    try:
        transcript = adapter.transcribe(audio_path)
    except (OSError, RuntimeError, ValueError) as exc:
        transcript_metrics["reason"] = str(exc)
        issues.append(_issue(
            "STT_FAILED", "error" if require_transcript else "warning",
            f"Local STT không tạo được transcript: {exc}",
            target="local_stt", action="repair_local_stt_setup",
        ))
        return

    expected = " ".join(segment.narration for segment in voiceover.segments)
    similarity = _transcript_similarity(expected, transcript)
    transcript_metrics.update({"similarity": similarity, "transcript_chars": len(transcript)})
    if similarity < similarity_threshold:
        issues.append(_issue(
            "TRANSCRIPT_MISMATCH", "error",
            f"Transcript local khớp script {similarity:.0%}, dưới ngưỡng {similarity_threshold:.0%}.",
            target="audio_or_segment", action="resynthesise_mismatched_segment",
        ))
    _append_segment_transcript_issues(
        issues, transcript_metrics, voiceover, adapter,
        similarity_threshold=similarity_threshold,
    )
    # Only a repetition the script never authored is a TTS artifact.  Comparing
    # against the script keeps Whisper's unreliable punctuation from deciding
    # whether "gọi là X. X là..." was a stutter or a definition.
    repeated = _adjacent_repeated_phrase(transcript)
    if repeated and f"{repeated} {repeated}" in _normalised_words(expected):
        repeated = None
    if repeated:
        transcript_metrics["repeated_phrase"] = repeated
        issues.append(_issue(
            "TRANSCRIPT_REPEAT", "error", f"Transcript lặp liền câu/ý: '{repeated}'.",
            target="audio_or_segment", action="remove_duplicate_tts_segment",
        ))


def _finish(
    cache_dir: Path | None,
    cache_key: str,
    issues: list[QualityIssue],
    metrics: dict[str, object],
    *,
    cache_context: Mapping[str, object],
) -> AudioQualityResult:
    repair_payload = {issue.code: issue.repair for issue in issues}
    result = AudioQualityResult(
        passed=not any(issue.severity == "error" for issue in issues),
        cache_key=cache_key,
        cached=False,
        issues=tuple(issues),
        metrics=metrics,
        repair_payload=repair_payload,
    )
    _save_cached(cache_dir, result, cache_context=cache_context)
    return result


def _load_cached(
    cache_dir: Path | None,
    cache_key: str,
    *,
    cache_context: Mapping[str, object],
) -> AudioQualityResult | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"audio-quality-{cache_key}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_key") != cache_key:
            return None
        # Version-1 cache entries do not carry policy/model context.  Treat
        # them as misses so a newly configured local STT model is actually run.
        if payload.get("cache_context") != dict(cache_context):
            return None
        issues = tuple(QualityIssue(**issue) for issue in payload["issues"])
        return AudioQualityResult(
            passed=bool(payload["passed"]), cache_key=cache_key, cached=False, issues=issues,
            metrics=dict(payload.get("metrics", {})), repair_payload=dict(payload.get("repair_payload", {})),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_cached(
    cache_dir: Path | None,
    result: AudioQualityResult,
    *,
    cache_context: Mapping[str, object],
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"audio-quality-{result.cache_key}.json"
    payload = asdict(result)
    payload["cached"] = False
    payload["cache_context"] = dict(cache_context)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def audio_duration_target_sec(
    video_type: str, *, segment_count: int
) -> tuple[float, float]:
    """Centre and tolerance of the contract's own audio window.

    The voiceover node validates the same file against `audio_runtime_bounds_sec`,
    so this gate must accept exactly that window.  Deriving the centre from
    `target_minutes * 60` instead compared an audio measurement against a
    viewer-domain number that excludes transition loss: for a 36-section Long the
    two windows overlapped by 16s out of 180s, and every script planned to the
    middle of the contract was rejected here after its TTS had been paid for.
    """
    lower, upper = contract_for(video_type).audio_runtime_bounds_sec(
        segment_count=segment_count,
    )
    return (lower + upper) / 2, (upper - lower) / 2


def _target_duration(voiceover: Voiceover) -> float | None:
    segment_count = len(voiceover.segments)
    if segment_count > 0:
        from ..content_profiles import load_content_profile

        profile = (
            load_content_profile(
                voiceover.content_profile_id, version=voiceover.content_profile_version,
            )
            if voiceover.content_profile_version else None
        )
        lower, upper = contract_for(
            voiceover.video_type, profile
        ).audio_runtime_bounds_sec(segment_count=segment_count)
        return (lower + upper) / 2
    if voiceover.target_minutes is not None and voiceover.target_minutes > 0:
        return voiceover.target_minutes * 60
    if voiceover.duration_sec > 0:
        return voiceover.duration_sec
    return None


def _duration_tolerance(voiceover: Voiceover, fallback_sec: float) -> float:
    """Widen a caller's flat tolerance to the contract's accepted audio range.

    A caller may still tighten the gate below the contract, but it must never be
    narrower than what the voiceover node already accepted.  In particular, a
    profile's calibrated runtime tolerance belongs to the same range: otherwise
    an audio file accepted at the voiceover boundary can fail this later quality
    gate by a fraction of a second at the lower edge.
    """
    segment_count = len(voiceover.segments)
    if segment_count <= 0:
        return fallback_sec
    from ..content_profiles import load_content_profile

    profile = (
        load_content_profile(
            voiceover.content_profile_id, version=voiceover.content_profile_version,
        )
        if voiceover.content_profile_version else None
    )
    contract = contract_for(voiceover.video_type, profile)
    lower, upper = contract.audio_runtime_bounds_sec(segment_count=segment_count)
    return max(
        fallback_sec,
        (upper - lower) / 2 + contract.runtime_tolerance_sec,
    )


def _sha256_file(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _gate_cache_context(
    adapter: TranscriptAdapter,
    availability: SttAvailability,
    *,
    duration_tolerance_sec: float,
    transcript_similarity_threshold: float,
    max_silence_ratio: float,
    require_transcript: bool,
) -> dict[str, object]:
    custom_context = getattr(adapter, "cache_context", None)
    stt_context: object
    if callable(custom_context):
        stt_context = custom_context()
    else:
        stt_context = {
            "adapter": availability.adapter,
            "available": availability.available,
            "reason": availability.reason,
        }
    return {
        "version": _CACHE_VERSION,
        "transcript_similarity_algorithm": TRANSCRIPT_SIMILARITY_ALGORITHM,
        "thresholds": {
            "duration_tolerance_sec": duration_tolerance_sec,
            "transcript_similarity_threshold": transcript_similarity_threshold,
            "max_silence_ratio": max_silence_ratio,
            "require_transcript": require_transcript,
        },
        "stt": stt_context,
    }


def _local_model_identity(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"configured": False}
    try:
        resolved = path.expanduser().resolve(strict=False)
        stat = resolved.stat()
    except OSError:
        return {"configured": True, "path": str(path.expanduser()), "exists": False}

    manifest: list[dict[str, object]] = []
    if resolved.is_dir():
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            candidate = resolved / name
            try:
                item = candidate.stat()
            except OSError:
                continue
            manifest.append({"name": name, "size": item.st_size, "mtime_ns": item.st_mtime_ns})
    return {
        "configured": True,
        "path": str(resolved),
        "is_dir": resolved.is_dir(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "manifest": manifest,
    }


def _package_version(distribution: str) -> str:
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:  # noqa: BLE001 - optional dependency metadata is best-effort
        return "unknown"


def _issue(code: str, severity: str, message: str, *, target: str, action: str) -> QualityIssue:
    return QualityIssue(code, severity, message, {"target": target, "action": action})


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _append_segment_transcript_issues(
    issues: list[QualityIssue],
    transcript_metrics: dict[str, object],
    voiceover: Voiceover,
    adapter: TranscriptAdapter,
    *,
    similarity_threshold: float,
) -> None:
    """Fail on the worst-matching segment, not on the script average.

    Production 2026-08-30 read the café owner's name "An" as "Ăn" (0.69) and
    "Sáu giờ mười hai phút," as "6h12 phút" (0.80). Both are far below the
    threshold and both passed, because a whole-script comparison averaged them
    into thousands of correct characters. A viewer hears the line, not the mean.

    Runs only where segments kept their own audio, so it costs nothing extra on
    a voiceover that only has a merged file.
    """
    segments = [
        (index, segment)
        for index, segment in enumerate(voiceover.segments)
        if segment.audio_path and Path(segment.audio_path).is_file()
    ]
    if not segments:
        return
    wanted, heard = [], []
    for _index, segment in segments:
        wanted.append(segment.narration)
        try:
            heard.append(adapter.transcribe(Path(segment.audio_path)))
        except (OSError, RuntimeError, ValueError):
            heard.append("")
    offset, worst = worst_segment_similarity(wanted, heard)
    if offset < 0:
        return
    segment_index = segments[offset][0]
    transcript_metrics.update(
        {"worst_segment_index": segment_index, "worst_segment_similarity": worst}
    )
    if worst < similarity_threshold:
        issues.append(_issue(
            "SEGMENT_TRANSCRIPT_MISMATCH", "error",
            f"Đoạn {segment_index + 1} chỉ khớp {worst:.0%} (ngưỡng "
            f"{similarity_threshold:.0%}): {wanted[offset][:60]!r} nghe thành "
            f"{heard[offset][:60]!r}.",
            target="audio_or_segment", action="resynthesise_mismatched_segment",
        ))


def worst_segment_similarity(
    expected: list[str], heard: list[str]
) -> tuple[int, float]:
    """Return the worst-matching segment and its score.

    Comparing the joined script against the joined transcript averages a local
    fault away: a real round-trip on the published Long read the café owner's
    name "An" as "Ăn" at 0.69 and "Sáu giờ mười hai phút," as "6h12 phút" at
    0.80, and both passed because 5,984 characters of correct narration sat
    around them. A viewer does not hear an average; they hear the line where
    the name is wrong.
    """
    worst_index, worst = -1, 1.0
    for index, (want, got) in enumerate(zip(expected, heard)):
        if not want.strip():
            continue
        score = _transcript_similarity(want, got)
        if score < worst:
            worst_index, worst = index, score
    return worst_index, worst


def _transcript_similarity(expected: str, actual: str) -> float:
    return SequenceMatcher(
        None, _normalise_words(expected), _normalise_words(actual), autojunk=False,
    ).ratio()


def _normalise_words(text: str) -> str:
    return " ".join(_canonical_word_tokens(text))


def _normalised_words(text: str) -> str:
    """Punctuation-free word stream, so a script phrase matches a transcript one."""
    return " ".join(_canonical_word_tokens(text))


def _canonical_word_tokens(text: str) -> list[str]:
    words = _WORD_RE.findall(_TIME_SHORTHAND_RE.sub(r" \1 giờ \2 phút ", text.casefold()))
    canonical: list[str] = []
    index = 0
    while index < len(words):
        matched = _match_clock_time(words, index)
        if matched is not None:
            token, index = matched
            canonical.append(token)
            continue
        # A transcriber spells quantities as digits while the script spells them
        # as words. Clock times were already reconciled; a standalone count was
        # not, so "mười lăm" and "15" scored as a mismatch and a correctly
        # spoken line could be blocked (production 2026-08-31, 0.78 on a line
        # the voice read perfectly). Fold both spellings onto one token.
        quantity = _match_standalone_number(words, index)
        if quantity is not None:
            token, index = quantity
            canonical.append(token)
            continue
        canonical.append(words[index])
        index += 1
    return canonical


def _match_standalone_number(words: list[str], index: int) -> tuple[str, int] | None:
    """Fold a written-out Vietnamese quantity onto its digit form."""
    if words[index].isdigit():
        return f"#{int(words[index])}", index + 1
    for span in range(4, 0, -1):
        end = index + span
        if end > len(words):
            continue
        chunk = words[index:end]
        # `_parse_vietnamese_number` tolerates a trailing non-numeric word, which
        # would swallow the unit ("mười lăm phút" -> 15, eating "phút"). Only
        # accept a span that is numbers all the way through.
        if not all(_is_number_word(word) for word in chunk):
            continue
        value = _parse_vietnamese_number(chunk)
        if value is not None:
            return f"#{value}", end
    return None


def _is_number_word(word: str) -> bool:
    stripped = _strip_accents(word)
    return stripped.isdigit() or stripped in _VIETNAMESE_NUMBERS or stripped == "muoi"


def _match_clock_time(words: list[str], index: int) -> tuple[str, int] | None:
    if words[index].isdigit() and index + 1 < len(words) and words[index + 1] == "giờ":
        hour = int(words[index])
        next_index = index + 2
        minute = 0
        if next_index < len(words) and words[next_index].isdigit():
            minute = int(words[next_index])
            next_index += 1
            if next_index < len(words) and words[next_index] == "phút":
                next_index += 1
        return _clock_token(hour, minute), next_index

    for hour_span in range(4, 0, -1):
        hour_end = index + hour_span
        if hour_end >= len(words) or words[hour_end] != "giờ":
            continue
        hour = _parse_vietnamese_number(words[index:hour_end])
        if hour is None or not 0 <= hour <= 23:
            continue
        next_index = hour_end + 1
        minute = 0
        minute_end = next_index
        for minute_span in range(4, 0, -1):
            candidate_end = next_index + minute_span
            if candidate_end > len(words):
                continue
            parsed = _parse_vietnamese_number(words[next_index:candidate_end])
            if parsed is None or not 0 <= parsed <= 59:
                continue
            minute = parsed
            minute_end = candidate_end
            if minute_end < len(words) and words[minute_end] == "phút":
                minute_end += 1
            break
        return _clock_token(hour, minute), minute_end
    return None


def _clock_token(hour: int, minute: int) -> str:
    return f"time_{hour:02d}_{minute:02d}"


def _parse_vietnamese_number(words: list[str]) -> int | None:
    tokens = [_strip_accents(word) for word in words if word]
    if not tokens:
        return None
    if len(tokens) == 1:
        if tokens[0].isdigit():
            return int(tokens[0])
        return _VIETNAMESE_NUMBERS.get(tokens[0])
    if tokens[0] == "muoi":
        if len(tokens) == 1:
            return 10
        unit = _VIETNAMESE_NUMBERS.get(tokens[1])
        return 10 + unit if unit is not None else None
    tens = _VIETNAMESE_NUMBERS.get(tokens[0])
    if tens is None:
        return None
    if len(tokens) >= 2 and tokens[1] == "muoi":
        if len(tokens) == 2:
            return tens * 10
        unit = _VIETNAMESE_NUMBERS.get(tokens[2])
        return (tens * 10) + unit if unit is not None else None
    if len(tokens) >= 3 and tokens[1] in {"linh", "le"}:
        unit = _VIETNAMESE_NUMBERS.get(tokens[2])
        return (tens * 10) + unit if unit is not None else None
    return None


def _strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn"
    )


def _adjacent_repeated_phrase(transcript: str) -> str | None:
    """Find speech duplicated back to back, without flagging normal exposition.

    Two artifacts matter: a stutter repeats a phrase inside one sentence, and a
    duplicated TTS segment repeats a whole sentence.  Scanning the raw word
    stream caught both but also flagged "...gọi là chi phí chìm. Chi phí chìm là
    tiền..." — naming a term and then defining it — because stripping
    punctuation erases the boundary that tells the two apart.
    """
    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(transcript) if part.strip()]
    for sentence in sentences:
        words = _WORD_RE.findall(sentence.casefold())
        for size in range(min(12, len(words) // 2), 2, -1):
            for start in range(0, len(words) - (size * 2) + 1):
                if words[start:start + size] == words[start + size:start + (size * 2)]:
                    return " ".join(words[start:start + size])
    for first, second in zip(sentences, sentences[1:]):
        words = _WORD_RE.findall(first.casefold())
        if len(words) > 2 and words == _WORD_RE.findall(second.casefold()):
            return " ".join(words)
    return None
