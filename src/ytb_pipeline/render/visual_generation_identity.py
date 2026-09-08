"""Identity for reusable generated-story pixels.

This is intentionally narrower than a profile release.  Editorial policy and
script contracts can change without changing a particular image request; the
generation cache only depends on inputs that actually reach the image model.
Reference media are identified by their observed bytes, not their path or the
profile's broad release number.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.settings import settings
from ..providers.image.comfyui_story_provider import SAMPLER, SCHEDULER

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from ..pkg.models import Segment


GENERATION_INPUT_CONTRACT_VERSION = "phase14-visual-input-v1"


class VisualGenerationInputError(ValueError):
    """A declared image-model input cannot be observed safely."""


def _reference_sha256(path: Path, *, label: str) -> str:
    target = Path(path)
    if not target.is_file():
        raise VisualGenerationInputError(
            f"Visual reference integrity failure: missing {label}: {target}"
        )
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise VisualGenerationInputError(
            f"Visual reference integrity failure: unreadable {label}: {target}"
        ) from exc


def _reference_identity(profile: "ContentProfile", characters: tuple[str, ...]) -> dict[str, str]:
    """Hash only the reference files the selected provider will consume."""
    unique = tuple(dict.fromkeys(characters))
    if not unique:
        return {}
    resolver = getattr(profile, "character_reference_path", None)
    if not callable(resolver):
        # Resolver tests and third-party adapters may pass a deliberately
        # lightweight profile proxy. A loaded ContentProfile always has the
        # resolver above, so production retains byte-level identity. Keep the
        # old proxy contract deterministic rather than making its synthetic
        # character names look like a missing production asset.
        identities = {
            f"character:{character_id}": f"unresolved-reference:{character_id}"
            for character_id in unique
        }
        if len(unique) >= 2:
            identities["duo"] = "unresolved-reference:duo"
        return identities
    identities = {
        f"character:{character_id}": _reference_sha256(
            resolver(character_id), label=f"character:{character_id}"
        )
        for character_id in unique
    }
    if len(unique) >= 2:
        duo_resolver = getattr(profile, "duo_reference_path", None)
        if not callable(duo_resolver):
            raise VisualGenerationInputError(
                "Visual reference integrity failure: profile cannot resolve duo reference."
            )
        identities["duo"] = _reference_sha256(duo_resolver(), label="duo")
    return identities


def visual_input_fingerprint(
    segment: "Segment", profile: "ContentProfile", dimensions: tuple[int, int]
) -> str:
    """Fingerprint the exact model-facing input for one generated scene.

    Do not add ``profile.version`` here. It is a broad editorial release
    marker, whereas a cache key must only change when this image's request,
    model parameters, or consumed reference bytes change.
    """
    visual = profile.visual_generation
    if visual is None:
        raise VisualGenerationInputError("Profile không bật visual_generation.")
    characters = tuple(dict.fromkeys(segment.scene_characters))
    payload: dict[str, Any] = {
        "contract_version": GENERATION_INPUT_CONTRACT_VERSION,
        "profile_id": profile.profile_id,
        "dimensions": [dimensions[0], dimensions[1]],
        "visual_intent": segment.visual_intent.strip(),
        "characters": list(characters),
        "references": _reference_identity(profile, characters),
        "style_prompt": visual.style_prompt,
        "negative_prompt": visual.negative_prompt,
        "steps": visual.steps,
        "cfg": visual.cfg,
        "solo_weight": visual.solo_weight,
        "duo_weight": visual.duo_weight,
        "duo_denoise": visual.duo_denoise,
        "checkpoint": settings.comfyui_sdxl_checkpoint,
        "clip_vision_model": settings.comfyui_clip_vision_model,
        "ipadapter_model": settings.comfyui_ipadapter_model,
        "sampler": SAMPLER,
        "scheduler": SCHEDULER,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def generation_key(
    segment: "Segment", profile: "ContentProfile", dimensions: tuple[int, int]
) -> str:
    """Compatibility-named cache identity for generated story images."""
    return visual_input_fingerprint(segment, profile, dimensions)
