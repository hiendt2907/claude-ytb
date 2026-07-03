"""Khâu 1 — Ideation.

KỊCH BẢN do Claude viết tay trong chat, lưu thành file `scripts/*.json`. Module
này chỉ NẠP + VALIDATE file đó thành `Script` — đây cũng là CỔNG VERIFY (độ dài,
mở đầu, compliance) mà Claude phải tuân theo khi soạn kịch bản. Không gọi API
nào ở đây.
"""

import json
from pathlib import Path

from ..pkg.models import ComplianceCheck, Script, Segment, VideoIdea

# Các mục verify bắt buộc trong khối `compliance` của mỗi file kịch bản.
_COMPLIANCE_FIELDS = ("community", "copyright", "accuracy", "advertiser", "coppa", "notes")

# Tốc độ đọc narration (đo thực từ video đã render): ~1197 ký tự/phút giọng vi-VN.
CHARS_PER_MIN = 1197.0
# Video dài (ngang) bắt buộc trong khoảng này — đủ sâu, không lan man.
LONG_MIN_MINUTES = 10
LONG_MAX_MINUTES = 30
# Short (dọc) BẮT BUỘC trên 0.8 phút, dưới 1.2 phút (~1.000-1.400 ký tự, ~45-60s)
# — ngắn, đánh mạnh vào 5-8s đầu để giữ Stayed-to-watch, không lê thê.
SHORT_MIN_MINUTES = 0.8
SHORT_MAX_MINUTES = 1.2

# Mở đầu LONG-FORM (mục 1b video-quality-rules.md): phần CỐ ĐỊNH duy nhất của lời
# chào. Phần sau cụm này do kịch bản tự sinh đa dạng (đọc tiêu đề + câu móc).
# SHORT cấm mở bằng cụm này — vào hook 2s thẳng để giữ Stayed-to-watch.
GREETING_PREFIX = "Mến chào các bạn,"


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

    segments = tuple(
        Segment(
            caption=s.get("caption", ""),
            narration=s["narration"].strip(),
            code=s.get("code", ""),
            danger=bool(s.get("danger", False)),
            broll=s.get("broll", ""),
            video_type=s.get("video_type", "image_motion"),
            emphasis=_normalize_emphasis(s.get("emphasis", ())),
            hook=bool(s.get("hook", False)),
            transition=bool(s.get("transition", False)),
        )
        for s in data["sections"]
        if s.get("narration", "").strip()
    )
    if not segments:
        raise ValueError(f"Kịch bản {path.name} không có đoạn narration hợp lệ.")

    _validate_length(segments, data.get("target_minutes"), path.name)
    _validate_intro(segments, data.get("target_minutes"), path.name)

    idea = VideoIdea(
        topic=data.get("topic", data["title"]),
        title=data["title"],
        description=data.get("description", ""),
        tags=tuple(data.get("tags", ())),
        voice=data.get("voice", "vi-VN-NamMinhNeural"),
        compliance=compliance,
    )
    body = "\n\n".join(seg.narration for seg in segments)
    return Script(**vars(idea), body=body, segments=segments)


def _validate_length(segments, target_minutes, name: str) -> None:
    """Ép độ dài cho video dài (ngang).

    Kịch bản khai báo `target_minutes` (video ngang BẮT BUỘC có) -> fail-fast nếu
    nội dung quá mỏng so với mục tiêu (tránh "video dài" chỉ 6 phút lan man) hoặc
    target nằm ngoài khoảng [10, 30] phút.

    Short (không khai báo `target_minutes`) -> ép thời lượng trong
    (SHORT_MIN_MINUTES, SHORT_MAX_MINUTES) phút: fail-fast nếu narration ước
    lượng ≤ SHORT_MIN_MINUTES (quá ngắn/sơ sài) hoặc ≥ SHORT_MAX_MINUTES
    (lê thê, vượt khung Short).
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
    if est < target_minutes:
        chars_can = int(target_minutes * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: nội dung quá mỏng — ước lượng ~{est:.1f} phút nhưng "
            f"mục tiêu {target_minutes:.0f} phút. Viết chi tiết & sâu hơn (cần ~"
            f"{chars_can:,} ký tự narration: thêm cơ chế/ví dụ cụ thể/số liệu có "
            "nguồn/bước áp dụng, KHÔNG nói chung chung)."
        )


def _validate_short_length(segments, name: str) -> None:
    """Ép thời lượng Short: BẮT BUỘC trên SHORT_MIN_MINUTES, dưới SHORT_MAX_MINUTES.

    Short không khai báo `target_minutes`. Narration ước lượng phải nằm trong
    khoảng (SHORT_MIN_MINUTES, SHORT_MAX_MINUTES) phút — fail-fast nếu quá
    ngắn (sơ sài) hoặc quá dài (vượt khung, lê thê).
    """
    est = estimate_minutes(segments)
    if est <= SHORT_MIN_MINUTES:
        chars_need = int(SHORT_MIN_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: Short quá ngắn — ước lượng ~{est:.2f} phút, phải "
            f"TRÊN {SHORT_MIN_MINUTES:.1f} phút (cần > ~{chars_need:,} ký tự "
            "narration). Viết chi tiết hơn: mỗi ý thêm cơ chế 'tại sao' + ví dụ/"
            "con số cụ thể + bước áp dụng, KHÔNG nói chung chung."
        )
    if est >= SHORT_MAX_MINUTES:
        chars_max = int(SHORT_MAX_MINUTES * CHARS_PER_MIN)
        raise ValueError(
            f"Kịch bản {name}: Short quá dài — ước lượng ~{est:.2f} phút, phải "
            f"DƯỚI {SHORT_MAX_MINUTES:.1f} phút (tối đa ~{chars_max:,} ký tự "
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
