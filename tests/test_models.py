from dataclasses import replace

from ytb_pipeline.pkg.models import Script, VideoIdea


def test_script_enriches_idea_without_mutation():
    # Arrange
    idea = VideoIdea(topic="t", title="ti", description="d", tags=("a",))

    # Act
    script = replace(Script(**vars(idea)), body="xin chào")

    # Assert
    assert script.body == "xin chào"
    assert script.title == "ti"
    assert idea.title == "ti"  # bản gốc không đổi
