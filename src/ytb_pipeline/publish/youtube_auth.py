"""OAuth 2.0 cho YouTube Data API — lưu/refresh token trong secrets/.

Lần đầu mở browser để bạn đăng nhập; các lần sau dùng lại token đã lưu.
"""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config.settings import settings

# YouTube và Drive dùng TOKEN RIÊNG: kênh upload là brand account
# ("1 Cốc Café 6h") — brand account KHÔNG có Drive; Drive thuộc tài khoản cá nhân.
# Tách scope + token file để mỗi dịch vụ xác thực bằng đúng tài khoản của nó.
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",  # chỉ đụng file do app tạo
]


def get_youtube_client():
    """Trả về resource client đã xác thực để gọi YouTube Data API (brand channel)."""
    creds = _load_or_authorize(settings.youtube_token_file, YOUTUBE_SCOPES)
    return build("youtube", "v3", credentials=creds)


def get_drive_client():
    """Trả về resource client đã xác thực để gọi Drive API (tài khoản cá nhân)."""
    creds = _load_or_authorize(settings.drive_token_file, DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def _load_or_authorize(token_file: str, scopes: list[str]) -> Credentials:
    token_path = Path(token_file)
    secrets_path = Path(settings.youtube_client_secrets)

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
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
