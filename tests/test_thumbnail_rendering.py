from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ytb_pipeline.pkg.models import Segment, ThumbnailBrief, Voiceover
from ytb_pipeline.render import compose, compose_ai


def _voiceover(*, with_brief: bool) -> Voiceover:
    brief = (
        ThumbnailBrief(
            visual_contradiction="Mở laptop nhưng lại lướt điện thoại",
            subject="Người đi làm trước laptop",
            emotion="bối rối",
            headline="NÃO ĐANG TRỐN",
        )
        if with_brief else None
    )
    return Voiceover(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        segments=(Segment(caption="Hook", narration="Mở laptop rồi cầm điện thoại."),),
        thumbnail_brief=brief,
    )


@pytest.mark.parametrize("renderer", (compose, compose_ai))
def test_thumbnail_text_uses_brief_headline_and_keeps_legacy_title_fallback(renderer):
    assert renderer._thumbnail_text(_voiceover(with_brief=True)) == "NÃO ĐANG TRỐN"
    assert renderer._thumbnail_text(_voiceover(with_brief=False)) == "Mở laptop rồi cầm điện thoại"
    context = renderer._thumbnail_context(_voiceover(with_brief=True))
    assert "Mở laptop nhưng lại lướt điện thoại" in context
    assert "Người đi làm trước laptop" in context
    assert "bối rối" in context
    assert renderer._thumbnail_context(_voiceover(with_brief=False)) == ""


def test_slide_renderer_writes_thumbnail_with_brief_headline(monkeypatch, tmp_path):
    voiceover = _voiceover(with_brief=True)
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(compose, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(compose, "_render_segment", lambda *args, **kwargs: None)
    monkeypatch.setattr(compose, "_concat_clips", lambda _clips, out: out.write_bytes(b"video"))

    def _thumbnail(text, **kwargs):
        captured.append((text, kwargs["thumbnail_context"]))
        return Image.new("RGB", (2, 2))

    monkeypatch.setattr(compose, "_caption_image", _thumbnail)

    result = compose.render_video(voiceover)

    assert captured == [("NÃO ĐANG TRỐN", "Người đi làm trước laptop — bối rối\nMở laptop nhưng lại lướt điện thoại")]
    assert result.thumbnail_path is not None and result.thumbnail_path.exists()


def test_ai_renderer_writes_thumbnail_with_brief_headline(monkeypatch, tmp_path):
    voiceover = _voiceover(with_brief=True)
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(compose_ai, "validate_visual_hook", lambda _voice: None)
    monkeypatch.setattr(compose_ai, "_dims", lambda: (1080, 1920, False))
    monkeypatch.setattr(compose_ai, "_visual_cache_suffix", lambda: "test")
    monkeypatch.setattr(compose_ai.slide, "_audio_duration", lambda _audio: 1.0)
    monkeypatch.setattr(
        compose_ai,
        "_render_broll_segment",
        lambda *_args, **kwargs: Path(kwargs["out"]).write_bytes(b"segment"),
    )
    monkeypatch.setattr(compose_ai, "_hook_coldopen", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        compose_ai.transitions,
        "concat_with_transitions",
        lambda _clips, _flags, out: Path(out).write_bytes(b"video"),
    )
    monkeypatch.setattr(compose_ai, "_timeline_duration", lambda _clips: 1.0)
    monkeypatch.setattr(compose_ai, "validate_render", lambda *args, **kwargs: None)

    def _thumbnail(text, *, dims, context):
        captured.append((text, context))
        return Image.new("RGB", dims)

    monkeypatch.setattr(compose_ai, "_thumbnail", _thumbnail)

    result = compose_ai.render_video_ai(voiceover)

    assert captured == [("NÃO ĐANG TRỐN", "Người đi làm trước laptop — bối rối\nMở laptop nhưng lại lướt điện thoại")]
    assert result.thumbnail_path is not None and result.thumbnail_path.exists()
