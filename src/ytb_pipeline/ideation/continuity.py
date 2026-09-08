"""Series memory write-back: what an episode changed, recorded after it ships.

The continuity ledger of a content profile is fed into the generation prompt so
a new episode knows the world it enters.  Reading alone is not enough: without a
write-back, `current_episode` stays 0 and episode two is written as though
episode one never aired.

The script itself declares what changed — the model already knows, and asking it
again later would invent facts.  Everything here is therefore a pure function
over that declaration, applied only once the episode has actually published.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


class ContinuityError(ValueError):
    """A continuity declaration is missing required structure."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ContinuityError(f"continuity.{field} phải là mảng chuỗi.")
    items = tuple(_text(item) for item in value)
    if any(not item for item in items):
        raise ContinuityError(f"continuity.{field} không được chứa phần tử rỗng.")
    return items


def episode_from_payload(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validated continuity declaration from a script payload, or None.

    Returns None for a script that declares nothing — the explainer profiles and
    every legacy script — so the caller can stay unconditional.
    """
    raw = payload.get("continuity")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ContinuityError("continuity phải là object.")

    summary = _text(raw.get("episode_summary"))
    if not summary:
        raise ContinuityError("continuity.episode_summary không được rỗng.")

    changes_raw = raw.get("character_changes") or {}
    if not isinstance(changes_raw, Mapping):
        raise ContinuityError("continuity.character_changes phải là object.")
    changes: dict[str, str] = {}
    for name, change in changes_raw.items():
        speaker = _text(name).lower()
        if not speaker:
            raise ContinuityError("continuity.character_changes cần tên nhân vật.")
        described = _text(change)
        if not described:
            raise ContinuityError(
                f"continuity.character_changes['{speaker}'] không được rỗng."
            )
        changes[speaker] = described

    return {
        "episode_summary": summary,
        "character_changes": changes,
        "threads_opened": list(_string_list(raw.get("threads_opened"), field="threads_opened")),
        "threads_closed": list(_string_list(raw.get("threads_closed"), field="threads_closed")),
    }


def apply_episode(
    ledger: Mapping[str, Any],
    *,
    slug: str,
    title: str,
    declaration: Mapping[str, Any],
    published_at: str,
    url: str,
) -> dict[str, Any]:
    """Ledger AFTER this episode aired.  Never mutates the ledger passed in.

    Idempotent by slug: a resumed publish re-enters this function with an
    episode already recorded, and must not count it twice.
    """
    updated = json.loads(json.dumps(ledger, ensure_ascii=False))
    episodes = list(updated.get("episodes") or [])
    if any(_text(entry.get("slug")) == _text(slug) for entry in episodes):
        return updated

    number = len(episodes) + 1
    episodes.append({
        "episode": number,
        "slug": _text(slug),
        "title": _text(title),
        "published_at": _text(published_at),
        "url": _text(url),
        "summary": declaration["episode_summary"],
        "character_changes": dict(declaration["character_changes"]),
        "threads_opened": list(declaration["threads_opened"]),
        "threads_closed": list(declaration["threads_closed"]),
    })

    open_threads = list(updated.get("open_threads") or [])
    for thread in declaration["threads_opened"]:
        if thread not in open_threads:
            open_threads.append(thread)
    closed = set(declaration["threads_closed"])
    open_threads = [thread for thread in open_threads if thread not in closed]

    state = dict(updated.get("character_state") or {})
    for speaker, change in declaration["character_changes"].items():
        history = list(state.get(speaker) or [])
        history.append({"episode": number, "change": change})
        state[speaker] = history

    updated["episodes"] = episodes
    updated["current_episode"] = number
    updated["open_threads"] = open_threads
    updated["character_state"] = state
    return updated


def ledger_path(profile: Any) -> Path | None:
    """Path of the profile's continuity ledger, or None when it declares none."""
    relative = profile.prompts.get("continuity")
    if not relative:
        return None
    return profile.root / relative


def record_published_episode(
    profile: Any,
    payload: Mapping[str, Any],
    *,
    slug: str,
    title: str,
    published_at: str,
    url: str,
) -> bool:
    """Write the episode into the profile ledger.  True when the ledger changed.

    A profile without a ledger, or a script without a declaration, is a no-op —
    continuity is a property of series profiles, not of the pipeline.
    """
    path = ledger_path(profile)
    if path is None:
        return False
    declaration = episode_from_payload(payload)
    if declaration is None:
        return False
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityError(f"Không đọc được continuity ledger: {path}") from exc
    if not isinstance(ledger, dict):
        raise ContinuityError(f"Continuity ledger phải là object: {path}")

    updated = apply_episode(
        ledger,
        slug=slug,
        title=title,
        declaration=declaration,
        published_at=published_at,
        url=url,
    )
    if updated == ledger:
        return False
    _write_atomic(path, updated)
    return True


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(handle)
    Path(temporary).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
