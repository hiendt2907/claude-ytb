"""Tests for user-facing video quality messages."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytb_pipeline.webui import quality


class _RunResult:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr


def test_analyze_video_file_reports_ready_for_clean_30fps_video(monkeypatch) -> None:
    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(
                stdout=(
                    '{"streams":[{"avg_frame_rate":"30/1","pix_fmt":"yuv420p",'
                    '"nb_frames":"300","duration":"10.0"}],"format":{"duration":"10.0"}}'
                )
            )
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = quality.analyze_video_file(Path("ok.mp4"))

    assert result.status == "ready"
    assert result.title == "Sẵn sàng đăng"
    assert result.issues == ()


def test_analyze_video_file_translates_freeze_to_rerender_message(monkeypatch) -> None:
    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(
                stdout=(
                    '{"streams":[{"avg_frame_rate":"30/1","pix_fmt":"yuv420p",'
                    '"nb_frames":"300","duration":"10.0"}],"format":{"duration":"10.0"}}'
                )
            )
        if any("freezedetect" in part for part in cmd):
            return _RunResult(
                stderr="[freezedetect @ 0x0] freeze_start: 8.4\n"
                "[freezedetect @ 0x0] freeze_duration: 1.2\n"
                "[freezedetect @ 0x0] freeze_end: 9.6\n"
            )
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = quality.analyze_video_file(Path("freeze.mp4"))

    assert result.status == "rerender"
    assert result.title == "Nên render lại"
    assert "đứng hình" in result.issues[0].message


def test_analyze_video_file_warns_when_audio_and_video_duration_differ(monkeypatch) -> None:
    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(
                stdout=(
                    '{"streams":['
                    '{"codec_type":"video","avg_frame_rate":"30/1","pix_fmt":"yuv420p",'
                    '"nb_frames":"300","duration":"10.0"},'
                    '{"codec_type":"audio","duration":"7.0"}'
                    '],"format":{"duration":"10.0"}}'
                )
            )
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = quality.analyze_video_file(Path("mismatch.mp4"))

    assert result.status == "review"
    assert any("tiếng và hình" in issue.message for issue in result.issues)


def test_summarize_quality_includes_source_coverage_message() -> None:
    result = quality.VideoQualityResult(
        path="ok.mp4",
        status="ready",
        title="Sẵn sàng đăng",
        summary="Video ổn, có thể dùng.",
    )

    summary = quality.summarize_quality(
        (result,), ("Còn 2 clip nguồn chưa được dùng trong batch này.",)
    )

    assert summary.status == "review"
    assert summary.title == "Cần xem lại"
    assert summary.messages == ("Còn 2 clip nguồn chưa được dùng trong batch này.",)
