"""Unit test command ffmpeg quan trọng trong render.py, không gọi ffmpeg thật."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, ClipSegment
from ytb_pipeline.assembler import render as render_module
from ytb_pipeline.assembler.profiles import AutoEditProfile


def test_loop_and_trim_reencodes_cfr_instead_of_stream_copy(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    render_module._loop_and_trim(tmp_path / "in.mp4", 3.0, tmp_path / "out.mp4")

    cmd = commands[0]
    assert "-c copy" not in " ".join(cmd)
    assert "fps=30" in cmd[cmd.index("-vf") + 1]
    assert "yuv420p" in cmd
    assert "-r" in cmd
    assert cmd[cmd.index("-r") + 1] == "30"


def test_concat_clips_cuts_selected_segments_with_ss_and_t(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    clip = Clip(path=tmp_path / "clip.mp4", scene_index=0, sub_index=(1, 1))
    group = ClipGroup(
        scene_index=0,
        clips=(clip,),
        segments=(ClipSegment(clip=clip, start_sec=2.5, end_sec=6.0, score=0.9),),
    )

    render_module._concat_clips(
        group,
        tmp_path / "out.mp4",
        target_size=(1920, 1080),
        fit_mode="pad",
        edit_profile=render_module.resolve_profile("affiliate_default"),
    )

    cmd = commands[0]
    assert "-ss" in cmd
    assert cmd[cmd.index("-ss") + 1] == "2.5"
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "3.5"
    assert str(clip.path) in cmd


def test_render_output_pads_voice_so_audio_does_not_cut_video(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_render_scene_segment(
        group: ClipGroup,
        target_duration: float,
        out_path: Path,
        target_size: tuple[int, int],
        fit_mode: str,
        edit_profile: AutoEditProfile,
        enable_ken_burns: bool = True,
        transition_seed: int = 0,
    ) -> Path:
        return out_path

    def fake_concat_with_transitions(
        segment_paths: list[Path],
        durations: tuple[float, ...],
        out_path: Path,
        edit_profile: AutoEditProfile,
        transition_duration: float,
        transition_seed: int = 0,
    ) -> Path:
        return out_path

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)
    monkeypatch.setattr(render_module, "_render_scene_segment", fake_render_scene_segment)
    monkeypatch.setattr(render_module, "_concat_with_transitions", fake_concat_with_transitions)

    clip = Clip(path=tmp_path / "clip.mp4", scene_index=0, sub_index=(1, 1))
    assignment = Assignment(
        output_index=0,
        groups=(ClipGroup(scene_index=0, clips=(clip,)),),
    )

    render_module.render_output(
        assignment=assignment,
        scene_durations=(12.0,),
        voice_track=tmp_path / "voice.m4a",
        out_path=tmp_path / "out.mp4",
        tmp_dir=tmp_path / "tmp",
    )

    cmd = commands[0]
    assert "[1:a:0]apad[a]" in cmd
    assert "[a]" in cmd
    assert "1:a:0" not in cmd[cmd.index("-map") :]


def test_xfade_transition_style_varies_by_profile() -> None:
    fast = render_module.resolve_profile("tiktok_shop_fast")
    fashion = render_module.resolve_profile("fashion_tryon")
    smooth = render_module.resolve_profile("product_review_smooth")

    assert render_module._transition_style_for_profile(fast, 1, seed=1) in {"zoomin", "fadefast", "dissolve"}
    assert render_module._transition_style_for_profile(fashion, 1, seed=1) in {"smoothleft", "fadefast", "dissolve"}
    assert render_module._transition_style_for_profile(smooth, 1, seed=1) in {"fade", "dissolve"}


def test_xfade_transition_style_changes_by_seed() -> None:
    fast = render_module.resolve_profile("tiktok_shop_fast")

    styles = {
        render_module._transition_style_for_profile(fast, 1, seed=seed)
        for seed in range(8)
    }

    assert len(styles) >= 2
