"""Khâu 4 — Upload YouTube + SEO + analytics.

Tôn trọng settings.dry_run: khi true, KHÔNG upload thật, chỉ log dự định.
Khi false: dùng OAuth (youtube_auth) để videos.insert + thumbnails.set.

Phân loại Short vs clip:
  - video DỌC và ≤ 180s (3 phút) -> Short: gắn #Shorts vào mô tả để YouTube xếp đúng.
  - còn lại (vd > 3p, hoặc ngang) -> clip thường, không gắn #Shorts.
YouTube không có API riêng cho Short — xếp loại dựa trên thời lượng + tỉ lệ khung
hình + hashtag #Shorts. Từ 10/2024 YouTube cho phép Short dài tới 3 phút (trước là 60s).

Hashtag + khai báo AI:
  - Tự build hashtag tìm kiếm từ video.tags + bộ tag khám phá theo ngách. #Shorts đứng
    đầu nếu là Short; YouTube chỉ hiển thị 3 hashtag đầu nhưng phần mô tả vẫn giữ thêm
    hashtag liên quan để tăng tín hiệu tìm kiếm/đề xuất.
  - Luôn set status.containsSyntheticMedia = settings.youtube_contains_synthetic_media
    (mặc định True) — khai báo "nội dung thay đổi/tổng hợp bởi AI", bắt buộc minh bạch
    theo chính sách YouTube từ 2024 vì kênh này 100% voice TTS + visual AI render.

Comment CTA (Short -> Long funnel):
  - Sau khi upload 1 Short có `strategy.cta_target` (slug Long đích), tự động đăng 1
    comment dẫn về Long đó NẾU Long đã publish (dòng ledger `stage=done, status=ok`
    có URL). YouTube Data API v3 KHÔNG có endpoint ghim comment — chỉ đăng được, việc
    ghim vẫn phải làm tay trong Studio; log luôn nhắc rõ để không gây kỳ vọng sai.
"""

import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

from ..config.settings import settings
from ..pkg.models import PublishResult, RenderedVideo
from ..platform.metadata import MetadataAdapter
from .validation import validate_monetization_ready

# YouTube cho phép Short tới 3 phút (180s) từ 10/2024; short của pipeline nhắm 1–1.5 phút.
SHORT_MAX_SEC = 180
HASHTAG_LIMIT = 12
YOUTUBE_TAG_LIMIT = 30

ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = ROOT / "data" / "ledger.md"

_metadata_adapter = MetadataAdapter()


