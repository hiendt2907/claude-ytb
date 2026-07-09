"""Unit test cho hậu kỳ cắt bỏ đoạn xấu sau khi render video-only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ytb_pipeline.assembler import cutting
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd, ffprobe_cmd


def test_parse_cut_ranges_accepts_timestamp_and_seconds() -> None:
    ranges = cutting.parse_cut_ranges(
        """
        00:03-00:05.5
        12.0 - 14.25
        """
    )

    assert ranges == (
        cutting.CutRange(start_sec=3.0, end_sec=5.5),
        cutting.CutRange(start_sec=12.0, end_sec=14.25),
    )


def test_parse_cut_ranges_merges_overlap_and_sorts() -> None:
    ranges = cutting.parse_cut_ranges("8-10\n2-4\n3.5-5")

    assert ranges == (
        cutting.CutRange(start_sec=2.0, end_sec=5.0),
        cutting.CutRange(start_sec=8.0, end_sec=10.0),
    )


def test_parse_cut_ranges_rejects_invalid_range() -> None:
    with pytest.raises(ValueError, match="Dòng 1"):
        cutting.parse_cut_ranges("5-3")


def test_cut_video_excludes_ranges_and_keeps_remaining_parts(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)
    monkeypatch.setattr(cutting, "ffprobe_duration", lambda path: 20.0)

    cutting.cut_video_excluding_ranges(
        in_path=tmp_path / "raw.mp4",
        out_path=tmp_path / "cut.mp4",
        cut_ranges=(
            cutting.CutRange(start_sec=2.0, end_sec=5.0),
            cutting.CutRange(start_sec=12.0, end_sec=14.0),
        ),
    )

    cmd = commands[0]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=0.0:end=2.0" in filter_complex
    assert "trim=start=5.0:end=12.0" in filter_complex
    assert "trim=start=14.0:end=20.0" in filter_complex
    assert "concat=n=3:v=1:a=0[v]" in filter_complex
    assert "-map" in cmd
    assert "[v]" in cmd


def test_conform_does_not_trim_video_that_is_longer_than_voice(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_duration(path: Path) -> float:
        return 5.0 if path.name == "voice.wav" else 12.0

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)
    monkeypatch.setattr(cutting, "ffprobe_duration", fake_duration)

    cutting.conform_video_to_voice_duration(
        video_path=tmp_path / "cut.mp4",
        voice_track=tmp_path / "voice.wav",
        out_path=tmp_path / "fit.mp4",
    )

    cmd = commands[0]
    assert "-stream_loop" not in cmd
    assert "-t" not in cmd


def test_mux_voice_pads_audio_so_short_voice_does_not_cut_video(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)

    cutting.mux_voice_after_video(
        video_path=tmp_path / "video.mp4",
        voice_track=tmp_path / "voice.wav",
        out_path=tmp_path / "final.mp4",
    )

    cmd = commands[0]
    assert "[1:a:0]apad[a]" in cmd
    assert "[a]" in cmd
    assert "1:a:0" not in cmd[cmd.index("-map") :]


def test_manual_cut_final_keeps_video_before_cut_when_voice_is_short(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.mp4"
    cut_path = tmp_path / "cut.mp4"
    fit_path = tmp_path / "fit.mp4"
    voice_path = tmp_path / "voice.wav"
    final_path = tmp_path / "final.mp4"

    subprocess.run(
        [
            ffmpeg_cmd(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:d=1:r=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=160x90:d=1:r=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:d=1:r=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:s=160x90:d=1:r=30",
            "-filter_complex",
            "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]",
            "-map",
            "[v]",
            str(raw_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        [
            ffmpeg_cmd(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            str(voice_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    cutting.cut_video_excluding_ranges(raw_path, cut_path, (cutting.CutRange(1.0, 2.0),))
    cutting.conform_video_to_voice_duration(cut_path, voice_path, fit_path)
    cutting.mux_voice_after_video(fit_path, voice_path, final_path)

    duration = float(
        subprocess.run(
            [
                ffprobe_cmd(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(final_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    first_pixel = subprocess.run(
        [
            ffmpeg_cmd(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(final_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout

    assert duration == pytest.approx(3.0, abs=0.15)
    assert first_pixel[0] > 200
    assert first_pixel[1] < 40
    assert first_pixel[2] < 40


def test_apply_emoji_preset_adds_drawbox_sticker_filters(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)

    out_path = cutting.apply_emoji_preset(
        video_path=tmp_path / "video.mp4",
        out_path=tmp_path / "emoji.mp4",
        preset="sales",
        seed=1,
    )

    assert out_path == tmp_path / "emoji.mp4"
    cmd = commands[0]
    video_filter = cmd[cmd.index("-vf") + 1]
    assert "drawbox=" in video_filter
    assert any(color in video_filter for color in ("0xff3b30", "0x21c55d", "0xfacc15"))


def test_apply_emoji_preset_varies_by_seed(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)

    cutting.apply_emoji_preset(tmp_path / "video.mp4", tmp_path / "emoji1.mp4", "sales", seed=1)
    cutting.apply_emoji_preset(tmp_path / "video.mp4", tmp_path / "emoji2.mp4", "sales", seed=2)

    first_filter = commands[0][commands[0].index("-vf") + 1]
    second_filter = commands[1][commands[1].index("-vf") + 1]
    assert first_filter != second_filter


def test_apply_emoji_preset_none_returns_original_path(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"

    assert cutting.apply_emoji_preset(video_path, tmp_path / "out.mp4", "none") == video_path


def test_suggest_cut_ranges_for_video_detects_black_and_freeze(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        filter_arg = cmd[cmd.index("-vf") + 1]
        if "blackdetect" in filter_arg:
            stderr = "black_start:1.0 black_end:2.2 black_duration:1.2"
        else:
            stderr = "freeze_start:3.0 freeze_end:4.5 freeze_duration:1.5"
        return subprocess.CompletedProcess(cmd, 0, "", stderr)

    monkeypatch.setattr(cutting.subprocess, "run", fake_run)
    monkeypatch.setattr(cutting, "ffprobe_duration", lambda path: 10.0)

    ranges = cutting.suggest_cut_ranges_for_video(tmp_path / "video.mp4")

    assert ranges == (
        cutting.CutRange(start_sec=1.0, end_sec=2.2),
        cutting.CutRange(start_sec=3.0, end_sec=4.5),
    )
