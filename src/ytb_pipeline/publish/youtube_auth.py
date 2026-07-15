"""OAuth 2.0 cho YouTube Data API — lưu/refresh token trong secrets/.

Lần đầu mở browser để bạn đăng nhập; các lần sau dùng lại token đã lưu.
"""

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config.settings import settings
from ..notify import telegram


class ReauthRequiredError(RuntimeError):
    """Token hết hạn/bị revoke và cần đăng nhập lại qua browser — không thể tự
    phục hồi trong tiến trình chạy nền (cron/launchd, không có màn hình)."""

# YouTube và Drive dùng TOKEN RIÊNG: kênh upload là brand account
# ("1 Cốc Café 6h") — brand account KHÔNG có Drive; Drive thuộc tài khoản cá nhân.
# Tách scope + token file để mỗi dịch vụ xác thực bằng đúng tài khoản của nó.
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",  # chỉ đụng file do app tạo
]


def get_youtube_client(*, allow_interactive: bool = False):
    """Trả về resource client đã xác thực để gọi YouTube Data API (brand channel)."""
    creds = _load_or_authorize(
        settings.youtube_token_file, YOUTUBE_SCOPES, allow_interactive=allow_interactive
    )
    return build("youtube", "v3", credentials=creds)


def get_youtube_analytics_client(*, allow_interactive: bool = False):
    """Authenticated Analytics API client, using the same brand-channel token."""
    creds = _load_or_authorize(
        settings.youtube_token_file, YOUTUBE_SCOPES, allow_interactive=allow_interactive
    )
    return build("youtubeAnalytics", "v2", credentials=creds)


def get_drive_client(*, allow_interactive: bool = False):
    """Trả về resource client đã xác thực để gọi Drive API (tài khoản cá nhân)."""
    creds = _load_or_authorize(
        settings.drive_token_file, DRIVE_SCOPES, allow_interactive=allow_interactive
    )
    return build("drive", "v3", credentials=creds)


def _load_or_authorize(
    token_file: str, scopes: list[str], *, allow_interactive: bool = False
) -> Credentials:
    token_path = Path(token_file)
    secrets_path = Path(settings.youtube_client_secrets)

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.valid:
        return creds

    needs_interactive_auth = not (creds and creds.expired and creds.refresh_token)
    if not needs_interactive_auth:
        try:
            creds.refresh(Request())
        except RefreshError:
            # Refresh token bị Google revoke/hết hạn -- không thể tự phục hồi,
            # cần đăng nhập lại tương tác (mở browser).
            needs_interactive_auth = True

    if needs_interactive_auth:
        if not allow_interactive:
            # Chạy nền (cron/launchd) không có màn hình để mở browser -- báo Telegram
            # rồi dừng job này (không retry vô hạn), KHÔNG cố run_local_server() vì
            # sẽ treo. User tự chạy `ytb auth` khi ngồi máy để đăng nhập lại.
            try:
                telegram.send_message(
                    f"⚠️ Token OAuth ({token_path.name}) hết hạn/bị revoke — cần đăng "
                    "nhập lại. Chạy `ytb auth` trên máy rồi `ytb batch retry <slug>` để "
                    "tiếp tục video đang dở."
                )
            except Exception:  # noqa: BLE001 — báo Telegram là best-effort, không che lỗi OAuth thật
                pass
            raise ReauthRequiredError(
                f"Token {token_path} cần đăng nhập lại tương tác — chạy `ytb auth`."
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
