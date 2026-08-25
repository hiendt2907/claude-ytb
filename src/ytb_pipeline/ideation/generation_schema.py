"""JSON Schema used to constrain local LLM script generation at the API boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..content_contract import CONTRACT_VERSION, contract_for

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile

# The one vocabulary the prompt teaches, the schema enforces, and the
# pre-publish quality gate checks against.
SECTION_PURPOSES = ("situation", "core_answer", "evidence", "application", "payoff")


def script_generation_schema(
    video_type: str | None = None, *, content_profile: "ContentProfile | None" = None
) -> dict[str, Any]:
    """Return the reusable envelope schema for both Short and Long scripts.

    Editorial rules remain in the contract/QA layers.  This schema has one job:
    prevent a model from emitting strings or loose field names inside
    ``sections`` where the pipeline requires objects.
    """
    nullable_string = {"type": ["string", "null"]}
    section_contract = (
        contract_for(video_type, content_profile)
        if video_type in {"short", "long"}
        else None
    )
    section_bounds: dict[str, int] = {}
    if section_contract is not None:
        section_bounds["minItems"] = section_contract.minimum_sections
        # Shorts are a fixed six-beat format.  Longs permit limited editorial
        # variation but remain bounded so model output cannot exceed the
        # timing contract with a proliferation of tiny sections.
        section_bounds["maxItems"] = (
            content_profile.format_for(video_type).max_sections
            if content_profile is not None
            else section_contract.minimum_sections
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
            "speaker_id": {"type": "string"},
            "visual_asset": {"type": "string"},
            "caption": nullable_string,
            "hook": {"type": ["string", "boolean", "null"]},
            "transition": nullable_string,
            "payoff": nullable_string,
            "emphasis": nullable_string,
        },
        "required": [
            "purpose", "time_goal", "voiceover", "visual_intent",
            "caption", "hook", "transition", "payoff", "emphasis",
        ],
        "additionalProperties": True,
    }
    if content_profile is None or content_profile.content_rules.require_pexels_query:
        section["required"].append("pexels_query")
    if content_profile is not None and content_profile.narrative_mode == "character_story":
        section["required"].extend(("speaker_id", "visual_asset"))
        section["properties"]["speaker_id"] = {
            "type": "string",
            "enum": sorted(content_profile.voice_cast),
        }
    required = [
        "ruleset_id", "slug", "topic", "title", "description", "tags",
        "video_type", "voice_profile", "thumbnail_brief", "sections", "compliance",
    ]
    if (
        video_type == "short"
        and (
            content_profile is None
            or content_profile.content_rules.require_short_source_trace
        )
    ):
        required.append("strategy")
    elif video_type == "long":
        required.append("target_minutes")
    properties: dict[str, Any] = {
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
    }
    if content_profile is not None:
        properties.update({
            "profile_id": {"type": "string", "const": content_profile.profile_id},
            "profile_version": {"type": "string", "const": content_profile.version},
        })
        required.extend(("profile_id", "profile_version"))
    if content_profile is not None and content_profile.narrative_mode == "character_story":
        # Ghi bởi chính tập vừa viết: model đang biết tập này thay đổi những gì.
        # Hỏi lại sau khi publish sẽ là bịa. Ledger chỉ chép lại tuyên bố này.
        properties["continuity"] = {
            "type": "object",
            "properties": {
                "episode_summary": {"type": "string"},
                "character_changes": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "threads_opened": {"type": "array", "items": {"type": "string"}},
                "threads_closed": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "episode_summary", "character_changes", "threads_opened", "threads_closed",
            ],
            "additionalProperties": False,
        }
        required.append("continuity")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }
