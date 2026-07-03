"""Các dataclass bất biến chảy qua từng khâu của pipeline.

Mỗi khâu nhận model của khâu trước và trả về một bản sao được làm giàu thêm
qua `dataclasses.replace()` — KHÔNG mutate bản gốc.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    """Một đoạn của video: caption hiện trên màn hình + lời đọc.

    Được làm giàu dần: TTS bổ sung audio_path + duration_sec."""

    caption: str
    narration: str
    code: str = ""           # lệnh/đoạn code hiện trong terminal card (tùy chọn)
    danger: bool = False      # True -> tô đỏ cảnh báo
    broll: str = ""           # từ khoá (tiếng Anh) tìm B-roll stock cho render-ai
    video_type: str = "image_motion"  # image_motion | ai_video | static_terminal
    emphasis: tuple[str, ...] = ()  # từ khoá pop lớn (visual aid), vd "Quy tắc 2 phút"
    hook: bool = False        # cảnh hành động mạnh -> dồn vào cold-open hook đầu video
    transition: bool = False  # chèn whoosh + xfade NGAY TRƯỚC đoạn này (vấn đề->giải pháp)
    audio_path: Path | None = None
    duration_sec: float = 0.0


@dataclass(frozen=True)
class ComplianceCheck:
    """Kết quả CỔNG VERIFY chạy TRƯỚC khi lên kịch bản.

    Mỗi nội dung phải đạt tiêu chuẩn cộng đồng YouTube, bản quyền, an toàn
    quảng cáo + COPPA, tính chính xác & nguồn — xem video-quality-rules.md (mục 0).
    `passed=False` => khâu ideation phải dừng/sửa/loại ý tưởng, không viết script."""

    passed: bool
    community: str = ""      # Community Guidelines
    copyright: str = ""       # bản quyền nhạc/hình/B-roll/quote (license rõ)
    accuracy: str = ""        # số liệu/tuyên bố đã kiểm chứng + nguồn
    advertiser: str = ""      # advertiser-friendly / monetization
    coppa: str = ""           # made-for-kids đúng
    notes: str = ""           # ghi chú/nguồn bổ sung


@dataclass(frozen=True)
class VideoIdea:
    """Đầu ra khâu ideation (Claude viết, nạp từ scripts/*.json)."""

    topic: str
    title: str
    description: str
    tags: tuple[str, ...] = ()
    voice: str = "vi-VN-NamMinhNeural"
    compliance: ComplianceCheck | None = None


@dataclass(frozen=True)
class Script(VideoIdea):
    """VideoIdea + kịch bản đã chia đoạn."""

    body: str = ""
    segments: tuple[Segment, ...] = ()


@dataclass(frozen=True)
class Voiceover(Script):
    """Script + audio đã render (mỗi segment đã có audio_path/duration)."""

    audio_path: Path | None = None
    duration_sec: float = 0.0


@dataclass(frozen=True)
class RenderedVideo(Voiceover):
    """Voiceover + video file cuối cùng."""

    video_path: Path | None = None
    thumbnail_path: Path | None = None


@dataclass(frozen=True)
class PublishResult(RenderedVideo):
    """RenderedVideo + kết quả upload."""

    youtube_id: str | None = None
    url: str | None = None
    uploaded: bool = False
