"""Áp branding lên kênh đang được token cấp quyền: banner + mô tả + từ khoá.

Avatar (ảnh đại diện) và handle KHÔNG set được qua API — làm thủ công trong Studio.
"""

from __future__ import annotations

from pathlib import Path

from googleapiclient.http import MediaFileUpload

from ytb_pipeline.publish.youtube_auth import get_youtube_client

BANNER = Path("assets/branding/banner.png")

DESCRIPTION = (
    "☕ Chào bạn, mừng bạn ghé 1 Cốc Café 6h!\n\n"
    "Mỗi sáng một cốc café, một chút động lực — kênh chia sẻ những điều nhỏ giúp ngày "
    "của bạn nhẹ hơn và có động lực hơn.\n\n"
    "Ở đây bạn sẽ tìm thấy:\n"
    "• Thói quen & mẹo bắt đầu ngày mới tỉnh táo, có kiểm soát\n"
    "• Động lực và tư duy để sống – làm việc hiệu quả hơn\n"
    "• Mẹo sống, năng suất, đôi khi cả vài mẹo công nghệ hay ho\n\n"
    "🔔 Video mới đều đặn — đăng ký kênh và pha một cốc, cùng bắt đầu ngày mới nhé!\n"
    "📩 Hợp tác / liên hệ: danghien2907@gmail.com"
)
KEYWORDS = (
    'động_lực "thói quen buổi sáng" "morning routine" lifestyle "phát triển bản thân" '
    'năng suất "mẹo sống" buổi_sáng "dậy sớm" "sống tích cực" café "tư duy tích cực" '
    '"vlog tiếng Việt"'
)


def main() -> None:
    yt = get_youtube_client()

    ch = yt.channels().list(part="id,brandingSettings", mine=True).execute()
    item = ch["items"][0]
    channel_id = item["id"]
    title = item.get("brandingSettings", {}).get("channel", {}).get("title", "?")
    print(f"Kênh: {title} ({channel_id})")

    # 1) upload banner
    print("→ Upload banner…")
    up = yt.channelBanners().insert(
        media_body=MediaFileUpload(str(BANNER), mimetype="image/png", resumable=False)
    ).execute()
    banner_url = up["url"]
    print("  banner url:", banner_url)

    # 2) set mô tả + từ khoá + gắn banner
    print("→ Cập nhật mô tả, từ khoá, banner…")
    branding = item.get("brandingSettings", {})
    branding.setdefault("channel", {})
    branding["channel"]["description"] = DESCRIPTION
    branding["channel"]["keywords"] = KEYWORDS
    branding.setdefault("image", {})
    branding["image"]["bannerExternalUrl"] = banner_url

    yt.channels().update(
        part="brandingSettings",
        body={"id": channel_id, "brandingSettings": branding},
    ).execute()
    print("✓ Đã áp branding (banner + mô tả + từ khoá).")
    print("  Avatar + handle: tự đặt trong YouTube Studio.")


if __name__ == "__main__":
    main()
