#!/usr/bin/env python3
"""Reproducible, fail-closed post-render Gate 1 verifier.

This is deliberately repository-relative: unlike the historical scratchpad
runner it can be executed from a fresh checkout and always reports all five
layers before returning a non-zero status. Human review is intentionally not
automated; a machine PASS is not a publish approval.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def check_tts_stt(root: Path, slug: str, video: Path, render: dict) -> tuple[bool, str]:
    """Compare speech extracted from the final MP4 with the source script."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.ideation.generator import load_script
    from ytb_pipeline.voiceover.quality import FasterWhisperSttAdapter, _transcript_similarity
    from ytb_pipeline.voiceover.tts import _prepare_narration

    script = load_script(root / "scripts" / f"{slug}.json")
    wav = root / "assets" / "production_readiness" / "gate1" / "audio" / f"{slug}_mp4.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vn", "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )
    stt = FasterWhisperSttAdapter(
        model_path=settings.quality_stt_model_path, device=settings.quality_stt_device,
        compute_type=settings.quality_stt_compute_type, cpu_threads=settings.quality_stt_cpu_threads,
    )
    expected = " ".join(_prepare_narration(segment.narration or "") for segment in script.segments)
    heard = stt.transcribe(wav)
    score = _transcript_similarity(expected, heard)
    threshold = 0.82
    return score >= threshold, f"similarity={score:.3f} threshold={threshold:.2f}"


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _render_node(project: dict) -> dict:
    nodes = project.get("nodes", {})
    if isinstance(nodes, dict):
        return dict(nodes.get("render") or {})
    return next((dict(node) for node in nodes if node.get("node_id") == "render"), {})


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def _duration(stream: dict) -> float:
    return float(stream.get("duration") or 0.0)


def check_container(video: Path) -> tuple[bool, str]:
    data = _probe(video)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream or not audio_stream:
        return False, "thiếu video hoặc audio stream"
    width, height = video_stream.get("width"), video_stream.get("height")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    checks = [
        video_stream.get("codec_name") == "h264",
        audio_stream.get("codec_name") in {"aac", "mp3"},
        (width, height) == (1920, 1080),
        300.0 <= duration <= 420.0,
    ]
    return all(checks), f"codec={video_stream.get('codec_name')}/{audio_stream.get('codec_name')} size={width}x{height} duration={duration:.2f}s"


def check_av_and_silence(video: Path) -> tuple[bool, str]:
    data = _probe(video)
    streams = data.get("streams", [])
    durations = [_duration(s) for s in streams if s.get("codec_type") in {"video", "audio"}]
    drift_ms = abs(durations[0] - durations[1]) * 1000 if len(durations) >= 2 else float("inf")
    silence = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(video), "-af", "silencedetect=noise=-45dB:d=2.0", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silence_hits = silence.stderr.count("silence_duration:")
    return drift_ms <= 1000.0 and silence_hits == 0, f"drift={drift_ms:.1f}ms dead_air_segments={silence_hits}"


def check_subtitles(video: Path) -> tuple[bool, str]:
    siblings = [video.with_suffix(ext) for ext in (".srt", ".vtt")]
    existing = [path for path in siblings if path.is_file() and path.stat().st_size > 0]
    return bool(existing), "files=" + ",".join(path.name for path in existing)


def check_visual(project: dict) -> tuple[bool, str]:
    node = project.get("nodes", {}).get("visual_assets", {}) if isinstance(project.get("nodes"), dict) else {}
    status = str(node.get("status") or "")
    review = int(node.get("review_required") or 0)
    return status in {"done", "ok", "completed"} and review == 0, f"status={status or 'missing'} review_required={review}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    args = parser.parse_args(argv)
    root = _root()
    sys.path.insert(0, str(root / "src"))
    project_path = root / "assets" / "projects" / args.slug / "project.json"
    if not project_path.is_file():
        print(f"FAIL project missing: {project_path}")
        return 2
    project = json.loads(project_path.read_text(encoding="utf-8"))
    render = _render_node(project)
    output_ref = str(render.get("output_ref") or "")
    video = Path(output_ref)
    if not video.is_absolute():
        video = root / video
    if not video.is_file():
        print(f"FAIL video missing: {video}")
        return 2

    checks = [
        ("1.container", lambda: check_container(video)),
        ("2.av_dead_air", lambda: check_av_and_silence(video)),
        ("3.tts_stt", lambda: check_tts_stt(root, args.slug, video, render)),
        ("4.subtitle", lambda: check_subtitles(video)),
        ("5.visual", lambda: check_visual(project)),
    ]
    failed = 0
    for name, check in checks:
        try:
            passed, detail = check()
        except Exception as exc:  # noqa: BLE001 - every layer must report
            passed, detail = False, str(exc)
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
        failed += not passed
    print("MACHINE_PASS" if failed == 0 else f"MACHINE_FAIL layers={failed}")
    print("HUMAN_WATCH_REQUIRED")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