def publish(video: RenderedVideo, platform: str = "youtube_short") -> PublishResult:
    """Upload qua YouTube Data API (OAuth), set title/tags/thumbnail tối ưu SEO.

    `platform` chỉ chọn `PlatformProfile` dùng để chuẩn hoá metadata qua
    `MetadataAdapter` (sẵn cho khâu publish khác tái dùng) — hành vi upload
    thật ở module này vẫn luôn nhắm YouTube Data API. Tham số có default
    "youtube_short" để `publish(video)` cũ không cần đổi lời gọi.
    """
    # Chuẩn hoá metadata theo platform profile (hiện chỉ dùng để giữ tương thích
    # tương lai — title/description/tags thật vẫn build lại bên dưới như cũ).
    _metadata_adapter.adapt(
        title=video.title,
        description=video.description,
        tags=list(video.tags),
        platform=platform,
        privacy=settings.youtube_privacy,
        publish_at=settings.youtube_publish_at or None,
        contains_synthetic_media=settings.youtube_contains_synthetic_media,
    )

    if settings.dry_run:
        return _dry_run(video)

    validate_monetization_ready(video)

    if video.video_path is None or not video.video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file video: {video.video_path}")

    is_short = _is_short(video)
    seo_tags = _build_seo_tags(video, is_short)
    hashtags = _build_hashtags(video, is_short)
    description = _with_hashtags(video.description, hashtags)
    print(f"  Loại: {'YouTube Short (dọc, ≤3p)' if is_short else 'Clip thường'}")
    print(f"  Hashtag: {' '.join(hashtags) or '(không có)'}")
    print(f"  SEO tags: {', '.join(seo_tags)}")

    # import trong hàm để DRY_RUN không cần thư viện Google
    from googleapiclient.http import MediaFileUpload

    from .youtube_auth import get_youtube_client

    youtube = get_youtube_client()

    body = {
        "snippet": {
            "title": video.title[:100],
            "description": description,
            "tags": seo_tags,
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
    _add_to_playlist(youtube, youtube_id)
    _post_cta_comment(youtube, youtube_id, video)

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


def _build_seo_tags(video: RenderedVideo, is_short: bool) -> list[str]:
    """Tags gửi vào YouTube snippet: chỉ giữ từ khóa được script xác nhận."""
    seeds: list[str] = list(video.tags)
    if is_short:
        seeds.extend(("shorts", "youtube shorts"))

    tags: list[str] = []
    seen: set[str] = set()
    for raw in seeds:
        tag = " ".join(str(raw).strip().split())
        key = tag.casefold()
        if not tag or key in seen:
            continue
        tags.append(tag[:500])
        seen.add(key)
        if len(tags) >= YOUTUBE_TAG_LIMIT:
            break
    return tags


def _build_hashtags(video: RenderedVideo, is_short: bool) -> list[str]:
    """Hashtag trong mô tả: #Shorts trước, sau đó tag script + tag khám phá, bỏ trùng."""
    hashtags = ["#Shorts"] if is_short else []
    for tag in _build_seo_tags(video, is_short):
        hashtag = _to_hashtag(tag)
        if not hashtag or hashtag.lower() in (h.lower() for h in hashtags):
            continue
        hashtags.append(hashtag)
        if len(hashtags) >= HASHTAG_LIMIT:
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


def _add_to_playlist(youtube, youtube_id: str) -> None:  # noqa: ANN001
    if not settings.youtube_playlist_id:
        return
    youtube.playlistItems().insert(
        part="snippet",
        body={"snippet": {"playlistId": settings.youtube_playlist_id,
                           "resourceId": {"kind": "youtube#video", "videoId": youtube_id}}},
    ).execute()


def _published_url_for_slug(slug: str, ledger_path: Path | None = None) -> str | None:
    """URL youtu.be của lần publish MỚI NHẤT (`stage=done, status=ok`) cho `slug`.

    None nếu slug chưa từng done/ok — Long đích có thể chưa lên lịch/chưa publish.
    """
    path = ledger_path if ledger_path is not None else LEDGER_PATH
    if not path.exists():
        return None
    url = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 6 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        if cols[1] != slug or cols[3] != "done" or cols[4] != "ok":
            continue
        match = re.search(r"https://youtu\.be/\S+", cols[5])
        if match:
            url = match.group(0)
    return url


def _post_cta_comment(youtube, youtube_id: str, video: RenderedVideo) -> None:  # noqa: ANN001
    """Đăng comment dẫn về Long-form funnel đích của Short (nếu có + đã publish).

    Chỉ đăng comment — YouTube Data API v3 không có endpoint ghim comment, nên
    KHÔNG được hứa hẹn tự động ghim. Lỗi ở đây không chặn publish đã thành công.
    """
    target_slug = str(getattr(video.strategy, "cta_target", "") or "").strip()
    if not target_slug:
        return
    target_url = _published_url_for_slug(target_slug)
    if not target_url:
        print(f"  ⚠ Chưa đăng comment CTA: Long đích '{target_slug}' chưa publish (chưa có trong ledger).")
        return
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": youtube_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": f"Xem phân tích đầy đủ ở video này: {target_url}"},
                    },
                },
            },
        ).execute()
        print(f"  ✓ Đã tự động đăng comment dẫn Long-form: {target_url}")
        print("  [Action Required] Đã tự động đăng comment. Sếp nhớ mở Studio ghim tay nhé!")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ Không đăng được comment CTA (không chặn publish): {exc}")


def _dry_run(video: RenderedVideo) -> PublishResult:
    is_short = _is_short(video)
    print("── DRY RUN — không upload thật ──")
    print(f"  Loại  : {'YouTube Short (dọc, ≤3p)' if is_short else 'Clip thường'}")
    print(f"  Title : {video.title}")
    print(f"  Tags  : {', '.join(_build_seo_tags(video, is_short))}")
    print(f"  Hashtag: {' '.join(_build_hashtags(video, is_short)) or '(không có)'}")
    print(f"  Made with AI (containsSyntheticMedia): {settings.youtube_contains_synthetic_media}")
    print(f"  Video : {video.video_path}")
    print(f"  Thumb : {video.thumbnail_path}")
    print(f"  Privacy: {settings.youtube_privacy}  |  Thời lượng: {video.duration_sec:.1f}s")
    target_slug = str(getattr(video.strategy, "cta_target", "") or "").strip()
    if target_slug:
        target_url = _published_url_for_slug(target_slug)
        print(
            f"  Comment CTA: sẽ đăng dẫn tới '{target_slug}' -> {target_url}"
            if target_url else
            f"  Comment CTA: bỏ qua — Long đích '{target_slug}' chưa publish"
        )
    return replace(PublishResult(**vars(video)), uploaded=False, url=None)
