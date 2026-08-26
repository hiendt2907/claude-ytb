"""Khâu 1 — Ideation.

KỊCH BẢN do Claude viết tay trong chat, lưu thành file `scripts/*.json`. Module
này chỉ NẠP + VALIDATE file đó thành `Script` — đây cũng là CỔNG VERIFY (độ dài,
mở đầu, compliance) mà Claude phải tuân theo khi soạn kịch bản. Không gọi API
nào ở đây.
"""

import json
import re
from pathlib import Path

from ..config.settings import settings
from ..content_profiles import ContentProfile, load_content_profile
from ..content_contract import (
    CONTRACT_VERSION,
    EDGE_CHARS_PER_MIN,
    F5_CHARS_PER_MIN,
    contract_for,
    chars_per_min_for_provider as _contract_chars_per_min,
    effective_chars_per_min,
    estimate_duration_sec,
)
from ..pkg.models import (
    ComplianceCheck,
    ContentStrategy,
    HookPlan,
    Script,
    Segment,
    ThumbnailBrief,
    VideoIdea,
)

# Các mục verify bắt buộc trong khối `compliance` của mỗi file kịch bản.
_COMPLIANCE_FIELDS = ("community", "copyright", "accuracy", "advertiser", "coppa", "notes")

def chars_per_min_for_provider(
    provider: str | None = None, *, video_type: str | None = None
) -> float:
    """Tốc độ planning theo provider đang được chọn.

    F5 giữ nhịp tự nhiên ở tempo an toàn cho STT; Edge gửi rate trực tiếp cho
    provider. `video_type` chọn nhịp riêng của Long khi đã đo được. Mọi output
    vẫn bị kiểm tra lại bằng duration đo từ file audio.
    """
    return _contract_chars_per_min(provider or settings.tts_provider, video_type=video_type)


# Compatibility export for older callers.  It must match the configured voice
# provider; keeping F5 here would make fixtures and planning disagree with the
# runtime duration gate whenever the provider changes.
CHARS_PER_MIN = chars_per_min_for_provider()
# Compatibility exports.  Values belong to ``content_contract.py``; stages
# must call ``contract_for`` rather than introduce format-local thresholds.
LONG_MIN_MINUTES = int(contract_for("long").viewer_runtime_bounds_sec[0] / 60)
LONG_MAX_MINUTES = int(contract_for("long").viewer_runtime_bounds_sec[1] / 60)
LONG_RUNTIME_MAX_MINUTES = LONG_MAX_MINUTES
LONG_MIN_SECTIONS = contract_for("long").minimum_sections
SHORT_MIN_MINUTES = contract_for("short").viewer_runtime_bounds_sec[0] / 60
SHORT_MAX_MINUTES = contract_for("short").viewer_runtime_bounds_sec[1] / 60
SHORT_ANSWER_START_TARGET_SEC = contract_for("short").answer_start_target_sec or 4.0

# Mở đầu LONG-FORM (mục 1b video-quality-rules.md): phần CỐ ĐỊNH duy nhất của lời
# chào. Phần sau cụm này do kịch bản tự sinh đa dạng (đọc tiêu đề + câu móc).
# SHORT cấm mở bằng cụm này — vào hook 2s thẳng để giữ Stayed-to-watch.
GREETING_PREFIX = "Mến chào các bạn,"
VIDEO_TYPES = ("short", "long")
VOICE_PROFILES = ("knowledge", "inspiring")
_WEAK_PEXELS_QUERIES = {"", "video", "stock footage", "broll", "background", "abstract"}


def estimate_minutes(
    segments, *, tts_provider: str | None = None, video_type: str | None = None,
    content_profile: ContentProfile | None = None,
) -> float:
    """Ước lượng planning theo provider; không thay thế duration audio thực.

    `video_type` chọn nhịp đọc riêng của Long — một Long đọc liền mạch nên
    nhanh hơn Short cùng số ký tự.
    """
    chars = sum(len(seg.narration) for seg in segments)
    # The per-profile pace correction has been calibrated for Longs, where
    # multi-voice segment handoffs materially affect the admission floor. Keep
    # legacy/Short estimates on the public compatibility helper; their
    # fixtures and their separately calibrated Short contract use that rate.
    rate = (
        effective_chars_per_min(
            tts_provider or settings.tts_provider,
            video_type=video_type,
            content_profile=content_profile,
        )
        if video_type == "long" and content_profile is not None
        else chars_per_min_for_provider(tts_provider, video_type=video_type)
    )
    return estimate_duration_sec(chars, chars_per_minute=rate) / 60


