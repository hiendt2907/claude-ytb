"""Chuẩn hoá + validate + repair script JSON từ LLM cho `ytb batch start`.

Tách khỏi ideation_cmd.py: đây là các hàm THUẦN xử lý text/JSON (dễ test,
không I/O ngoài trừ ghi script file + log) và vòng lặp validate→QA→repair
có giới hạn số lần.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from ..agents.base import AgentStatus
from ..agents.qa_agent import QAAgent
from ..agents.editorial_review_agent import run_editorial_review
from ..analytics.quality_report import missing_required_purposes
from ..config.settings import settings
from ..content_contract import contract_for, effective_chars_per_min
from ..ideation.generator import load_script
from ..content_profiles import ContentProfile, load_content_profile
from ..ideation.script_contract import validate_script_payload
from .state_io import atomic_write_json
from .ideation_error_engine import record_ideation_failure
from .ideation_json_heal import heal_json, strip_code_fence
from .ideation_prompts import (
    LONG_SAFE_MIN_CHARS,
    LONG_SAFE_MAX_CHARS,
    SHORT_MAX_CHARS,
    SHORT_MIN_CHARS,
    SHORT_TARGET_CHARS,
    hook_repair_prompt,
    narrator_reflection_repair_prompt,
    editorial_rewrite_prompt,
    ledger_topics,
    long_extension_prompt,
    short_expansion_allowed_indexes,
    short_expansion_prompt,
    script_generation_system_prompt,
    PERSONAL_FINANCE_PSYCHOLOGY_PROFILE,
)


class IdeationQualityFailure(RuntimeError):
    """A rejected candidate that a batch may replace without stopping all work."""

    def __init__(self, message: str, payload: dict) -> None:
        super().__init__(message)
        self.payload = payload


_EVIDENCE_SOURCE_TYPES = {"primary", "peer_reviewed", "official"}
_EVIDENCE_FIELDS = ("claim", "source_title", "publisher", "published_year", "url", "source_type")


def _explicit_profile(payload: dict) -> ContentProfile | None:
    profile_id = str(payload.get("profile_id") or "").strip()
    return load_content_profile(
        profile_id, version=str(payload.get("profile_version") or "").strip() or None,
    ) if profile_id else None


def _editorial_review_evidence(payload: dict, review: object) -> dict:
    """Persist the exact editorial verdict that admitted a generated script.

    This is deliberately attached only after the reviewer passes, so it does
    not alter the payload the reviewer scores or leak into rewrite prompts.
    The canonical payload digest makes a later human audit able to tell which
    transcript bytes the verdict covered.
    """
    reviewed_payload_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "passed": bool(getattr(review, "passed", False)),
        "overall_score": getattr(review, "overall_score", None),
        "dimension_scores": dict(getattr(review, "dimension_scores", None) or {}),
        "profile_id": str(payload.get("profile_id") or ""),
        "profile_version": str(payload.get("profile_version") or ""),
        "reviewed_payload_sha256": reviewed_payload_sha256,
    }


def repair_system_prompt(payload: dict) -> str:
    """Follow-up LLM calls inherit the same editorial profile as generation."""
    return script_generation_system_prompt(
        _explicit_profile(payload), video_type=str(payload.get("video_type") or "") or None
    )


def _repair_character_bounds(
    payload: dict, video_type: str
) -> tuple[int, int, int]:
    """Return absolute min/max and safe midpoint for this script's profile."""
    profile = _explicit_profile(payload)
    if profile is None:
        if video_type == "short":
            return SHORT_MIN_CHARS, SHORT_MAX_CHARS, SHORT_TARGET_CHARS
        return LONG_SAFE_MIN_CHARS, LONG_SAFE_MAX_CHARS, (
            LONG_SAFE_MIN_CHARS + LONG_SAFE_MAX_CHARS
        ) // 2
    format_profile = profile.format_for(video_type)
    contract = contract_for(video_type, profile)
    rate = effective_chars_per_min(profile.providers.tts, video_type=video_type, content_profile=profile)
    lower_sec, upper_sec = contract.audio_runtime_bounds_sec(
        segment_count=format_profile.min_sections
    )
    absolute_min = int(rate * lower_sec / 60)
    absolute_max = int(rate * upper_sec / 60)
    safe_min, safe_max = contract.safe_character_bounds(
        chars_per_minute=rate, segment_count=format_profile.min_sections
    )
    return absolute_min, absolute_max, (safe_min + safe_max) // 2


def validate_financial_evidence_register(payload: dict, *, required: bool) -> None:
    """Fail closed when a financial-psychology script lacks auditable evidence."""
    if not required:
        return
    if payload.get("editorial_profile") != PERSONAL_FINANCE_PSYCHOLOGY_PROFILE:
        raise ValueError("Financial script phải khai editorial_profile=personal_finance_psychology.")
    register = payload.get("evidence_register")
    if not isinstance(register, list) or not register:
        raise ValueError("Financial script cần evidence_register không rỗng cho mọi claim kiểm chứng.")
    accuracy = str((payload.get("compliance") or {}).get("accuracy", "")).casefold()
    if "evidence_register" not in accuracy:
        raise ValueError("compliance.accuracy phải xác nhận evidence_register bao phủ các factual claim.")
    for index, source in enumerate(register, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"evidence_register[{index}] phải là object.")
        missing = [field for field in _EVIDENCE_FIELDS if not str(source.get(field, "")).strip()]
        if missing:
            raise ValueError(f"evidence_register[{index}] thiếu: {', '.join(missing)}.")
        url = str(source["url"]).strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"evidence_register[{index}].url phải là URL HTTPS trực tiếp.")
        if str(source["source_type"]).strip() not in _EVIDENCE_SOURCE_TYPES:
            raise ValueError(f"evidence_register[{index}].source_type không hợp lệ.")
        try:
            published_year = int(str(source["published_year"]).strip())
        except ValueError as exc:
            raise ValueError(f"evidence_register[{index}].published_year phải là năm.") from exc
        if not 1900 <= published_year <= 2100:
            raise ValueError(f"evidence_register[{index}].published_year ngoài khoảng hợp lệ.")


