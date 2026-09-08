"""The single contract a run compiles once and every stage then reads.

Today prompt, QA, repair, judge, render and release gate each hold their own
copy of the rules, kept in sync by nothing. That is how a Long's planned
character window came to sit at 404-504s against a 300-420s gate: the prompt
planned at the raw provider rate while the gate measured at the profile's
corrected one. Compiling once, from one source, is the fix.

`compile_contract` is pure. It takes a settings SNAPSHOT rather than reading the
global `settings`, so the same inputs always give the same contract — which is
what makes the fingerprints trustworthy as invalidation keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from ..content_contract import ContentContract, contract_for
from .capability import ProviderCapabilitySnapshot
from .fingerprint import creative_policy_fingerprint, runtime_binding_fingerprint

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile

CONTRACT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SettingsSnapshot:
    """The subset of `settings` a contract reads, frozen at the run boundary."""

    tts_provider: str
    llm_provider: str
    short_viewer_min_sec: float
    short_viewer_max_sec: float
    short_min_sections: int
    long_viewer_min_sec: float
    long_viewer_max_sec: float
    long_min_sections: int
    e2e_test: bool
    visual_judge_provider: str = ""
    visual_judge_model: str = ""


@dataclass(frozen=True)
class EditorialPolicy:
    enabled: bool
    minimum_score: int
    max_rewrites: int
    rubric_prompt_name: str


@dataclass(frozen=True)
class VisualPolicy:
    enabled: bool
    candidate_count: int
    selection_policy: str
    semantic_rejection_recovery: str
    judge_enabled: bool
    judge_minimum_score: float
    hard_fail_on_judge_error: bool


@dataclass(frozen=True)
class RuntimeBinding:
    """Who actually serves this run, and where each choice came from."""

    llm_provider: str
    tts_provider: str
    render_provider: str
    judge_provider: str
    judge_model: str
    # "profile" or "operator_override" — an override must be traceable, never
    # silently in effect. See visual_assets.resolve_judge_target.
    judge_source: str
    tts_pace_factor: float


@dataclass(frozen=True)
class EffectiveProductionContract:
    """Compiled once per run; every stage reads this instead of its own copy."""

    schema_version: int
    profile_id: str
    profile_version: str
    creative_policy_fingerprint: str
    runtime_binding_fingerprint: str
    content: Mapping[str, ContentContract]
    editorial: EditorialPolicy
    visual: VisualPolicy
    runtime: RuntimeBinding
    capabilities: ProviderCapabilitySnapshot
    generates_shorts: bool = True
    _rates: Mapping[str, float] = field(default_factory=dict)

    def content_for(self, video_type: str) -> ContentContract:
        key = video_type.strip().lower()
        if key not in self.content:
            raise ValueError(f"Contract không có video_type {video_type!r}.")
        return self.content[key]

    def chars_per_min(self, video_type: str) -> float:
        """The rate to PLAN with: provider rate corrected by the profile's pace.

        Planning with the raw provider rate is the defect this contract exists
        to remove — the same character count then measures 27% longer in real
        audio than the prompt assumed.
        """
        key = video_type.strip().lower()
        if key not in self._rates:
            raise ValueError(f"Contract không có video_type {video_type!r}.")
        return self._rates[key]


_DEFAULT_EDITORIAL = EditorialPolicy(
    enabled=False, minimum_score=0, max_rewrites=0, rubric_prompt_name=""
)
# A profile that generates no images still needs a policy object; one candidate
# and fail-closed recovery matches what the resolver does without a visual
# block, so an absent block and an explicit minimal one behave identically.
_DEFAULT_VISUAL = VisualPolicy(
    enabled=False,
    candidate_count=1,
    selection_policy="first_valid",
    semantic_rejection_recovery="fail_closed",
    judge_enabled=False,
    judge_minimum_score=0.0,
    hard_fail_on_judge_error=False,
)


def _editorial_policy(profile: "ContentProfile") -> EditorialPolicy:
    review = profile.editorial_review
    if review is None:
        return _DEFAULT_EDITORIAL
    return EditorialPolicy(
        enabled=review.enabled,
        minimum_score=review.minimum_score,
        max_rewrites=review.max_rewrites,
        rubric_prompt_name=review.rubric_prompt_name,
    )


def _visual_policy(profile: "ContentProfile") -> VisualPolicy:
    generation = profile.visual_generation
    if generation is None:
        return _DEFAULT_VISUAL
    judge = generation.visual_judge
    return VisualPolicy(
        enabled=generation.enabled,
        candidate_count=generation.candidate_count,
        selection_policy=generation.selection_policy,
        semantic_rejection_recovery=generation.semantic_rejection_recovery,
        judge_enabled=judge.enabled if judge is not None else False,
        judge_minimum_score=judge.minimum_score if judge is not None else 0.0,
        hard_fail_on_judge_error=(
            judge.hard_fail_on_judge_error if judge is not None else False
        ),
    )


def _runtime_binding(
    profile: "ContentProfile", snapshot: SettingsSnapshot
) -> RuntimeBinding:
    generation = profile.visual_generation
    judge = generation.visual_judge if generation is not None else None
    profile_provider = judge.provider if judge is not None else ""
    profile_model = judge.model if judge is not None else ""

    override_provider = snapshot.visual_judge_provider.strip()
    override_model = snapshot.visual_judge_model.strip()
    # Both halves or neither: a half-configured override would silently pair an
    # operator's provider with the profile's model. `Settings` refuses that at
    # the boundary; this keeps the contract honest if it ever slips through.
    use_override = bool(override_provider and override_model)

    return RuntimeBinding(
        llm_provider=profile.providers.llm,
        tts_provider=profile.providers.tts,
        render_provider=profile.providers.render,
        judge_provider=override_provider if use_override else profile_provider,
        judge_model=override_model if use_override else profile_model,
        judge_source="operator_override" if use_override else "profile",
        tts_pace_factor=profile.providers.tts_pace_factor,
    )


def compile_contract(
    profile: "ContentProfile",
    settings_snapshot: SettingsSnapshot,
    capabilities: ProviderCapabilitySnapshot,
) -> EffectiveProductionContract:
    """Pure: same profile + snapshot + capabilities always give the same contract."""
    content = {
        video_type: contract_for(video_type, profile) for video_type in ("short", "long")
    }
    pace = profile.providers.tts_pace_factor
    rates = {
        video_type: capabilities.chars_per_min(video_type) * pace
        for video_type in ("short", "long")
    }
    return EffectiveProductionContract(
        schema_version=CONTRACT_SCHEMA_VERSION,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        creative_policy_fingerprint=creative_policy_fingerprint(profile),
        runtime_binding_fingerprint=runtime_binding_fingerprint(profile, settings_snapshot),
        content=content,
        editorial=_editorial_policy(profile),
        visual=_visual_policy(profile),
        runtime=_runtime_binding(profile, settings_snapshot),
        capabilities=capabilities,
        generates_shorts=profile.content_rules.allow_short_generation,
        _rates=rates,
    )


def snapshot_from_settings(source: object) -> SettingsSnapshot:
    """The boundary: read the live settings ONCE, then compile purely from it.

    Every other function in this package takes the snapshot. That is what makes
    the fingerprints reproducible — a contract compiled from ambient globals
    could differ between two calls in the same run and would be useless as an
    invalidation key.
    """
    def text(name: str) -> str:
        return str(getattr(source, name, "") or "")

    def number(name: str) -> float:
        return float(getattr(source, name, 0.0) or 0.0)

    def count(name: str) -> int:
        return int(getattr(source, name, 0) or 0)

    return SettingsSnapshot(
        tts_provider=text("tts_provider"),
        llm_provider=text("llm_provider"),
        short_viewer_min_sec=number("short_viewer_min_sec"),
        short_viewer_max_sec=number("short_viewer_max_sec"),
        short_min_sections=count("short_min_sections"),
        long_viewer_min_sec=number("long_viewer_min_sec"),
        long_viewer_max_sec=number("long_viewer_max_sec"),
        long_min_sections=count("long_min_sections"),
        e2e_test=bool(getattr(source, "e2e_test", False)),
        visual_judge_provider=text("visual_judge_provider"),
        visual_judge_model=text("visual_judge_model"),
    )
