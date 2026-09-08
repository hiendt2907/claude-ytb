"""Fail-closed checks for already-registered generated media."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset_registry import AssetRegistry, content_sha256


class VisualAssetIntegrityError(ValueError):
    """A prior asset/checkpoint is inconsistent and must be repaired manually."""


def record_matches_observed_file(record: dict[str, Any], path: Path) -> bool:
    expected = record.get("content_sha256")
    if not isinstance(expected, str) or not expected or not path.is_file():
        return False
    try:
        return str(content_sha256(path)) == expected
    except OSError:
        return False


def assert_registered_cache_is_intact(
    registry: AssetRegistry, *, generation_key: str, path: Path
) -> None:
    """Refuse to overwrite a cache location with broken registered history.

    A missing/replaced file is an integrity incident, not a semantic rejection.
    Generating again would hide the evidence and spend GPU on a retry that no
    review policy explicitly authorized.
    """
    observations = [
        record
        for record in registry.find_by_generation_key(generation_key)
        if Path(str(record.get("local_path") or "")) == path
    ]
    if observations and not any(record_matches_observed_file(record, path) for record in observations):
        raise VisualAssetIntegrityError(
            "Visual asset integrity failure: registered generation cache is missing "
            f"or its content hash no longer matches: {path}"
        )
