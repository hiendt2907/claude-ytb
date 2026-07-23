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
from typing import Any, Callable, Mapping, Protocol

from ..pkg.models import Voiceover

_CACHE_VERSION = 2
_WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)


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

        model = WhisperModel(str(self.model_path))
        segments, _info = model.transcribe(str(audio_path), vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())

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
    transcript_similarity_threshold: float = 0.94,
    max_silence_ratio: float = 0.65,
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
    elif target_duration is not None and abs(actual_duration - target_duration) > duration_tolerance_sec:
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
) -> None:
    transcript_metrics: dict[str, object] = {"adapter": status.adapter, "available": status.available}
    metrics["transcript"] = transcript_metrics
    if not status.available:
        transcript_metrics["reason"] = status.reason
        issues.append(_issue(
            "STT_UNAVAILABLE", "warning", f"Không chạy transcript diff: {status.reason}",
            target="local_stt", action="configure_local_stt",
        ))
        return
    try:
        transcript = adapter.transcribe(audio_path)
    except (OSError, RuntimeError, ValueError) as exc:
        transcript_metrics["reason"] = str(exc)
        issues.append(_issue(
            "STT_FAILED", "warning", f"Local STT không tạo được transcript: {exc}",
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
    repeated = _adjacent_repeated_phrase(transcript)
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


def _target_duration(voiceover: Voiceover) -> float | None:
    if voiceover.target_minutes is not None and voiceover.target_minutes > 0:
        return voiceover.target_minutes * 60
    if voiceover.duration_sec > 0:
        return voiceover.duration_sec
    segment_total = sum(segment.duration_sec for segment in voiceover.segments)
    return segment_total if segment_total > 0 else None


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
        "thresholds": {
            "duration_tolerance_sec": duration_tolerance_sec,
            "transcript_similarity_threshold": transcript_similarity_threshold,
            "max_silence_ratio": max_silence_ratio,
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


def _transcript_similarity(expected: str, actual: str) -> float:
    return SequenceMatcher(None, _normalise_words(expected), _normalise_words(actual)).ratio()


def _normalise_words(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.casefold()))


def _adjacent_repeated_phrase(transcript: str) -> str | None:
    words = _WORD_RE.findall(transcript.casefold())
    for size in range(min(12, len(words) // 2), 2, -1):
        for start in range(0, len(words) - (size * 2) + 1):
            if words[start:start + size] == words[start + size:start + (size * 2)]:
                return " ".join(words[start:start + size])
    return None
