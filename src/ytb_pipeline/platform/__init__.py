"""Platform-independence layer — Phase 4 của migration plan.

`profiles.py` định nghĩa ràng buộc kỹ thuật/metadata theo từng nền tảng
(YouTube Short/Long, Instagram Reel, Podcast, Blog). `metadata.py`
chuyển metadata thô của script thành `PublishMetadata` đã áp ràng buộc đó,
để publish provider không cần biết business logic
viết title/hashtag — chỉ nhận `PublishMetadata` đã chuẩn hoá.
"""

from .metadata import MetadataAdapter, PublishMetadata
from .profiles import PROFILES, Platform, PlatformProfile, get_profile

__all__ = [
    "Platform",
    "PlatformProfile",
    "PROFILES",
    "get_profile",
    "MetadataAdapter",
    "PublishMetadata",
]
