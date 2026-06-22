"""Đẩy video đã upload YouTube lên Google Drive.

Tải file vào 1 thư mục Drive (tạo nếu chưa có), trả về link xem. Dùng scope
`drive.file` (chỉ đụng file do app tạo) — tối thiểu quyền. Lỗi Drive KHÔNG làm
hỏng kết quả upload YouTube: gọi nơi an toàn, bắt lỗi mềm ở caller.

`move=True`: sau khi tải lên Drive THÀNH CÔNG, xoá file local (chỉ giữ trên máy
tới lúc upload). Chỉ xoá khi Drive đã trả id (đảm bảo không mất video).
"""

from __future__ import annotations

from pathlib import Path

from ..config.settings import settings

FOLDER_MIME = "application/vnd.google-apps.folder"


def backup_to_drive(video_path: Path, *, move: bool = False) -> str | None:
    """Tải `video_path` lên thư mục Drive cấu hình. Trả về webViewLink (hoặc None).

    move=True: xoá file local sau khi Drive xác nhận đã nhận file (có id)."""
    if video_path is None or not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file để backup: {video_path}")

    from googleapiclient.http import MediaFileUpload

    from .youtube_auth import get_drive_client

    drive = get_drive_client()
    folder_id = _ensure_folder(drive, settings.drive_folder)

    meta = {"name": video_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    f = drive.files().create(
        body=meta, media_body=media, fields="id,webViewLink"
    ).execute()
    link = f.get("webViewLink")
    print(f"  ✓ Đã đưa lên Drive ({settings.drive_folder}): {link}")

    # Chỉ xoá local khi Drive đã xác nhận có file (an toàn không mất video)
    if move and f.get("id"):
        video_path.unlink(missing_ok=True)
        print(f"  ✓ Đã xoá bản local: {video_path}")

    return link


def _ensure_folder(drive, name: str) -> str:
    """Tìm thư mục Drive theo tên (do app tạo); tạo mới nếu chưa có. Trả về id."""
    q = (
        f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    res = drive.files().list(q=q, spaces="drive", fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    folder = drive.files().create(
        body={"name": name, "mimeType": FOLDER_MIME}, fields="id"
    ).execute()
    return folder["id"]
