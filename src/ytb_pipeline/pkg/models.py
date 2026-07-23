"""Các dataclass bất biến chảy qua từng khâu của pipeline.

Mỗi khâu nhận model của khâu trước và trả về một bản sao được làm giàu thêm
qua `dataclasses.replace()` — KHÔNG mutate bản gốc.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HookPlan:
    """Editorial contract for the first seconds of a Short.

    The contract is intentionally separate from the rendered narration so the
    generator, audio QA, and analytics feedback can agree on what was tested.
    """

    situation: str
    core_answer: str
    open_loop: str
    answer_by_sec: float = 5.0

    def __post_init__(self) -> None:
        if not all((self.situation.strip(), self.core_answer.strip(), self.open_loop.strip())):
            raise ValueError("HookPlan cần situation, core_answer và open_loop.")
        if not 0 < self.answer_by_sec <= 5:
            raise ValueError("HookPlan.answer_by_sec phải nằm trong khoảng (0, 5].")


@dataclass(frozen=True)
class ContentStrategy:
    """Stable content metadata used by ideation, funnel QA, and analytics."""

    format_id: str
    core_mechanism: str
    audience_problem: str
    angle: str
    long_form_slug: str = ""
    playlist: str = ""
    cta_target: str = ""
    source_long_slug: str = ""
    source_section_index: int | None = None
    source_excerpt: str = ""
    hook: HookPlan | None = None

    def __post_init__(self) -> None:
        required = (self.format_id, self.core_mechanism, self.audience_problem, self.angle)
        if not all(value.strip() for value in required):
            raise ValueError("ContentStrategy thiếu format, mechanism, audience problem hoặc angle.")
        funnel = (self.long_form_slug, self.playlist, self.cta_target)
        if any(funnel) and not all(value.strip() for value in funnel):
            raise ValueError("ContentStrategy có funnel thì phải đủ long_form_slug, playlist và cta_target.")
        source = (self.source_long_slug, self.source_section_index, self.source_excerpt)
        if any(value not in (None, "") for value in source):
            if not self.source_long_slug.strip() or self.source_section_index is None or not self.source_excerpt.strip():
                raise ValueError("ContentStrategy có source trace thì phải đủ long slug, section index và excerpt.")
            if self.source_section_index < 0:
                raise ValueError("ContentStrategy.source_section_index phải >= 0.")


@dataclass(frozen=True)
class Segment:
    """Một đoạn của video: caption hiện trên màn hình + lời đọc.

    Được làm giàu dần: TTS bổ sung audio_path + duration_sec."""

    caption: str
    narration: str
    time_goal: float | None = None  # mục tiêu thời lượng section, nếu Claude khai báo
    voiceover: str = ""       # alias schema mới; loader đồng bộ với narration
    visual_intent: str = ""    # mô tả hình ảnh/hành động cần thấy
    pexels_query: str = ""     # query Pexels chuẩn; broll giữ tương thích cũ
    code: str = ""           # lệnh/đoạn code hiện trong terminal card (tùy chọn)
    danger: bool = False      # True -> tô đỏ cảnh báo
    broll: str = ""           # từ khoá (tiếng Anh) tìm B-roll stock cho render-ai
    video_type: str = "image_motion"  # image_motion | ai_video | static_terminal
    emphasis: tuple[str, ...] = ()  # từ khoá pop lớn (visual aid), vd "Quy tắc 2 phút"
    voice_style: str = ""  # override profile diễn xuất cho riêng segment
    voice_tempo: float | None = None  # 0.88–1.12; giữ pitch khi post-process
    voice_pitch: float | None = None  # semitone, giới hạn an toàn ±2
    voice_gain: float | None = None  # dB, giới hạn an toàn ±3
    voice_pause_before: float | None = None  # giây
    voice_pause_after: float | None = None  # giây
    hook: bool = False        # cảnh hành động mạnh -> dồn vào cold-open hook đầu video
    transition: bool = False  # chèn whoosh + xfade NGAY TRƯỚC đoạn này (vấn đề->giải pháp)
    hook_text: str = ""       # schema mới: lý do section này là hook
    transition_text: str = "" # schema mới: câu/cảnh chuyển ý
    payoff: str = ""          # schema mới: giá trị/chốt ý của section
    purpose: str = ""         # situation | core_answer | evidence | application | payoff
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
class ThumbnailBrief:
    """Editorial contract for a thumbnail before the render stage.

    The brief is deliberately short and structured so the first script response
    can give the renderer a usable packaging direction without a second LLM
    repair turn.  It remains optional for scripts created before this contract.
    """

    visual_contradiction: str
    subject: str
    emotion: str
    headline: str

    def __post_init__(self) -> None:
        fields = (
            self.visual_contradiction,
            self.subject,
            self.emotion,
            self.headline,
        )
        if not all(isinstance(value, str) and value.strip() for value in fields):
            raise ValueError(
                "ThumbnailBrief cần visual_contradiction, subject, emotion và headline."
            )
        if len(self.headline.split()) > 4:
            raise ValueError("ThumbnailBrief.headline không được quá 4 từ.")


@dataclass(frozen=True)
class VideoIdea:
    """Đầu ra khâu ideation (Claude viết, nạp từ scripts/*.json)."""

    topic: str
    title: str
    description: str
    tags: tuple[str, ...] = ()
    video_type: str = "short"  # short | long
    voice_profile: str = ""  # knowledge | inspiring; rỗng = tự suy luận legacy
    target_minutes: float | None = None
    voice: str = "vi-VN-NamMinhNeural"
    compliance: ComplianceCheck | None = None
    strategy: ContentStrategy | None = None
    ruleset_id: str = ""


@dataclass(frozen=True)
class Script(VideoIdea):
    """VideoIdea + kịch bản đã chia đoạn."""

    body: str = ""
    segments: tuple[Segment, ...] = ()
    thumbnail_brief: ThumbnailBrief | None = None


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
