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
