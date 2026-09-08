"""Deterministic release-schema validation for raw script payloads.

The loader deliberately accepts legacy JSON so existing drafts remain readable.
This module has the opposite responsibility: identify whether an unmodified raw
payload is publishable under the current content contract.  It never repairs or
normalizes its input; callers receive structured findings they can surface to a
writer or an automated repair step.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal, Mapping

from ..content_contract import CONTRACT_VERSION, contract_for
from ..content_profiles import ContentProfile, ContentProfileError, load_content_profile


Profile = Literal["current", "legacy"]


@dataclass(frozen=True)
class ScriptContractFinding:
    """One deterministic schema violation in a raw script payload."""

    rule: str
    path: str
    message: str


@dataclass(frozen=True)
class ScriptContractResult:
    """Non-throwing outcome of a release-schema check."""

    profile: Profile
    publishable: bool
    findings: tuple[ScriptContractFinding, ...]

    @property
    def is_publishable(self) -> bool:
        """Readable alias for callers that use predicate-style checks."""
        return self.publishable


def validate_script_payload(payload: Mapping[str, Any] | object) -> ScriptContractResult:
    """Return whether *payload* satisfies the current publish schema.

    A non-current ruleset is always classified as ``legacy`` and is explicitly
    nonpublishable.  We intentionally stop there: applying current required
    fields to a legacy draft produces a noisy, misleading report and can make a
    compatibility reader look like a release approval gate.
    """
    if not isinstance(payload, Mapping):
        return _legacy_result("payload", "Payload phải là object JSON.")

    if _text(payload.get("ruleset_id")) != CONTRACT_VERSION:
        return _legacy_result(
            "ruleset_id",
            f"Payload publishable phải dùng ruleset_id={CONTRACT_VERSION!r}.",
        )

    findings: list[ScriptContractFinding] = []
    content_profile = None
    declared_profile_id = _text(payload.get("profile_id"))
    declared_version = _text(payload.get("profile_version"))
    if declared_profile_id:
        try:
            content_profile = load_content_profile(
                declared_profile_id, version=declared_version or None,
            )
        except ContentProfileError as exc:
            _add(findings, "profile.valid", "profile_id", str(exc))
            return ScriptContractResult("current", False, tuple(findings))
    if content_profile is not None:
        if not declared_version:
            _add(
                findings,
                "profile.version_required",
                "profile_version",
                "Script có profile_id phải khai báo profile_version.",
            )
        elif declared_version != content_profile.version:
            _add(
                findings,
                "profile.version_matches",
                "profile_version",
                f"profile_version phải là {content_profile.version!r}.",
            )
    video_type = _text(payload.get("video_type")).lower()
    if video_type not in ("short", "long"):
        _add(
            findings,
            "video_type.supported",
            "video_type",
            "video_type phải là 'short' hoặc 'long'.",
        )
        _validate_thumbnail(payload.get("thumbnail_brief"), findings)
        _validate_sections(payload.get("sections"), findings, None, content_profile)
        return ScriptContractResult("current", False, tuple(findings))

    contract = contract_for(video_type, content_profile)
    _validate_target(payload, video_type, findings, content_profile)
    _validate_thumbnail(payload.get("thumbnail_brief"), findings)
    sections = _validate_sections(
        payload.get("sections"), findings, contract.minimum_sections, content_profile,
        maximum_sections=(
            content_profile.format_for(video_type).max_sections
            if content_profile is not None else None
        ),
    )
    if video_type == "short" and (
        content_profile is None
        or content_profile.content_rules.require_short_source_trace
    ):
        _validate_short_strategy(payload.get("strategy"), sections, findings)

    return ScriptContractResult("current", not findings, tuple(findings))


def validate_payload(payload: Mapping[str, Any] | object) -> ScriptContractResult:
    """Compatibility-friendly short name for :func:`validate_script_payload`."""
    return validate_script_payload(payload)


def validate_script_contract(payload: Mapping[str, Any] | object) -> ScriptContractResult:
    """Explicit alias for integrations that name the gate after its contract."""
    return validate_script_payload(payload)


def _legacy_result(path: str, message: str) -> ScriptContractResult:
    return ScriptContractResult(
        profile="legacy",
        publishable=False,
        findings=(ScriptContractFinding("ruleset_id.current", path, message),),
    )


def _validate_target(
    payload: Mapping[str, Any], video_type: str, findings: list[ScriptContractFinding],
    content_profile: ContentProfile | None = None,
) -> None:
    target = payload.get("target_minutes")
    if video_type == "short":
        if target is not None:
            _add(
                findings,
                "target_minutes.short_absent",
                "target_minutes",
                "Short không được khai báo target_minutes.",
            )
        return

    if not _positive_number(target):
        _add(
            findings,
            "target_minutes.long_required",
            "target_minutes",
            "Long phải có target_minutes là số dương.",
        )
        return
    lower_sec, upper_sec = contract_for("long", content_profile).viewer_runtime_bounds_sec
    if not lower_sec / 60 <= float(target) <= upper_sec / 60:
        _add(
            findings,
            "target_minutes.long_within_contract",
            "target_minutes",
            f"target_minutes của Long phải nằm trong [{lower_sec / 60:g}, {upper_sec / 60:g}].",
        )


def _validate_thumbnail(raw: object, findings: list[ScriptContractFinding]) -> None:
    if not isinstance(raw, Mapping):
        _add(
            findings,
            "thumbnail_brief.required",
            "thumbnail_brief",
            "Payload publishable phải có object thumbnail_brief.",
        )
        return
    for field in ("visual_contradiction", "subject", "emotion", "headline"):
        if not _text(raw.get(field)):
            _add(
                findings,
                f"thumbnail_brief.{field}.required",
                f"thumbnail_brief.{field}",
                f"thumbnail_brief.{field} không được để trống.",
            )


# Lặp nguyên văn một câu ngắn có thể là chủ ý ("Minh mở laptop."); lặp nguyên
# một đoạn dài thì không — đó là dấu hiệu bước vá đã chép lại nội dung cũ.
_DUPLICATE_SECTION_MIN_CHARS = 60


def _normalised_narration(section: Any) -> str:
    if not isinstance(section, Mapping):
        return ""
    text = _text(section.get("voiceover")) or _text(section.get("narration"))
    return " ".join(text.lower().split())


def _check_duplicate_sections(raw: list, findings: list[ScriptContractFinding]) -> None:
    """Chặn hai section mang cùng một lời đọc.

    Bước vá Long ("extend") từng trả lời bằng cách phát lại nguyên phần mở đầu:
    section 16-22 trùng từng chữ với 0-6. Mọi cổng khác đều qua — thời lượng,
    số section, purpose, preflight — vì không cổng nào so các section VỚI NHAU,
    nên video sẽ đọc lại hai phút đầu.
    """
    seen: dict[str, int] = {}
    for index, section in enumerate(raw):
        narration = _normalised_narration(section)
        if len(narration) < _DUPLICATE_SECTION_MIN_CHARS:
            continue
        first = seen.get(narration)
        if first is None:
            seen[narration] = index
            continue
        _add(
            findings,
            "sections.duplicate",
            f"sections[{index}]",
            f"Lời đọc trùng nguyên văn với section {first + 1}; mỗi section phải mang nội dung mới.",
        )


def _validate_scene_characters(
    raw: Any, content_profile: ContentProfile, path: str, findings: list[ScriptContractFinding],
) -> None:
    """scene_characters phải TỒN TẠI (rỗng hợp lệ = cảnh không người) và mỗi
    tên phải thuộc cast của profile, khác narrator, không lặp, tối đa 2."""
    if raw is None:
        _add(findings, f"{path}.scene_characters.required", f"{path}.scene_characters", "scene_characters không được thiếu (dùng [] nếu cảnh không có nhân vật).")
        return
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        _add(findings, f"{path}.scene_characters.type", f"{path}.scene_characters", "scene_characters phải là mảng chuỗi.")
        return
    if len(raw) > 2:
        _add(findings, f"{path}.scene_characters.max", f"{path}.scene_characters", "scene_characters tối đa 2 nhân vật trong một khung hình.")
    if len(set(raw)) != len(raw):
        _add(findings, f"{path}.scene_characters.duplicate", f"{path}.scene_characters", "scene_characters không được lặp tên.")
    cast = {
        name for name in content_profile.voice_cast
        if name != content_profile.editorial_contract.narration_speaker_id
    }
    for name in raw:
        if name not in cast:
            _add(
                findings, f"{path}.scene_characters.unknown", f"{path}.scene_characters",
                f"'{name}' không nằm trong voice_cast của profile '{content_profile.profile_id}'.",
            )


def _validate_conversation_turn(
    section: Mapping[str, Any],
    content_profile: ContentProfile,
    *,
    section_index: int,
    path: str,
    findings: list[ScriptContractFinding],
) -> None:
    """Enforce profile-owned conversation planning metadata.

    This is deliberately profile-configured, not keyed to a cast name or a
    series. The shared workflow only knows that a story profile opted into
    explicit speaker-turn ownership before TTS.
    """
    if not content_profile.content_rules.require_conversation_turns:
        return
    if "turn" not in section:
        _add(findings, f"{path}.turn.required", f"{path}.turn", "Story profile yêu cầu field turn cho mọi section.")
        return
    speaker = _text(section.get("speaker_id")).lower()
    turn = section.get("turn")
    if speaker == content_profile.editorial_contract.narration_speaker_id:
        if turn is not None:
            _add(findings, f"{path}.turn.narrator_null", f"{path}.turn", "Narrator phải có turn=null; lời trực tiếp thuộc section nhân vật.")
        return
    if not isinstance(turn, Mapping):
        _add(findings, f"{path}.turn.object", f"{path}.turn", "Section nhân vật cần turn object gồm scene, intent, responds_to.")
        return
    for field in ("scene", "intent"):
        if not _text(turn.get(field)):
            _add(findings, f"{path}.turn.{field}.required", f"{path}.turn.{field}", f"turn.{field} không được để trống.")
    responds_to = turn.get("responds_to")
    if responds_to is None:
        return
    if isinstance(responds_to, bool) or not isinstance(responds_to, int) or not 1 <= responds_to < section_index:
        _add(
            findings,
            f"{path}.turn.responds_to.previous_section",
            f"{path}.turn.responds_to",
            "turn.responds_to phải là null hoặc số section 1-based đứng trước lượt hiện tại.",
        )


def _validate_sections(
    raw: object, findings: list[ScriptContractFinding], minimum_sections: int | None,
    content_profile: ContentProfile | None = None,
    maximum_sections: int | None = None,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(raw, list):
        _add(findings, "sections.required", "sections", "sections phải là một mảng.")
        return ()
    if minimum_sections is not None and len(raw) < minimum_sections:
        _add(
            findings,
            "sections.minimum_count",
            "sections",
            f"Cần ít nhất {minimum_sections} section theo content contract.",
        )
    if maximum_sections is not None and len(raw) > maximum_sections:
        _add(
            findings,
            "sections.maximum_count",
            "sections",
            f"Không được vượt quá {maximum_sections} section theo content profile.",
        )

    _check_duplicate_sections(raw, findings)

    sections: list[Mapping[str, Any]] = []
    for index, section in enumerate(raw):
        path = f"sections[{index}]"
        if not isinstance(section, Mapping):
            _add(findings, "sections.object", path, "Mỗi section phải là object.")
            continue
        sections.append(section)
        # `voiceover` is the canonical generation key.  `narration` remains a
        # compatibility alias consumed by the loader, so the release contract
        # accepts either one but never requires both.
        if not (_text(section.get("voiceover")) or _text(section.get("narration"))):
            _add(
                findings,
                f"{path}.voiceover_or_narration.required",
                path,
                "voiceover hoặc narration không được để trống.",
            )
        required_fields = ["purpose", "visual_intent"]
        if content_profile is None or content_profile.content_rules.require_pexels_query:
            required_fields.append("pexels_query")
        auto_visuals = (
            content_profile is not None
            and content_profile.narrative_mode == "character_story"
            and content_profile.visual_generation is not None
            and content_profile.visual_generation.enabled
        )
        if content_profile is not None and content_profile.narrative_mode == "character_story":
            required_fields.append("speaker_id")
            if not auto_visuals:
                required_fields.append("visual_asset")
        for field in required_fields:
            if not _text(section.get(field)):
                _add(
                    findings,
                    f"{path}.{field}.required",
                    f"{path}.{field}",
                    f"{field} không được để trống.",
                )
        if auto_visuals:
            _validate_scene_characters(section.get("scene_characters"), content_profile, path, findings)
        if (
            content_profile is not None
            and content_profile.narrative_mode == "character_story"
            and _text(section.get("speaker_id"))
            and _text(section.get("speaker_id")).lower() not in content_profile.voice_cast
        ):
            _add(
                findings,
                f"{path}.speaker_id.in_voice_cast",
                f"{path}.speaker_id",
                f"speaker_id phải thuộc voice_cast: {sorted(content_profile.voice_cast)}.",
            )
        if content_profile is not None and content_profile.narrative_mode == "character_story":
            _validate_conversation_turn(
                section,
                content_profile,
                section_index=index + 1,
                path=path,
                findings=findings,
            )
        if not _positive_number(section.get("time_goal")):
            _add(
                findings,
                f"{path}.time_goal.positive_number",
                f"{path}.time_goal",
                "time_goal phải là số hữu hạn lớn hơn 0.",
            )
    return tuple(sections)


def _validate_short_strategy(
    raw: object, sections: tuple[Mapping[str, Any], ...], findings: list[ScriptContractFinding]
) -> None:
    if not isinstance(raw, Mapping):
        _add(findings, "strategy.short_required", "strategy", "Short publishable phải có object strategy.")
        return
    for field in (
        "format_id",
        "core_mechanism",
        "audience_problem",
        "angle",
        "long_form_slug",
        "playlist",
        "cta_target",
        "source_long_slug",
        "source_excerpt",
    ):
        if not _text(raw.get(field)):
            _add(
                findings,
                f"strategy.{field}.required",
                f"strategy.{field}",
                f"strategy.{field} không được để trống cho Short.",
            )

    source_index = raw.get("source_section_index")
    if not isinstance(source_index, int) or isinstance(source_index, bool) or source_index < 0:
        _add(
            findings,
            "strategy.source_section_index.nonnegative_integer",
            "strategy.source_section_index",
            "source_section_index phải là số nguyên >= 0.",
        )
    if _text(raw.get("source_long_slug")) != _text(raw.get("long_form_slug")):
        _add(
            findings,
            "strategy.source_long_slug.matches_long_form_slug",
            "strategy.source_long_slug",
            "source_long_slug phải khớp long_form_slug.",
        )

    hook = raw.get("hook")
    if not isinstance(hook, Mapping):
        _add(findings, "strategy.hook.required", "strategy.hook", "Short phải có strategy.hook.")
    else:
        for field in ("situation", "core_answer", "open_loop"):
            if not _text(hook.get(field)):
                _add(
                    findings,
                    f"strategy.hook.{field}.required",
                    f"strategy.hook.{field}",
                    f"strategy.hook.{field} không được để trống.",
                )

    purposes = tuple(_text(section.get("purpose")) for section in sections)
    if purposes[:2] != ("situation", "core_answer"):
        _add(
            findings,
            "sections.short_opening_order",
            "sections",
            "Hai section đầu của Short phải lần lượt là situation và core_answer.",
        )


def _positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _add(findings: list[ScriptContractFinding], rule: str, path: str, message: str) -> None:
    findings.append(ScriptContractFinding(rule=rule, path=path, message=message))
