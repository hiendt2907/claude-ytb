"""Tests for lightweight profile recommendations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytb_pipeline.assembler.models import Clip, SceneFolder
from ytb_pipeline.webui import recommend as recommend_module
from ytb_pipeline.webui.recommend import recommend_profile


class _RunResult:
    def __init__(self, stderr: str = "") -> None:
        self.stderr = stderr


def _fake_ffmpeg_ydif(*ydif_values: float):
    """Fake subprocess.run trả stderr có dòng metadata=print như ffmpeg thật,
    để _estimate_motion_score parse ra đúng các giá trị YDIF cho trước."""

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        lines = "\n".join(f"lavfi.signalstats.YDIF={value}" for value in ydif_values)
        return _RunResult(stderr=lines)

    return fake_run


def _clip(scene_index: int, ref: tuple[int, ...]) -> Clip:
    name = ".".join(str(part) for part in ref)
    return Clip(
        path=Path(f"scene_{scene_index}/{name}.mp4"),
        scene_index=scene_index,
        sub_index=ref,
    )


def test_recommend_profile_prefers_fast_for_vertical_many_clips(monkeypatch) -> None:
    # Không có tín hiệu chuyển động đo được (ffmpeg "hỏng") -> phải rơi về
    # heuristic cấu trúc cũ (nhiều cảnh/nhiều clip + dọc).
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        raise FileNotFoundError("ffmpeg không có trong test env")

    monkeypatch.setattr(subprocess, "run", fake_run)

    scenes = tuple(
        SceneFolder(
            scene_index=index,
            path=Path(f"scene_{index}"),
            clips=(
                _clip(index, (index + 1, 1)),
                _clip(index, (index + 1, 2)),
                _clip(index, (index + 1, 3)),
            ),
        )
        for index in range(5)
    )

    suggestion = recommend_profile(scenes, aspect_ratio="9:16", mode="random")

    assert suggestion.profile_name == "tiktok_shop_fast"
    assert "nhiều clip" in suggestion.reason


def test_recommend_profile_respects_manual_mode() -> None:
    scenes = (
        SceneFolder(
            scene_index=0,
            path=Path("scene_0"),
            clips=(_clip(0, (1, 1)),),
        ),
    )

    suggestion = recommend_profile(scenes, aspect_ratio="16:9", mode="manual")

    assert suggestion.profile_name == "affiliate_default"
    assert "Tự chọn clip" in suggestion.reason


def test_recommend_profile_uses_measured_high_motion(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_ffmpeg_ydif(30.0, 28.0, 35.0))

    scenes = (
        SceneFolder(scene_index=0, path=Path("cảnh_1"), clips=(_clip(0, (1, 1)),)),
        SceneFolder(scene_index=1, path=Path("cảnh_2"), clips=(_clip(1, (2, 1)),)),
    )

    suggestion = recommend_profile(scenes, aspect_ratio="16:9", mode="random")

    assert suggestion.profile_name == "tiktok_shop_fast"
    assert "chuyển động" in suggestion.reason


def test_recommend_profile_uses_measured_low_motion(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_ffmpeg_ydif(4.0, 5.0, 3.0))

    scenes = (
        SceneFolder(scene_index=0, path=Path("cảnh_1"), clips=(_clip(0, (1, 1)),)),
        SceneFolder(scene_index=1, path=Path("cảnh_2"), clips=(_clip(1, (2, 1)),)),
    )

    suggestion = recommend_profile(scenes, aspect_ratio="16:9", mode="random")

    assert suggestion.profile_name == "product_review_smooth"
    assert "chuyển động" in suggestion.reason


def test_recommend_profile_falls_back_when_motion_analysis_fails(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        raise FileNotFoundError("ffmpeg không có trong test env")

    monkeypatch.setattr(subprocess, "run", fake_run)

    scenes = (
        SceneFolder(
            scene_index=0,
            path=Path("cảnh_1"),
            clips=(_clip(0, (1, 1)), _clip(0, (1, 2))),
        ),
    )

    suggestion = recommend_profile(scenes, aspect_ratio="16:9", mode="random")

    assert suggestion.profile_name == "product_review_smooth"
    assert "Ít cảnh" in suggestion.reason


def test_estimate_motion_score_returns_none_on_timeout(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=8.0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert recommend_module._estimate_motion_score(tmp_path / "clip.mp4") is None
