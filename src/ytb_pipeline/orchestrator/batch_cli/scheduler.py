"""Lập lịch publish_at cho video pending trong assets/auto_state.json.

Hằng số mutable (AUTO_STATE_PATH, DEFAULT_SCHEDULE_SLOTS, VN_TZ) và hàm dùng
chung (done_slugs) đọc qua `_cli()` tại thời điểm gọi để test patch qua
`batch_cli.<TÊN>` vẫn hiệu lực — xem `queue_manager.py::_cli()`.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta

from ..state_io import locked_json_update


def _cli():
    """Import trễ package batch_cli — xem queue_manager._cli() cho lý do."""
    from .. import batch_cli

    return batch_cli


def _parse_schedule_slots(raw: str) -> list[time]:
    slots: list[time] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            hour_text, minute_text = value.split(":", 1)
            slots.append(time(hour=int(hour_text), minute=int(minute_text)))
        except ValueError as exc:
            raise SystemExit(f"✗ Slot schedule không hợp lệ: '{value}'. Dùng dạng HH:MM, vd 11:30,20:30.") from exc
    if not slots:
        raise SystemExit("✗ Cần ít nhất 1 slot schedule, vd --schedule-slots 11:30,20:30.")
    return slots


def _parse_long_publish_at(raw: str) -> list[datetime]:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    moments: list[datetime] = []
    for value in values:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SystemExit("✗ --long-publish-at phải là RFC3339, vd 2026-08-04T20:30:00+07:00.") from exc
        if moment.tzinfo is None:
            raise SystemExit("✗ --long-publish-at phải có timezone, vd +07:00.")
        moments.append(moment)
    return moments


def _latest_batch_key(data: dict) -> str:
    batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
    if not batch_keys:
        raise SystemExit("✗ Không tìm thấy batch shorts_funnel_batch_* trong assets/auto_state.json.")
    return batch_keys[-1]


def schedule_pending_videos(args: argparse.Namespace, *, now: datetime | None = None) -> int:
    """Gán publish_at cho video pending chưa có lịch trong batch mới nhất.

    Không ghi đè video đã có publish_at để tránh đổi lịch đã set tay/đã upload.
    """
    cli = _cli()
    if not cli.AUTO_STATE_PATH.exists():
        raise SystemExit(f"✗ Không tìm thấy queue: {cli.AUTO_STATE_PATH}")

    done = cli.done_slugs()
    slots = _parse_schedule_slots(getattr(args, "schedule_slots", cli.DEFAULT_SCHEDULE_SLOTS))
    start_days = getattr(args, "schedule_start_days", 1)
    if start_days < 0:
        raise SystemExit("✗ --schedule-start-days không được âm.")

    base_now = now or datetime.now(cli.VN_TZ)
    start_date_value = str(getattr(args, "schedule_start_date", "")).strip()
    try:
        start_date = (
            date.fromisoformat(start_date_value)
            if start_date_value
            else base_now.astimezone(cli.VN_TZ).date() + timedelta(days=start_days)
        )
    except ValueError as exc:
        raise SystemExit("✗ --schedule-start-date phải là YYYY-MM-DD.") from exc
    long_moments = _parse_long_publish_at(str(getattr(args, "long_publish_at", "")))
    with locked_json_update(cli.AUTO_STATE_PATH) as data:
        requested_batch_key = str(getattr(args, "batch_key", "") or "").strip()
        batch_key = requested_batch_key or _latest_batch_key(data)
        if batch_key not in data:
            raise SystemExit(f"✗ Không tìm thấy batch '{batch_key}' trong assets/auto_state.json.")
        batch = data[batch_key]
        daily_bundle = batch.get("daily_cadence") == {"longs": 1, "shorts": 2}

        def eligible(video: dict) -> bool:
            return (
                video.get("slug") not in done
                and video.get("status", "ok") not in {"needs_review", "error"}
                and video.get("quality_status") == "pass"
                and video.get("qa_status") == "pass"
                and video.get("ruleset_id") == cli.CONTRACT_VERSION
                and video.get("assets_valid") is not False
                and not str(video.get("publish_at", "")).strip()
            )

        long_pending = [video for video in batch.get("long_videos", []) if eligible(video)]
        short_pending = [
            video
            for video in sorted(batch.get("short_videos", []), key=lambda v: int(v.get("day", 0)))
            if eligible(video)
        ]

        if daily_bundle:
            if len(slots) < 3:
                raise SystemExit("✗ Daily bundle cần 3 slots: Short 1, Short 2, rồi Long.")
            shorts_by_long: dict[str, list[dict]] = {}
            for short in short_pending:
                shorts_by_long.setdefault(str(short.get("long_form_slug", "")).strip(), []).append(short)
            for long_video in long_pending:
                target = str(long_video.get("slug", "")).strip()
                if len(shorts_by_long.get(target, [])) != 2:
                    raise SystemExit(
                        f"✗ Daily bundle yêu cầu Long '{target}' có đúng 2 Shorts cùng Long trước khi schedule."
                    )
            if len(short_pending) != len(long_pending) * 2:
                raise SystemExit("✗ Daily bundle chỉ schedule khi mọi Short thuộc đúng một Long pending.")
            if long_moments and len(long_moments) < len(long_pending):
                raise SystemExit("✗ Thiếu mốc --long-publish-at cho Long pending.")
            for index, long_video in enumerate(long_pending):
                moment = (
                    long_moments[index]
                    if long_moments
                    else datetime.combine(start_date + timedelta(days=index), slots[-1], tzinfo=cli.VN_TZ)
                )
                linked = sorted(shorts_by_long[str(long_video["slug"])], key=lambda item: int(item.get("day", 0)))
                for short_index, short in enumerate(linked):
                    short["publish_at"] = datetime.combine(
                        moment.astimezone(cli.VN_TZ).date(), slots[short_index], tzinfo=cli.VN_TZ
                    ).isoformat(timespec="seconds")
                long_video["publish_at"] = moment.isoformat(timespec="seconds")
        elif long_moments:
            if len(long_moments) < len(long_pending):
                raise SystemExit("✗ Thiếu mốc --long-publish-at cho Long pending.")
            for video, moment in zip(long_pending, long_moments):
                video["publish_at"] = moment.isoformat(timespec="seconds")
            for index, video in enumerate(short_pending):
                slot = slots[index % len(slots)]
                scheduled_date = start_date + timedelta(days=index // len(slots))
                video["publish_at"] = datetime.combine(scheduled_date, slot, tzinfo=cli.VN_TZ).isoformat(
                    timespec="seconds"
                )
        # Legacy batches retain their prior weekly policy. New batches use the
        # daily_bundle branch above and never reach this compatibility path.
        elif getattr(args, "schedule_slots", cli.DEFAULT_SCHEDULE_SLOTS) in {
            cli.DEFAULT_SCHEDULE_SLOTS,
            "06:00,20:30",
        }:
            sunday = start_date + timedelta(days=(6 - start_date.weekday()) % 7)
            for video in long_pending:
                video["publish_at"] = datetime.combine(sunday, slots[-1], tzinfo=cli.VN_TZ).isoformat(
                    timespec="seconds"
                )
                sunday += timedelta(days=7)
            date_cursor = start_date
            for index, video in enumerate(short_pending):
                while date_cursor.weekday() == 6:
                    date_cursor += timedelta(days=1)
                slot = slots[index % len(slots)]
                video["publish_at"] = datetime.combine(date_cursor, slot, tzinfo=cli.VN_TZ).isoformat(
                    timespec="seconds"
                )
                if index % len(slots) == len(slots) - 1:
                    date_cursor += timedelta(days=1)
        else:
            pending = sorted(long_pending + short_pending, key=lambda v: int(v.get("day", 0)))
            for index, video in enumerate(pending):
                slot = slots[index % len(slots)]
                scheduled_date = start_date + timedelta(days=index // len(slots))
                video["publish_at"] = datetime.combine(scheduled_date, slot, tzinfo=cli.VN_TZ).isoformat(
                    timespec="seconds"
                )

    slot_text = ",".join(f"{slot.hour:02d}:{slot.minute:02d}" for slot in slots)
    count = len(long_pending) + len(short_pending)
    print(f"✓ Đã schedule {count} video pending trong {batch_key} từ {start_date.isoformat()} (slots={slot_text}).")
    return count
