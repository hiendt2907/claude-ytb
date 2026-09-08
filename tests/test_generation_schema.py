import pytest
from ytb_pipeline.content_contract import CONTRACT_VERSION, contract_for
from ytb_pipeline.ideation.generation_schema import script_generation_schema


def test_qwen_generation_schema_requires_the_release_ruleset_and_long_target():
    schema = script_generation_schema("long")

    assert "ruleset_id" in schema["required"]
    assert "target_minutes" in schema["required"]
    assert schema["properties"]["ruleset_id"]["const"] == CONTRACT_VERSION
    assert schema["properties"]["sections"]["minItems"] == contract_for("long").minimum_sections
    assert schema["properties"]["sections"]["maxItems"] == int(contract_for("long").minimum_sections * 1.5)


def test_qwen_generation_schema_requires_short_strategy_but_not_long_target():
    short_schema = script_generation_schema("short")

    assert "strategy" in short_schema["required"]
    assert "target_minutes" not in short_schema["required"]
    assert short_schema["properties"]["sections"]["minItems"] == 6
    assert short_schema["properties"]["sections"]["maxItems"] == 6


@pytest.mark.parametrize("video_type", ["short", "long"])
def test_section_purpose_is_a_closed_enum_the_provider_can_enforce(video_type):
    """Prose alone did not hold: a 36-section Long invented 15 free-form purposes.

    The prompt already states the five canonical values, but the schema declared
    `purpose` as an open string, so structured output could not enforce it.  The
    pre-publish gate then had to translate via a hardcoded table built from one
    old script's vocabulary, and blocked the Long for a missing 'core_answer'.
    """
    from ytb_pipeline.analytics.quality_report import _REQUIRED_PURPOSES
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    schema = script_generation_schema(video_type)
    purpose = schema["properties"]["sections"]["items"]["properties"]["purpose"]

    assert "enum" in purpose, "purpose phải là enum để structured output ép được"
    allowed = set(purpose["enum"])
    # Every purpose the pre-publish gate demands must be one the model may emit.
    assert set(_REQUIRED_PURPOSES[video_type]) <= allowed
