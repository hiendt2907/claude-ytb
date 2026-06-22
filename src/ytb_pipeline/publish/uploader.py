"""Khâu 4 — Upload YouTube + SEO + analytics.

Tôn trọng settings.dry_run: khi true, KHÔNG upload thật, chỉ log dự định.
Khi false: dùng OAuth (youtube_auth) để videos.insert + thumbnails.set.

Phân loại Short vs clip:
  - video DỌC và ≤ 180s (3 phút) -> Short: gắn #Shorts vào mô tả để YouTube xếp đúng.
  - còn lại (vd > 3p, hoặc ngang) -> clip thường, không gắn #Shorts.
YouTube không có API riêng cho Short — xếp loại dựa trên thời lượng + tỉ lệ khung
hình + hashtag #Shorts. Từ 10/2024 YouTube cho phép Short dài tới 3 phút (trước là 60s).
"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from ..config.settings import settings
from ..pkg.models import PublishResult, RenderedVideo

# YouTube cho phép Short tới 3 phút (180s) từ 10/2024; short của pipeline nhắm 1–2 phút.
SHORT_MAX_SEC = 180


def publish(video: RenderedVideo) -> PublishResult:
    """Upload qua YouTube Data API (OAuth), set title/tags/thumbnail tối ưu SEO."""
    if settings.dry_run:
        return _dry_run(video)

    if video.video_path is None or not video.video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file video: {video.video_path}")

    # import trong hàm để DRY_RUN không cần thư viện Google
    from googleapiclient.http import MediaFileUpload

    from .youtube_auth import get_youtube_client

    youtube = get_youtube_client()

    is_short = _is_short(video)
    description = _with_shorts_tag(video.description) if is_short else video.description
    print(f"  Loại: {'YouTube Short (dọc, ≤3p)' if is_short else 'Clip thường'}")

    body = {
        "snippet": {
            "title": video.title[:100],
            "description": description,
            "tags": list(video.tags),
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": settings.youtube_privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # Lên lịch tự công khai: YouTube yêu cầu privacyStatus=private + publishAt (RFC3339).
    if settings.youtube_publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = settings.youtube_publish_at
        print(f"  Lên lịch công khai lúc: {settings.youtube_publish_at}")

    media = MediaFileUpload(str(video.video_path), resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload {int(status.progress() * 100)}%")

    youtube_id = response["id"]
    print(f"  ✓ Đã upload: https://youtu.be/{youtube_id}")

    _set_thumbnail(youtube, youtube_id, video)

    return replace(
        PublishResult(**vars(video)),
        youtube_id=youtube_id,
        url=f"https://youtu.be/{youtube_id}",
        uploaded=True,
    )


def _is_short(video: RenderedVideo) -> bool:
    """True nếu video DỌC và ngắn (≤180s = 3 phút) -> đăng dạng Short."""
    if video.duration_sec and video.duration_sec >= SHORT_MAX_SEC:
        return False
    w, h = _dimensions(video.video_path)
    if not w or not h:
        # không đo được kích thước -> dựa vào thời lượng (mặc định render Short là dọc)
        return bool(video.duration_sec and video.duration_sec < SHORT_MAX_SEC)
    return h > w and (video.duration_sec or 0) < SHORT_MAX_SEC


def _dimensions(path: Path | None) -> tuple[int, int]:
    """Đọc (width, height) bằng ffprobe; (0,0) nếu lỗi."""
    if not path or not Path(path).exists():
        return (0, 0)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, check=True, text=True,
        ).stdout
        s = json.loads(out)["streams"][0]
        return (int(s["width"]), int(s["height"]))
    except Exception:  # noqa: BLE001
        return (0, 0)


def _with_shorts_tag(description: str) -> str:
    """Thêm #Shorts vào cuối mô tả nếu chưa có."""
    if "#shorts" in description.lower():
        return description
    return f"{description.rstrip()}\n\n#Shorts"


def _set_thumbnail(youtube, youtube_id: str, video: RenderedVideo) -> None:
    """Đặt thumbnail tùy chỉnh. Lỗi (kênh chưa verify) -> cảnh báo, không fail."""
    if not video.thumbnail_path or not video.thumbnail_path.exists():
        return
    from googleapiclient.http import MediaFileUpload

    try:
        youtube.thumbnails().set(
            videoId=youtube_id,
            media_body=MediaFileUpload(str(video.thumbnail_path)),
        ).execute()
        print("  ✓ Đã đặt thumbnail")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ Không đặt được thumbnail (kênh cần verify?): {exc}")


def _dry_run(video: RenderedVideo) -> PublishResult:
    print("── DRY RUN — không upload thật ──")
    print(f"  Loại  : {'YouTube Short (dọc, ≤3p)' if _is_short(video) else 'Clip thường'}")
    print(f"  Title : {video.title}")
    print(f"  Tags  : {', '.join(video.tags)}")
    print(f"  Video : {video.video_path}")
    print(f"  Thumb : {video.thumbnail_path}")
    print(f"  Privacy: {settings.youtube_privacy}  |  Thời lượng: {video.duration_sec:.1f}s")
    return replace(PublishResult(**vars(video)), uploaded=False, url=None)
