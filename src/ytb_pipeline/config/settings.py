"""Cấu hình tập trung, nạp từ env vars. Validate tại startup (fail fast)."""

import re
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # TTS — xKiro (cloud) là default từ amendment 2026-08-24 (PROJECT_VISION.md
    # Amendment Log): giảm tải TTS khỏi MacBook, Mac chỉ chạy workflow/pipeline.
    tts_provider: str = "xkiro"  # xkiro | f5 | vieneu | vixtts | edge | elevenlabs
    # xKiro exposes an OpenAI-compatible POST /v1/audio/speech endpoint.
    # Keep the API key in .env only; it is never written to project artifacts.
    xkiro_api_key: str = ""
    xkiro_tts_url: str = "https://api.xkiro.com/v1/audio/speech"
    xkiro_model: str = "xkiro-voice"
    xkiro_voice: str = "confident-male-vietnamese"
    xkiro_max_chars_per_piece: int = Field(default=48, ge=24, le=160)
    xkiro_timeout_sec: float = Field(default=120.0, gt=0)
    xkiro_max_retries: int = Field(default=3, ge=1, le=5)
    # xKiro cũng lộ /v1/chat/completions OpenAI-compatible (LLM), tách endpoint
    # riêng với TTS dù chung API key. Ideation chỉ dùng một model đã chọn rõ;
    # lỗi phải dừng để operator biết, không âm thầm đổi chất lượng/nội dung.
    xkiro_llm_url: str = "https://api.xkiro.com/v1/chat/completions"
    # xKiro gateway namespace; DeepSeek V4 Pro supports up to 65k output tokens.
    xkiro_llm_model: str = "deepseek/deepseek-v4-pro"
    # Phase 11 operator-smoke defaults. Production selection remains owned by
    # each content profile's `visual_generation.visual_judge` block; these
    # values do not enable `vlm_ranked` globally.
    visual_judge_provider: str = ""
    visual_judge_model: str = ""
    # Operator override for what the engine may accept on its own when the
    # Judge rejects every candidate. Empty keeps whatever the content profile
    # declares — including the default, which is to halt and wait for a person.
    # This exists because a project pins its profile SNAPSHOT, so a policy
    # added to a live profile cannot reach work already in flight.
    visual_auto_disposition: str = ""
    visual_auto_accept_minimum_score: float = 0.0
    # Comma-separated Judge hard-failure codes the override may waive.
    visual_auto_accept_waived_failures: str = ""
    # Optional operator override for Edge remote speech rate. Empty keeps the profile rate.
    edge_tts_rate_override: str = ""
    # Explicit local F5 backend. Production keeps Apple Silicon MPS; CPU is a
    # deliberate fallback for isolated diagnosis when MPS is not progressing.
    f5_device: Literal["mps", "cpu"] = Field(
        default="mps", validation_alias=AliasChoices("F5_DEVICE")
    )
    elevenlabs_api_key: str = ""
    vieneu_tts_cmd: str = ""
    vixtts_cmd: str = ""

    # Content profiles — mỗi chủ đề là một thư mục tự chứa prompt, contract,
    # voice cast, provider policy và asset. PlatformProfile là khái niệm riêng.
    content_profile_id: str = "one-cup-cafe-6h"
    content_profiles_dir: Path = Field(default=Path("profiles"))

    # Telegram (cổng duyệt kịch bản)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_approval: bool = True  # bật cổng duyệt ở khâu ideation

    # Render
    # ai (default, rollback 2026-08-24 — xem docs/TOOL_UPGRADE_PLAN.md): compose
    # B-roll THẬT từ asset catalog/cache local đã có sẵn trên máy
    # (assets/broll/ + asset_catalog.json). KHÔNG gọi Pexels online — tải mạng
    # chỉ xảy ra khi operator tự bật rõ `BROLL_ALLOW_DOWNLOADS=true` (mặc định
    # false). Renderer "motion" (Pillow+FFmpeg hình học) đã bị GỠ KHỎI CODEBASE
    # 2026-08-24 — đây là sai lầm kiến trúc của một phiên trước, không dùng lại
    # trừ khi có amendment mới trong PROJECT_VISION.md.
    render_provider: str = "ai"  # ai | slide | story (profile-owned illustrations)
    image_provider: str = "pillow"  # dùng cho thumbnail/overlay; không dùng làm video chính
    # "pexels" ở đây là TÊN NGUỒN GỐC asset (video licensed từ Pexels), KHÔNG
    # đồng nghĩa "gọi Pexels API online" — với BROLL_ALLOW_DOWNLOADS=false
    # (mặc định), toàn bộ B-roll lấy từ asset catalog/cache local đã tải sẵn.
    broll_strategy: str = "pexels"  # pexels = compose từ thư viện B-roll (local-first)
    broll_allow_downloads: bool = False  # local-first: chỉ tải Pexels khi opt-in rõ ràng
    comfyui_url: str = "http://127.0.0.1:8188"  # ComfyUI local API (Flux)
    flux_checkpoint_name: str = "flux1-dev-fp8.safetensors"
    # ComfyUI/SDXL + IPAdapter cho content profile character_story — capability
    # riêng biệt với Flux ở trên (Flux dùng txt2img thuần, không có identity
    # anchor). Xem providers/image/comfyui_story_provider.py.
    comfyui_sdxl_checkpoint: str = "sd_xl_base_1.0.safetensors"
    comfyui_clip_vision_model: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
    comfyui_ipadapter_model: str = "ip-adapter-plus_sdxl_vit-h.safetensors"
    # Which story-scene image provider `render/story.py::resolve_scene_image`
    # uses for character_story profiles. Config-selectable ALTERNATIVE, not a
    # fallback and not a new default: CLAUDE.md's local-first visual/render
    # policy is unchanged — "comfyui" (local) stays the default. "codex" shells
    # out to the Codex CLI's built-in cloud image_gen tool (opt-in, cloud).
    story_image_provider: str = "comfyui"  # comfyui | codex
    orientation: str = "portrait"   # portrait (1080x1920 Short) | landscape (1920x1080 clip)
    # Chỉ bắt buộc khi BROLL_ALLOW_DOWNLOADS=true (opt-in tải thêm B-roll mới).
    # Local-only mode (mặc định) không cần key này — key rỗng vẫn render được
    # miễn asset catalog/cache local có đủ cảnh phù hợp.
    pexels_api_key: str = ""         # key free: https://www.pexels.com/api/
    # Caption chạy theo lời nói (lower-third). Mặc định TẮT — mặt video sạch, không
    # chữ chạy liên tục. Tiêu đề cold-open, terminal card và emphasis chip vẫn giữ.
    show_captions: bool = False

    # Nhịp ngắt nghỉ giọng đọc (ms): chèn khoảng lặng để không đọc một lèo.
    pause_comma_ms: int = 250       # nghỉ sau dấu phẩy / ; :
    pause_sentence_ms: int = 400    # nghỉ sau . ! ? …
    pause_segment_ms: int = 500     # nghỉ giữa các segment

    # Hiệu năng (tốc độ sản xuất) — chỉnh xuống 1 nếu gặp rate-limit/quá tải.
    edge_tts_workers: int = 1        # tuần tự để tránh Edge TTS throttling; tăng có chủ đích
    broll_download_workers: int = 4  # số file B-roll Pexels tải SONG SONG
    # Preset x264: clip TRUNG GIAN (kenburns/bg/segment) bị re-encode lại ở bước
    # ghép cuối nên encode nhanh không đổi chất lượng output; file CUỐI giữ
    # "medium" (chất lượng như trước) — đổi sang "veryfast" nếu ưu tiên tốc độ.
    x264_preset_work: str = "veryfast"
    x264_preset_final: str = "medium"

    # YouTube
    # API key (chỉ đọc công khai: videos.list mostPopular cho research trending).
    # Upload vẫn dùng OAuth client_secrets dưới đây. Lấy key free ở Google Cloud Console.
    youtube_api_key: str = ""
    youtube_client_secrets: str = "secrets/client_secret.json"
    youtube_token_file: str = "secrets/youtube_token.json"
    drive_token_file: str = "secrets/drive_token.json"  # token Drive RIÊNG (tài khoản cá nhân)
    youtube_privacy: str = "private"   # private | unlisted | public
    youtube_category_id: str = "28"     # 28 = Science & Technology
    youtube_playlist_id: str = ""       # playlist đích; rỗng = không tự gán
    # Lên lịch tự công khai: RFC3339 (vd 2026-06-17T06:00:00+0700). Khi đặt, video
    # giữ private tới mốc này rồi YouTube tự chuyển PUBLIC. Rỗng = không lên lịch.
    youtube_publish_at: str = ""
    # Toàn bộ video kênh này là AI-generated (voice TTS + visual AI render) -> luôn khai
    # báo "nội dung thay đổi/tổng hợp bởi AI" (containsSyntheticMedia) khi upload, theo
    # yêu cầu minh bạch của YouTube từ 2024. Để false chỉ khi có video KHÔNG dùng AI.
    youtube_contains_synthetic_media: bool = True

    # Platform
    default_platform: str = "youtube_short"  # youtube_short | youtube_long | instagram_reel | facebook_reel
    target_platforms: str = "youtube_short"
    manual_publish_dir: Path = Field(default=Path("assets/manual_publish_queue"))
    instagram_access_token: str = ""
    facebook_access_token: str = ""

    # Paths
    assets_dir: Path = Field(default=Path("assets"))
    output_dir: Path = Field(default=Path("assets/output"))
    asset_catalog_path: Path = Field(default=Path("assets/asset_catalog.json"))
    # Durable provenance/catalog for character_story generated visuals (Phase
    # 3 Asset Registry) — separate file from asset_catalog.json above, which
    # only tracks licensed Pexels stock-footage reuse.
    asset_registry_path: Path = Field(default=Path("assets/asset_registry.json"))
    analytics_path: Path = Field(default=Path("assets/analytics.json"))
    # Checkpoint DAG: mỗi video 1 file <projects_dir>/<slug>/project.json —
    # resume skip node đã DONE (xem project/workflow.py).
    projects_dir: Path = Field(default=Path("assets/projects"))
    # Local-only post-TTS and post-render evidence.  ``report`` is the default.
    # A real audio-content defect (quality_status="failed") always blocks
    # render in every mode — pipeline.py::enforce_checkpointed_audio_quality —
    # since render is the most expensive step and render_quality would reject
    # bad audio at publish anyway. ``strict`` additionally blocks on a local QA
    # *tooling* crash (STT/cache failure); ``report`` only warns on that case.
    # Cửa sổ runtime của từng định dạng — chỉnh qua env, KHÔNG sửa code.
    # Định dạng thắng thay đổi theo dữ liệu kênh: đo 2026-08-25 trên 60 video,
    # nhóm <=40s đạt 755 view / 55.4% xem hết / 8 trong 16 sub toàn kênh, trong
    # khi dải 60-90s chỉ 217 view / 18.4%. Giữ mặc định cũ để batch đang chạy
    # không bị đổi hợp đồng giữa chừng; đổi bằng SHORT_VIEWER_MIN_SEC/... khi
    # muốn thử dải mới.
    short_viewer_min_sec: float = 60.0
    short_viewer_max_sec: float = 90.0
    short_min_sections: int = 6
    long_viewer_min_sec: float = 720.0
    long_viewer_max_sec: float = 900.0
    long_min_sections: int = 24
    quality_gate_mode: Literal["off", "report", "strict"] = "report"
    quality_reports_dir: Path = Field(default=Path("assets/quality_reports"))
    # Optional local Faster-Whisper model directory for post-TTS transcript QA.
    # Empty keeps STT disabled; the pipeline never accepts a remote model name/URL
    # and never downloads a model on behalf of the operator.
    quality_stt_model_path: Path | None = None
    # Leave all runtime knobs unset to preserve Faster-Whisper's legacy defaults.
    # Operators can opt into a reproducible local CPU int8 audit when needed.
    quality_stt_device: Literal["auto", "cpu", "cuda"] | None = None
    quality_stt_compute_type: Literal["default", "int8", "int8_float16", "float16", "float32"] | None = None
    quality_stt_cpu_threads: int | None = Field(default=None, ge=1)

    # Drive — sau khi upload YouTube THẬT, MOVE video lên Drive rồi xoá file local
    # (chỉ giữ trên máy tới khi upload xong). Cần token có scope drive.file.
    drive_backup: bool = True
    drive_folder: str = "Claude-YTB"

    # Behaviour
    dry_run: bool = True
    # Bắn Telegram tiến độ TỪNG VIDEO khi chạy `ytb batch run` (bắt đầu + kết
    # quả kèm URL) — best-effort, lỗi gửi không làm hỏng batch.
    telegram_progress: bool = True

    # Listener — daemon nghe lệnh Telegram. Mỗi lệnh chạy 1 phiên `claude -p` MỚI
    # (không --continue/--resume) nên context luôn sạch = ý "/clear mỗi lệnh".
    claude_bin: str = "claude"
    codex_bin: str = "codex"
    # Cờ thêm cho `claude -p`. Mặc định BYPASS quyền để daemon chạy tự trị không
    # bị chặn (user đã chủ động chọn). Để rỗng nếu muốn tự cấp quyền qua allowedTools.
    listener_claude_args: str = "--dangerously-skip-permissions"
    # Tiền tố skill cho lệnh /auto (pipeline youtube). Lệnh tự do KHÔNG bọc skill này.
    listener_skill: str = "/youtube-auto"
    # Cho phép lệnh /sh chạy shell tùy ý trên máy (mạnh + nguy hiểm). Bật có chủ đích.
    listener_allow_shell: bool = True

    # LLM — ideation chỉ dùng xKiro/DeepSeek V4 Pro (amendment 2026-08-26).
    # MacBook chỉ chạy workflow/pipeline, không còn chạy local LLM inference.
    llm_provider: str = "xkiro"
    # Explicit opt-in only: shortens the Long contract for local E2E tests.
    # Production remains 12–15 minutes unless this flag is set.
    e2e_test: bool = Field(
        default=False,
        validation_alias=AliasChoices("E2E_TEST", "YTB_E2E_TEST"),
    )
    # Kept for compatibility with non-ideation adapters. Ideation does not
    # consult this flag: it must never substitute Codex/Claude for xKiro.
    llm_fallback_enabled: bool = False

    # Video generation
    video_provider: str = "pexels"        # pexels là đường render footage thật mặc định
    wan_model_path: str = ""              # path to Wan2.2 model weights
    wan_cli: str = "wan2.2"
    render_validation_max_drift_sec: float = 1.0

    # Default true từ amendment 2026-08-24: TTS/LLM mặc định đã là cloud
    # (xKiro) nên cờ "cho phép cloud" phải mở theo, nếu không
    # `model_post_init` bên dưới sẽ tự ép `tts_provider` về lại "f5" trên máy
    # mới/.env trống. Set false tường minh trong .env nếu muốn ép về F5 local.
    allow_cloud_providers: bool = True

    @field_validator("quality_stt_model_path", mode="before")
    @classmethod
    def _blank_stt_model_path_is_disabled(cls, value: object) -> object:
        """Keep an empty env var opt-in rather than resolving it to ``Path('.')``."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("edge_tts_rate_override")
    @classmethod
    def _edge_tts_rate_override_is_valid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not re.fullmatch(r"[+-](?:[0-9]|[1-9][0-9]|100)%", value):
            raise ValueError("EDGE_TTS_RATE_OVERRIDE must be between -100% and +100%.")
        return value

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        """Make local-first the default even when legacy .env still names cloud providers.

        Legacy cloud TTS providers still need ALLOW_CLOUD_PROVIDERS=true.
        Pexels is the production video-footage path and is not downgraded to
        Pillow image-motion anymore.
        """
        if self.quality_stt_device == "cpu" and self.quality_stt_compute_type in {"float16", "int8_float16"}:
            raise ValueError("quality_stt_compute_type is not supported with quality_stt_device=cpu")
        if bool(self.visual_judge_provider.strip()) != bool(self.visual_judge_model.strip()):
            raise ValueError(
                "VISUAL_JUDGE_PROVIDER và VISUAL_JUDGE_MODEL phải được cấu hình cùng nhau."
            )
        if self.allow_cloud_providers:
            return
        if self.tts_provider in {"edge", "elevenlabs", "xkiro"}:
            self.tts_provider = "f5"


class SettingsError(RuntimeError):
    """A configuration problem, stated without the configuration's secrets."""


def _redacted_reason(exc: ValidationError) -> str:
    """Render a validation failure from `loc` + `msg` only.

    Pydantic attaches the *input* to every error it raises. For a check that
    runs in `model_post_init` that input is the entire settings mapping, so the
    default rendering prints credentials — `xkiro_api_key`, `telegram_bot_token`
    and `dashboard_password` among them — into stderr and any log that captures
    the exception. Nothing here reads `error["input"]`, and the caller raises
    outside the `except` block so the original never survives as `__context__`.
    """
    reasons = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "")).strip()
        reasons.append(f"{field}: {message}" if field else message)
    return "; ".join(reasons) or "cấu hình không hợp lệ."


def build_settings() -> Settings:
    """Load `Settings` from the environment, failing without echoing secrets."""
    reason: str | None = None
    try:
        return Settings()
    except ValidationError as exc:
        reason = _redacted_reason(exc)
    # Raised out here on purpose: inside the handler Python would record the
    # original ValidationError as `__context__`, putting the secret-bearing
    # mapping back within reach of anything that walks the exception chain.
    raise SettingsError(f"Cấu hình không hợp lệ: {reason}")


settings = build_settings()
