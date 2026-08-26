"""Load topic-scoped content profiles from self-contained directories.

A content profile owns editorial rules, format contracts, provider choices,
voice cast, and local render assets for one topic.  The workflow/DAG remains
shared.  This is deliberately separate from ``platform.profiles``: a content
profile answers *what/how we tell*, while a platform profile answers *where we
publish*.
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


_PROFILE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ContentProfileError(ValueError):
    """A profile directory is missing, unsafe, or violates its schema."""


@dataclass(frozen=True)
class FormatProfile:
    viewer_min_sec: float
    viewer_max_sec: float
    min_sections: int
    max_sections: int

    def __post_init__(self) -> None:
        if self.viewer_min_sec <= 0 or self.viewer_max_sec <= self.viewer_min_sec:
            raise ContentProfileError("Format cần viewer_min_sec < viewer_max_sec và đều dương.")
        if self.min_sections < 1:
            raise ContentProfileError("Format cần ít nhất một section.")
        if self.max_sections < self.min_sections:
            raise ContentProfileError("Format cần max_sections >= min_sections.")

    @property
    def viewer_runtime_bounds_sec(self) -> tuple[float, float]:
        return self.viewer_min_sec, self.viewer_max_sec


@dataclass(frozen=True)
class ProviderProfile:
    llm: str
    tts: str
    render: str
    broll_strategy: str
    broll_allow_downloads: bool
    # Hệ số bù tốc độ đọc thật của profile so với hằng số CPM chung của
    # provider. Đo được ~7-8% chênh lệch có hệ thống cho ban-so-6 (hội thoại
    # nhiều giọng, chuyển giọng giữa các segment có overhead mà hằng số CPM
    # đo trên kênh 1-giọng không tính tới) qua hai lần render Long thật.
    tts_pace_factor: float = 1.0

    def __post_init__(self) -> None:
        if not (0 < self.tts_pace_factor <= 2):
            raise ContentProfileError("providers.tts_pace_factor phải nằm trong (0, 2].")


@dataclass(frozen=True)
class ContentRules:
    require_pexels_query: bool
    require_short_source_trace: bool
    require_conversation_turns: bool = False


# The explainer taxonomy every schema-version-1 profile relied on before
# `editorial_contract` existed. Kept ONLY as the compatibility default for a
# profile.json that does not declare its own purpose_vocabulary/required_purposes
# — a new narrative form (interview, panel, diary...) must never be forced
# through this vocabulary just because the field is absent.
_LEGACY_PURPOSE_VOCABULARY: tuple[str, ...] = (
    "situation", "core_answer", "evidence", "application", "payoff",
)
_LEGACY_REQUIRED_PURPOSES: Mapping[str, tuple[str, ...]] = {
    "short": ("situation", "core_answer", "application", "payoff"),
    "long": ("situation", "core_answer", "evidence", "application", "payoff"),
}


@dataclass(frozen=True)
class PurposePolicy:
    """Closed section-purpose vocabulary + which purposes each format requires.

    Declared by the profile so the generation schema, the offline preflight
    gate, and the pre-publish release gate can agree on one vocabulary without
    core code branching on narrative_mode or profile_id.
    """

    vocabulary: tuple[str, ...]
    required: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.vocabulary:
            raise ContentProfileError("editorial_contract.purpose_vocabulary không được rỗng.")
        for video_type, required in self.required.items():
            if video_type not in ("short", "long"):
                raise ContentProfileError(
                    f"editorial_contract.required_purposes có video_type không hợp lệ: {video_type!r}."
                )
            unknown = [purpose for purpose in required if purpose not in self.vocabulary]
            if unknown:
                raise ContentProfileError(
                    "editorial_contract.required_purposes."
                    f"{video_type} chứa purpose ngoài vocabulary: {unknown}."
                )

    def required_for(self, video_type: str) -> tuple[str, ...]:
        return self.required.get((video_type or "").strip().lower(), ())


@dataclass(frozen=True)
class EditorialContractProfile:
    """The profile-declared editorial policy shared by every LLM entry path:
    initial generation, repair, Long extension, and Short expansion."""

    purpose_policy: PurposePolicy
    # Seam for migrating off the "narrator" sentinel identity. Every existing
    # v1 profile still uses the literal "narrator" default, so this alone does
    # not change behaviour; it lets a future profile declare a different
    # narration speaker id without a core code change.
    narration_speaker_id: str = "narrator"

    def __post_init__(self) -> None:
        if not self.narration_speaker_id.strip():
            raise ContentProfileError("editorial_contract.narration_speaker_id không được rỗng.")


_LEGACY_EDITORIAL_CONTRACT = EditorialContractProfile(
    purpose_policy=PurposePolicy(
        vocabulary=_LEGACY_PURPOSE_VOCABULARY, required=_LEGACY_REQUIRED_PURPOSES,
    ),
)


@dataclass(frozen=True)
class RenderProfile:
    assets_dir_name: str
    show_captions: bool
    inter_segment_gap_sec: float
    transition_overlap_sec: float
    scene_assets: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.inter_segment_gap_sec) or not 0 <= self.inter_segment_gap_sec <= 2:
            raise ContentProfileError("render.inter_segment_gap_sec phải nằm trong [0, 2].")
        if not isfinite(self.transition_overlap_sec) or not 0 <= self.transition_overlap_sec <= 2:
            raise ContentProfileError("render.transition_overlap_sec phải nằm trong [0, 2].")


@dataclass(frozen=True)
class ContentProfile:
    profile_id: str
    version: str
    display_name: str
    topic: str
    narrative_mode: str
    root: Path
    prompts: Mapping[str, str]
    formats: Mapping[str, FormatProfile]
    providers: ProviderProfile
    voice_cast: Mapping[str, str]
    content_rules: ContentRules
    render: RenderProfile
    visual_generation: "VisualGenerationProfile | None" = None
    editorial_contract: EditorialContractProfile = field(default=_LEGACY_EDITORIAL_CONTRACT)
    editorial_review: "EditorialReviewProfile | None" = None

    def editorial_review_rubric_text(self) -> str:
        if self.editorial_review is None:
            raise ContentProfileError(f"Profile '{self.profile_id}' không bật editorial_review.")
        return self.prompt_text(self.editorial_review.rubric_prompt_name)

    def character_reference_path(self, character_id: str) -> Path:
        vg = self.visual_generation
        if vg is None or character_id not in vg.characters:
            raise ContentProfileError(
                f"Profile '{self.profile_id}' không có ảnh neo cho nhân vật '{character_id}'."
            )
        return _safe_child(
            self.assets_dir, vg.characters[character_id],
            field=f"visual_generation.characters.{character_id}",
        )

    def duo_reference_path(self) -> Path:
        vg = self.visual_generation
        if vg is None or not vg.duo_reference_image:
            raise ContentProfileError(
                f"Profile '{self.profile_id}' không khai duo_reference_image."
            )
        return _safe_child(
            self.assets_dir, vg.duo_reference_image, field="visual_generation.duo_reference_image"
        )

    def format_for(self, video_type: str) -> FormatProfile:
        try:
            return self.formats[video_type.strip().lower()]
        except (AttributeError, KeyError) as exc:
            raise ContentProfileError(
                f"Profile '{self.profile_id}' không hỗ trợ format {video_type!r}."
            ) from exc

    def prompt_text(self, name: str) -> str:
        try:
            relative = self.prompts[name]
        except KeyError as exc:
            raise ContentProfileError(
                f"Profile '{self.profile_id}' thiếu prompt '{name}'."
            ) from exc
        path = _safe_child(self.root, relative, field=f"prompts.{name}")
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ContentProfileError(f"Không đọc được prompt profile: {path}") from exc

    def voice_for(self, speaker_id: str) -> str:
        normalized = (speaker_id or self.editorial_contract.narration_speaker_id).strip().lower()
        try:
            return self.voice_cast[normalized]
        except KeyError as exc:
            raise ContentProfileError(
                f"Profile '{self.profile_id}' không khai báo voice cho speaker '{normalized}'."
            ) from exc

    @property
    def assets_dir(self) -> Path:
        return _safe_child(self.root, self.render.assets_dir_name, field="render.assets_dir")

    @property
    def visual_asset_names(self) -> tuple[str, ...]:
        if self.render.scene_assets:
            return self.render.scene_assets
        if not self.assets_dir.is_dir():
            return ()
        return tuple(sorted(
            path.name for path in self.assets_dir.iterdir()
            if path.is_file() and not path.name.startswith(".")
        ))

    def visual_asset_path(self, relative: str) -> Path:
        relative = relative.strip()
        if self.render.scene_assets and relative not in self.render.scene_assets:
            raise ContentProfileError(
                f"visual_asset {relative!r} không nằm trong render.scene_assets "
                f"của profile '{self.profile_id}'."
            )
        path = _safe_child(self.assets_dir, relative, field="sections.visual_asset")
        if not relative or not path.is_file():
            raise ContentProfileError(f"Không tìm thấy visual_asset: {path}")
        return path


@dataclass(frozen=True)
class EditorialReviewProfile:
    """Opt-in LLM narrative-quality gate, scoped to this profile's own rubric.

    Deterministic `script_contract` validation only checks schema/cast/turn
    shape — it cannot judge dialogue quality, narrator discipline, or
    timeline sense. This is a SEPARATE, optional LLM review a profile can
    turn on; absent (`enabled=False` or the block missing entirely), zero
    extra LLM calls are made and behaviour is unchanged from before this
    field existed.
    """

    enabled: bool
    # Key into `ContentProfile.prompts` — resolved via `profile.prompt_text()`,
    # same lookup every other declared prompt already uses.
    rubric_prompt_name: str

    def __post_init__(self) -> None:
        if self.enabled and not self.rubric_prompt_name.strip():
            raise ContentProfileError(
                "editorial_review.rubric_prompt_name không được rỗng khi enabled=true."
            )


@dataclass(frozen=True)
class VisualGenerationProfile:
    """Local ComfyUI/IPAdapter identity-anchored scene generation.

    Only meaningful for narrative_mode == "character_story": a mechanism
    explainer has no recurring cast, so there is no identity to anchor.
    `load_content_profile` enforces that gate.
    """

    enabled: bool
    style_prompt: str
    negative_prompt: str
    steps: int
    cfg: float
    solo_weight: float
    duo_weight: float
    duo_denoise: float
    characters: Mapping[str, str]
    duo_reference_image: str

    def __post_init__(self) -> None:
        if self.steps < 1:
            raise ContentProfileError("visual_generation.steps phải >= 1.")
        if not (0 < self.cfg <= 30):
            raise ContentProfileError("visual_generation.cfg phải nằm trong (0, 30].")
        if not (0 <= self.solo_weight <= 2):
            raise ContentProfileError("visual_generation.solo_weight phải nằm trong [0, 2].")
        if not (0 <= self.duo_weight <= 2):
            raise ContentProfileError("visual_generation.duo_weight phải nằm trong [0, 2].")
        if not (0 < self.duo_denoise <= 1):
            raise ContentProfileError("visual_generation.duo_denoise phải nằm trong (0, 1].")


def profiles_root(profiles_dir: Path | str | None = None) -> Path:
    if profiles_dir is None:
        from .config.settings import settings

        profiles_dir = settings.content_profiles_dir
    path = Path(profiles_dir)
    return path if path.is_absolute() else _PROJECT_ROOT / path


def load_content_profile(
    profile_id: str | None = None, *, profiles_dir: Path | str | None = None
) -> ContentProfile:
    if profile_id is None:
        from .config.settings import settings

        profile_id = settings.content_profile_id
    profile_id = str(profile_id).strip()
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ContentProfileError(f"Content profile id không hợp lệ: {profile_id!r}.")

    root = profiles_root(profiles_dir).resolve()
    folder = (root / profile_id).resolve()
    if folder.parent != root:
        raise ContentProfileError(f"Content profile id không hợp lệ: {profile_id!r}.")
    config_path = _safe_child(folder, "profile.json", field="profile.json")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContentProfileError(f"Không tìm thấy content profile '{profile_id}': {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContentProfileError(f"profile.json không phải JSON hợp lệ: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ContentProfileError(f"profile.json phải là object: {config_path}")
    if raw.get("profile_id") != profile_id:
        raise ContentProfileError(
            f"profile_id trong {config_path} phải khớp tên thư mục '{profile_id}'."
        )
    if raw.get("schema_version") != 1:
        raise ContentProfileError(f"Profile '{profile_id}' cần schema_version=1.")

    prompts = _string_map(raw.get("prompts"), "prompts")
    formats_raw = _mapping(raw.get("formats"), "formats")
    formats = {
        name: _format_profile(value, f"formats.{name}")
        for name, value in formats_raw.items()
        if name in {"short", "long"}
    }
    if set(formats) != {"short", "long"}:
        raise ContentProfileError(f"Profile '{profile_id}' phải khai báo short và long.")
    providers_raw = _mapping(raw.get("providers"), "providers")
    rules_raw = _mapping(raw.get("content_rules"), "content_rules")
    render_raw = _mapping(raw.get("render"), "render")
    voice_cast = _string_map(raw.get("voice_cast"), "voice_cast")
    editorial_contract = _editorial_contract_profile(raw.get("editorial_contract"))
    if editorial_contract.narration_speaker_id not in voice_cast:
        raise ContentProfileError(
            f"Profile '{profile_id}' phải có voice_cast.{editorial_contract.narration_speaker_id}."
        )

    profile = ContentProfile(
        profile_id=profile_id,
        version=_required_text(raw, "version"),
        display_name=_required_text(raw, "display_name"),
        topic=_required_text(raw, "topic"),
        narrative_mode=_required_text(raw, "narrative_mode"),
        root=folder,
        prompts=prompts,
        formats=formats,
        providers=ProviderProfile(
            llm=_required_text(providers_raw, "llm", prefix="providers"),
            tts=_required_text(providers_raw, "tts", prefix="providers"),
            render=_required_text(providers_raw, "render", prefix="providers"),
            broll_strategy=_required_text(
                providers_raw, "broll_strategy", prefix="providers"
            ),
            broll_allow_downloads=_exact_bool(
                providers_raw, "broll_allow_downloads", prefix="providers"
            ),
            tts_pace_factor=_finite_number(
                providers_raw, "tts_pace_factor", prefix="providers", default=1.0
            ),
        ),
        voice_cast=voice_cast,
        content_rules=ContentRules(
            require_pexels_query=_exact_bool(
                rules_raw, "require_pexels_query", prefix="content_rules"
            ),
            require_short_source_trace=_exact_bool(
                rules_raw, "require_short_source_trace", prefix="content_rules"
            ),
            require_conversation_turns=_exact_bool(
                rules_raw, "require_conversation_turns", prefix="content_rules"
            ),
        ),
        render=RenderProfile(
            assets_dir_name=_required_text(render_raw, "assets_dir", prefix="render"),
            show_captions=_exact_bool(render_raw, "show_captions", prefix="render"),
            inter_segment_gap_sec=_finite_number(
                render_raw, "inter_segment_gap_sec", prefix="render"
            ),
            transition_overlap_sec=_finite_number(
                render_raw, "transition_overlap_sec", prefix="render"
            ),
            scene_assets=_string_tuple(render_raw.get("scene_assets", ()), "render.scene_assets"),
        ),
        visual_generation=_visual_generation_profile(raw.get("visual_generation"), profile_id),
        editorial_contract=editorial_contract,
        editorial_review=_editorial_review_profile(raw.get("editorial_review")),
    )
    if (
        profile.narrative_mode == "character_story"
        and profile.render.inter_segment_gap_sec < profile.render.transition_overlap_sec
    ):
        raise ContentProfileError(
            "Story profile cần inter_segment_gap_sec >= transition_overlap_sec "
            "để lời thoại hai nhân vật không chồng lên nhau."
        )
    if profile.visual_generation is not None and profile.narrative_mode != "character_story":
        raise ContentProfileError(
            f"Profile '{profile_id}' bật visual_generation nhưng narrative_mode không phải "
            "'character_story'. Tính năng chỉ áp dụng cho profile series kể truyện."
        )
    for name in prompts:
        profile.prompt_text(name)
    if (
        profile.editorial_review is not None
        and profile.editorial_review.enabled
        and profile.editorial_review.rubric_prompt_name not in profile.prompts
    ):
        raise ContentProfileError(
            f"Profile '{profile_id}': editorial_review.rubric_prompt_name "
            f"'{profile.editorial_review.rubric_prompt_name}' phải là một key trong prompts."
        )
    if not profile.assets_dir.is_dir():
        raise ContentProfileError(
            f"Profile '{profile_id}' thiếu thư mục asset: {profile.assets_dir}"
        )
    for asset_name in profile.render.scene_assets:
        profile.visual_asset_path(asset_name)
    if profile.visual_generation is not None and profile.visual_generation.enabled:
        for character_id in profile.visual_generation.characters:
            if (
                character_id == profile.editorial_contract.narration_speaker_id
                or character_id not in profile.voice_cast
            ):
                raise ContentProfileError(
                    f"Profile '{profile_id}': visual_generation.characters['{character_id}'] "
                    "phải là một nhân vật khai trong voice_cast (khác narrator)."
                )
            path = profile.character_reference_path(character_id)
            if not path.is_file():
                raise ContentProfileError(f"Không tìm thấy ảnh neo nhận dạng: {path}")
        if profile.visual_generation.duo_reference_image:
            duo_path = profile.duo_reference_path()
            if not duo_path.is_file():
                raise ContentProfileError(f"Không tìm thấy duo_reference_image: {duo_path}")
    return profile


def _editorial_review_profile(raw: Any) -> "EditorialReviewProfile | None":
    if raw is None:
        return None
    mapping = _mapping(raw, "editorial_review")
    return EditorialReviewProfile(
        enabled=_exact_bool(mapping, "enabled", prefix="editorial_review"),
        rubric_prompt_name=str(mapping.get("rubric_prompt_name") or "").strip(),
    )


def _visual_generation_profile(raw: Any, profile_id: str) -> "VisualGenerationProfile | None":
    if raw is None:
        return None
    mapping = _mapping(raw, "visual_generation")
    return VisualGenerationProfile(
        enabled=_exact_bool(mapping, "enabled", prefix="visual_generation"),
        style_prompt=_required_text(mapping, "style_prompt", prefix="visual_generation"),
        negative_prompt=_required_text(mapping, "negative_prompt", prefix="visual_generation"),
        steps=_positive_int(mapping, "steps", path="visual_generation"),
        cfg=_finite_number(mapping, "cfg", prefix="visual_generation"),
        solo_weight=_finite_number(mapping, "solo_weight", prefix="visual_generation"),
        duo_weight=_finite_number(mapping, "duo_weight", prefix="visual_generation"),
        duo_denoise=_finite_number(mapping, "duo_denoise", prefix="visual_generation"),
        characters=_string_map(mapping.get("characters"), "visual_generation.characters"),
        duo_reference_image=str(mapping.get("duo_reference_image") or "").strip(),
    )


def _editorial_contract_profile(raw: Any) -> EditorialContractProfile:
    if raw is None:
        return _LEGACY_EDITORIAL_CONTRACT
    mapping = _mapping(raw, "editorial_contract")
    vocabulary = (
        _string_tuple(mapping["purpose_vocabulary"], "editorial_contract.purpose_vocabulary")
        if "purpose_vocabulary" in mapping
        else _LEGACY_PURPOSE_VOCABULARY
    )
    if "required_purposes" in mapping:
        required_raw = _mapping(mapping["required_purposes"], "editorial_contract.required_purposes")
        required = {
            key: _string_tuple(value, f"editorial_contract.required_purposes.{key}")
            for key, value in required_raw.items()
        }
    else:
        required = dict(_LEGACY_REQUIRED_PURPOSES)
    narration_speaker_id = (
        _required_text(mapping, "narration_speaker_id", prefix="editorial_contract")
        if "narration_speaker_id" in mapping
        else "narrator"
    )
    return EditorialContractProfile(
        purpose_policy=PurposePolicy(vocabulary=vocabulary, required=required),
        narration_speaker_id=narration_speaker_id,
    )


def profile_fingerprint(profile: ContentProfile) -> str:
    """Hash every profile input that can change narration, voice, or render."""
    paths = [profile.root / "profile.json"]
    paths.extend(
        _safe_child(profile.root, relative, field=f"prompts.{name}")
        for name, relative in profile.prompts.items()
    )
    paths.extend(profile.visual_asset_path(name) for name in profile.visual_asset_names)
    if profile.visual_generation is not None:
        paths.append(profile.root / "profile.json")  # visual_generation block itself
        paths.extend(
            profile.character_reference_path(name) for name in profile.visual_generation.characters
        )
        if profile.visual_generation.duo_reference_image:
            paths.append(profile.duo_reference_path())
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(profile.root).as_posix()):
        relative = path.relative_to(profile.root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def profile_environment(profile: ContentProfile) -> dict[str, str]:
    """Environment overlay consumed by one isolated pipeline subprocess."""
    short = profile.format_for("short")
    long = profile.format_for("long")
    return {
        "CONTENT_PROFILE_ID": profile.profile_id,
        "CONTENT_PROFILES_DIR": str(profile.root.parent),
        "LLM_PROVIDER": profile.providers.llm,
        "TTS_PROVIDER": profile.providers.tts,
        "RENDER_PROVIDER": profile.providers.render,
        "BROLL_STRATEGY": profile.providers.broll_strategy,
        # Compatibility capability used by doctor; story rendering never calls
        # VideoProvider because BROLL_STRATEGY=none and RenderProvider=story.
        "VIDEO_PROVIDER": "pexels",
        "BROLL_ALLOW_DOWNLOADS": str(profile.providers.broll_allow_downloads).lower(),
        "SHOW_CAPTIONS": str(profile.render.show_captions).lower(),
        "PROFILE_INTER_SEGMENT_GAP_SEC": str(profile.render.inter_segment_gap_sec),
        "PROFILE_TRANSITION_OVERLAP_SEC": str(profile.render.transition_overlap_sec),
        "XKIRO_VOICE": profile.voice_for(profile.editorial_contract.narration_speaker_id),
        "SHORT_VIEWER_MIN_SEC": str(short.viewer_min_sec),
        "SHORT_VIEWER_MAX_SEC": str(short.viewer_max_sec),
        "SHORT_MIN_SECTIONS": str(short.min_sections),
        "SHORT_MAX_SECTIONS": str(short.max_sections),
        "LONG_VIEWER_MIN_SEC": str(long.viewer_min_sec),
        "LONG_VIEWER_MAX_SEC": str(long.viewer_max_sec),
        "LONG_MIN_SECTIONS": str(long.min_sections),
        "LONG_MAX_SECTIONS": str(long.max_sections),
    }


def _safe_child(root: Path, relative: str, *, field: str) -> Path:
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ContentProfileError(f"{field} không được đi ra ngoài thư mục profile.")
    return path


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentProfileError(f"{field} phải là object.")
    return value


def _string_map(value: Any, field: str) -> Mapping[str, str]:
    mapping = _mapping(value, field)
    result = {str(key).strip(): str(item).strip() for key, item in mapping.items()}
    if not result or not all(result) or not all(result.values()):
        raise ContentProfileError(f"{field} không được rỗng.")
    return result


def _required_text(mapping: Mapping[str, Any], field: str, *, prefix: str = "") -> str:
    raw = mapping.get(field)
    if not isinstance(raw, str) or not raw.strip():
        path = f"{prefix}.{field}" if prefix else field
        raise ContentProfileError(f"Profile thiếu field {path}.")
    return raw.strip()


def _exact_bool(
    mapping: Mapping[str, Any], field: str, *, prefix: str = "", default: bool = False
) -> bool:
    raw = mapping.get(field, default)
    if type(raw) is not bool:
        path = f"{prefix}.{field}" if prefix else field
        raise ContentProfileError(f"{path} phải là JSON boolean.")
    return raw


def _finite_number(
    mapping: Mapping[str, Any], field: str, *, prefix: str = "", default: float = 0.0
) -> float:
    raw = mapping.get(field, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(float(raw)):
        path = f"{prefix}.{field}" if prefix else field
        raise ContentProfileError(f"{path} phải là số hữu hạn.")
    return float(raw)


def _positive_int(mapping: Mapping[str, Any], field: str, *, path: str) -> int:
    raw = mapping.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ContentProfileError(f"{path}.{field} phải là số nguyên dương.")
    return raw


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContentProfileError(f"{field} phải là array string không rỗng.")
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        raise ContentProfileError(f"{field} không được chứa tên trùng.")
    return result


def _format_profile(value: Any, field: str) -> FormatProfile:
    mapping = _mapping(value, field)
    try:
        return FormatProfile(
            viewer_min_sec=_finite_number(mapping, "viewer_min_sec", prefix=field),
            viewer_max_sec=_finite_number(mapping, "viewer_max_sec", prefix=field),
            min_sections=_positive_int(mapping, "min_sections", path=field),
            max_sections=(
                _positive_int(mapping, "max_sections", path=field)
                if "max_sections" in mapping
                else _positive_int(mapping, "min_sections", path=field)
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContentProfileError(f"{field} thiếu hoặc sai kiểu.") from exc
