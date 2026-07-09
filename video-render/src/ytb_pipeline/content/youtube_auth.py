"""OAuth 2.0 cho YouTube Data API — lưu/refresh token trong `secrets/`.

Port rút gọn từ claude-ytb/publish/youtube_auth.py: bỏ Drive scope + Telegram
notify (không cần trong video-render), giữ nguyên luồng refresh/reauth và
credentials/token dùng chung với kênh YouTube của claude-ytb (đã chốt với
user — xem CLAUDE.md mục Publish).
"""

from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import load_content_settings

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


class ReauthRequiredError(RuntimeError):
    """Token hết hạn/bị revoke — cần đăng nhập lại tương tác (mở browser)."""


def get_youtube_client(*, allow_interactive: bool = False):
    """Trả về resource client đã xác thực để gọi YouTube Data API."""
    settings = load_content_settings()
    creds = _load_or_authorize(
        settings.youtube_token_path,
        settings.youtube_client_secret_path,
        YOUTUBE_SCOPES,
        allow_interactive=allow_interactive,
    )
    return build("youtube", "v3", credentials=creds)


def _load_or_authorize(
    token_file: str, secrets_file: str, scopes: list[str], *, allow_interactive: bool
) -> Credentials:
    token_path = Path(token_file)
    secrets_path = Path(secrets_file)

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.valid:
        return creds

    needs_interactive = not (creds and creds.expired and creds.refresh_token)
    if not needs_interactive:
        try:
            creds.refresh(Request())
        except RefreshError:
            needs_interactive = True

    if needs_interactive:
        if not allow_interactive:
            raise ReauthRequiredError(
                f"Token {token_path} cần đăng nhập lại tương tác — gọi "
                "get_youtube_client(allow_interactive=True) từ terminal có màn hình."
            )
        if not secrets_path.exists():
            raise FileNotFoundError(
                f"Thiếu OAuth client: {secrets_path}. Tải Desktop OAuth JSON từ "
                "Google Cloud Console và đặt vào đó."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds
