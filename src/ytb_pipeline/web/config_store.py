"""Đọc/ghi cấu hình động cho dashboard.

Nguồn sự thật khi sửa qua web là ``data/config.json`` — được nạp như một
SettingsSource ưu tiên hơn ``.env`` (xem config/settings.py). Module này:

  - mô tả các field cho phép sửa (FIELDS) kèm nhóm + kiểu + cờ nhạy cảm;
  - đọc giá trị hiệu lực hiện tại từ singleton ``settings``;
  - ghi thay đổi vào config.json (atomic) rồi RELOAD singleton trong tiến trình
    để mọi tham chiếu ``from ...config.settings import settings`` thấy ngay.

KHÔNG mutate bản cũ ngoài việc đồng bộ nội dung singleton (singleton là điểm
nối duy nhất, phải cập nhật tại chỗ để code đã import thấy giá trị mới).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings as settings_module
from ..config.settings import DYNAMIC_CONFIG_FILE, Settings


@dataclass(frozen=True)
class Field:
    """Mô tả 1 field cấu hình hiển thị trên dashboard."""

    name: str
    label: str
    group: str
    kind: str = "str"           # str | int | bool | choice | secret
    choices: tuple[str, ...] = ()
    help: str = ""

    @property
    def sensitive(self) -> bool:
        return self.kind == "secret"


# Danh mục field cho phép sửa trên dashboard, theo nhóm. Secrets hiển thị dạng
# che; để trống khi lưu = GIỮ giá trị cũ (không xoá secret bằng form rỗng).
FIELDS: tuple[Field, ...] = (
    # Hành vi
    Field("dry_run", "DRY_RUN (render local, không upload)", "Hành vi", "bool"),
    # TTS
    Field("tts_provider", "TTS provider", "Voiceover", "choice",
          ("edge", "elevenlabs", "f5")),
    Field("elevenlabs_api_key", "ElevenLabs API key", "Voiceover", "secret"),
    Field("pause_comma_ms", "Nghỉ sau dấu phẩy (ms)", "Voiceover", "int"),
    Field("pause_sentence_ms", "Nghỉ cuối câu (ms)", "Voiceover", "int"),
    Field("pause_segment_ms", "Nghỉ giữa segment (ms)", "Voiceover", "int"),
    # Render
    Field("render_provider", "Render provider", "Render", "choice", ("slide", "ai")),
    Field("orientation", "Hướng video", "Render", "choice", ("portrait", "landscape")),
    Field("pexels_api_key", "Pexels API key", "Render", "secret"),
    Field("show_captions", "Hiện caption chạy", "Render", "bool"),
    # YouTube
    Field("youtube_api_key", "YouTube API key (research)", "YouTube", "secret"),
    Field("youtube_privacy", "Quyền riêng tư", "YouTube", "choice",
          ("private", "unlisted", "public")),
    Field("youtube_category_id", "Category ID", "YouTube"),
    Field("youtube_publish_at", "Lên lịch công khai (RFC3339)", "YouTube"),
    Field("drive_backup", "Backup lên Drive sau upload", "YouTube", "bool"),
    Field("drive_folder", "Thư mục Drive", "YouTube"),
    # Telegram
    Field("telegram_bot_token", "Telegram bot token", "Telegram", "secret"),
    Field("telegram_chat_id", "Telegram chat ID", "Telegram"),
    Field("telegram_approval", "Bật cổng duyệt Telegram", "Telegram", "bool"),
    # Listener
    Field("listener_allow_shell", "Cho phép /sh (nguy hiểm)", "Listener", "bool"),
    Field("listener_skill", "Skill cho /auto", "Listener"),
    # Dashboard
    Field("dashboard_password", "Mật khẩu dashboard", "Dashboard", "secret"),
    Field("dashboard_host", "Host", "Dashboard"),
    Field("dashboard_port", "Port", "Dashboard", "int"),
)

_FIELD_BY_NAME = {f.name: f for f in FIELDS}
_SENSITIVE = {f.name for f in FIELDS if f.sensitive}


def _config_path() -> Path:
    return DYNAMIC_CONFIG_FILE


def read_overrides() -> dict[str, Any]:
    """Đọc raw overrides đã lưu trong data/config.json (rỗng nếu chưa có)."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def effective_value(name: str) -> Any:
    """Giá trị đang có hiệu lực (từ singleton settings)."""
    return getattr(settings_module.settings, name)


def grouped_fields() -> dict[str, list[Field]]:
    """FIELDS gom theo nhóm, giữ thứ tự khai báo."""
    groups: dict[str, list[Field]] = {}
    for f in FIELDS:
        groups.setdefault(f.group, []).append(f)
    return groups


def _coerce(field: Field, raw: str) -> Any:
    """Ép giá trị form (string) về kiểu đúng cho field."""
    if field.kind == "bool":
        return raw in ("1", "true", "on", "yes")
    if field.kind == "int":
        return int(raw)
    return raw


def save(form: dict[str, Any]) -> list[str]:
    """Ghi thay đổi từ form vào config.json (atomic) + reload singleton.

    - bool không có trong form = False (checkbox bỏ tick).
    - secret để trống = giữ giá trị override cũ (không ghi đè bằng rỗng).
    Trả về danh sách tên field đã thay đổi.
    """
    current = read_overrides()
    new = dict(current)  # bản sao — không mutate dict cũ
    changed: list[str] = []

    for field in FIELDS:
        if field.kind == "bool":
            raw = "1" if field.name in form else "0"
        elif field.name in form:
            raw = str(form[field.name]).strip()
        else:
            continue  # field không gửi lên → bỏ qua

        if field.sensitive and raw == "":
            continue  # secret rỗng = giữ nguyên

        value = _coerce(field, raw)
        if new.get(field.name) != value:
            new[field.name] = value
            changed.append(field.name)

    if changed:
        _write_atomic(new)
        reload_settings()
    return changed


def _write_atomic(data: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def reload_settings() -> None:
    """Tạo Settings mới (đọc lại config.json + .env) rồi đồng bộ vào singleton.

    Cập nhật tại chỗ nội dung singleton để mọi module đã ``import settings``
    thấy giá trị mới mà không cần restart.
    """
    fresh = Settings()
    settings_module.settings.__dict__.update(fresh.__dict__)


def public_value(field: Field) -> str:
    """Giá trị hiển thị trên form: secret che thành placeholder nếu đã đặt."""
    value = effective_value(field.name)
    if field.sensitive:
        return "••••••••" if value else ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)
