"""Publish YouTube — upload trực tiếp thay vì chỉ xuất file, hỗ trợ `publish_at`
(RFC3339) để lên lịch tự công khai.

Port rút gọn từ claude-ytb/publish/uploader.py: bỏ SEO/hashtag/discovery-tag
đặc thù kênh cũ (không áp dụng cho use case này), giữ nguyên cơ chế
`privacyStatus=private` + `publishAt` để YouTube tự công khai đúng giờ.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import load_content_settings


@dataclass(frozen=True)
class PublishResult:
    youtube_id: str
    url: str


def publish_video(
    video_path: Path,
    title: str,
    description: str,
    tags: tuple[str, ...] = (),
    *,
    thumbnail_path: Path | None = None,
    publish_at: str | None = None,
) -> PublishResult:
    """Upload `video_path` lên YouTube qua Data API (OAuth).

    Nếu `publish_at` được set (vd "2026-07-10T09:00:00Z"), video ở chế độ
    private + tự công khai đúng giờ đó — không cần cron riêng.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file video: {video_path}")

    settings = load_content_settings()

    # import trong hàm để test không cần thư viện Google khi mock get_youtube_client.
    from googleapiclient.http import MediaFileUpload

    from .youtube_auth import get_youtube_client

    youtube = get_youtube_client()

    body: dict = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": list(tags)[:30],
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": settings.youtube_privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": settings.youtube_contains_synthetic_media,
        },
    }
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(str(video_path), resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    youtube_id = response["id"]

    if thumbnail_path is not None and thumbnail_path.exists():
        _set_thumbnail(youtube, youtube_id, thumbnail_path)

    return PublishResult(youtube_id=youtube_id, url=f"https://youtu.be/{youtube_id}")


def _set_thumbnail(youtube, youtube_id: str, thumbnail_path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    try:
        youtube.thumbnails().set(
            videoId=youtube_id, media_body=MediaFileUpload(str(thumbnail_path))
        ).execute()
    except Exception:  # noqa: BLE001 — thumbnail lỗi (kênh chưa verify) không chặn publish
        pass
