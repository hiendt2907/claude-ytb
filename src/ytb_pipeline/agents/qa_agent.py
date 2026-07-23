"""QAAgent — quality gate enforcer, THUẦN rule-based (không gọi LLM).

Chạy lại các cổng verify tương đương `ideation/generator.py` (length/intro/
compliance) trên dữ liệu script đã có trong context (không cần file), cộng
2 gate mới: niche self-help mantra + sourced claims (vd "studies show" thiếu
nguồn) + dedup theo `context["done_topics"]`.

`passed=False` => downstream agent KHÔNG được chạy tiếp (enforced bởi caller,
agent này chỉ báo cáo). QA không phân loại hay áp luật riêng cho format hình
ảnh/giải trí; các script được kiểm tra theo cùng một hợp đồng nội dung.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..ideation import series as series_mod
from ..content_contract import contract_for, estimate_duration_sec
from ..ideation.generator import GREETING_PREFIX, chars_per_min_for_provider
from .base import AgentResult, AgentStatus

_SELF_HELP_MANTRAS = (
    "just believe in yourself",
    "hãy tin vào bản thân",
    "bạn có thể làm được mọi thứ",
    "manifest your dreams",
)
_SOURCED_CLAIM_PHRASES = (
    "studies show",
    "nghiên cứu cho thấy",
    "các nhà khoa học",
    "research shows",
)
_SOURCE_HINTS = ("http://", "https://", "nguồn:", "source:", "doi:")
_STAGE_DIRECTION_PATTERNS = (
    "cú hình tiếp theo:",
    "beat sau:",
    "chốt cảnh:",
    "[",
    "]",
)
_IMMEDIATE_ACTION_HINTS = ("hãy ", "thử ngay", "ngay hôm nay", "ngay bây giờ", "làm ngay")
_ABSOLUTE_CLAIM_HINTS = ("chắc chắn", "đảm bảo", "100%", "luôn luôn", "mọi người")
_HEALTH_FINANCE_HINTS = (
    "chữa khỏi", "điều trị", "lo âu", "trầm cảm", "bệnh", "thuốc",
    "lợi nhuận", "đầu tư", "giàu", "kiếm tiền", "tài chính",
)


class QAAgent:
    name = "qa"

    @property
    def required_context_keys(self) -> list[str]:
        return ["script"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return "script" in context

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            script = context["script"]
            violations: list[dict[str, str]] = []
            warnings: list[dict[str, str]] = []

            violations.extend(_check_compliance(script))
            violations.extend(_check_length(script))
            violations.extend(_check_intro(script))
            violations.extend(_check_self_help(script))
            violations.extend(_check_dedup(script, context.get("done_topics")))
            violations.extend(_check_absolute_health_finance_claims(script))
            if context.get("strict", False):
                violations.extend(_check_hook_strength(script))
                violations.extend(_check_hook_contract(script))
                if _get(script, "ruleset_id", ""):
                    violations.extend(_check_release_schema(script))
                violations.extend(_check_central_mechanism(script))
                violations.extend(_check_stage_direction_leak(script))
                violations.extend(_check_knowledge_examples(script))
                violations.extend(_check_immediate_action(script))
                violations.extend(_check_final_payoff(script))
                violations.extend(_check_pexels_queries(script))
            warnings.extend(_check_sourced_claims(script))

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={
                    "passed": len(violations) == 0,
                    "violations": violations,
                    "warnings": warnings,
                },
                latency_ms=_elapsed_ms(start),
            )
        except Exception as exc:  # noqa: BLE001 — agent KHÔNG BAO GIỜ raise
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                output=None,
                error=str(exc),
                latency_ms=_elapsed_ms(start),
            )


# ---------------------------------------------------------------------------
# Gate helpers — đọc script dict/dataclass, KHÔNG mutate, KHÔNG raise (gom
# thành violation dict thay vì ValueError như generator.py bản file-based).
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _segments_of(script: Any) -> list[Any]:
    return list(_get(script, "segments", ()) or ())


def _narration_of(segment: Any) -> str:
    return _get(segment, "narration", "") or ""


def _check_compliance(script: Any) -> list[dict[str, str]]:
    compliance = _get(script, "compliance")
    passed = _get(compliance, "passed") if compliance is not None else None
    if compliance is None or passed is not True:
        return [{
            "rule": "compliance",
            "detail": "Thiếu khối compliance hoặc 'passed' != true.",
        }]
    return []


def _check_length(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if not segments:
        return [{"rule": "length", "detail": "Script không có segment narration."}]

    target_minutes = _get(script, "target_minutes")
    video_type = "long" if target_minutes is not None else "short"
    contract = contract_for(video_type)
    est_sec = estimate_duration_sec(
        sum(len(_narration_of(segment)) for segment in segments),
        chars_per_minute=chars_per_min_for_provider(),
    )

    if target_minutes is not None:
        min_minutes = contract.viewer_runtime_bounds_sec[0] / 60
        max_minutes = contract.viewer_runtime_bounds_sec[1] / 60
        if not (min_minutes <= target_minutes <= max_minutes):
            return [{
                "rule": "length",
                "detail": (
                    f"target_minutes={target_minutes} ngoài khoảng "
                    f"[{min_minutes:.0f}, {max_minutes:.0f}]."
                ),
            }]
        if est_sec < float(target_minutes) * 60 + contract.transition_loss_sec(len(segments)):
            return [{
                "rule": "length",
                "detail": f"Nội dung quá mỏng: audio ước lượng {est_sec / 60:.1f}p < target {target_minutes}p.",
            }]
    try:
        contract.validate_audio_runtime(
            est_sec, segment_count=len(segments) if _get(script, "ruleset_id", "") else 1
        )
    except ValueError as exc:
        return [{"rule": "length", "detail": str(exc)}]
    return []


def _check_intro(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if not segments:
        return []
    first = _narration_of(segments[0]).lstrip()
    is_long = _get(script, "target_minutes") is not None
    starts_with_greeting = first.startswith(GREETING_PREFIX)

    if is_long and not starts_with_greeting:
        return [{
            "rule": "intro",
            "detail": f"Video dài phải mở đầu bằng \"{GREETING_PREFIX}\".",
        }]
    if not is_long and starts_with_greeting:
        return [{
            "rule": "intro",
            "detail": f"Short KHÔNG được mở bằng \"{GREETING_PREFIX}\".",
        }]
    return []


def _check_self_help(script: Any) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for segment in _segments_of(script):
        narration_lower = _narration_of(segment).lower()
        for mantra in _SELF_HELP_MANTRAS:
            if mantra in narration_lower:
                violations.append({
                    "rule": "niche_self_help",
                    "detail": f"Phát hiện mantra self-help chung chung: '{mantra}'.",
                })
    return violations


def _repair(rule: str, detail: str, suggestion: str) -> dict[str, str]:
    return {"rule": rule, "detail": detail, "suggestion": suggestion}


def _script_video_type(script: Any) -> str:
    raw = str(_get(script, "video_type", "") or "").lower()
    if raw in {"long", "short"}:
        return raw
    return "long" if _get(script, "target_minutes") is not None else "short"


def _check_hook_strength(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if not segments:
        return []
    first = _narration_of(segments[0]).strip()
    first_words = first.split()[:28]
    first_text = " ".join(first_words).lower()
    if _script_video_type(script) == "long" and first.startswith(GREETING_PREFIX):
        first_text = first_text.replace(GREETING_PREFIX.lower(), "", 1).strip()
    strong_markers = (
        "vì sao", "thật ra", "nghịch lý", "sai lầm", "bí mật", "đừng", "không phải",
        "nhưng", "bỗng", "ngay trước mặt", "hóa ra",
    )
    has_question_hook = "?" in first
    if len(first_words) < 8 or not (has_question_hook or any(marker in first_text for marker in strong_markers)):
        return [_repair(
            "hook",
            "Hook 3-5 giây đầu chưa đủ mạnh hoặc chưa có nghịch lý/vấn đề rõ.",
            "Viết lại câu mở đầu thành một mâu thuẫn cụ thể: 'Bạn tưởng X, nhưng thật ra Y...' hoặc 'Đừng làm X trước khi hiểu Y'.",
        )]
    return []


def _check_hook_contract(script: Any) -> list[dict[str, str]]:
    """Validate strategy-v1 structure before the audio timing gate runs.

    Legacy scripts intentionally have no strategy and remain eligible for audit;
    newly generated strategy scripts must expose the exact beat that earns the
    first five seconds of attention.
    """
    strategy = _get(script, "strategy")
    if strategy is None or _script_video_type(script) != "short":
        return []
    hook = _get(strategy, "hook")
    required = (
        _get(strategy, "format_id", ""),
        _get(strategy, "core_mechanism", ""),
        _get(strategy, "audience_problem", ""),
        _get(strategy, "angle", ""),
        _get(strategy, "long_form_slug", ""),
        _get(strategy, "playlist", ""),
        _get(strategy, "cta_target", ""),
        _get(hook, "situation", ""),
        _get(hook, "core_answer", ""),
        _get(hook, "open_loop", ""),
    )
    segments = _segments_of(script)
    purposes = [_get(segment, "purpose", "") for segment in segments]
    contract = contract_for("short")
    deadline = _get(hook, "answer_by_sec", 0)
    if (
        not all(str(value).strip() for value in required)
        or purposes[:2] != ["situation", "core_answer"]
        or deadline != contract.answer_start_deadline_sec
    ):
        return [_repair(
            "hook_contract",
            "Strategy Short phải có hook đầy đủ, funnel đích và segment purpose='core_answer'.",
            "Khai báo format/cơ chế/góc, long_form_slug/playlist/cta_target, rồi đặt câu trả lời lõi vào một segment core_answer.",
        )]
    return []


def _check_release_schema(script: Any) -> list[dict[str, str]]:
    """Schema required for every newly produced, publishable script."""
    thumbnail = _get(script, "thumbnail_brief")
    if thumbnail is None:
        return [_repair(
            "thumbnail_brief",
            "Kịch bản chưa có thumbnail_brief trước khi TTS/render.",
            "Bổ sung visual_contradiction, subject, emotion và headline (≤4 từ).",
        )]
    if _script_video_type(script) != "short":
        return []
    strategy = _get(script, "strategy")
    if strategy is None:
        return []
    source = (
        _get(strategy, "source_long_slug", ""),
        _get(strategy, "source_section_index", None),
        _get(strategy, "source_excerpt", ""),
    )
    if not source[0] or source[1] is None or not source[2]:
        return [_repair(
            "short_source_trace",
            "Short thiếu dấu vết section Long làm nguồn.",
            "Khai báo source_long_slug, source_section_index và source_excerpt trùng Long đích.",
        )]
    if source[0] != _get(strategy, "long_form_slug", ""):
        return [_repair(
            "short_source_trace",
            "source_long_slug không khớp long_form_slug.",
            "Dùng đúng Long đích cho source trace và CTA.",
        )]
    return []


def _check_central_mechanism(script: Any) -> list[dict[str, str]]:
    """Keep each episode focused when the script explicitly names mechanisms."""
    names = re.findall(r"cơ chế\s+([\wà-ỹ\s]{2,40}?)(?:[,.;:]|\s+(?:và|nhưng|cũng)\s)", _script_text(script).lower())
    # "các cơ chế khiến ta trì hoãn" is a generic CTA/effect phrase, not a
    # second named mechanism.  Only named mechanisms participate in the
    # one-mechanism gate.
    generic_starts = {"khiến", "gây", "giúp", "dẫn", "làm", "để", "trong", "về"}
    unique = {
        " ".join(name.split())
        for name in names
        if name.strip() and name.split(maxsplit=1)[0] not in generic_starts
    }
    # The regex has no semantic knowledge of Vietnamese mechanism names.  A
    # later mention can therefore include a following verb/question and look
    # like a second mechanism ("lời nguyền tri thức" vs "lời nguyền tri thức
    # hỏi điểm bắt đầu").  Treat prefix extensions as the same named mechanism;
    # genuinely different names remain independent candidates below.
    unique = {
        name for name in unique
        if not any(name != other and name.startswith(other + " ") for other in unique)
    }
    if len(unique) <= 1:
        return []
    return [_repair(
        "central_mechanism",
        f"Script đang nêu nhiều cơ chế cạnh tranh: {', '.join(sorted(unique)[:3])}.",
        "Chọn một cơ chế làm trục; các khái niệm còn lại chỉ được dùng làm bối cảnh hoặc loại bỏ.",
    )]


def _check_stage_direction_leak(script: Any) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(_segments_of(script), start=1):
        narration_lower = _narration_of(segment).lower()
        leaked = [p for p in _STAGE_DIRECTION_PATTERNS if p in narration_lower]
        if leaked:
            violations.append(_repair(
                "stage_direction",
                f"Section {index} có stage direction bị lẫn vào voiceover: {', '.join(leaked)}.",
                "Chuyển chỉ dẫn hình ảnh sang visual_intent/pexels_query; voiceover chỉ giữ lời đọc tự nhiên.",
            ))
    return violations


def _check_knowledge_examples(script: Any) -> list[dict[str, str]]:
    # Example quality is semantic/editorial, not a fixed keyword or label contract.
    # Leave that judgment to the upstream script generation/review model rather than
    # rejecting narration based on literal Vietnamese labels.
    return []


def _check_immediate_action(script: Any) -> list[dict[str, str]]:
    final_text = _narration_of(_segments_of(script)[-1]).lower() if _segments_of(script) else ""
    if any(hint in final_text for hint in _IMMEDIATE_ACTION_HINTS):
        return []
    return [_repair(
        "immediate_action",
        "Phần chốt chưa có một hành động có thể làm ngay sau khi xem.",
        "Kết bằng một mệnh lệnh nhỏ, cụ thể và làm được ngay, ví dụ 'Hãy đặt điện thoại ngoài bàn trong 10 phút tới'.",
    )]


def _check_final_payoff(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if segments and str(_get(segments[-1], "payoff", "") or "").strip():
        return []
    return [_repair(
        "final_payoff",
        "Section cuối thiếu payoff nêu rõ người xem nhận được gì khi áp dụng.",
        "Điền field payoff ở section cuối bằng kết quả cụ thể, thay vì chỉ dừng ở lời khuyên.",
    )]


def _check_absolute_health_finance_claims(script: Any) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for segment in _segments_of(script):
        text = _narration_of(segment).lower()
        absolute_claims = []
        for hint in _ABSOLUTE_CLAIM_HINTS:
            if hint not in text:
                continue
            if hint == "mọi người":
                if re.search(r"mọi người\s+(?:đều|sẽ|phải|luôn|chắc chắn|không thể)", text):
                    absolute_claims.append(hint)
                continue
            for match in re.finditer(re.escape(hint), text):
                prefix = text[max(0, match.start() - 48):match.start()]
                if not re.search(r"(không|chẳng|chưa|tránh)[^.?!]{0,40}$", prefix):
                    absolute_claims.append(hint)
                    break
        if any(hint in text for hint in _HEALTH_FINANCE_HINTS) and absolute_claims:
            violations.append(_repair(
                "health_finance_claim",
                "Phát hiện tuyên bố y tế/tài chính tuyệt đối hoặc áp dụng cho mọi người.",
                "Bỏ cam kết chắc chắn; nêu giới hạn, nguồn đáng tin và khuyến khích hỏi chuyên gia phù hợp.",
            ))
    return violations


def _segment_query(segment: Any) -> str:
    return str(_get(segment, "pexels_query", "") or _get(segment, "broll", "") or "")


def _check_pexels_queries(script: Any) -> list[dict[str, str]]:
    weak = {"", "video", "stock footage", "broll", "background", "abstract"}
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(_segments_of(script), start=1):
        query = _segment_query(segment).strip().lower()
        if query in weak or len(query.split()) < 2:
            violations.append(_repair(
                "pexels_query",
                f"Section {index} có Pexels query yếu/thiếu: {query or '<empty>'}.",
                "Viết query tiếng Anh mô tả cảnh cụ thể có chủ thể + hành động, ví dụ 'person checking phone at desk' hoặc 'busy street decision making'.",
            ))
    return violations


def _check_sourced_claims(script: Any) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for segment in _segments_of(script):
        narration = _narration_of(segment)
        narration_lower = narration.lower()
        for phrase in _SOURCED_CLAIM_PHRASES:
            if phrase in narration_lower:
                has_source = any(hint in narration_lower for hint in _SOURCE_HINTS)
                if not has_source:
                    warnings.append({
                        "rule": "sourced_claims",
                        "detail": f"Cụm '{phrase}' không kèm nguồn rõ ràng.",
                    })
    return warnings


def _script_text(script: Any) -> str:
    parts = [
        str(_get(script, "topic", "") or ""),
        str(_get(script, "title", "") or ""),
        str(_get(script, "description", "") or ""),
        " ".join(str(tag) for tag in (_get(script, "tags", ()) or ())),
    ]
    for segment in _segments_of(script):
        parts.extend([
            str(_get(segment, "caption", "") or ""),
            str(_get(segment, "broll", "") or ""),
            _narration_of(segment),
            " ".join(str(item) for item in (_get(segment, "emphasis", ()) or ())),
        ])
    return " ".join(parts)


def _check_dedup(script: Any, done_topics: Any) -> list[dict[str, str]]:
    if not done_topics:
        return []
    candidates = [
        value
        for value in (
            _get(script, "topic", ""),
            _get(script, "title", ""),
        )
        if value
    ]
    if not candidates:
        return []
    done_slugs = {series_mod.slugify(t) for t in done_topics}
    for candidate in candidates:
        slug = series_mod.slugify(candidate)
        if slug in done_slugs:
            return [{
                "rule": "series_dedup",
                "detail": f"Chủ đề/title '{candidate}' (slug={slug}) đã có trong done_topics.",
            }]
        for done_topic in done_topics:
            similarity = _topic_similarity(candidate, str(done_topic))
            if similarity >= 0.55:
                return [_repair(
                    "series_semantic_dedup",
                    f"Chủ đề/title '{candidate}' gần trùng '{done_topic}' (similarity={similarity:.2f}).",
                    "Đổi sang một cơ chế tâm lý khác, không chỉ thay ví dụ hoặc cách diễn đạt của tập đã có.",
                )]
    return []


def _topic_similarity(left: str, right: str) -> float:
    """Conservative lexical similarity for queue/ledger entries without an LLM call."""
    normalized_left = _normalise_topic_numbers(series_mod.slugify(left))
    normalized_right = _normalise_topic_numbers(series_mod.slugify(right))
    left_tokens = {token for token in normalized_left.split("-") if len(token) > 1}
    right_tokens = {token for token in normalized_right.split("-") if len(token) > 1}
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if len(overlap) < 4:
        return 0.0
    return len(overlap) / len(left_tokens | right_tokens)


def _normalise_topic_numbers(value: str) -> str:
    return value.replace("mot-tram-nghin", "100-000").replace("100-nghin", "100-000")


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
