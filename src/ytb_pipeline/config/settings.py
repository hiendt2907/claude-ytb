"""Cấu hình tập trung, nạp từ env vars. Validate tại startup (fail fast)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # TTS
    tts_provider: str = "f5"  # f5 | vieneu | vixtts | edge | elevenlabs
    elevenlabs_api_key: str = ""
    vieneu_tts_cmd: str = ""
    vixtts_cmd: str = ""

    # Telegram (cổng duyệt kịch bản)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_approval: bool = True  # bật cổng duyệt ở khâu ideation

    # Render
    render_provider: str = "ai"  # slide | ai
    image_provider: str = "pillow"  # dùng cho thumbnail/overlay; không dùng làm video chính
    broll_strategy: str = "pexels"  # pexels = footage thật; local_image_motion đã bỏ khỏi production
    comfyui_url: str = "http://127.0.0.1:8188"  # ComfyUI local API (Flux)
    flux_checkpoint_name: str = "flux1-dev-fp8.safetensors"
    orientation: str = "portrait"   # portrait (1080x1920 Short) | landscape (1920x1080 clip)
    pexels_api_key: str = ""         # key free: https://www.pexels.com/api/
    # Caption chạy theo lời nói (lower-third). Mặc định TẮT — mặt video sạch, không
    # chữ chạy liên tục. Tiêu đề cold-open, terminal card và emphasis chip vẫn giữ.
    show_captions: bool = False

    # Nhịp ngắt nghỉ giọng đọc (ms): chèn khoảng lặng để không đọc một lèo.
    pause_comma_ms: int = 250       # nghỉ sau dấu phẩy / ; :
    pause_sentence_ms: int = 400    # nghỉ sau . ! ? …
    pause_segment_ms: int = 500     # nghỉ giữa các segment

    # Hiệu năng (tốc độ sản xuất) — chỉnh xuống 1 nếu gặp rate-limit/quá tải.
    edge_tts_workers: int = 4        # số segment edge-tts tổng hợp SONG SONG
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
    # Lên lịch tự công khai: RFC3339 (vd 2026-06-17T06:00:00+0700). Khi đặt, video
    # giữ private tới mốc này rồi YouTube tự chuyển PUBLIC. Rỗng = không lên lịch.
    youtube_publish_at: str = ""
    # Toàn bộ video kênh này là AI-generated (voice TTS + visual AI render) -> luôn khai
    # báo "nội dung thay đổi/tổng hợp bởi AI" (containsSyntheticMedia) khi upload, theo
    # yêu cầu minh bạch của YouTube từ 2024. Để false chỉ khi có video KHÔNG dùng AI.
    youtube_contains_synthetic_media: bool = True

    # Platform
    default_platform: str = "youtube_short"  # youtube_short | youtube_long | tiktok | instagram_reel | facebook_reel
    target_platforms: str = "youtube_short"
    manual_publish_dir: Path = Field(default=Path("assets/manual_publish_queue"))
    tiktok_access_token: str = ""
    instagram_access_token: str = ""
    facebook_access_token: str = ""

    # Paths
    assets_dir: Path = Field(default=Path("assets"))
    output_dir: Path = Field(default=Path("assets/output"))

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
    # Cờ thêm cho `claude -p`. Mặc định BYPASS quyền để daemon chạy tự trị không
    # bị chặn (user đã chủ động chọn). Để rỗng nếu muốn tự cấp quyền qua allowedTools.
    listener_claude_args: str = "--dangerously-skip-permissions"
    # Tiền tố skill cho lệnh /auto (pipeline youtube). Lệnh tự do KHÔNG bọc skill này.
    listener_skill: str = "/youtube-auto"
    # Cho phép lệnh /sh chạy shell tùy ý trên máy (mạnh + nguy hiểm). Bật có chủ đích.
    listener_allow_shell: bool = True

    # LLM
    llm_provider: str = "ollama"          # ollama | claude
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_coder_model: str = "qwen2.5-coder:7b"

    # Video generation
    video_provider: str = "pexels"        # pexels là đường render footage thật mặc định
    wan_model_path: str = ""              # path to Wan2.2 model weights
    wan_cli: str = "wan2.2"
    render_validation_max_drift_sec: float = 1.0

    # Local stack shortcut: set OMNI_LOCAL=true for local LLM/TTS only.
    # Render vẫn dùng Pexels footage thật; không quay lại Pillow image-motion.
    local_mode: bool = False
    allow_cloud_providers: bool = False

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        """Make local-first the default even when legacy .env still names cloud providers.

        Legacy LLM/TTS cloud providers still need ALLOW_CLOUD_PROVIDERS=true.
        Pexels is the production video-footage path and is not downgraded to
        Pillow image-motion anymore.
        """
        if self.allow_cloud_providers:
            return
        if self.llm_provider == "claude":
            self.llm_provider = "ollama"
        if self.tts_provider in {"edge", "elevenlabs"}:
            self.tts_provider = "f5"


settings = Settings()
