"""State I/O cho `ytb batch start` — ledger, auto_state.json, slug uniqueness.

Tách khỏi ideation_cmd.py. Đọc hằng số path (AUTO_STATE_PATH/LEDGER_PATH/...)
qua `_cli()` tại thời điểm gọi để monkeypatch trên batch_cli vẫn hiệu lực
(xem docstring đầu queue_manager.py).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ..ideation.series import slugify
from .state_io import locked_json_update

LEDGER_HEADER = "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"


def _cli():
    from . import batch_cli

    return batch_cli


def count_pending_ideation(type_of_vid: str, auto_state_path: Path | None = None) -> tuple[int, list[str]]:
    """Đếm scripts ĐÃ viết xong (đã có trong batch nhưng chưa done trong ledger) theo loại video.

    Trả (số lượng, danh sách slug) để prompt resume nói rõ "đừng viết lại cái này".
    """
    cli = _cli()
    auto_state_path = auto_state_path if auto_state_path is not None else cli.AUTO_STATE_PATH
    data = json.loads(Path(auto_state_path).read_text(encoding="utf-8"))
    video_key = "long_videos" if type_of_vid == "long" else "short_videos"

    batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
    if not batch_keys:
        return 0, []
    batch = data[batch_keys[-1]]
    videos = batch.get(video_key, [])

    done = cli.done_slugs()
    pending = [v["slug"] for v in videos if v["slug"] not in done]
    return len(pending), pending


def clear_ledger_for_fresh_ideas(ledger_path: Path) -> Path | None:
    """Reset ledger history for fresh ideation, keeping a timestamped backup."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not ledger_path.exists():
        ledger_path.write_text(LEDGER_HEADER, encoding="utf-8")
        return None

    text = ledger_path.read_text(encoding="utf-8")
    if text.strip():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = ledger_path.with_name(f"{ledger_path.stem}.backup.{stamp}{ledger_path.suffix}")
        backup_path.write_text(text, encoding="utf-8")
    else:
        backup_path = None
    ledger_path.write_text(LEDGER_HEADER, encoding="utf-8")
    return backup_path


def ledger_slugs(ledger_text: str) -> set[str]:
    slugs: set[str] = set()
    for line in ledger_text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [part.strip() for part in line.strip("|").split("|")]
        if len(cols) >= 2 and cols[1] and cols[1].lower() != "slug":
            slugs.add(cols[1])
    return slugs


def existing_queue_slugs(auto_state_path: Path) -> set[str]:
    if not auto_state_path.exists():
        return set()
    try:
        data = json.loads(auto_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    slugs: set[str] = set()
    for batch in data.values():
        if not isinstance(batch, dict):
            continue
        for key in ("long_videos", "short_videos"):
            for item in batch.get(key, []) or []:
                slug = item.get("slug") if isinstance(item, dict) else None
                if slug:
                    slugs.add(str(slug))
    return slugs


def unique_slug(base_slug: str, used_slugs: set[str], scripts_dir: Path) -> str:
    base = slugify(base_slug) or "video"
    candidate = base
    index = 2
    while candidate in used_slugs or (scripts_dir / f"{candidate}.json").exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def write_local_batch_item(script_path: Path, payload: dict, args: argparse.Namespace) -> None:
    """Đăng ký 1 script mới vào batch được chọn + ghi ledger.

    `batch_key` cho phép tạo batch mới độc lập thay vì vô tình trộn vào batch
    legacy mới nhất. Không có key thì giữ nguyên hành vi tương thích cũ.
    """
    cli = _cli()
    with locked_json_update(cli.AUTO_STATE_PATH) as data:
        explicit_key = str(getattr(args, "batch_key", "") or "").strip()
        if explicit_key:
            if not explicit_key.startswith("shorts_funnel_batch_"):
                raise SystemExit("✗ --batch-key phải bắt đầu bằng 'shorts_funnel_batch_'.")
            batch_key = explicit_key
        else:
            batch_key = sorted([k for k in data if k.startswith("shorts_funnel_batch_")])[-1:] or ["shorts_funnel_batch_local"]
            batch_key = batch_key[0]
        batch = data.setdefault(batch_key, {"status": "active", "long_videos": [], "short_videos": []})
        key = "long_videos" if args.type_of_vid == "long" else "short_videos"
        videos = batch.setdefault(key, [])
        if any(v.get("slug") == script_path.stem for v in videos if isinstance(v, dict)):
            raise SystemExit(f"✗ Trùng slug trong queue: {script_path.stem}. Dừng để tránh overwrite/rerun sai.")
        funnel = {
            field: str(getattr(args, field, "") or payload.get(field, "")).strip()
            for field in ("long_form_slug", "playlist", "cta_target")
        }
        # Legacy one-off generation predates funnel batches.  The strict
        # relationship contract is activated by the explicit batch boundary,
        # so existing callers remain compatible while every new scheduled
        # funnel batch is fail-fast.
        if args.type_of_vid == "short" and explicit_key:
            missing = [field for field, value in funnel.items() if not value]
            if missing:
                raise SystemExit(
                    "✗ Short phải có long_form_slug, playlist, và cta_target trước khi được ghi vào batch."
                )
            long_slugs = {
                str(item.get("slug", ""))
                for item in batch.get("long_videos", [])
                if isinstance(item, dict)
            }
            if funnel["long_form_slug"] not in long_slugs:
                raise SystemExit("✗ long_form_slug của Short phải trỏ tới Long đã có trong cùng batch.")
            if funnel["cta_target"] != funnel["long_form_slug"]:
                raise SystemExit("✗ cta_target của Short phải khớp long_form_slug.")
        day = max([int(v.get("day", 0)) for v in videos] or [0]) + 1
        videos.append({
            "day": day,
            "slug": script_path.stem,
            "topic": payload.get("topic", payload.get("title", script_path.stem)),
            "orientation": "landscape" if args.type_of_vid == "long" else "portrait",
            "render_provider": "ai",
            "dry_run": cli.settings.dry_run,
            "publish_at": cli.settings.youtube_publish_at,
            "stage": "ideation",
            "status": "ok",
            "shorts_status": "queued",
            "series": payload.get("series", ""),
            "content_pillar": payload.get("content_pillar", ""),
            "core_mechanism": payload.get("core_mechanism", ""),
            "audience_problem": payload.get("audience_problem", ""),
            "long_form_slug": funnel["long_form_slug"],
            "playlist": funnel["playlist"],
            "cta_target": funnel["cta_target"],
        })
    cli.update_ledger(
        script_path.stem,
        payload.get("title", ""),
        "ideation",
        "ok",
        f"LLM script validated: {script_path}",
    )
