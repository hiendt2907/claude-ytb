"""JSON Schema used to constrain local LLM script generation at the API boundary."""

from __future__ import annotations

from typing import Any

from ..content_contract import CONTRACT_VERSION, contract_for

# The one vocabulary the prompt teaches, the schema enforces, and the
# pre-publish quality gate checks against.
SECTION_PURPOSES = ("situation", "core_answer", "evidence", "application", "payoff")


def script_generation_schema(video_type: str | None = None) -> dict[str, Any]:
    """Return the reusable envelope schema for both Short and Long scripts.

    Editorial rules remain in the contract/QA layers.  This schema has one job:
    prevent a model from emitting strings or loose field names inside
    ``sections`` where the pipeline requires objects.
    """
    nullable_string = {"type": ["string", "null"]}
    section_contract = contract_for(video_type) if video_type in {"short", "long"} else None
    section_bounds: dict[str, int] = {}
    if section_contract is not None:
        section_bounds["minItems"] = section_contract.minimum_sections
        # Shorts are a fixed six-beat format.  Longs permit limited editorial
        # variation but remain bounded so model output cannot exceed the
        # timing contract with a proliferation of tiny sections.
        section_bounds["maxItems"] = (
            section_contract.minimum_sections
            if video_type == "short"
            else int(section_contract.minimum_sections * 1.5)
        )
    section = {
        "type": "object",
        "properties": {
            # Closed vocabulary so structured output enforces what the prompt
            # only stated in prose.  A 36-section Long invented 15 free-form
            # purposes, and the pre-publish gate — which demands the canonical
            # five — blocked it after render for a missing "core_answer".
            "purpose": {"type": "string", "enum": list(SECTION_PURPOSES)},
            "time_goal": {"type": "number"},
            "voiceover": {"type": "string"},
            "narration": {"type": "string"},
            "visual_intent": {"type": "string"},
            "pexels_query": {"type": "string"},
            "caption": nullable_string,
            "hook": {"type": ["string", "boolean", "null"]},
            "transition": nullable_string,
            "payoff": nullable_string,
            "emphasis": nullable_string,
        },
        "required": [
            "purpose", "time_goal", "voiceover", "visual_intent",
            "pexels_query", "caption", "hook", "transition", "payoff", "emphasis",
        ],
        "additionalProperties": True,
    }
    required = [
        "ruleset_id", "slug", "topic", "title", "description", "tags",
        "video_type", "voice_profile", "thumbnail_brief", "sections", "compliance",
    ]
    if video_type == "short":
        required.append("strategy")
    elif video_type == "long":
        required.append("target_minutes")
    return {
        "type": "object",
        "properties": {
            "ruleset_id": {"type": "string", "const": CONTRACT_VERSION},
            "slug": {"type": "string"},
            "topic": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "video_type": (
                {"type": "string", "const": video_type}
                if video_type in {"short", "long"}
                else {"type": "string", "enum": ["short", "long"]}
            ),
            "target_minutes": {"type": "number", "exclusiveMinimum": 0},
            "voice_profile": {"type": "string"},
            "thumbnail_brief": {"type": "object"},
            "strategy": {"type": "object"},
            "sections": {"type": "array", "items": section, **section_bounds},
            "compliance": {"type": "object"},
        },
        "required": required,
        "additionalProperties": True,
    }
