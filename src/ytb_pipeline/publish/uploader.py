"""Khâu 4 — Upload YouTube + SEO + analytics.

Tôn trọng settings.dry_run: khi true, KHÔNG upload thật, chỉ log dự định.
Khi false: dùng OAuth (youtube_auth) để videos.insert + thumbnails.set.

Phân loại Short vs clip:
  - video DỌC và ≤ 180s (3 phút) -> Short: gắn #Shorts vào mô tả để YouTube xếp đúng.
  - còn lại (vd > 3p, hoặc ngang) -> clip thường, không gắn #Shorts.
YouTube không có API riêng cho Short — xếp loại dựa trên thời lượng + tỉ lệ khung
hình + hashtag #Shorts. Từ 10/2024 YouTube cho phép Short dài tới 3 phút (trước là 60s).

Hashtag + khai báo AI:
  - Tự build tối đa 3 hashtag (từ video.tags, + #Shorts nếu là Short) chèn vào mô tả
    — YouTube hiển thị 3 hashtag đầu tìm thấy ngay phía trên tiêu đề.
  - Luôn set status.containsSyntheticMedia = settings.youtube_contains_synthetic_media
    (mặc định True) — khai báo "nội dung thay đổi/tổng hợp bởi AI", bắt buộc minh bạch
    theo chính sách YouTube từ 2024 vì kênh này 100% voice TTS + visual AI render.
"""

import json
import re
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
    hashtags = _build_hashtags(video, is_short)
    description = _with_hashtags(video.description, hashtags)
    print(f"  Loại: {'YouTube Short (dọc, ≤3p)' if is_short else 'Clip thường'}")
    print(f"  Hashtag: {' '.join(hashtags) or '(không có)'}")

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
            "containsSyntheticMedia": settings.youtube_contains_synthetic_media,
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


def _to_hashtag(tag: str) -> str:
    """Chuẩn hoá 1 tag SEO thường (có thể có dấu/khoảng trắng) thành 1 hashtag liền,
    giữ chữ/số Unicode (kể cả tiếng Việt có dấu), bỏ khoảng trắng + ký tự đặc biệt."""
    cleaned = re.sub(r"[^\w]", "", tag, flags=re.UNICODE)
    return f"#{cleaned}" if cleaned else ""


def _build_hashtags(video: RenderedVideo, is_short: bool) -> list[str]:
    """Tối đa 3 hashtag — đúng số YouTube hiển thị phía trên tiêu đề. #Shorts luôn
    đứng đầu nếu là Short, còn lại lấy từ video.tags (đã chọn SEO), bỏ trùng."""
    hashtags = ["#Shorts"] if is_short else []
    for tag in video.tags:
        hashtag = _to_hashtag(tag)
        if not hashtag or hashtag.lower() in (h.lower() for h in hashtags):
            continue
        hashtags.append(hashtag)
        if len(hashtags) >= 3:
            break
    return hashtags


def _with_hashtags(description: str, hashtags: list[str]) -> str:
    """Chèn dòng hashtag vào cuối mô tả, trừ hashtag nào đã có sẵn trong mô tả."""
    missing = [h for h in hashtags if h.lower() not in description.lower()]
    if not missing:
        return description
    return f"{description.rstrip()}\n\n{' '.join(missing)}"


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
    is_short = _is_short(video)
    print("── DRY RUN — không upload thật ──")
    print(f"  Loại  : {'YouTube Short (dọc, ≤3p)' if is_short else 'Clip thường'}")
    print(f"  Title : {video.title}")
    print(f"  Tags  : {', '.join(video.tags)}")
    print(f"  Hashtag: {' '.join(_build_hashtags(video, is_short)) or '(không có)'}")
    print(f"  Made with AI (containsSyntheticMedia): {settings.youtube_contains_synthetic_media}")
    print(f"  Video : {video.video_path}")
    print(f"  Thumb : {video.thumbnail_path}")
    print(f"  Privacy: {settings.youtube_privacy}  |  Thời lượng: {video.duration_sec:.1f}s")
    return replace(PublishResult(**vars(video)), uploaded=False, url=None)
