"""Cấu hình cho content pipeline — đọc từ env, không hardcode path/key."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentSettings:
    claude_bin: str
    claude_model: str
    claude_fallback_model: str
    pexels_api_key: str
    youtube_api_key: str
    youtube_client_secret_path: str
    youtube_token_path: str
    youtube_privacy: str
    youtube_category_id: str
    youtube_contains_synthetic_media: bool
    ledger_path: str


def load_content_settings() -> ContentSettings:
    return ContentSettings(
        claude_bin=os.environ.get("CLAUDE_BIN", "claude"),
        claude_model=os.environ.get("CLAUDE_MODEL", "sonnet"),
        claude_fallback_model=os.environ.get("CLAUDE_FALLBACK_MODEL", "haiku"),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        # Mặc định trỏ vào credentials copy từ claude-ytb/secrets/ (đã chốt dùng
        # lại cùng kênh YouTube) — xem CLAUDE.md mục Publish.
        youtube_client_secret_path=os.environ.get(
            "YOUTUBE_CLIENT_SECRET", "secrets/client_secret.json"
        ),
        youtube_token_path=os.environ.get("YOUTUBE_TOKEN", "secrets/youtube_token.json"),
        youtube_privacy=os.environ.get("YOUTUBE_PRIVACY", "private"),
        youtube_category_id=os.environ.get("YOUTUBE_CATEGORY_ID", "22"),
        youtube_contains_synthetic_media=os.environ.get(
            "YOUTUBE_CONTAINS_SYNTHETIC_MEDIA", "true"
        ).lower()
        in ("1", "true", "yes"),
        ledger_path=os.environ.get("CONTENT_LEDGER_PATH", "data/content_ledger.json"),
    )
