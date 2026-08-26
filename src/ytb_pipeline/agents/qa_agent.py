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
from collections import Counter
from typing import Any

from ..ideation import series as series_mod
from ..content_contract import contract_for, effective_chars_per_min, estimate_duration_sec
from ..content_profiles import load_content_profile
from ..ideation.generator import GREETING_PREFIX
from ..config.settings import settings
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
            violations.extend(_check_dedup(
                script, context.get("done_topics"), context.get("exempt_slugs", ()),
            ))
            violations.extend(_check_absolute_health_finance_claims(script))
            if context.get("strict", False):
                violations.extend(_check_hook_strength(script))
                violations.extend(_check_hook_contract(script))
                if _get(script, "ruleset_id", ""):
                    violations.extend(_check_release_schema(script))
                violations.extend(_check_stage_direction_leak(script))
                violations.extend(_check_speaker_prefix_leak(script))
                violations.extend(_check_story_speaker_ownership(script))
                violations.extend(_check_character_voiceover_is_direct(script))
                violations.extend(_check_story_series_arc(script))
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


def _content_profile(script: Any):
    if not _get(script, "content_profile_version", ""):
        return None
    return load_content_profile(_get(script, "content_profile_id", "") or None)


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
    profile = _content_profile(script)
    contract = contract_for(video_type, profile)
    est_sec = estimate_duration_sec(
        sum(len(_narration_of(segment)) for segment in segments),
        chars_per_minute=effective_chars_per_min(
            profile.providers.tts if profile else settings.tts_provider,
            video_type=video_type,
            content_profile=profile,
        ),
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
        required_target_sec = float(target_minutes) * 60 + contract.transition_loss_sec(len(segments))
        if est_sec + contract.runtime_tolerance_sec < required_target_sec:
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

    profile = _content_profile(script)
    opening_mode = (
        profile.content_rules.long_opening_mode if profile is not None else "channel_greeting"
    )
    if is_long and opening_mode == "channel_greeting" and not starts_with_greeting and not settings.e2e_test:
        return [{
            "rule": "intro",
            "detail": f"Video dài phải mở đầu bằng \"{GREETING_PREFIX}\".",
        }]
    if is_long and opening_mode == "pain_first" and starts_with_greeting:
        return [{
            "rule": "intro",
            "detail": "Profile pain_first phải mở thẳng bằng tình huống đau, không dùng lời chào.",
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


# Neo phải là một khoảnh khắc CỤ THỂ, không phải một buổi chung chung: "sáu
# giờ bảy" khác "những buổi sáng". Vì thế mốc thời gian chỉ tính khi đi kèm một
# con số. Không dùng để "đếm từ khoá hay" — chỉ để phân biệt một cảnh có neo
# với một câu trừu tượng.
_STORY_MOMENT_MARKERS = (
    "giờ", "phút", "rưỡi", "sáng", "trưa", "chiều", "tối", "đêm", "hôm",
)
_STORY_NUMBER_WORDS = frozenset({
    "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười",
    "mươi", "rưỡi", "kém",
})
# Dấu hiệu có thứ để mất — hai lớp NGỮ NGHĨA khác nhau, cả hai đều là "stake"
# hợp lệ theo STORY_HOOK_CONTRACT (ideation_prompts.py): (1) nghĩa vụ/thời hạn
# chưa xong; (2) hậu quả/rủi ro. Một câu mở thật của Qwen ("sợ hỏi An thì bị
# chê là thiếu chủ động") có anchor rõ nhưng vẫn bị QA từ chối vì lớp (2)
# trước đây chưa có marker nào — không phải vì thiếu marker "sợ hỏi ... bị
# chê" cụ thể, mà vì thiếu CẢ LỚP hậu quả/rủi ro trong danh sách.
_STORY_STAKE_OBLIGATION_MARKERS = (
    "phải", "chưa", "vẫn", "còn", "sắp", "kịp", "hạn", "trễ", "muộn",
    "trước khi", "nhưng", "quên", "lỡ",
)
# "bị" là trợ từ bị động-nghịch (adversative passive) của tiếng Việt: gần như
# luôn đứng trước một hậu quả xấu xảy đến cho chủ thể ("bị chê", "bị la", "bị
# phạt", "bị đuổi", "bị trừ điểm"...), khác với "được" (trung tính/tích cực).
# Vì vậy một từ "bị" khái quát được cả lớp hậu quả mà không cần liệt kê từng
# động từ theo sau. "sợ"/"lo"/"nếu"/"nhỡ"/"kẻo" đánh dấu một rủi ro nhân vật
# đang lường trước, dù hậu quả có thể chưa xảy ra.
_STORY_STAKE_RISK_MARKERS = (
    "bị", "sợ", "lo", "nếu", "nhỡ", "kẻo",
)
_STORY_STAKE_MARKERS = _STORY_STAKE_OBLIGATION_MARKERS + _STORY_STAKE_RISK_MARKERS


def _story_words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)


def _check_story_hook(script: Any, profile: Any) -> list[dict[str, str]]:
    """Cổng mở đầu cho profile kể chuyện.

    Một cảnh mở mạnh không cần nghịch lý — nó cần hai thứ: NEO (người xem biết
    mình đang ở đâu, lúc nào, với ai) và THỨ ĐỂ MẤT (một nghĩa vụ chưa xong,
    một thời hạn). Luật cũ đòi từ khoá nghịch lý nên loại thẳng mọi mở đầu bằng
    cảnh, dù đó chính là điều làm series khác với video khuyên bảo.
    """
    segments = _segments_of(script)
    if not segments:
        return []
    first = _narration_of(segments[0]).strip()
    words = _story_words(first)
    narrator_id = profile.editorial_contract.narration_speaker_id
    cast = {name for name in profile.voice_cast if name != narrator_id}
    word_set = set(words)
    has_clock = any(marker in word_set for marker in _STORY_MOMENT_MARKERS) and (
        bool(_STORY_NUMBER_WORDS & word_set) or any(character.isdigit() for character in first)
    )
    has_anchor = bool(cast & word_set) or has_clock
    lowered = first.lower()
    has_stake = any(marker in words for marker in _STORY_STAKE_MARKERS) or any(
        marker in lowered for marker in _STORY_STAKE_MARKERS if " " in marker
    )
    if len(words) >= 8 and has_anchor and has_stake:
        return []
    return [_repair(
        "hook",
        "Cảnh mở đầu chưa neo được khoảnh khắc hoặc chưa có gì để mất.",
        "Mở bằng một mốc cụ thể (giờ, nơi chốn, tên nhân vật) rồi nêu ngay việc "
        "đang dở hoặc thời hạn đang đến, ví dụ: 'Sáu giờ bảy, Minh mở laptop. "
        "Tám rưỡi phải gửi bản đề xuất.'",
    )]


def _check_hook_strength(script: Any) -> list[dict[str, str]]:
    profile = _content_profile(script)
    if profile is not None and profile.narrative_mode == "character_story":
        return _check_story_hook(script, profile)
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
    deadline_ok = isinstance(deadline, (int, float)) and 0 < float(deadline) <= float(contract.answer_start_deadline_sec or 0)
    if (
        not all(str(value).strip() for value in required)
        or purposes[:2] != ["situation", "core_answer"]
        or not deadline_ok
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
    # A single regex match is not evidence of a competing mechanism: natural
    # narration commonly says "cơ chế này" or uses a descriptive tail once.
    # Count normalized mentions first; only repeatedly named mechanisms enter
    # the gate. This keeps the rule topic-agnostic instead of hardcoding words.
    normalized = [" ".join(name.split()) for name in names if name.strip()]
    counts = Counter(normalized)
    unique = {name for name, count in counts.items() if count >= 2}
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


def _check_speaker_prefix_leak(script: Any) -> list[dict[str, str]]:
    """Tên nhân vật đứng đầu lời đọc sẽ bị TTS đọc thành tiếng.

    `speaker_id` đã định tuyến giọng rồi, nên "An: Cậu đã mở..." vừa thừa vừa
    phá nhịp. Chỉ chặn dạng tiền tố "<tên>:" — gọi tên nhân vật trong câu là
    lời thoại bình thường.
    """
    profile = _content_profile(script)
    if profile is None or profile.narrative_mode != "character_story":
        return []
    narrator_id = profile.editorial_contract.narration_speaker_id
    cast = {name for name in profile.voice_cast if name != narrator_id}
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(_segments_of(script), start=1):
        head = _narration_of(segment).strip().split(":", 1)[0].strip().lower()
        if head and head in cast:
            violations.append(_repair(
                "speaker_prefix",
                f"Section {index} mở đầu bằng tên người nói ('{head}:'); TTS sẽ đọc cả tên.",
                "Bỏ tiền tố tên khỏi voiceover; giọng đã được chọn qua speaker_id.",
            ))
    return violations


def _check_story_speaker_ownership(script: Any) -> list[dict[str, str]]:
    """Reject a character's direct speech hidden inside a narrator segment.

    The schema-level ``turn`` card handles ownership before TTS. This second
    guard catches the most damaging escaped form: a long first-person address
    after narrative staging, which causes the narrator voice to read a whole
    character monologue. It is profile-configured and Vietnamese-generic; it
    does not know Minh, An, or any series-specific wording.
    """
    profile = _content_profile(script)
    if (
        profile is None
        or profile.narrative_mode != "character_story"
        or not profile.content_rules.require_conversation_turns
    ):
        return []
    direct_address = re.compile(
        r"(?:anh|chị|em|cậu|bạn)\s+ơi\s*,\s*(?:em|tôi|mình)\b",
        flags=re.IGNORECASE,
    )
    narrator_id = profile.editorial_contract.narration_speaker_id
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(_segments_of(script), start=1):
        if str(_get(segment, "speaker_id", narrator_id) or narrator_id).strip().lower() != narrator_id:
            continue
        narration = _narration_of(segment).strip()
        if len(narration) >= 220 and direct_address.search(narration):
            violations.append(_repair(
                "speaker_ownership",
                f"Section {index} gán một lời xưng hô trực tiếp dài cho narrator.",
                "Tách lời đó thành section riêng với speaker_id của nhân vật; narrator chỉ neo cảnh và hành động.",
            ))
    return violations


def _check_character_voiceover_is_direct(script: Any) -> list[dict[str, str]]:
    """A routed character voice may not narrate its own staging before speech."""
    profile = _content_profile(script)
    if (
        profile is None
        or profile.narrative_mode != "character_story"
        or not profile.content_rules.require_conversation_turns
    ):
        return []
    narrator_id = profile.editorial_contract.narration_speaker_id
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(_segments_of(script), start=1):
        speaker = str(_get(segment, "speaker_id", narrator_id) or narrator_id).strip().lower()
        if speaker == narrator_id:
            continue
        narration = _narration_of(segment).strip()
        colon = narration.find(":")
        if 0 < colon < len(narration) - 8:
            prelude = narration[:colon].casefold()
            # A character may naturally quote the exact words they are about
            # to say ("Tôi sẽ nói một câu: ...").  That is direct speech,
            # not narrator staging.  The unsafe shape remains third-person
            # action before the quote ("An đặt cốc xuống: ...").
            if re.search(r"\b(?:tôi|mình|em|tớ|ta|chúng tôi)\b", prelude):
                continue
            violations.append(_repair(
                "character_voiceover_direct",
                f"Section {index} có phần dẫn/hành động trước dấu ':' trong voiceover của {speaker}.",
                "Chuyển hành động sang narrator hoặc visual_intent; voiceover nhân vật chỉ giữ câu họ nói trực tiếp.",
            ))
    return violations


_NEXT_EPISODE_MARKERS = (
    "tập sau", "hẹn gặp lại", "lần tới", "phần sau",
)


def _check_story_series_arc(script: Any) -> list[dict[str, str]]:
    """Enforce an opt-in three-voice Long-series ending at the release gate.

    The profile declares roles, so this contains no knowledge of a particular
    cast or series. It proves the generated transcript kept the storyteller as
    the frame, let both characters actually participate, and left a truthful
    invitation into the following episode.
    """
    profile = _content_profile(script)
    if (
        profile is None
        or profile.narrative_mode != "character_story"
        or _script_video_type(script) != "long"
        or not profile.content_rules.story_primary_speaker_id
    ):
        return []
    segments = _segments_of(script)
    if not segments:
        return []
    rules = profile.content_rules
    narrator_id = profile.editorial_contract.narration_speaker_id
    primary = rules.story_primary_speaker_id
    supporting = rules.story_supporting_speaker_id
    speakers = [
        str(_get(segment, "speaker_id", narrator_id) or narrator_id).strip().lower()
        for segment in segments
    ]
    violations: list[dict[str, str]] = []
    unexpected = sorted(set(speakers) - {narrator_id, primary, supporting})
    if unexpected:
        violations.append(_repair(
            "story_series_cast",
            f"Story Long có speaker ngoài cast ba vai đã khai báo: {', '.join(unexpected)}.",
            "Chỉ dùng narrator, nhân vật chính và nhân vật phụ của profile; không thêm speaker mới.",
        ))
    missing = [speaker for speaker in (primary, supporting) if speaker not in speakers]
    if missing:
        violations.append(_repair(
            "story_series_roles",
            f"Story Long thiếu lượt thoại của vai: {', '.join(missing)}.",
            "Cho cả nhân vật chính lẫn nhân vật phụ một lượt thoại trực tiếp, có phản hồi nhân quả.",
        ))
    if speakers[0] != narrator_id or speakers[-1] != narrator_id:
        violations.append(_repair(
            "story_series_narrator_frame",
            "Story Long phải để narrator mở bối cảnh và khép ý nghĩa ở section cuối.",
            "Mở bằng narrator neo cảnh/cái giá; kết bằng narrator đúc kết cho người xem.",
        ))
    if rules.require_next_episode_bridge:
        final_text = _narration_of(segments[-1]).casefold()
        if not any(marker in final_text for marker in _NEXT_EPISODE_MARKERS):
            violations.append(_repair(
                "story_series_next_episode",
                "Phần chốt Story Long chưa hẹn một câu hỏi/lựa chọn cho tập tiếp theo.",
                "Giữ phần đúc kết của narrator và thêm một bridge tự nhiên như 'Tập sau...' hoặc 'Hẹn gặp lại...'.",
            ))
    return violations


def _check_knowledge_examples(script: Any) -> list[dict[str, str]]:
    # Example quality is semantic/editorial, not a fixed keyword or label contract.
    # Leave that judgment to the upstream script generation/review model rather than
    # rejecting narration based on literal Vietnamese labels.
    return []


# Một hành động cụ thể trong truyện được nhận ra bằng phạm vi đo được: một
# lượng thời gian, một số lần. "Làm việc kế tiếp trong hai mươi phút" là thứ
# người xem sao chép được; "cảm thấy nhẹ nhõm hơn" thì không.
_STORY_BOUNDED_ACTION_UNITS = ("phút", "giây", "tiếng", "trang", "dòng", "lần", "bước", "câu")


def _has_bounded_action(text: str) -> bool:
    words = _story_words(text)
    if not any(unit in words for unit in _STORY_BOUNDED_ACTION_UNITS):
        return False
    return bool(_STORY_NUMBER_WORDS & set(words)) or any(c.isdigit() for c in text)


# A generalised lesson needs enough substance to actually say something to
# the viewer, not just a one-line tag stapled onto the scene.
_NARRATOR_LESSON_MIN_WORDS = 12
# A lesson generalises to the VIEWER, not to the character it just watched —
# it needs a marker of direct address or of a repeatable/general situation
# ("next time", "you", "every time"), the same way a real advice-giving
# sentence would open in Vietnamese.
_NARRATOR_LESSON_ADDRESS_MARKERS = (
    "bạn", "chúng ta", "lần tới", "lần sau", "mỗi khi", "mỗi lần", "đừng",
)


def _is_narrator_lesson_closing(profile: Any, final_segment: Any, final_text: str) -> bool:
    """Opt-in ending contract: the NARRATOR generalises the story into a
    lesson spoken directly to the viewer (`content_rules.narrator_lesson_closing`),
    instead of the legacy contract requiring a bounded action a character does.

    A plain narrator sentence that just resolves the scene ("Buổi sáng trôi
    qua và Minh cảm thấy nhẹ nhõm hơn") is NOT a lesson — it still talks
    about a character in third person. This is rejected two ways: it must
    not name any cast member, and it must carry a direct-address/generalising
    marker, not just be a long narrator line.
    """
    if (
        profile is None
        or profile.narrative_mode != "character_story"
        or not profile.content_rules.narrator_lesson_closing
    ):
        return False
    narrator_id = profile.editorial_contract.narration_speaker_id
    speaker = str(_get(final_segment, "speaker_id", narrator_id) or narrator_id).strip().lower()
    if speaker != narrator_id:
        return False
    # The lesson is addressed to the viewer. A separate, explicitly marked
    # next-episode bridge may naturally refer back to a character, so only
    # evaluate the lesson portion for a cast-name leak.
    normalized_final = final_text.casefold()
    bridge_positions = [
        normalized_final.find(marker)
        for marker in _NEXT_EPISODE_MARKERS
        if normalized_final.find(marker) >= 0
    ]
    lesson_text = final_text[:min(bridge_positions)] if bridge_positions else final_text
    words = _story_words(lesson_text)
    if len(words) < _NARRATOR_LESSON_MIN_WORDS:
        return False
    cast = {name for name in profile.voice_cast if name != narrator_id}
    if cast & set(words):
        return False
    word_set = set(words)
    has_address = any(
        marker in word_set for marker in _NARRATOR_LESSON_ADDRESS_MARKERS if " " not in marker
    ) or any(
        marker in lesson_text for marker in _NARRATOR_LESSON_ADDRESS_MARKERS if " " in marker
    )
    return has_address


def _check_immediate_action(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    final_text = _narration_of(segments[-1]).lower() if segments else ""
    profile = _content_profile(script)
    if (
        profile is not None
        and _script_video_type(script) == "short"
        and profile.content_rules.short_ending_mode == "funnel_bridge"
    ):
        strategy = _get(script, "strategy", None)
        long_slug = str(_get(strategy, "long_form_slug", "") or "").strip()
        cta_target = str(_get(strategy, "cta_target", "") or "").strip()
        source_long_slug = str(_get(strategy, "source_long_slug", "") or "").strip()
        bridge_markers = ("video dài", "xem tiếp", "xem video", "long")
        if (
            long_slug
            and long_slug == cta_target == source_long_slug
            and any(marker in final_text for marker in bridge_markers)
        ):
            return []
        return [_repair(
            "funnel_bridge",
            "Short phễu phải kết bằng cầu nối tự nhiên tới đúng video Long đã khai báo.",
            "Nêu phần Long sẽ giải thích tiếp và giữ long_form_slug, cta_target, source_long_slug trùng nhau.",
        )]
    if any(hint in final_text for hint in _IMMEDIATE_ACTION_HINTS):
        return []
    if (
        profile is not None
        and profile.narrative_mode == "character_story"
        and _has_bounded_action(final_text)
    ):
        # Truyện kiếm được phần chốt bằng cách CHO THẤY hành động, không bằng
        # cách ra lệnh. Bắt buộc chữ "Hãy" là quy ước của kênh giải thích.
        return []
    if segments and _is_narrator_lesson_closing(profile, segments[-1], final_text):
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
    profile = _content_profile(script)
    if profile is not None and not profile.content_rules.require_pexels_query:
        return []
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


def _check_dedup(
    script: Any, done_topics: Any, exempt_slugs: Any = (),
) -> list[dict[str, str]]:
    """Chặn chủ đề trùng, trừ những slug đang được thay tại chỗ.

    `--replace-slug` viết lại kịch bản cho một slot ĐÃ tồn tại, nên slug của nó
    đương nhiên có trong ledger. Không miễn trừ thì mọi lần thay đều bị từ chối:
    operator xin viết lại một tập, pipeline trả lời rằng tập đó đã có rồi.
    """
    if not done_topics:
        return []
    exempt = {series_mod.slugify(str(slug)) for slug in (exempt_slugs or ()) if str(slug).strip()}
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
    done_slugs = {series_mod.slugify(t) for t in done_topics} - exempt
    for candidate in candidates:
        slug = series_mod.slugify(candidate)
        if slug in exempt:
            continue
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
