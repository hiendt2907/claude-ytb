"""Profile-scoped LLM editorial review — a quality gate `script_contract`
cannot express.

Deterministic validation (`ideation/script_contract.py`) only verifies
schema/cast/turn/field SHAPE. It cannot judge whether the narrator actually
narrates instead of drifting into a character's voice, whether a causal turn
makes sense, or whether the episode timeline holds together — a script can
satisfy every deterministic field and still read badly. This module asks the
profile's OWN declared rubric via the profile's LLM provider, and only when
the profile opts in (`editorial_review.enabled`); a profile that never
declares this block (every real profile as of this change) never triggers an
LLM call from here.

Reviews are cached by (profile fingerprint, script content) so an unchanged
script is never re-reviewed — mirrors the content-hash cache pattern used for
scene image generation in `render/story.py::resolve_scene_image`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..content_profiles import ContentProfile, profile_fingerprint


@dataclass(frozen=True)
class EditorialReviewResult:
    passed: bool
    blocking_findings: tuple[str, ...]
    section_refs: tuple[int, ...]
    repair_brief: str


class ReviewProvider(Protocol):
    async def complete(
        self, prompt: str, *, system: str, max_tokens: int, temperature: float, json_output: bool,
    ) -> str: ...


def _cache_key(profile: ContentProfile, script_payload: dict) -> str:
    digest = hashlib.sha256()
    digest.update(profile_fingerprint(profile).encode("utf-8"))
    digest.update(json.dumps(script_payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _to_result(data: dict) -> EditorialReviewResult:
    return EditorialReviewResult(
        passed=data["passed"],
        blocking_findings=tuple(data["blocking_findings"]),
        section_refs=tuple(data["section_refs"]),
        repair_brief=data["repair_brief"],
    )


def _parse_review_response(text: str) -> EditorialReviewResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Editorial review LLM trả JSON không hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Editorial review LLM phải trả một JSON object.")
    passed = data.get("passed")
    if not isinstance(passed, bool):
        raise ValueError("Editorial review thiếu field passed (boolean).")
    blocking = data.get("blocking_findings") or []
    if not isinstance(blocking, list) or not all(isinstance(item, str) for item in blocking):
        raise ValueError("blocking_findings phải là mảng string.")
    refs = data.get("section_refs") or []
    if not isinstance(refs, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in refs
    ):
        raise ValueError("section_refs phải là mảng số nguyên.")
    return EditorialReviewResult(
        passed=passed,
        blocking_findings=tuple(blocking),
        section_refs=tuple(refs),
        repair_brief=str(data.get("repair_brief") or ""),
    )


async def run_editorial_review(
    profile: ContentProfile,
    script_payload: dict,
    *,
    provider: ReviewProvider,
    cache_dir: Path,
) -> EditorialReviewResult | None:
    """Return None (no LLM call) when the profile has not opted into review."""
    review_profile = profile.editorial_review
    if review_profile is None or not review_profile.enabled:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(profile, script_payload)
    cache_path = cache_dir / f"{key}.json"
    if cache_path.is_file():
        return _to_result(json.loads(cache_path.read_text(encoding="utf-8")))
    rubric = profile.editorial_review_rubric_text()
    prompt = (
        "Review this Vietnamese YouTube script JSON against the rubric below. "
        "Return ONLY one JSON object with keys: passed (boolean), blocking_findings "
        "(array of short strings), section_refs (array of one-based section indices "
        "the findings refer to), repair_brief (a short instruction for how to fix "
        "the findings, empty string when passed is true).\n\n"
        f"Rubric:\n{rubric}\n\n"
        f"Script JSON:\n{json.dumps(script_payload, ensure_ascii=False, indent=2)}"
    )
    text = await provider.complete(
        prompt,
        system=(
            "You are a strict editorial reviewer applying exactly the rubric given; "
            "do not invent rules the rubric does not state."
        ),
        max_tokens=1024,
        temperature=0.0,
        json_output=True,
    )
    result = _parse_review_response(text)
    cache_path.write_text(
        json.dumps({
            "passed": result.passed,
            "blocking_findings": list(result.blocking_findings),
            "section_refs": list(result.section_refs),
            "repair_brief": result.repair_brief,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