def validate_runtime_duration(
    video_type: str, duration_sec: float, *, segment_count: int = 1
) -> None:
    """Validate source-audio runtime against the canonical viewer contract."""
    contract_for(video_type).validate_audio_runtime(duration_sec, segment_count=segment_count)


def load_script(source: str | Path) -> Script:
    """Nạp kịch bản từ file JSON (hoặc slug trong thư mục scripts/).

    Validate tại ranh giới: thiếu field bắt buộc -> fail fast với thông báo rõ.
    """
    path = _resolve(source)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy kịch bản: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    explicit_profile = bool(str(data.get("profile_id") or "").strip())
    profile_id = str(data.get("profile_id") or settings.content_profile_id).strip()
    content_profile = load_content_profile(profile_id)
    active_profile = content_profile if explicit_profile else None
    declared_profile_version = str(data.get("profile_version") or "").strip()
    if explicit_profile and not declared_profile_version:
        raise ValueError(
            f"Kịch bản {path.name}: script có profile_id phải khai báo profile_version."
        )
    if declared_profile_version and declared_profile_version != content_profile.version:
        raise ValueError(
            f"Kịch bản {path.name}: profile_version={declared_profile_version!r} "
            f"không khớp profile '{profile_id}' version={content_profile.version!r}."
        )
    video_type = _normalize_video_type(data.get("video_type"), data.get("target_minutes"))

    for required in ("title", "sections"):
        if not data.get(required):
            raise ValueError(f"Kịch bản {path.name} thiếu field bắt buộc: '{required}'")

    compliance = _validate_compliance(data.get("compliance"), path.name)
    # `strategy` là hợp đồng funnel của kênh giải thích. Với profile không dùng
    # nó, một `strategy` model lỡ thêm vào KHÔNG được phép đánh hỏng cả tập:
    # nó không mang nghĩa gì trong hợp đồng của profile đó.
    strategy = (
        _strategy_from_raw(data.get("strategy"), path.name)
        if content_profile.content_rules.require_short_source_trace
        else None
    )
    thumbnail_brief = _thumbnail_brief_from_raw(data.get("thumbnail_brief"), path.name)

    target_minutes = data.get("target_minutes")
    segments = tuple(_segment_from_raw(s, path.name) for s in data["sections"]
                     if _section_voiceover(s).strip())
    if not segments:
        raise ValueError(f"Kịch bản {path.name} không có đoạn narration hợp lệ.")
    if active_profile is not None:
        format_profile = active_profile.format_for(video_type)
        if len(segments) < format_profile.min_sections:
            raise ValueError(
                f"Kịch bản {path.name}: profile cần ít nhất "
                f"{format_profile.min_sections} section."
            )
        if len(segments) > format_profile.max_sections:
            raise ValueError(
                f"Kịch bản {path.name}: profile cho phép tối đa "
                f"{format_profile.max_sections} section."
            )

    current_ruleset = str(data.get("ruleset_id", "")).strip() == CONTRACT_VERSION
    _validate_length(
        segments, target_minutes, path.name,
        renderer_aware=current_ruleset, content_profile=active_profile,
    )
    _validate_long_structure(
        segments, target_minutes, path.name, content_profile=active_profile
    )
    _validate_intro(
        segments, target_minutes, path.name, content_profile=active_profile
    )
    _validate_pexels_queries(
        segments,
        path.name,
        required=(
            current_ruleset
            and (active_profile is None or active_profile.content_rules.require_pexels_query)
        ),
    )
    if video_type == "short" and (
        active_profile is None or active_profile.content_rules.require_short_source_trace
    ):
        _validate_short_hook_contract(
            segments, strategy, path.name, content_profile=active_profile
        )

    idea = VideoIdea(
        topic=data.get("topic", data["title"]),
        title=data["title"],
        description=data.get("description", ""),
        tags=tuple(data.get("tags", ())),
        content_profile_id=content_profile.profile_id,
        content_profile_version=content_profile.version if explicit_profile else "",
        video_type=video_type,
        voice_profile=_normalize_voice_profile(data.get("voice_profile")),
        target_minutes=target_minutes,
        voice=data.get("voice", "vi-VN-NamMinhNeural"),
        compliance=compliance,
        strategy=strategy,
        ruleset_id=str(data.get("ruleset_id", "")).strip(),
    )
    body = "\n\n".join(seg.narration for seg in segments)
    return Script(
        **vars(idea),
        body=body,
        segments=segments,
        thumbnail_brief=thumbnail_brief,
    )


