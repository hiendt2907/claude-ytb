"""Adapter — bọc `publish/drive.py` (Google Drive backup) thành PublishProvider.

Đây là provider BACKUP (chạy sau khi YouTube đã publish), không phải provider
chính của khâu publish — `get_publish_provider()` mặc định trả "youtube".
`publish()` ở đây nhận RenderedVideo/PublishResult đã có video_path và chỉ
đẩy file lên Drive, trả lại cùng video kèm ghi chú backup (không thay đổi
hành vi gốc của `backup_to_drive`).
"""

from ...pkg.models import PublishResult, RenderedVideo


class DrivePublishProvider:
    name = "drive"

    async def publish(self, video: RenderedVideo) -> PublishResult:
        from dataclasses import replace

        from ...publish.drive import backup_to_drive

        link = backup_to_drive(video.video_path, move=False)
        if isinstance(video, PublishResult):
            return replace(video, url=link or video.url)
        return PublishResult(**vars(video), url=link, uploaded=False)

    def is_available(self) -> bool:
        from ...config.settings import settings

        return bool(settings.drive_backup)
