from dataclasses import replace
from pathlib import Path

from ytb_pipeline.pkg.models import Script, Segment, VideoIdea


def test_script_enriches_idea_without_mutation():
    # Arrange
    idea = VideoIdea(topic="t", title="ti", description="d", tags=("a",))

    # Act
    script = replace(Script(**vars(idea)), body="xin chào")

    # Assert
    assert script.body == "xin chào"
    assert script.title == "ti"
    assert idea.title == "ti"  # bản gốc không đổi


def test_new_profile_fields_do_not_break_legacy_positional_constructors():
    idea = VideoIdea("topic", "title", "description", (), "long")
    segment = Segment(
        "caption", "narration", None, "voiceover", "visual", "query", "code",
        False, "broll", "image_motion", (), "style", 1.0, 0.0, 0.0, 0.0,
        0.0, False, False, "hook", "transition", "payoff", "purpose",
        Path("audio.mp3"), 2.0,
    )

    assert idea.video_type == "long"
    assert idea.content_profile_id == "one-cup-cafe-6h"
    assert segment.audio_path == Path("audio.mp3")
    assert segment.speaker_id == "narrator"
