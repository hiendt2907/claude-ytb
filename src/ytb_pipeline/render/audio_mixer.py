"""FFmpeg execution boundary for deterministic Timeline audio layers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .timeline import Timeline

_SUPPORTED_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def _validate_audio_asset(path: Path) -> None:
    if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"Audio media cấu hình không hợp lệ hoặc thiếu: {path}")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "audio":
        raise ValueError(f"Audio media không có audio stream hợp lệ: {path}")


def mix_timeline_audio(ffmpeg: str, video_path: Path, output_path: Path, timeline: Timeline) -> Path:
    """Mix local optional tracks while using narration/video duration as ceiling."""
    layers = (*timeline.music_clips, *timeline.sfx_clips)
    if not layers:
        return video_path
    for layer in layers:
        _validate_audio_asset(layer.asset_path)
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path)]
    for layer in layers:
        if layer.loop:
            command.extend(("-stream_loop", "-1"))
        command.extend(("-i", str(layer.asset_path)))
    filters = ["[0:a]aresample=44100,asetpts=PTS-STARTPTS[narration]"]
    labels = ["[narration]"]
    for index, layer in enumerate(layers, start=1):
        end = min(timeline.expected_duration_sec, layer.start_sec + layer.duration_sec)
        chain = f"[{index}:a]atrim=0:{max(0.001, end - layer.start_sec):.3f},asetpts=PTS-STARTPTS,volume={layer.gain_db}dB"
        if layer.fade_in_sec:
            chain += f",afade=t=in:st=0:d={layer.fade_in_sec:.3f}"
        if layer.fade_out_sec:
            chain += f",afade=t=out:st={max(0.0, end-layer.start_sec-layer.fade_out_sec):.3f}:d={layer.fade_out_sec:.3f}"
        chain += f",adelay={round(layer.start_sec * 1000)}|{round(layer.start_sec * 1000)}[layer{index}]"
        filters.append(chain)
        labels.append(f"[layer{index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[mixed]")
    command.extend(("-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[mixed]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output_path)))
    subprocess.run(command, check=True)
    return output_path
