"""Two fingerprints, deliberately independent.

`profile_fingerprint` in `content_profiles` hashes profile.json as a whole file.
That is correct for "did anything about this profile change", and wrong as an
invalidation key: it cannot tell a rewritten story rule from a swapped vendor.
On 2026-09-02 that conflation meant a provider outage left every script pinned
to a profile version permanently unproducible, because the fix lived in a new
version those scripts could not move to.

  creative_policy  — what a WRITER decides: format bounds, story rules, prompt
                     text, editorial rubric, visual art direction.
  runtime_binding  — what an OPERATOR decides: which provider, which model,
                     sampler settings, budgets, measured rates.

Changing a model must move the second and leave the first untouched. Everything
in this module exists to keep that true.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from .effective import SettingsSnapshot


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prompt_texts(profile: "ContentProfile") -> dict[str, str]:
    """Hash prompt CONTENT, not filenames: editing a prompt is a story change."""
    texts: dict[str, str] = {}
    for name in sorted(profile.prompts):
        try:
            body = profile.prompt_text(name)
        except Exception:  # a snapshot missing an optional prompt
            body = ""
        texts[name] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return texts


def creative_policy_fingerprint(profile: "ContentProfile") -> str:
    """Everything that decides how the story is told."""
    formats = {
        name: {
            "viewer_min_sec": fmt.viewer_min_sec,
            "viewer_max_sec": fmt.viewer_max_sec,
            "min_sections": fmt.min_sections,
            "max_sections": fmt.max_sections,
            "runtime_tolerance_sec": fmt.runtime_tolerance_sec,
        }
        for name, fmt in sorted(profile.formats.items())
    }

    editorial_review: dict[str, Any] = {}
    if profile.editorial_review is not None:
        editorial_review = {
            "enabled": profile.editorial_review.enabled,
            "rubric_prompt_name": profile.editorial_review.rubric_prompt_name,
            "minimum_score": profile.editorial_review.minimum_score,
            "max_rewrites": profile.editorial_review.max_rewrites,
        }

    # Art direction is authored, so it belongs here. Sampler settings are tuned
    # to a checkpoint and belong to the runtime binding instead.
    art_direction: dict[str, Any] = {}
    if profile.visual_generation is not None:
        art_direction = {
            "enabled": profile.visual_generation.enabled,
            "style_prompt": profile.visual_generation.style_prompt,
            "negative_prompt": profile.visual_generation.negative_prompt,
            "characters": dict(sorted(profile.visual_generation.characters.items())),
            "duo_reference_image": profile.visual_generation.duo_reference_image,
        }

    return _digest(
        {
            "profile_id": profile.profile_id,
            "version": profile.version,
            "narrative_mode": profile.narrative_mode,
            "topic": profile.topic,
            "formats": formats,
            "content_rules": _asdict(profile.content_rules),
            "editorial_contract": _editorial_contract_payload(profile),
            "editorial_review": editorial_review,
            "art_direction": art_direction,
            "prompts": _prompt_texts(profile),
            "format_prompts": dict(sorted(profile.format_prompts.items())),
            "scene_planning_mode": profile.scene_planning.mode,
        }
    )


def runtime_binding_fingerprint(
    profile: "ContentProfile", settings_snapshot: "SettingsSnapshot"
) -> str:
    """Everything that decides who serves the request, and with what settings."""
    visual: dict[str, Any] = {}
    if profile.visual_generation is not None:
        generation = profile.visual_generation
        visual = {
            "steps": generation.steps,
            "cfg": generation.cfg,
            "solo_weight": generation.solo_weight,
            "duo_weight": generation.duo_weight,
            "duo_denoise": generation.duo_denoise,
            "candidate_count": generation.candidate_count,
            "selection_policy": generation.selection_policy,
            "candidate_policy_version": generation.candidate_policy_version,
            "semantic_rejection_recovery": generation.semantic_rejection_recovery,
        }
        if generation.visual_judge is not None:
            visual["judge"] = {
                "enabled": generation.visual_judge.enabled,
                "provider": generation.visual_judge.provider,
                "model": generation.visual_judge.model,
                "policy_version": generation.visual_judge.policy_version,
                "minimum_score": generation.visual_judge.minimum_score,
                "hard_fail_on_judge_error": generation.visual_judge.hard_fail_on_judge_error,
            }

    return _digest(
        {
            "providers": {
                "llm": profile.providers.llm,
                "tts": profile.providers.tts,
                "render": profile.providers.render,
                "broll_strategy": profile.providers.broll_strategy,
                "tts_pace_factor": profile.providers.tts_pace_factor,
            },
            "voice_cast": dict(sorted(profile.voice_cast.items())),
            "visual": visual,
            "operator_overrides": {
                "visual_judge_provider": settings_snapshot.visual_judge_provider,
                "visual_judge_model": settings_snapshot.visual_judge_model,
                "tts_provider": settings_snapshot.tts_provider,
                "llm_provider": settings_snapshot.llm_provider,
            },
        }
    )


def _asdict(record: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(record) and not isinstance(record, type):
        return dict(sorted(asdict(record).items()))
    return {}


def _editorial_contract_payload(profile: "ContentProfile") -> dict[str, Any]:
    contract = profile.editorial_contract
    payload = _asdict(contract)
    # Paths are machine-specific; a snapshot on another machine must fingerprint
    # the same. Drop anything path-shaped rather than hashing an absolute path.
    return {k: v for k, v in payload.items() if "root" not in k and "path" not in k}