def _normalize_video_type(raw: str | None, target_minutes) -> str:
    if raw is None:
        return "long" if target_minutes is not None else "short"
    value = str(raw).strip().lower()
    if value in VIDEO_TYPES:
        return value
    if value.startswith("short"):
        return "short"
    if value.startswith("long"):
        return "long"
    raise ValueError(f"video_type phải là một trong {VIDEO_TYPES}, không phải {raw!r}")


def _normalize_voice_profile(raw: str | None) -> str:
    if raw is None:
        return "knowledge"
    value = str(raw).strip().lower()
    if value in VOICE_PROFILES:
        return value
    raise ValueError(f"voice_profile phải là một trong {VOICE_PROFILES}, không phải {raw!r}")


def _strategy_from_raw(raw: dict | None, name: str) -> ContentStrategy | None:
    """Load strategy-v1 metadata while keeping all legacy scripts readable."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Kịch bản {name}: strategy phải là object.")
    hook_raw = raw.get("hook")
    if not isinstance(hook_raw, dict):
        raise ValueError(f"Kịch bản {name}: strategy.hook phải là object.")
    try:
        hook = HookPlan(
            situation=str(hook_raw.get("situation", "")).strip(),
            core_answer=str(hook_raw.get("core_answer", "")).strip(),
            open_loop=str(hook_raw.get("open_loop", "")).strip(),
            answer_by_sec=float(hook_raw.get("answer_by_sec", 5.0)),
        )
        return ContentStrategy(
            format_id=str(raw.get("format_id", "")).strip(),
            core_mechanism=str(raw.get("core_mechanism", "")).strip(),
            audience_problem=str(raw.get("audience_problem", "")).strip(),
            angle=str(raw.get("angle", "")).strip(),
            long_form_slug=str(raw.get("long_form_slug", "")).strip(),
            playlist=str(raw.get("playlist", "")).strip(),
            cta_target=str(raw.get("cta_target", "")).strip(),
            source_long_slug=str(raw.get("source_long_slug", "")).strip(),
            source_section_index=_optional_source_section_index(raw.get("source_section_index"), name),
            source_excerpt=str(raw.get("source_excerpt", "")).strip(),
            hook=hook,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kịch bản {name}: strategy không hợp lệ: {exc}") from exc


def _thumbnail_brief_from_raw(raw: dict | None, name: str) -> ThumbnailBrief | None:
    """Load the optional thumbnail contract without breaking legacy scripts."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Kịch bản {name}: thumbnail_brief phải là object.")
    try:
        return ThumbnailBrief(
            visual_contradiction=raw.get("visual_contradiction", ""),
            subject=raw.get("subject", ""),
            emotion=raw.get("emotion", ""),
            headline=raw.get("headline", ""),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kịch bản {name}: thumbnail_brief không hợp lệ: {exc}") from exc


def _optional_source_section_index(raw, name: str) -> int | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"Kịch bản {name}: source_section_index phải là số nguyên.")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kịch bản {name}: source_section_index phải là số nguyên.") from exc
    if value < 0:
        raise ValueError(f"Kịch bản {name}: source_section_index phải >= 0.")
    return value


def _section_voiceover(raw: dict) -> str:
    return str(raw.get("voiceover") or raw.get("narration") or "")


