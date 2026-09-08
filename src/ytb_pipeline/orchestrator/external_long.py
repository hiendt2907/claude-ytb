"""Read-only validation for an explicitly referenced completed Long."""

from __future__ import annotations

import json
from pathlib import Path


def completed_external_long_source(archive_dir: Path, slug: str, completed_slugs: set[str]) -> Path | None:
    """Return a usable archived Long only when its ledger state is completed."""
    if slug not in completed_slugs:
        return None
    path = archive_dir / f"{slug}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    sections = payload.get("sections")
    if payload.get("video_type") != "long" or not isinstance(sections, list) or not sections:
        return None
    return path
