"""Khâu 1 — Ideation.

KỊCH BẢN do Claude viết tay trong chat, lưu thành file `scripts/*.json`. Module
này chỉ NẠP + VALIDATE file đó thành `Script` — đây cũng là CỔNG VERIFY (độ dài,
mở đầu, compliance) mà Claude phải tuân theo khi soạn kịch bản. Không gọi API
nào ở đây.
"""

import json
import re
from pathlib import Path

from ..pkg.models import ComplianceCheck, Script, Segment, VideoIdea

# Các mục verify bắt buộc trong khối `compliance` của mỗi file kịch bản.
_COMPLIANCE_FIELDS = ("community", "copyright", "accuracy", "advertiser", "coppa", "notes")

# Tốc độ đọc narration đo từ Edge-TTS vi-VN ở ~2x. F5 được post-process cùng
# tốc độ hiệu dụng trong `voiceover/tts.py`, nên đây là một hợp đồng chung cho
# mọi provider TTS và là cơ sở duy nhất để tính thời lượng từ số ký tự.
CHARS_PER_MIN = 1197.0
# Video dài (ngang) 12–15 phút: đủ chiều sâu, nhưng không kéo dài lan man.
LONG_MIN_MINUTES = 12
LONG_MAX_MINUTES = 15
# Short (dọc) 1–1.5 phút: đủ thời gian cho cơ chế + ví dụ + ứng dụng.
SHORT_MIN_MINUTES = 1.0
SHORT_MAX_MINUTES = 1.5

# Mở đầu LONG-FORM (mục 1b video-quality-rules.md): phần CỐ ĐỊNH duy nhất của lời
# chào. Phần sau cụm này do kịch bản tự sinh đa dạng (đọc tiêu đề + câu móc).
# SHORT cấm mở bằng cụm này — vào hook 2s thẳng để giữ Stayed-to-watch.
GREETING_PREFIX = "Mến chào các bạn,"
VIDEO_TYPES = ("short", "long")
VOICE_PROFILES = ("knowledge", "inspiring")
_WEAK_PEXELS_QUERIES = {"", "video", "stock footage", "broll", "background", "abstract"}


def estimate_minutes(segments) -> float:
    """Ước lượng thời lượng narration (phút) theo tổng số ký tự."""
    chars = sum(len(seg.narration) for seg in segments)
    return chars / CHARS_PER_MIN


def load_script(source: str | Path) -> Script:
    """Nạp kịch bản từ file JSON (hoặc slug trong thư mục scripts/).

    Validate tại ranh giới: thiếu field bắt buộc -> fail fast với thông báo rõ.
    """
    path = _resolve(source)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy kịch bản: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    for required in ("title", "sections"):
        if not data.get(required):
            raise ValueError(f"Kịch bản {path.name} thiếu field bắt buộc: '{required}'")

    compliance = _validate_compliance(data.get("compliance"), path.name)

    video_type = _normalize_video_type(data.get("video_type"), data.get("target_minutes"))
    target_minutes = data.get("target_minutes")
    segments = tuple(_segment_from_raw(s, path.name) for s in data["sections"]
                     if _section_voiceover(s).strip())
    if not segments:
        raise ValueError(f"Kịch bản {path.name} không có đoạn narration hợp lệ.")

    _validate_length(segments, target_minutes, path.name)
    _validate_intro(segments, target_minutes, path.name)
    _validate_pexels_queries(segments, path.name)

    idea = VideoIdea(
        topic=data.get("topic", data["title"]),
        title=data["title"],
        description=data.get("description", ""),
        tags=tuple(data.get("tags", ())),
        video_type=video_type,
        voice_profile=_normalize_voice_profile(data.get("voice_profile")),
        target_minutes=target_minutes,
        voice=data.get("voice", "vi-VN-NamMinhNeural"),
        compliance=compliance,
    )
    body = "\n\n".join(seg.narration for seg in segments)
    return Script(**vars(idea), body=body, segments=segments)


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


def _section_voiceover(raw: dict) -> str:
    return str(raw.get("voiceover") or raw.get("narration") or "")


def _segment_from_raw(raw: dict, name: str) -> Segment:
    narration = _section_voiceover(raw).strip()
    pexels_query = str(raw.get("pexels_query") or "").strip()
    broll = pexels_query or str(raw.get("broll") or "").strip()
    if "voiceover" not in raw and "narration" not in raw:
        raise ValueError(f"Kịch bản {name}: section thiếu voiceover/narration.")
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
        hook=bool(raw.get("hook", False)),
        transition=bool(raw.get("transition", False)),
        hook_text=str(raw.get("hook_text", raw.get("hook_reason", ""))).strip(),
        transition_text=str(raw.get("transition_text", "")).strip(),
        payoff=str(raw.get("payoff", "")).strip(),
    )


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


def _validate_pexels_queries(segments: tuple[Segment, ...], name: str) -> None:
    for index, seg in enumerate(segments, start=1):
        if not seg.pexels_query:
            continue
        query = seg.pexels_query.strip().lower()
        if query in _WEAK_PEXELS_QUERIES or len(query.split()) < 2:
            raise ValueError(
                f"Kịch bản {name}: section {index} có pexels_query yếu/thiếu. "
                "Query phải mô tả rõ hình ảnh hoặc hành động cụ thể bằng tiếng Anh."
            )