def _segment_from_raw(raw: dict, name: str) -> Segment:
    narration = _section_voiceover(raw).strip()
    pexels_query = str(raw.get("pexels_query") or "").strip()
    broll = pexels_query or str(raw.get("broll") or "").strip()
    if "voiceover" not in raw and "narration" not in raw:
        raise ValueError(f"Kịch bản {name}: section thiếu voiceover/narration.")
    hook, legacy_hook_text = _flag_and_legacy_text(raw.get("hook"), name, "hook")
    transition, legacy_transition_text = _flag_and_legacy_text(
        raw.get("transition"), name, "transition"
    )
    return Segment(
        caption=str(raw.get("caption", "")).strip(),
        narration=narration,
        voiceover=narration,
        time_goal=_normalize_time_goal(raw.get("time_goal"), name),
        visual_intent=str(raw.get("visual_intent", "")).strip(),
        pexels_query=pexels_query,
        code=raw.get("code", ""),
        danger=bool(raw.get("danger", False)),
        broll=broll,
        video_type=raw.get("render_video_type", raw.get("video_type", "image_motion")),
        emphasis=_normalize_emphasis(raw.get("emphasis", ())),
        hook=hook,
        transition=transition,
        hook_text=str(raw.get("hook_text", raw.get("hook_reason", legacy_hook_text))).strip(),
        transition_text=str(raw.get("transition_text", legacy_transition_text)).strip(),
        payoff=str(raw.get("payoff", "")).strip(),
        purpose=str(raw.get("purpose", "")).strip(),
        speaker_id=str(raw.get("speaker_id") or "narrator").strip().lower(),
        visual_asset=str(raw.get("visual_asset") or "").strip(),
        scene_characters=_normalize_scene_characters(raw.get("scene_characters")),
        voice_style=str(raw.get("voice_style", raw.get("acting", ""))).strip(),
        voice_tempo=_optional_float(raw.get("voice_tempo"), name, "voice_tempo"),
        voice_pitch=_optional_float(raw.get("voice_pitch"), name, "voice_pitch"),
        voice_gain=_optional_float(raw.get("voice_gain"), name, "voice_gain"),
        voice_pause_before=_optional_float(raw.get("voice_pause_before"), name, "voice_pause_before"),
        voice_pause_after=_optional_float(raw.get("voice_pause_after"), name, "voice_pause_after"),
    )


def _flag_and_legacy_text(raw, name: str, field_name: str) -> tuple[bool, str]:
    """Parse a new boolean flag or migrate the legacy descriptive string."""
    if raw is None:
        return False, ""
    if isinstance(raw, bool):
        return raw, ""
    if isinstance(raw, str):
        return False, raw.strip()
    raise ValueError(f"Kịch bản {name}: {field_name} phải là boolean hoặc text mô tả.")


def _optional_float(raw, name: str, field_name: str) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kịch bản {name}: {field_name} phải là số.") from exc


def _normalize_time_goal(raw, name: str) -> float | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        matches = re.findall(r"\d+(?:\.\d+)?", raw)
        if not matches:
            raise ValueError(f"Kịch bản {name}: time_goal không hợp lệ: {raw!r}")
        raw = matches[-1]
    value = float(raw)
    if value <= 0:
        raise ValueError(f"Kịch bản {name}: time_goal phải > 0.")
    return value


def _validate_pexels_queries(
    segments: tuple[Segment, ...], name: str, *, required: bool = False
) -> None:
    for index, seg in enumerate(segments, start=1):
        if not seg.pexels_query:
            if required:
                raise ValueError(
                    f"Kịch bản {name}: section {index} thiếu pexels_query."
                )
            continue
        query = seg.pexels_query.strip().lower()
        if query in _WEAK_PEXELS_QUERIES or len(query.split()) < 2:
            raise ValueError(
                f"Kịch bản {name}: section {index} có pexels_query yếu/thiếu. "
                "Query phải mô tả rõ hình ảnh hoặc hành động cụ thể bằng tiếng Anh."
            )


