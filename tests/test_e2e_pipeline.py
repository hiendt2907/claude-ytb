"""Deterministic offline media journey: script input -> fake TTS -> render -> publish-prep."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ytb_pipeline.content_contract import CONTRACT_VERSION, contract_for
from ytb_pipeline.ideation.generator import load_script
from ytb_pipeline.pkg.models import Segment, Voiceover


def _ffmpeg(path: Path, lavfi: str, *, audio: bool = False) -> None:
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", lavfi]
    if audio:
        command += ["-ar", "44100", "-ac", "2", "-b:a", "128k"]
    else:
        command += ["-pix_fmt", "yuv420p"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)


@pytest.mark.e2e
async def test_offline_short_pipeline_renders_and_prepares_publish(tmp_path, monkeypatch):
    """Uses real ffmpeg audio/video and compose_ai, while every network path raises."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator import batch_cli
    from ytb_pipeline.publish.multiplatform import publish_to_platforms
    from ytb_pipeline.render import compose_ai

    def forbidden(*_args, **_kwargs):
        raise AssertionError("E2E local-only must not use network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(batch_cli, "finalize_published_item", forbidden)
    monkeypatch.setattr(settings, "orientation", "portrait")
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "broll_allow_downloads", False)
    monkeypatch.setattr(settings, "quality_gate_mode", "off")
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path / "output")

    broll = tmp_path / "broll.mp4"
    _ffmpeg(broll, "color=c=blue:size=480x854:duration=3:rate=25")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"assets": {"local": {
        "asset_id": "local", "source": "pexels", "license": "Pexels License",
        "source_url": "https://example.test/local", "local_path": str(broll),
        "topics": ["office work"], "orientation": "portrait", "duration_sec": 3, "uses": [],
    }}}), encoding="utf-8")
    monkeypatch.setattr(settings, "asset_catalog_path", catalog)

    narration = "Hãy bắt đầu bằng một bước nhỏ, rõ ràng và có thể hoàn thành ngay hôm nay. " * 4
    raw = {"ruleset_id": CONTRACT_VERSION, "video_type": "short", "title": "E2E local", "topic": "work",
           "description": "offline", "tags": ["work"],
           "compliance": {"passed": True, "community": "PASS", "copyright": "PASS", "accuracy": "PASS", "advertiser": "PASS", "coppa": "PASS", "notes": "test"},
           "thumbnail_brief": {"visual_contradiction": "x", "subject": "x", "emotion": "x", "headline": "E2E"},
           "strategy": {"format_id": "e2e", "core_mechanism": "x", "audience_problem": "x", "angle": "x", "long_form_slug": "long", "playlist": "p", "cta_target": "long", "source_long_slug": "long", "source_excerpt": "x", "source_section_index": 0, "hook": {"situation": "Bạn đang chần chừ.", "core_answer": "Hãy bắt đầu bằng một bước nhỏ, rõ ràng và có thể hoàn thành ngay hôm nay.", "open_loop": "x"}},
           "sections": []}
    for index in range(6):
        text = "Bạn đang chần chừ." if index == 0 else narration
        raw["sections"].append({"purpose": "situation" if index == 0 else ("core_answer" if index == 1 else "application"), "voiceover": text, "visual_intent": "office work", "pexels_query": "office work", "time_goal": 10})
    script_path = tmp_path / "short.json"
    script_path.write_text(json.dumps(raw), encoding="utf-8")
    script = load_script(script_path)

    voiced = []
    for index, segment in enumerate(script.segments):
        audio = tmp_path / f"audio-{index}.mp3"
        _ffmpeg(audio, "sine=frequency=220:duration=12", audio=True)
        voiced.append(replace(segment, audio_path=audio, duration_sec=12.0, broll="office work"))
    voiceover = Voiceover(**vars(replace(script, segments=tuple(voiced))), audio_path=voiced[0].audio_path, duration_sec=72.0)

    rendered = compose_ai.render_video_ai(voiceover)
    assert rendered.video_path and rendered.video_path.exists()
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(rendered.video_path)], capture_output=True, text=True, check=True).stdout)
    assert contract_for("short").viewer_runtime_bounds_sec[0] <= duration <= contract_for("short").viewer_runtime_bounds_sec[1]
    results = await publish_to_platforms(rendered, ["youtube_short"], project_id="e2e-local")
    assert results["youtube_short"].uploaded is False