def validate_release_purposes(payload: dict) -> None:
    """Apply the same purpose-completeness rule as preflight and release.

    ``validate_script_payload`` intentionally focuses on JSON shape while the
    release report owns semantic completeness.  Ideation sits before both TTS
    and queueing, therefore it must not accept a candidate that those later
    gates will certainly reject.
    """
    sections = payload.get("sections") or ()
    purposes = (
        str(section.get("purpose") or "")
        for section in sections
        if isinstance(section, dict)
    )
    profile = _explicit_profile(payload)
    required_purposes = (
        profile.editorial_contract.purpose_policy.required if profile is not None else None
    )
    missing = missing_required_purposes(
        str(payload.get("video_type") or ""), purposes, required_purposes=required_purposes,
    )
    if missing:
        messages = "; ".join(
            "Kịch bản thiếu section purpose="
            f"'{purpose}'; cổng trước publish sẽ chặn."
            for purpose in missing
        )
        raise ValueError(messages)


def json_from_llm(text: str) -> dict:
    """Parse structured LLM output, tolerating fenced JSON wrappers."""
    raw = strip_code_fence(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        start = raw.find("{")
        if start >= 0:
            decoder = json.JSONDecoder()
            try:
                value, end = decoder.raw_decode(raw[start:])
            except json.JSONDecodeError:
                # Một số model free qua xKiro (vd bọc markdown ```json, unescaped
                # quote) dễ trả JSON hỏng cú pháp hơn Claude/Codex — heal_json là
                # phương án cuối trước khi báo lỗi (xem docs/TOOL_UPGRADE_PLAN.md
                # amendment 2026-07-23, mở rộng 2026-08-24 cho xKiro).
                return _heal_or_reraise(raw[start:], exc)
            trailing = raw[start + end:].strip()
            # Một số CLI response kết thúc object bằng thêm một dấu `}`.
            # Chỉ bỏ qua closing brace dư, không nuốt text lỗi tùy ý.
            if trailing and set(trailing) != {"}"}:
                return _heal_or_reraise(raw[start:], exc)
            return value
        raise


def _heal_or_reraise(candidate: str, original: json.JSONDecodeError) -> dict:
    """Thử heal_json (json_repair); nếu không cứu được thì giữ nguyên lỗi gốc."""
    try:
        healed = heal_json(candidate, error_pos=original.pos)
    except ValueError:
        raise original from None
    # Tín hiệu chất lượng: heal_json chạy nghĩa là LLM provider trả JSON hỏng cú
    # pháp — cần thấy được để phát hiện sớm nếu tần suất tăng (xem finding
    # review 2026-07-23 về observability của lớp heal).
    print(
        "⚠ json_from_llm: JSON hỏng cú pháp, đã heal bằng json_repair "
        f"(lỗi gốc: {original}).",
        flush=True,
    )
    return healed


def append_local_start_log(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n===== {title} =====\n")
        f.write(body.rstrip())
        f.write("\n")


def strip_short_greeting(text: str) -> str:
    patterns = (
        r"\s*Chào mừng các bạn đến với video mới của chúng tôi\.\s*",
        r"\s*Chào mừng các bạn[^.?!]*[.?!]\s*",
        r"^\s*Hôm nay,\s*chúng ta sẽ\s*",
    )
    cleaned = text.strip()
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def trim_to_sentence(text: str, limit: int) -> str:
    text = strip_short_greeting(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if boundary >= max(60, int(limit * 0.55)):
        return cut[: boundary + 1].strip()
    boundary = cut.rfind(" ")
    if boundary >= max(60, int(limit * 0.65)):
        cut = cut[:boundary].rstrip()
    return cut.rstrip(" ,;:") + "."


def short_narration_chars(payload: dict) -> int:
    return sum(
        len(section.get("voiceover") or section.get("narration", "") or "")
        for section in payload.get("sections", []) or []
        if isinstance(section, dict)
    )


def validate_expected_video_type(
    payload: dict, *, expected_video_type: str, script_name: str
) -> None:
    """Reject an LLM script that does not match its queue slot's media contract."""
    actual = str(payload.get("video_type", "")).strip().lower()
    # Historical short JSON omitted video_type; the canonical loader infers it
    # from the absence of target_minutes.  Keep that compatible, but a long
    # slot must be explicit because that is the failure mode that corrupted W2.
    inferred_short = expected_video_type == "short" and not actual and payload.get("target_minutes") is None
    if actual != expected_video_type and not inferred_short:
        raise ValueError(
            f"Kịch bản {script_name}: expected {expected_video_type} from batch slot, "
            f"got video_type={actual or '<missing>'!r}."
        )
    has_target = payload.get("target_minutes") is not None
    if expected_video_type == "long" and not has_target:
        raise ValueError(f"Kịch bản {script_name}: expected long must declare target_minutes.")
    if expected_video_type == "short" and has_target:
        raise ValueError(f"Kịch bản {script_name}: expected short must not declare target_minutes.")


def validate_short_strategy_v1(payload: dict, *, source_long_context: dict | None = None) -> None:
    """Reject a new Short that would silently fall back to the legacy contract."""
    strategy = payload.get("strategy")
    if not isinstance(strategy, dict):
        raise ValueError("Short strategy-v1 bắt buộc phải có object strategy.")
    required = (
        "format_id", "core_mechanism", "audience_problem", "angle",
        "long_form_slug", "playlist", "cta_target",
    )
    missing = [field for field in required if not str(strategy.get(field, "")).strip()]
    hook = strategy.get("hook")
    if not isinstance(hook, dict):
        missing.append("hook")
        hook = {}
    missing.extend(
        f"hook.{field}"
        for field in ("situation", "core_answer", "open_loop")
        if not str(hook.get(field, "")).strip()
    )
    try:
        answer_by_sec = float(hook.get("answer_by_sec", 0))
    except (TypeError, ValueError):
        answer_by_sec = 0
    if not 0 < answer_by_sec <= 5:
        missing.append("hook.answer_by_sec<=5")
    if source_long_context is not None:
        required_source_fields = ("source_long_slug", "source_section_index", "source_excerpt")
        missing.extend(
            field for field in required_source_fields if not str(strategy.get(field, "")).strip()
        )
        candidates = source_long_context.get("candidates", [])
        selected = next(
            (
                candidate for candidate in candidates
                if candidate.get("section_index") == strategy.get("source_section_index")
                and candidate.get("excerpt") == strategy.get("source_excerpt")
            ),
            None,
        )
        if strategy.get("source_long_slug") != source_long_context.get("slug"):
            missing.append("source_long_slug")
        if selected is None:
            missing.append("source_excerpt")
        source_urls = {
            str(row.get("url", "")).strip()
            for row in source_long_context.get("evidence_register", [])
            if isinstance(row, dict) and str(row.get("url", "")).strip()
        }
        if source_urls:
            short_urls = {
                str(row.get("url", "")).strip()
                for row in payload.get("evidence_register", [])
                if isinstance(row, dict) and str(row.get("url", "")).strip()
            }
            if not source_urls.intersection(short_urls):
                missing.append("evidence_register source URL")
    ordered_sections = [
        section for section in payload.get("sections", []) or [] if isinstance(section, dict)
    ]
    purposes = {str(section.get("purpose", "")).strip() for section in ordered_sections}
    for purpose in ("situation", "core_answer"):
        if purpose not in purposes:
            missing.append(f"section.purpose={purpose}")
    if len(ordered_sections) >= 2 and purposes.issuperset({"situation", "core_answer"}):
        first_purpose = str(ordered_sections[0].get("purpose", "")).strip()
        second_purpose = str(ordered_sections[1].get("purpose", "")).strip()
        if (first_purpose, second_purpose) != ("situation", "core_answer"):
            missing.append("core_answer immediately after situation")
        else:
            situation = str(
                ordered_sections[0].get("voiceover") or ordered_sections[0].get("narration") or ""
            )
            if len(situation) > 120:
                missing.append("situation.voiceover<=120 characters")
            if not re.search(r"\b(nhưng|thật ra|đừng|không phải|vì sao)\b", situation, re.IGNORECASE):
                missing.append("situation needs a concrete tension marker")
            core_answer = str(hook.get("core_answer", "")).strip()
            core_voiceover = str(
                ordered_sections[1].get("voiceover") or ordered_sections[1].get("narration") or ""
            ).strip()
            if core_answer and not core_voiceover.startswith(core_answer):
                missing.append("core_answer must start the core_answer voiceover")
    if missing:
        raise ValueError("Short strategy-v1 thiếu/không hợp lệ: " + ", ".join(missing))


def normalize_short_narration(
    payload: dict, expected_video_type: str | None = None
) -> tuple[dict, str | None]:
    """Keep local Short scripts inside the hard length gate without another LLM hop."""
    if expected_video_type == "long" or payload.get("target_minutes") is not None:
        return payload, None
    candidate = deepcopy(payload)
    sections = [s for s in candidate.get("sections", []) or [] if isinstance(s, dict)]
    if not sections:
        return payload, None

    changed = False
    for section in sections:
        if not isinstance(section, dict):
            continue
        narration = section.get("voiceover") or section.get("narration", "")
        if isinstance(narration, str):
            cleaned = strip_short_greeting(narration)
            if cleaned != narration:
                section["voiceover"] = cleaned
                section["narration"] = cleaned
                changed = True

    short_min_chars, short_max_chars, short_target_chars = _repair_character_bounds(
        candidate, "short"
    )
    total = short_narration_chars(candidate)
    if total > short_max_chars:
        ratio = short_target_chars / total
        remaining = short_target_chars
        strategy = candidate.get("strategy")
        hook = strategy.get("hook") if isinstance(strategy, dict) else None
        core_answer = str(hook.get("core_answer", "")).strip() if isinstance(hook, dict) else ""
        for idx, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            narration = str(section.get("voiceover") or section.get("narration", ""))
            left = len(sections) - idx
            required_prefix = (
                core_answer
                if section.get("purpose") == "core_answer" and narration.startswith(core_answer)
                else ""
            )
            minimum = max(120, len(required_prefix))
            budget = max(minimum, min(len(narration), remaining - 80 * (left - 1)))
            proportional = max(minimum, int(len(narration) * ratio))
            budget = min(budget, proportional)
            section["voiceover"] = trim_to_sentence(narration, budget)
            section["narration"] = section["voiceover"]
            remaining -= len(section["voiceover"])
        changed = True
        total = short_narration_chars(candidate)
    # A boundary trim must be atomic: a sentence boundary can cut more than the
    # numeric budget.  Never replace a merely-overlong script with an undersized
    # one; let the editorial repair see the intact source instead.
    if total < short_min_chars:
        return payload, None
    # Script thiếu độ dài phải đi qua vòng repair LLM bên dưới caller. Không được
    # bơm câu mẫu: nó có thể đúng độ dài nhưng sai hoàn toàn title/topic.

    if not changed:
        return payload, None
    return candidate, f"normalized short narration to {total} chars"


def normalize_long_overflow(payload: dict, expected_video_type: str | None = None) -> tuple[dict, str | None]:
    """Trim only redundant middle narration when a valid Long narrowly exceeds its cap."""
    if expected_video_type != "long":
        return payload, None
    sections = [s for s in payload.get("sections", []) or [] if isinstance(s, dict)]
    total = short_narration_chars(payload)
    _long_min_chars, long_max_chars, _long_target_chars = _repair_character_bounds(
        payload, "long"
    )
    if total <= long_max_chars or len(sections) < 3:
        return payload, None
    excess = total - long_max_chars
    candidates = sections[1:-1]
    for section in sorted(candidates, key=lambda item: len(str(item.get("voiceover") or item.get("narration") or "")), reverse=True):
        if excess <= 0:
            break
        narration = str(section.get("voiceover") or section.get("narration") or "")
        removable = min(excess, max(0, len(narration) - 180))
        if removable <= 0:
            continue
        trimmed = trim_to_sentence(narration, len(narration) - removable)
        removed = len(narration) - len(trimmed)
        if removed > 0:
            section["voiceover"] = trimmed
            if "narration" in section:
                section["narration"] = trimmed
            excess -= removed
    if excess > 0:
        return payload, None
    return payload, f"trimmed long narration to {short_narration_chars(payload)} chars"


def append_long_extension(
    payload: dict, extension: dict, *, max_sections: int | None = None
) -> dict:
    """Insert new long-form sections at a declared narrative boundary.

    `max_sections` là trần section của content profile. Bản cũ nối thẳng mọi
    section mới, nên một Long quá mỏng được vá xong lại vượt trần và bị chính
    vòng validate kế tiếp từ chối — sau hai lượt gọi LLM đã trả tiền.

    Khi chạm trần, phần dư KHÔNG bị vứt: extension tồn tại để thêm ký tự, nên
    lời đọc thừa được gộp vào section cuối cùng còn chỗ.
    """
    sections = extension.get("sections")
    if not isinstance(sections, list) or not sections or not all(isinstance(item, dict) for item in sections):
        raise ValueError("Long extension phải trả về một mảng sections không rỗng.")
    current_sections = payload.get("sections")
    if not isinstance(current_sections, list) or len(current_sections) < 2:
        raise ValueError("Long cần ít nhất phần mở đầu và phần kết trước khi bổ sung.")

    insertion_index = _extension_insertion_index(extension, len(current_sections))
    enriched = deepcopy(payload)
    before = list(deepcopy(current_sections[:insertion_index]))
    after = list(deepcopy(current_sections[insertion_index:]))
    additions = deepcopy(sections)

    room = None if max_sections is None else max(0, max_sections - len(current_sections))
    kept = additions if room is None else additions[:room]
    overflow = [] if room is None else additions[room:]

    merged = [*before, *kept, *after]
    if overflow:
        # Prefer the last accepted addition, then the preceding existing beat.
        # If insertion is at the start of a full script, prepend to the next
        # beat rather than silently dropping the added narration.
        if kept:
            target = merged[len(before) + len(kept) - 1]
        elif before:
            target = before[-1]
        else:
            target = after[0]
        spilled = " ".join(
            str(section.get("voiceover") or section.get("narration") or "").strip()
            for section in overflow
        ).strip()
        if spilled:
            existing = str(target.get("voiceover") or target.get("narration") or "").strip()
            target["voiceover"] = f"{existing} {spilled}".strip()
            if "narration" in target:
                target["narration"] = target["voiceover"]

    enriched["sections"] = merged
    return enriched


def _extension_insertion_index(extension: dict, section_count: int) -> int:
    """Resolve a one-based LLM boundary, preserving old conclusion placement."""
    raw_index = extension.get("insert_before_section_index")
    if raw_index is None:
        return section_count - 1
    if isinstance(raw_index, bool):
        raise ValueError("insert_before_section_index phải là số nguyên 1-based.")
    try:
        index = int(raw_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("insert_before_section_index phải là số nguyên 1-based.") from exc
    if isinstance(raw_index, str) and raw_index.strip() != str(index):
        raise ValueError("insert_before_section_index phải là số nguyên 1-based.")
    if not 1 <= index <= section_count:
        raise ValueError(
            "insert_before_section_index phải trỏ tới một section hiện có "
            f"trong khoảng 1-{section_count}."
        )
    return index - 1


def apply_short_expansion(payload: dict, delta: dict) -> dict:
    """Apply an LLM's bounded additions without allowing a full script rewrite."""
    updates = delta.get("section_updates")
    if not isinstance(updates, list) or len(updates) != 1:
        raise ValueError("Short expansion phải trả về đúng một section_update.")
    current_sections = payload.get("sections")
    if not isinstance(current_sections, list):
        raise ValueError("Short hiện tại phải có mảng sections trước khi bổ sung.")
    allowed_indexes = set(
        short_expansion_allowed_indexes(
            payload, content_profile=_explicit_profile(payload),
        )
    )
    if not allowed_indexes:
        raise ValueError("Short không có section giữa an toàn để bổ sung.")

    enriched = deepcopy(payload)
    for update in updates:
        if not isinstance(update, dict):
            raise ValueError("Mỗi short section_update phải là object.")
        index = update.get("index")
        addition = str(update.get("append_voiceover", "")).strip()
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("short section_update.index phải là số nguyên.")
        if index not in allowed_indexes:
            raise ValueError(
                "Short chỉ được bổ sung section giữa an toàn "
                f"{sorted(allowed_indexes)}, không sửa hook/CTA."
            )
        if not addition:
            raise ValueError("short section_update.append_voiceover không được rỗng.")
        section = enriched["sections"][index]
        if not isinstance(section, dict):
            raise ValueError("Short section cần bổ sung phải là object.")
        existing = str(section.get("voiceover") or section.get("narration") or "").strip()
        if not existing:
            raise ValueError("Short section cần bổ sung phải có narration gốc.")
        combined = f"{existing} {addition}".strip()
        _short_min_chars, short_max_chars, _short_target_chars = _repair_character_bounds(
            payload, "short"
        )
        projected_total = short_narration_chars(payload) + len(combined) - len(existing)
        if projected_total > short_max_chars:
            raise ValueError(
                "Short expansion vượt runtime budget; không cắt hook/core/payoff/CTA để cứu delta."
            )
        if "voiceover" in section:
            section["voiceover"] = combined
        if "narration" in section:
            section["narration"] = combined
        if "voiceover" not in section and "narration" not in section:
            section["voiceover"] = combined
    return enriched


def apply_hook_repair(payload: dict, delta: dict) -> dict:
    """Replace ONLY the opening section's spoken text — nothing else.

    Bounded the same way as `apply_short_expansion`: the delta may name
    exactly one field (`voiceover`), and every other field of the payload —
    title, section count, purposes, strategy, continuity, payoff/CTA, other
    sections' content — is copied through untouched. `narration` is kept in
    sync only because `ideation.generator._section_voiceover` reads
    `voiceover` first; nothing downstream should ever branch on which of the
    two is present.
    """
    new_voiceover = str(delta.get("voiceover") or "").strip()
    if not new_voiceover:
        raise ValueError("Hook repair phải trả về voiceover không rỗng.")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Script không có sections để sửa hook.")
    first = sections[0]
    if not isinstance(first, dict):
        raise ValueError("Section đầu phải là object.")
    enriched = deepcopy(payload)
    section0 = enriched["sections"][0]
    section0["voiceover"] = new_voiceover
    if "narration" in section0:
        section0["narration"] = new_voiceover
    return enriched


def apply_narrator_reflection_repair(payload: dict, delta: dict) -> dict:
    """Replace only the final section's spoken text, preserving the payload."""
    new_voiceover = str(delta.get("voiceover") or "").strip()
    if not new_voiceover:
        raise ValueError("Narrator reflection repair phải trả về voiceover không rỗng.")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Script không có sections để sửa narrator reflection.")
    if not isinstance(sections[-1], dict):
        raise ValueError("Section cuối phải là object.")
    enriched = deepcopy(payload)
    final_section = enriched["sections"][-1]
    final_section["voiceover"] = new_voiceover
    if "narration" in final_section:
        final_section["narration"] = new_voiceover
    return enriched


def apply_editorial_rewrite(payload: dict, delta: dict) -> dict:
    """Replace ONLY the voiceover of the sections an editorial review cited.

    A full-transcript rewrite (the prior design) could silently regress a
    section the reviewer never flagged — production 2026-08-27 saw one break
    the opening hook, burning the whole repair budget on a violation nobody
    asked it to touch. Bounded the same way `apply_hook_repair` bounds itself
    to `sections[0]`: the delta may only name section indices, and every
    other field of the payload — title, structure, other sections' content,
    strategy, provenance — is copied through untouched. `narration` is kept
    in sync only because `ideation.generator._section_voiceover` reads
    `voiceover` first.
    """
    if not isinstance(delta, dict):
        raise ValueError("Editorial rewrite phải trả một JSON object.")
    section_deltas = delta.get("sections")
    if not isinstance(section_deltas, list) or not section_deltas:
        raise ValueError("Editorial rewrite phải trả về ít nhất một section trong `sections`.")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Script không có sections để sửa.")
    enriched = deepcopy(payload)
    enriched_sections = enriched["sections"]
    for item in section_deltas:
        if not isinstance(item, dict):
            raise ValueError("Mỗi phần tử `sections` trong editorial rewrite phải là object.")
        index = item.get("section_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Editorial rewrite: section_index phải là số nguyên.")
        zero_based = index - 1
        if zero_based < 0 or zero_based >= len(enriched_sections):
            raise ValueError(f"Editorial rewrite: section_index {index} ngoài phạm vi script.")
        new_voiceover = str(item.get("voiceover") or "").strip()
        if not new_voiceover:
            raise ValueError(f"Editorial rewrite: section_index {index} thiếu voiceover không rỗng.")
        target = enriched_sections[zero_based]
        target["voiceover"] = new_voiceover
        if "narration" in target:
            target["narration"] = new_voiceover
    return enriched


async def validate_or_repair_script(
    provider,
    payload: dict,
    script_path: Path,
    ledger_text: str,
    max_attempts: int = 3,
    log_path: Path | None = None,
    console_prefix: str = "",
    strict: bool = True,
    semantic_history: list[str] | None = None,
    expected_video_type: str | None = None,
    requires_financial_evidence: bool = False,
    source_long_context: dict | None = None,
    exempt_slugs: tuple[str, ...] = (),
) -> dict:
    """Write, validate, QA, and make profile-authorized content repairs.

    Deterministic schema and formatting defects are normalized locally.  The
    Most LLM follow-ups remain narrow (runtime, hook, identity). A profile may
    additionally opt into a bounded whole-transcript rewrite after its own
    editorial reviewer reports an insufficient viewer-quality score.
    """
    qa = QAAgent()
    done_topics = ledger_topics(ledger_text) + list(semantic_history or [])
    current = dict(payload)
    last_validation_error: str | None = None
    last_qa_output: dict | None = None
    long_extension_attempts = 0
    short_expansion_attempts = 0
    identity_repair_attempted = False
    hook_repair_attempted = False
    narrator_reflection_repair_attempted = False
    editorial_rewrites = 0
    report_path = script_path.parent.parent / "assets" / "quality_reports" / "ideation_errors.jsonl"
    initial_review_profile = _explicit_profile(current)
    editorial_retry_budget = (
        initial_review_profile.editorial_review.max_rewrites
        if initial_review_profile is not None and initial_review_profile.editorial_review is not None
        else 0
    )
    # Formatting/QA repairs and whole-transcript editorial rewrites solve
    # different failures.  A Long that first needs a length or hook repair
    # must not consume the profile's explicitly approved editorial budget.
    total_attempts = max_attempts + editorial_retry_budget

    for attempt in range(1, total_attempts + 1):
        # Editorial-reserved retries may validate and re-review the rewritten
        # transcript, but never borrow more contract-repair LLM calls.
        is_deterministic_attempt = attempt <= max_attempts
        current, long_note = normalize_long_overflow(current, expected_video_type)
        current, normalized_note = normalize_short_narration(
            current, expected_video_type=expected_video_type
        )
        if long_note or normalized_note:
            note = long_note or normalized_note
            if console_prefix:
                print(f"{console_prefix} normalize: {note}", flush=True)
            if log_path:
                append_local_start_log(log_path, f"NORMALIZE {attempt}", note)
        if console_prefix:
            print(f"{console_prefix} validate: attempt {attempt}/{total_attempts}", flush=True)
        if log_path:
            append_local_start_log(
                log_path,
                f"VALIDATION_ATTEMPT {attempt}",
                json.dumps(current, ensure_ascii=False, indent=2),
            )
        try:
            wording_meta = current.get("_wording_engine")
            if isinstance(wording_meta, dict) and not wording_meta.get("encoding_valid", True):
                flags = ", ".join(str(flag) for flag in wording_meta.get("flags", ()))
                raise ValueError(
                    "Wording Engine encoding flag: narration thiếu dấu tiếng Việt"
                    + (f" ({flags})" if flags else ".")
                )
            contract_result = validate_script_payload(current)
            if not contract_result.publishable:
                findings = "; ".join(
                    f"{finding.path}: {finding.message}"
                    for finding in contract_result.findings
                )
                raise ValueError(f"Script contract không đạt: {findings}")
            if expected_video_type is not None:
                validate_expected_video_type(
                    current,
                    expected_video_type=expected_video_type,
                    script_name=script_path.name,
                )
            validate_release_purposes(current)
            content_profile = load_content_profile(
                str(current.get("profile_id") or "") or None,
                version=str(current.get("profile_version") or "").strip() or None,
            )
            if (
                expected_video_type == "short"
                and content_profile.content_rules.require_short_source_trace
            ):
                validate_short_strategy_v1(current, source_long_context=source_long_context)
            validate_financial_evidence_register(
                current, required=requires_financial_evidence
            )
            script_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            script = load_script(script_path)
            last_validation_error = None
        except Exception as exc:  # noqa: BLE001
            script = None
            last_validation_error = str(exc)
            record_ideation_failure(
                report_path,
                script_name=script_path.name,
                attempt=attempt,
                validation_error=last_validation_error,
                qa=None,
            )
            if log_path:
                append_local_start_log(log_path, f"VALIDATION_ERROR {attempt}", last_validation_error)

        if (
            is_deterministic_attempt
            and
            script is None
            and expected_video_type == "long"
            and max_attempts > 1
            and long_extension_attempts < max_attempts - 1
            and last_validation_error
            and "nội dung quá mỏng" in last_validation_error
        ):
            long_min_chars, _long_max_chars, _long_target_chars = _repair_character_bounds(
                current, "long"
            )
            missing_chars = max(1, long_min_chars - short_narration_chars(current))
            extension_profile = _explicit_profile(current)
            extension_max_sections = (
                extension_profile.format_for("long").max_sections
                if extension_profile is not None else None
            )
            available_slots = (
                max(1, extension_max_sections - len(current.get("sections") or ()))
                if extension_max_sections is not None else None
            )
            # A thin script often lacks only one normal story beat. Asking for
            # 10-12 sections guaranteed a cap overflow and a dense, unnatural
            # merged paragraph. Use the smallest bounded count that can carry
            # the missing runtime, while leaving room for a complete beat.
            max_new_sections = (
                min(available_slots, max(1, math.ceil(missing_chars / 350)))
                if available_slots is not None else None
            )
            extension_request = long_extension_prompt(
                current, missing_chars, max_new_sections=max_new_sections,
                content_profile=extension_profile,
            )
            if console_prefix:
                print(f"{console_prefix} extend: asking LLM for missing long-form sections", flush=True)
            if log_path:
                append_local_start_log(log_path, "LONG_EXTENSION_PROMPT", extension_request)
            extension_text = await provider.complete(
                extension_request,
                system=repair_system_prompt(current),
                # A bounded delta needs a few thousand tokens, not a whole
                # script budget. Keeping this at 4k caps xKiro's dynamic
                # timeout near 102s instead of idling for several minutes
                # before surfacing an xKiro failure to the operator.
                max_tokens=4096,
                temperature=0.2,
                json_output=True,
            )
            if log_path:
                append_local_start_log(log_path, "LONG_EXTENSION_RESPONSE", extension_text)
            # Một lần vá hỏng là một lần vá THẤT BẠI, không phải lý do làm sập
            # cả lệnh batch: JSON lỗi từ bước extend từng thoát ra ngoài dưới
            # dạng traceback và giết luôn tiến trình, mất cả candidate đang có.
            try:
                current = append_long_extension(
                    current,
                    json_from_llm(extension_text),
                    max_sections=(
                        extension_profile.format_for("long").max_sections
                        if extension_profile is not None else None
                    ),
                )
            except (ValueError, json.JSONDecodeError) as exc:
                last_validation_error = f"Long extension không dùng được: {exc}"
                if log_path:
                    append_local_start_log(log_path, "LONG_EXTENSION_FAILED", last_validation_error)
            long_extension_attempts += 1
            continue

        if (
            is_deterministic_attempt
            and
            script is None
            and expected_video_type == "short"
            and max_attempts > 1
            and short_expansion_attempts < max_attempts - 1
            and last_validation_error
            and "quá ngắn" in last_validation_error
        ):
            short_min_chars, short_max_chars, short_target_chars = _repair_character_bounds(
                current, "short"
            )
            current_chars = short_narration_chars(current)
            missing_chars = max(1, short_min_chars - current_chars)
            target_chars = max(missing_chars, short_target_chars - current_chars)
            max_chars = max(missing_chars, short_max_chars - current_chars)
            short_profile = _explicit_profile(current)
            expansion_request = short_expansion_prompt(
                current,
                missing_chars,
                target_chars=target_chars,
                max_chars=max_chars,
                content_profile=short_profile,
            )
            if console_prefix:
                print(f"{console_prefix} extend: asking LLM for bounded Short additions", flush=True)
            if log_path:
                append_local_start_log(log_path, "SHORT_EXPANSION_PROMPT", expansion_request)
            expansion_text = await provider.complete(
                expansion_request,
                system=repair_system_prompt(current),
                max_tokens=2048,
                temperature=0.2,
                json_output=True,
            )
            if log_path:
                append_local_start_log(log_path, "SHORT_EXPANSION_RESPONSE", expansion_text)
            try:
                current = apply_short_expansion(current, json_from_llm(expansion_text))
            except (ValueError, json.JSONDecodeError) as exc:
                last_validation_error = f"Short expansion không dùng được: {exc}"
                if log_path:
                    append_local_start_log(log_path, "SHORT_EXPANSION_FAILED", last_validation_error)
            short_expansion_attempts += 1
            continue

        if script is not None:
            result = await qa.run({
                "script": script, "done_topics": done_topics, "strict": strict,
                "exempt_slugs": exempt_slugs,
            })
            if result.status == AgentStatus.SUCCESS:
                last_qa_output = result.output
                if log_path:
                    append_local_start_log(
                        log_path,
                        f"QA_RESULT {attempt}",
                        json.dumps(result.output, ensure_ascii=False, indent=2),
                    )
                if result.output and result.output.get("passed"):
                    review_profile = _explicit_profile(current)
                    review = (
                        await run_editorial_review(
                            review_profile, current, provider=provider,
                            cache_dir=settings.assets_dir / "editorial_review_cache" / review_profile.profile_id,
                        )
                        if review_profile is not None
                        else None
                    )
                    if review is None:
                        return current
                    review_evidence = _editorial_review_evidence(current, review)
                    if log_path:
                        append_local_start_log(
                            log_path,
                            f"EDITORIAL_REVIEW_RESULT {attempt}",
                            json.dumps(review_evidence, ensure_ascii=False, indent=2),
                        )
                    if review.passed:
                        current["_editorial_review"] = review_evidence
                        return current
                    last_qa_output = {
                        "passed": False,
                        "violations": [
                            {"rule": "editorial_review", "detail": finding}
                            for finding in review.blocking_findings
                        ],
                        "repair_brief": review.repair_brief,
                        "section_refs": list(review.section_refs),
                    }
                    if log_path:
                        append_local_start_log(
                            log_path,
                            f"EDITORIAL_REVIEW_FAILED {attempt}",
                            json.dumps(last_qa_output, ensure_ascii=False, indent=2),
                        )
                    review_config = review_profile.editorial_review
                    if (
                        review_config is not None
                        and editorial_rewrites < review_config.max_rewrites
                    ):
                        editorial_rewrites += 1
                        rewrite_request = editorial_rewrite_prompt(current, review)
                        if console_prefix:
                            print(f"{console_prefix} rewrite: editorial score below profile bar", flush=True)
                        if log_path:
                            append_local_start_log(log_path, "EDITORIAL_REWRITE_PROMPT", rewrite_request)
                        cited_sections = list(getattr(review, "section_refs", ()) or ())
                        # The response is now bounded to only the cited
                        # sections' voiceover, not a full script — size the
                        # budget to that, not to a whole-Long response.
                        rewrite_max_tokens = min(8192, max(1024, 700 * max(1, len(cited_sections))))
                        rewrite_text = await provider.complete(
                            rewrite_request,
                            system=repair_system_prompt(current),
                            max_tokens=rewrite_max_tokens,
                            temperature=0.35,
                            json_output=True,
                        )
                        if log_path:
                            append_local_start_log(log_path, "EDITORIAL_REWRITE_RESPONSE", rewrite_text)
                        try:
                            rewrite_delta = json_from_llm(rewrite_text)
                            current = apply_editorial_rewrite(current, rewrite_delta)
                            # An editorial rewrite legitimately touching the
                            # opening section can reintroduce a hook
                            # violation on brand-new text — a single-shot
                            # flag from an EARLIER, unrelated hook fix must
                            # not block fixing THIS one. Bounded: editorial
                            # rewrites are themselves capped by max_rewrites.
                            rewritten_indices = {
                                item.get("section_index")
                                for item in (rewrite_delta.get("sections") or [])
                                if isinstance(item, dict)
                            }
                            if 1 in rewritten_indices:
                                hook_repair_attempted = False
                            if len(current.get("sections") or ()) in rewritten_indices:
                                narrator_reflection_repair_attempted = False
                        except (ValueError, json.JSONDecodeError) as exc:
                            last_validation_error = f"Editorial rewrite không dùng được: {exc}"
                            if log_path:
                                append_local_start_log(
                                    log_path, "EDITORIAL_REWRITE_FAILED", last_validation_error,
                                )
                        continue
                record_ideation_failure(
                    report_path,
                    script_name=script_path.name,
                    attempt=attempt,
                    validation_error=None,
                    qa=last_qa_output,
                )
                # Multiple repairable violations can arrive in the SAME
                # QA_RESULT (a real Qwen candidate failed both series_dedup
                # and hook at once). Applying only one and re-validating used
                # to "swallow" the other: identity repair changed title/topic,
                # never touched narration, and the next QA round saw the
                # still-broken hook with no attempts left to fix it. Every
                # repairable rule found here is applied — in this fixed
                # order, each strictly single-shot via its own `*_attempted`
                # flag — inside the SAME attempt slot, so one extra
                # validate/QA round (not one per violation) is enough to
                # verify all of them.
                violation_rules = {
                    str(v.get("rule")) for v in (last_qa_output or {}).get("violations", [])
                }
                repaired_anything = False

                # A duplicate identity is a bounded repair: preserve every
                # section and ask the model only for a new title/topic pair.
                # This avoids paying for a full script regeneration while
                # keeping the semantic-dedup gate authoritative.
                if (
                    is_deterministic_attempt
                    and not identity_repair_attempted
                    and "series_dedup" in violation_rules
                ):
                    identity_repair_attempted = True
                    repaired_anything = True
                    repair_prompt = (
                        "Return ONLY JSON with keys title and topic.\n"
                        "Change only the title and topic of this video so neither is"
                        " identical or near-duplicate to any blocked topic below."
                        " Keep the same mechanism, evidence, and video intent; do not"
                        " rewrite narration or invent a different mechanism.\n"
                        f"Current title: {current.get('title', '')}\n"
                        f"Current topic: {current.get('topic', '')}\n"
                        f"Blocked topics: {json.dumps(done_topics, ensure_ascii=False)}"
                    )
                    if console_prefix:
                        print(f"{console_prefix} repair: title/topic only for series dedup", flush=True)
                    if log_path:
                        append_local_start_log(log_path, "IDENTITY_REPAIR_PROMPT", repair_prompt)
                    repair_text = await provider.complete(
                        repair_prompt,
                        system="You are a precise JSON editor. Output valid JSON only.",
                        max_tokens=256,
                        temperature=0.1,
                        json_output=True,
                        response_schema={
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "topic": {"type": "string"},
                            },
                            "required": ["title", "topic"],
                            "additionalProperties": False,
                        },
                    )
                    identity = json_from_llm(repair_text)
                    for key in ("title", "topic"):
                        value = identity.get(key)
                        if isinstance(value, str) and value.strip():
                            current[key] = value.strip()

                # A weak opening is a bounded repair too: rewrite ONLY the
                # first section's spoken text against the same anchor+stake
                # (or legacy Long greeting/tension-marker) contract the
                # generation and free-standing repair prompts already state,
                # never the whole script.
                if (
                    is_deterministic_attempt
                    and not hook_repair_attempted
                    and "hook" in violation_rules
                ):
                    hook_repair_attempted = True
                    repaired_anything = True
                    hook_violation = next(
                        (
                            v for v in (last_qa_output or {}).get("violations", [])
                            if str(v.get("rule")) == "hook"
                        ),
                        {},
                    )
                    hook_request = hook_repair_prompt(
                        current,
                        str(hook_violation.get("detail") or ""),
                        content_profile=_explicit_profile(current),
                    )
                    if console_prefix:
                        print(f"{console_prefix} repair: opening only for hook gate", flush=True)
                    if log_path:
                        append_local_start_log(log_path, "HOOK_REPAIR_PROMPT", hook_request)
                    hook_text = await provider.complete(
                        hook_request,
                        system=repair_system_prompt(current),
                        max_tokens=1024,
                        temperature=0.4,
                        json_output=True,
                        response_schema={
                            "type": "object",
                            "properties": {"voiceover": {"type": "string"}},
                            "required": ["voiceover"],
                            "additionalProperties": False,
                        },
                    )
                    if log_path:
                        append_local_start_log(log_path, "HOOK_REPAIR_RESPONSE", hook_text)
                    try:
                        current = apply_hook_repair(current, json_from_llm(hook_text))
                    except (ValueError, json.JSONDecodeError) as exc:
                        last_validation_error = f"Hook repair không dùng được: {exc}"
                        if log_path:
                            append_local_start_log(log_path, "HOOK_REPAIR_FAILED", last_validation_error)

                if (
                    is_deterministic_attempt
                    and not narrator_reflection_repair_attempted
                    and "narrator_reflection" in violation_rules
                ):
                    narrator_reflection_repair_attempted = True
                    repaired_anything = True
                    reflection_violation = next(
                        (
                            violation
                            for violation in (last_qa_output or {}).get("violations", [])
                            if str(violation.get("rule")) == "narrator_reflection"
                        ),
                        {},
                    )
                    reflection_request = narrator_reflection_repair_prompt(
                        current,
                        str(reflection_violation.get("detail") or ""),
                        content_profile=_explicit_profile(current),
                    )
                    if console_prefix:
                        print(
                            f"{console_prefix} repair: final narrator reflection only",
                            flush=True,
                        )
                    if log_path:
                        append_local_start_log(
                            log_path,
                            "NARRATOR_REFLECTION_REPAIR_PROMPT",
                            reflection_request,
                        )
                    reflection_text = await provider.complete(
                        reflection_request,
                        system=repair_system_prompt(current),
                        max_tokens=1024,
                        temperature=0.3,
                        json_output=True,
                        response_schema={
                            "type": "object",
                            "properties": {"voiceover": {"type": "string"}},
                            "required": ["voiceover"],
                            "additionalProperties": False,
                        },
                    )
                    if log_path:
                        append_local_start_log(
                            log_path,
                            "NARRATOR_REFLECTION_REPAIR_RESPONSE",
                            reflection_text,
                        )
                    try:
                        current = apply_narrator_reflection_repair(
                            current, json_from_llm(reflection_text)
                        )
                    except (ValueError, json.JSONDecodeError) as exc:
                        last_validation_error = (
                            f"Narrator reflection repair không dùng được: {exc}"
                        )
                        if log_path:
                            append_local_start_log(
                                log_path,
                                "NARRATOR_REFLECTION_REPAIR_FAILED",
                                last_validation_error,
                            )

                if repaired_anything:
                    continue
            else:
                last_qa_output = {"passed": False, "violations": [{"rule": "qa_agent", "detail": result.error}]}
                if log_path:
                    append_local_start_log(
                        log_path,
                        f"QA_ERROR {attempt}",
                        json.dumps(last_qa_output, ensure_ascii=False, indent=2),
                    )

        # Fail closed.  A broad "repair the full JSON" prompt is deliberately
        # forbidden: it spends cloud tokens and can regress already-approved
        # narrative, source trace, or funnel metadata.
        break

    if log_path:
        append_local_start_log(
            log_path,
            "FINAL_FAILURE",
            f"validation={last_validation_error!r}\nqa={last_qa_output!r}",
        )
    # Keep the rejected artifact and its exact QA evidence.  This means a
    # batch restart cannot silently turn a terminal quality failure into work.
    current["quality_status"] = "needs_review"
    current["quality_review"] = {
        "validation_error": last_validation_error,
        "qa": last_qa_output,
    }
    atomic_write_json(script_path, current)
    raise IdeationQualityFailure(
        "✗ LLM tạo script không qua QA sau "
        f"{total_attempts} lượt (gồm {max_attempts} lượt contract và "
        f"{editorial_retry_budget} lượt editorial). validation={last_validation_error!r} "
        f"qa={last_qa_output!r}",
        current,
    )