def _validate_length(
    segments, target_minutes, name: str, *, renderer_aware: bool = False,
    content_profile: ContentProfile | None = None,
) -> None:
    """Ép độ dài cho video dài (ngang).

    Kịch bản khai báo `target_minutes` (video ngang BẮT BUỘC có) -> fail-fast nếu
    nội dung quá mỏng so với mục tiêu, vượt 15 phút, hoặc target nằm ngoài khoảng
    [12, 15] phút.

    Short (không khai báo `target_minutes`) -> ép thời lượng trong
    [SHORT_MIN_MINUTES, SHORT_MAX_MINUTES] phút: fail-fast nếu narration ước
    lượng ngắn hơn 1 phút hoặc dài hơn 1.5 phút.
    """
    video_type = "short" if target_minutes is None else "long"
    contract = contract_for(video_type, content_profile)
    long_lower, long_upper = contract_for("long", content_profile).viewer_runtime_bounds_sec
    if target_minutes is not None and (
        not isinstance(target_minutes, (int, float))
        or not (long_lower / 60 <= target_minutes <= long_upper / 60)
    ):
        raise ValueError(
            f"Kịch bản {name}: 'target_minutes' phải trong khoảng "
            f"[{long_lower / 60:g}, {long_upper / 60:g}] phút cho video dài (ngang)."
        )
    tts_provider = content_profile.providers.tts if content_profile is not None else None
    est_sec = estimate_minutes(
        segments,
        tts_provider=tts_provider,
        video_type=video_type,
        content_profile=content_profile,
    ) * 60
    try:
        contract.validate_audio_runtime(
            est_sec, segment_count=len(segments) if renderer_aware else 1
        )
    except ValueError as exc:
        detail = str(exc)
        if "quá ngắn" in detail and video_type == "long":
            detail = f"nội dung quá mỏng — {detail}"
        raise ValueError(f"Kịch bản {name}: {detail}") from exc
    if target_minutes is None:
        return
    required_target_sec = float(target_minutes) * 60 + (
        contract.transition_loss_sec(len(segments)) if renderer_aware else 0.0
    )
    if est_sec + contract.runtime_tolerance_sec < required_target_sec:
        chars_can = int(
            required_target_sec / 60
            * chars_per_min_for_provider(tts_provider, video_type=video_type)
        )
        raise ValueError(
            f"Kịch bản {name}: nội dung quá mỏng — audio ước lượng ~{est_sec / 60:.1f} phút nhưng "
            f"mục tiêu {target_minutes:.0f} phút. Viết chi tiết & sâu hơn (cần ~"
            f"{chars_can:,} ký tự narration: thêm cơ chế/ví dụ cụ thể/số liệu có "
            "nguồn/bước áp dụng, KHÔNG nói chung chung)."
        )


def _validate_short_hook_contract(
    segments: tuple[Segment, ...], strategy: ContentStrategy | None, name: str,
    *, content_profile: ContentProfile | None = None,
) -> None:
    """Pre-TTS guard for the tested Short hook.

    ``answer_by_sec`` means the moment the answer *starts*, never the time at
    which a full explanatory section ends.  This deterministic check prevents
    obviously late hooks from spending local/cloud TTS time; post-TTS QA then
    confirms the same boundary from actual segment durations.
    """
    if strategy is None or strategy.hook is None:
        return  # Compatibility for scripts written before strategy-v1.
    if len(segments) < 2:
        raise ValueError(f"Kịch bản {name}: Short strategy cần situation và core_answer liên tiếp.")
    situation, answer_segment = segments[0], segments[1]
    if situation.purpose != "situation" or answer_segment.purpose != "core_answer":
        raise ValueError(
            f"Kịch bản {name}: Short strategy phải đặt situation rồi core_answer ngay sau đó."
        )
    answer = " ".join(strategy.hook.core_answer.split())
    narration = " ".join(answer_segment.narration.split())
    if not narration.startswith(answer):
        raise ValueError(f"Kịch bản {name}: core_answer phải mở đầu narration của section core_answer.")
    contract = contract_for("short", content_profile)
    tts_provider = content_profile.providers.tts if content_profile is not None else None
    estimated_start_sec = (
        len(situation.narration)
        / chars_per_min_for_provider(tts_provider, video_type="short")
        * 60
    )
    if estimated_start_sec > (contract.answer_start_deadline_sec or strategy.hook.answer_by_sec):
        raise ValueError(
            f"Kịch bản {name}: core_answer không thể bắt đầu trước "
            f"{strategy.hook.answer_by_sec:.1f}s (ước lượng {estimated_start_sec:.1f}s)."
        )


