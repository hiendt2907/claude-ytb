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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from ..content_profiles import ContentProfile, EditorialReviewProfile, profile_fingerprint


EDITORIAL_REVIEW_DIMENSIONS = frozenset({
    "human_truth",
    "spoken_naturalness",
    "causal_coherence",
    "role_fidelity",
    "useful_restraint",
})
_AUDIT_ONLY_FIELDS = frozenset({"_editorial_review"})


@dataclass(frozen=True)
class EditorialReviewResult:
    passed: bool
    blocking_findings: tuple[str, ...]
    section_refs: tuple[int, ...]
    repair_brief: str
    overall_score: int | None = None
    dimension_scores: Mapping[str, int] | None = None


class ReviewProvider(Protocol):
    async def complete(
        self, prompt: str, *, system: str, max_tokens: int, temperature: float, json_output: bool,
    ) -> str: ...


def _cache_key(profile: ContentProfile, script_payload: dict) -> str:
    digest = hashlib.sha256()
    digest.update(profile_fingerprint(profile).encode("utf-8"))
    digest.update(json.dumps(script_payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _reviewable_payload(script_payload: dict) -> dict:
    """Remove pipeline audit receipts before asking an independent reviewer.

    A saved approval is evidence for a human, not evidence for the next LLM.
    Keeping it out of this canonical payload also preserves the cache key when
    the transcript itself is unchanged.
    """
    return {
        key: value for key, value in script_payload.items()
        if key not in _AUDIT_ONLY_FIELDS
    }


def _to_result(data: dict) -> EditorialReviewResult:
    return EditorialReviewResult(
        passed=data["passed"],
        blocking_findings=tuple(data["blocking_findings"]),
        section_refs=tuple(data["section_refs"]),
        repair_brief=data["repair_brief"],
        overall_score=data.get("overall_score"),
        dimension_scores=data.get("dimension_scores"),
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
    # `section_refs` only points the repair prompt at sections; it is a hint,
    # not part of the gate. A judge answering ["4", "6"] used to raise here and
    # abort the whole supervised run before the review was even logged
    # (production 2026-08-30, ideation_20260830_111408). Accept any integral
    # value, keep rejecting anything that is not a section number.
    raw_refs = data.get("section_refs") or []
    if not isinstance(raw_refs, list):
        raise ValueError("section_refs phải là mảng số nguyên.")
    refs: list[int] = []
    for item in raw_refs:
        if isinstance(item, bool):
            raise ValueError("section_refs phải là mảng số nguyên.")
        if isinstance(item, int):
            refs.append(item)
            continue
        if isinstance(item, float) and item.is_integer():
            refs.append(int(item))
            continue
        if isinstance(item, str):
            try:
                refs.append(int(item.strip()))
                continue
            except ValueError as exc:
                raise ValueError("section_refs phải là mảng số nguyên.") from exc
        else:
            raise ValueError("section_refs phải là mảng số nguyên.")
    score = data.get("overall_score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10):
        raise ValueError("overall_score phải là số nguyên trong [0, 10].")
    dimension_scores = data.get("dimension_scores")
    if dimension_scores is not None:
        if not isinstance(dimension_scores, dict) or not all(
            isinstance(name, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 10
            for name, value in dimension_scores.items()
        ):
            raise ValueError("dimension_scores phải là object điểm số nguyên trong [0, 10].")
    return EditorialReviewResult(
        passed=passed,
        blocking_findings=tuple(blocking),
        section_refs=tuple(refs),
        repair_brief=str(data.get("repair_brief") or ""),
        overall_score=score,
        dimension_scores=dimension_scores,
    )


def median_review(draws: Sequence[EditorialReviewResult]) -> EditorialReviewResult:
    """Merge repeated reviews of one script into the verdict they agree on.

    Measured 2026-09-07 over nine independent reviews of one unchanged Long at
    `temperature=0.0`: individual dimensions ranged over 2-3 points (stdev
    0.47-0.74) and the mean over 1.40 (stdev 0.39). With that script's true
    mean at ~7.33 against a 7.5 bar, `mean>=7.5 & floor>=7` passed 1 draw in 9
    while `mean>=7.0 & floor>=6` passed 8 — same script, no word changed.

    Each dimension takes its own median, so one dimension's outlier cannot
    carry the verdict, and the findings come from whichever draw sits nearest
    the merged scores: findings that describe a different draw would send a
    repair after faults this verdict is not claiming.
    """
    if not draws:
        raise ValueError("median_review cần ít nhất một lượt chấm.")
    if len(draws) == 1:
        return draws[0]

    dimensions = sorted({name for draw in draws for name in (draw.dimension_scores or {})})
    merged_scores = {
        name: _lower_median(
            [int(draw.dimension_scores[name]) for draw in draws if name in (draw.dimension_scores or {})]
        )
        for name in dimensions
    }
    # Lower median, not the arithmetic mean: the rubric emits integers, and a
    # verdict of 7.5 is not a score any single review could have returned.
    nearest = min(
        draws,
        key=lambda draw: sum(
            abs(int((draw.dimension_scores or {}).get(name, 0)) - merged_scores[name])
            for name in dimensions
        ),
    )
    merged_overall = round(sum(merged_scores.values()) / len(merged_scores)) if merged_scores else 0
    return replace(
        nearest,
        dimension_scores=merged_scores,
        overall_score=merged_overall,
    )


def _lower_median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _bar_description(review_profile: "EditorialReviewProfile") -> str:
    """The bar in words, so the prompt and the code cannot quote different ones.

    The reviewer LLM sets `passed` itself. When it was told a 9/10 bar the code
    no longer enforces, it marked acceptable work failed and the repair loop
    chased a target nothing was measuring.
    """
    if review_profile.uses_mean_bar:
        return (
            f"trung bình năm tiêu chí >= {review_profile.minimum_mean_score:g}/10 "
            f"và không tiêu chí nào dưới {review_profile.minimum_dimension_score}/10"
        )
    return f"mọi tiêu chí >= {review_profile.minimum_score}/10"


def _bar_findings(
    review_profile: "EditorialReviewProfile",
    dimensions: Mapping[str, int],
    overall_score: int,
) -> list[str]:
    """Why this script missed — naming the dimension and the gap, not the bar.

    36% of the 855 blocking findings recorded under the old bar were bare
    restatements of the threshold ("các tiêu chí dưới ngưỡng 9/10: ..."), which
    tells a rewrite nothing it can act on.
    """
    if not review_profile.uses_mean_bar:
        bar = review_profile.minimum_score
        low = sorted(name for name, score in dimensions.items() if score < bar)
        findings: list[str] = []
        if overall_score < bar:
            findings.append(f"Điểm biên tập {overall_score}/10 dưới ngưỡng {bar}/10 của profile.")
        if low:
            findings.append(f"Các tiêu chí dưới ngưỡng {bar}/10: {', '.join(low)}.")
        return findings

    floor = review_profile.minimum_dimension_score
    mean_bar = review_profile.minimum_mean_score
    mean = sum(dimensions.values()) / len(dimensions)
    findings = []
    below = sorted(
        (name for name, score in dimensions.items() if score < floor),
        key=lambda name: dimensions[name],
    )
    for name in below:
        findings.append(
            f"{name} đạt {dimensions[name]}/10, dưới sàn {floor}/10 — "
            "tiêu chí này phải sửa, không bù được bằng tiêu chí khác."
        )
    if mean < mean_bar:
        weakest = ", ".join(
            f"{name} {dimensions[name]}"
            for name in sorted(dimensions, key=lambda n: dimensions[n])[:2]
        )
        findings.append(
            f"Trung bình {mean:.1f}/10 dưới ngưỡng {mean_bar:g}/10; "
            f"kéo điểm xuống nhiều nhất: {weakest}."
        )
    return findings


def _enforce_profile_score(
    profile: ContentProfile,
    result: EditorialReviewResult,
) -> EditorialReviewResult:
    """Apply the current profile bar to both fresh and cached verdicts."""
    review_profile = profile.editorial_review
    if review_profile is None or not (review_profile.minimum_score or review_profile.uses_mean_bar):
        return result
    if result.overall_score is None:
        raise ValueError(
            "Editorial review profile có minimum_score nhưng LLM không trả overall_score."
        )
    dimensions = dict(result.dimension_scores or {})
    if set(dimensions) != EDITORIAL_REVIEW_DIMENSIONS:
        missing = sorted(EDITORIAL_REVIEW_DIMENSIONS - set(dimensions))
        unexpected = sorted(set(dimensions) - EDITORIAL_REVIEW_DIMENSIONS)
        detail = []
        if missing:
            detail.append(f"thiếu {', '.join(missing)}")
        if unexpected:
            detail.append(f"không hợp lệ {', '.join(unexpected)}")
        raise ValueError(
            "Editorial review profile có minimum_score nhưng dimension_scores "
            f"phải có đúng năm tiêu chí ({'; '.join(detail) or 'không hợp lệ'})."
        )
    findings = _bar_findings(review_profile, dimensions, result.overall_score)
    if findings:
        return replace(
            result,
            passed=False,
            blocking_findings=tuple([*result.blocking_findings, *findings]),
            repair_brief=result.repair_brief or "Viết lại theo các tiêu chí rubric chưa đạt.",
        )
    return result


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
    review_payload = _reviewable_payload(script_payload)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(profile, review_payload)
    cache_path = cache_dir / f"{key}.json"
    if cache_path.is_file():
        return _enforce_profile_score(
            profile, _to_result(json.loads(cache_path.read_text(encoding="utf-8"))),
        )
    rubric = profile.editorial_review_rubric_text()
    strategy = review_payload.get("strategy")
    cold_open_contract = ""
    if (
        review_payload.get("video_type") == "short"
        and isinstance(strategy, dict)
        and strategy.get("format_id") == "core_answer_first_v1"
    ):
        hook = strategy.get("hook") if isinstance(strategy.get("hook"), dict) else {}
        core_answer = str(hook.get("core_answer") or "").strip()
        cold_open_contract = (
            "\n\nThis Short has a mandatory cold-open contract: section 1 is a very brief "
            "tension setup and section 2 must immediately begin with the configured core answer "
            f"{core_answer!r}. You must not recommend removing, delaying, or paraphrasing that "
            "required prefix merely because it states the answer early. Judge whether the later "
            "human scene earns and grounds it; findings may improve execution around the invariant "
            "but must remain compatible with it."
        )
    prompt = (
        "Review this Vietnamese YouTube script JSON against the rubric below. "
        "Return ONLY one JSON object with keys: passed (boolean), overall_score "
        "(integer 0-10), dimension_scores (object with integer 0-10 scores for "
        "human_truth, spoken_naturalness, causal_coherence, role_fidelity, useful_restraint), blocking_findings "
        "(array of short strings), section_refs (array of one-based section indices "
        "the findings refer to), repair_brief (a short instruction for how to fix "
        "the findings, empty string when passed is true). The profile bar is: "
        f"{_bar_description(review_profile)}. Scores missing that bar MUST set "
        "passed=false; scores meeting it MUST set passed=true. Do not award "
        "a high score merely because the JSON schema or an abstract structure is correct.\n\n"
        f"Rubric:\n{rubric}{cold_open_contract}\n\n"
        f"Script JSON:\n{json.dumps(review_payload, ensure_ascii=False, indent=2)}"
    )
    draws: list[EditorialReviewResult] = []
    samples = max(1, review_profile.review_samples)
    for index in range(samples):
        # The gateway caches byte-identical requests, so a second identical
        # call replays the first rather than drawing again. Vary only transport
        # metadata — the same escape `XkiroLLMProvider` uses to get past a
        # cached corrupt response — so every draw sees the same script and the
        # same rubric.
        request_prompt = prompt if not index else (
            f"{prompt}\n\n[review sample {index + 1} of {samples}; "
            "ignore this metadata when answering]"
        )
        text = await provider.complete(
            request_prompt,
            system=(
                "You are a strict editorial reviewer applying exactly the rubric given; "
                "do not invent rules the rubric does not state."
            ),
            max_tokens=1024,
            temperature=0.0,
            json_output=True,
        )
        try:
            draws.append(_parse_review_response(text))
        except ValueError as exc:
            # Fail closed, but never lose the evidence: the parse error alone
            # does not say what the judge actually returned, and production
            # 2026-08-30 ended with a traceback and an empty review log.
            raise ValueError(
                f"Editorial review response không dùng được: {exc} | raw={text!r:.2000}"
            ) from exc
    result = _enforce_profile_score(profile, median_review(draws))
    cache_path.write_text(
        json.dumps({
            "passed": result.passed,
            "blocking_findings": list(result.blocking_findings),
            "section_refs": list(result.section_refs),
            "repair_brief": result.repair_brief,
            "overall_score": result.overall_score,
            "dimension_scores": result.dimension_scores,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
