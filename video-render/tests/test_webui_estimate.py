"""Test ước tính thời gian render trước khi bấm xác nhận."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ytb_pipeline.assembler.models import Clip, SceneFolder
from ytb_pipeline.webui import app as app_module
from ytb_pipeline.webui.estimate import estimate_all, estimate_product


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _make_scene(scene_index: int, n_clips: int) -> SceneFolder:
    clips = tuple(
        Clip(
            path=Path(f"scene_{scene_index}/{scene_index}.{i}.mp4"),
            scene_index=scene_index,
            sub_index=(scene_index, i),
        )
        for i in range(1, n_clips + 1)
    )
    return SceneFolder(scene_index=scene_index, path=Path(f"scene_{scene_index}"), clips=clips)


def test_estimate_product_is_positive_and_scales_with_n_outputs(monkeypatch, tmp_path) -> None:
    scenes = (_make_scene(0, 3),)
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(2.0 for _ in groups),
    )

    small = estimate_product(scenes, tmp_path / "voice.wav", "p", 2, "clip_length", seed=1)
    large = estimate_product(scenes, tmp_path / "voice.wav", "p", 10, "clip_length", seed=1)

    assert small.estimated_seconds > 0
    assert large.estimated_seconds > small.estimated_seconds


def test_estimate_all_sums_grand_total(monkeypatch, tmp_path) -> None:
    scenes = (_make_scene(0, 2),)
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )
    voices = [tmp_path / "a.wav", tmp_path / "b.wav"]

    result = estimate_all(scenes, voices, "prod", 3, "clip_length", seed=1)

    assert len(result.items) == 2
    assert result.items[0].product_name == "prod_a"
    assert result.items[1].product_name == "prod_b"
    assert result.grand_total_estimated_seconds == sum(i.estimated_seconds for i in result.items)


def test_estimate_endpoint_rejects_missing_scenes_dir() -> None:
    client = TestClient(app_module.app)
    res = client.post(
        "/api/estimate",
        data={
            "scenes_dir": "/no/such/dir",
            "voice_tracks": ["/tmp/voice.wav"],
            "product_name": "p",
            "n_outputs": "2",
        },
    )
    assert res.status_code == 400


def test_estimate_endpoint_returns_items(monkeypatch, tmp_path) -> None:
    _touch(tmp_path / "scenes" / "scene_00" / "1.1.mp4")
    voice = tmp_path / "voice.wav"
    _touch(voice)
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )

    client = TestClient(app_module.app)
    res = client.post(
        "/api/estimate",
        data={
            "scenes_dir": str(tmp_path / "scenes"),
            "voice_tracks": [str(voice)],
            "product_name": "p",
            "n_outputs": "2",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["product_name"] == "p"
    assert body["grand_total_estimated_seconds"] > 0