def _validate_long_structure(
    segments, target_minutes, name: str,
    *, content_profile: ContentProfile | None = None,
) -> None:
    """Long-form needs editorial beats, not a few oversized narration blocks."""
    minimum = contract_for("long", content_profile).minimum_sections
    if target_minutes is not None and len(segments) < minimum:
        raise ValueError(
            f"Kịch bản {name}: video dài cần ít nhất {minimum} section "
            "để có nhịp hình, diễn giải và ứng dụng rõ ràng."
        )


def _validate_intro(
    segments, target_minutes, name: str,
    *, content_profile: ContentProfile | None = None,
) -> None:
    """Validate the profile-declared Long opening; Shorts never greet."""
    first = segments[0].narration.lstrip()
    is_long = target_minutes is not None
    starts_with_greeting = first.startswith(GREETING_PREFIX)

    opening_mode = (
        content_profile.content_rules.long_opening_mode
        if content_profile is not None
        else "channel_greeting"
    )
    if is_long and opening_mode == "channel_greeting" and not starts_with_greeting and not settings.e2e_test:
        raise ValueError(
            f"Kịch bản {name}: video dài phải mở đầu bằng cụm cố định "
            f"\"{GREETING_PREFIX}\" rồi đọc tiêu đề + câu móc (xem mục 1b). "
            "Phần sau cụm chào tự sinh đa dạng theo chủ đề."
        )
    if is_long and opening_mode == "pain_first" and starts_with_greeting:
        raise ValueError(
            f"Kịch bản {name}: profile pain_first phải mở thẳng bằng tình huống đau, "
            f"không dùng lời chào \"{GREETING_PREFIX}\"."
        )
    if not is_long and starts_with_greeting:
        raise ValueError(
            f"Kịch bản {name}: Short KHÔNG được mở bằng lời chào "
            f"\"{GREETING_PREFIX}\" — vào hook 2 giây thẳng để giữ Stayed-to-watch "
            "(lời chào + đọc tiêu đề chỉ dành cho video dài)."
        )


def _validate_compliance(raw: dict | None, name: str) -> ComplianceCheck:
    """CỔNG VERIFY: mỗi kịch bản phải mang kết quả verify đã PASS.

    Tiêu chuẩn cộng đồng/bản quyền/chính xác/an toàn quảng cáo + COPPA phải được
    kiểm TRƯỚC khi lên kịch bản (xem video-quality-rules.md mục 0). Thiếu khối
    `compliance` hoặc `passed` không True -> fail fast, không cho nạp.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"Kịch bản {name} thiếu khối 'compliance' (cổng verify tiêu chuẩn cộng đồng/"
            "bản quyền). Phải rà soát TRƯỚC khi lên kịch bản — xem video-quality-rules.md."
        )
    if raw.get("passed") is not True:
        raise ValueError(
            f"Kịch bản {name} chưa qua cổng verify ('passed' != true). Nội dung FAIL "
            "tiêu chuẩn cộng đồng/bản quyền phải sửa hoặc loại, không được nạp."
        )
    return ComplianceCheck(
        passed=True,
        **{f: str(raw.get(f, "")) for f in _COMPLIANCE_FIELDS},
    )


def _normalize_scene_characters(raw) -> tuple[str, ...]:
    """Nhân vật xuất hiện trong khung hình, dùng khi auto-generate ảnh.

    Không validate ở đây theo cast của profile — validate đó thuộc về
    script_contract (đã có content_profile trong tay), giữ hàm này thuần.
    """
    if raw is None or isinstance(raw, bool):
        return ()
    if isinstance(raw, str):
        value = raw.strip().lower()
        return (value,) if value else ()
    if isinstance(raw, (list, tuple)):
        return tuple(
            dict.fromkeys(str(item).strip().lower() for item in raw if str(item).strip())
        )
    return ()


def _normalize_emphasis(raw) -> tuple[str, ...]:
    """Normalize LLM-produced emphasis into tuple[str, ...].

    Local LLMs often return `true`/`false` or a single string even though the
    renderer expects an iterable of terms. Treat booleans/missing values as no
    emphasis and keep single strings as one term instead of iterating chars.
    """
    if raw is None or isinstance(raw, bool):
        return ()
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _resolve(source: str | Path) -> Path:
    path = Path(source)
    if path.suffix == ".json" or path.exists():
        return path
    # coi như slug: scripts/<slug>.json
    return Path("scripts") / f"{path.name}.json"
