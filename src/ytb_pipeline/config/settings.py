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
    tts_provider: str = "edge"  # edge | elevenlabs | f5
    elevenlabs_api_key: str = ""

    # Telegram (cổng duyệt kịch bản)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_approval: bool = True  # bật cổng duyệt ở khâu ideation

    # Render
    render_provider: str = "slide"  # slide | ai (B-roll stock từ Pexels)
    orientation: str = "portrait"   # portrait (1080x1920 Short) | landscape (1920x1080 clip)
    pexels_api_key: str = ""         # key free: https://www.pexels.com/api/
    # Caption chạy theo lời nói (lower-third). Mặc định TẮT — mặt video sạch, không
    # chữ chạy liên tục. Tiêu đề cold-open, terminal card và emphasis chip vẫn giữ.
    show_captions: bool = False

    # Nhịp ngắt nghỉ giọng đọc (ms): chèn khoảng lặng để không đọc một lèo.
    pause_comma_ms: int = 250       # nghỉ sau dấu phẩy / ; :
    pause_sentence_ms: int = 400    # nghỉ sau . ! ? …
    pause_segment_ms: int = 500     # nghỉ giữa các segment

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

    # Paths
    assets_dir: Path = Field(default=Path("assets"))
    output_dir: Path = Field(default=Path("assets/output"))

    # Drive — sau khi upload YouTube THẬT, MOVE video lên Drive rồi xoá file local
    # (chỉ giữ trên máy tới khi upload xong). Cần token có scope drive.file.
    drive_backup: bool = True
    drive_folder: str = "Claude-YTB"

    # Behaviour
    dry_run: bool = True

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


settings = Settings()