def _validate_length(segments, target_minutes, name: str) -> None:
    """Ép độ dài cho video dài (ngang).

    Kịch bản khai báo `target_minutes` (video ngang BẮT BUỘC có) -> fail-fast nếu
    nội dung quá mỏng so với mục tiêu, vượt 15 phút, hoặc target nằm ngoài khoảng
    [12, 15] phút.

    Short (không khai báo `target_minutes`) -> ép thời lượng trong
    [SHORT_MIN_MINUTES, SHORT_MAX_MINUTES] phút: fail-fast nếu narration ước
    lượng ngắn hơn 1 phút hoặc dài hơn 1.5 phút.
    """
    if target_minutes is None:
        _validate_short_length(segments, name)
        return
    if not isinstance(target_minutes, (int, float)) or not (
            LONG_MIN_MINUTES <= target_minutes <= LONG_MAX_MINUTES):
        raise ValueError(
            f"Kịch bản {name}: 'target_minutes' phải trong khoảng "
            f"[{LONG_MIN_MINUTES}, {LONG_MAX_MINUTES}] phút cho video dài (ngang)."
        )
    est = estimate_minutes(segments)
    if est < LONG_MIN_MINUTES:
        chars_need = int(LONG_MIN_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: nội dung quá mỏng — ước lượng ~{est:.1f} phút, "
            f"phải đạt ít nhất {LONG_MIN_MINUTES} phút (~{chars_need:,} ký tự narration)."
        )
    if est < target_minutes:
        chars_can = int(target_minutes * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: nội dung quá mỏng — ước lượng ~{est:.1f} phút nhưng "
            f"mục tiêu {target_minutes:.0f} phút. Viết chi tiết & sâu hơn (cần ~"
            f"{chars_can:,} ký tự narration: thêm cơ chế/ví dụ cụ thể/số liệu có "
            "nguồn/bước áp dụng, KHÔNG nói chung chung)."
        )
    if est > LONG_MAX_MINUTES:
        chars_max = int(LONG_MAX_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: video dài quá dài — ước lượng ~{est:.1f} phút, "
            f"phải không quá {LONG_MAX_MINUTES} phút (~{chars_max:,} ký tự narration). "
            "Cắt ý trùng/lặp, giữ một cơ chế và các bằng chứng cần thiết."
        )


def _validate_short_length(segments, name: str) -> None:
    """Ép thời lượng Short: BẮT BUỘC trong [SHORT_MIN_MINUTES, SHORT_MAX_MINUTES].

    Short không khai báo `target_minutes`. Narration ước lượng phải nằm trong
    khoảng 1–1.5 phút — fail-fast nếu quá ngắn (sơ sài) hoặc quá dài
    (vượt khung, lê thê).
    """
    est = estimate_minutes(segments)
    if est < SHORT_MIN_MINUTES:
        chars_need = int(SHORT_MIN_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: Short quá ngắn — ước lượng ~{est:.2f} phút, phải "
            f"ÍT NHẤT {SHORT_MIN_MINUTES:.1f} phút (cần ~{chars_need:,} ký tự "
            "narration). Viết chi tiết hơn: mỗi ý thêm cơ chế 'tại sao' + ví dụ/"
            "con số cụ thể + bước áp dụng, KHÔNG nói chung chung."
        )
    if est > SHORT_MAX_MINUTES:
        chars_max = int(SHORT_MAX_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: Short quá dài — ước lượng ~{est:.2f} phút, phải "
            f"KHÔNG QUÁ {SHORT_MAX_MINUTES:.1f} phút (tối đa ~{chars_max:,} ký tự "
            "narration). Cắt bớt đoạn thừa/khoảng chết, giữ nội dung cô đọng."
        )


def _validate_intro(segments, target_minutes, name: str) -> None:
    """Cổng mở đầu (mục 1b): video DÀI phải mở bằng lời chào; SHORT thì KHÔNG.

    Video dài (có `target_minutes`): segment đầu PHẢI bắt đầu bằng cụm cố định
    "Mến chào các bạn," (phần sau tự sinh: đọc tiêu đề + câu móc). Thiếu -> fail-fast.

    Short (không khai báo `target_minutes`): segment đầu KHÔNG được mở bằng lời chào
    — feed Shorts cần hook 2s thẳng, lời chào làm rớt Stayed-to-watch.
    """
    first = segments[0].narration.lstrip()
    is_long = target_minutes is not None
    starts_with_greeting = first.startswith(GREETING_PREFIX)

    if is_long and not starts_with_greeting:
        raise ValueError(
            f"Kịch bản {name}: video dài phải mở đầu bằng cụm cố định "
            f"\"{GREETING_PREFIX}\" rồi đọc tiêu đề + câu móc (xem mục 1b). "
            "Phần sau cụm chào tự sinh đa dạng theo chủ đề."
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
