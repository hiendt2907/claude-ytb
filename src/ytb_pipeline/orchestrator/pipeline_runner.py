"""Thực thi subprocess pipeline cho batch_cli: chạy `python -m ytb_pipeline
<script>`, retry lỗi tạm thời, xác minh video thật qua YouTube Data API, và xử
lý video kế tiếp trong queue.

Xem docstring đầu queue_manager.py về lý do các hàm ở đây đọc hằng số mutable
(ROOT, v.v.) và các hàm có thể bị monkeypatch (run_with_retry, verify_youtube_video,
log_path_for, update_ledger, emit_warning, ...) qua `_cli()` tại thời điểm gọi,
thay vì import tĩnh — để test patch `cli.<tên>` vẫn có hiệu lực dù logic nằm ở
module nào.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..publish.youtube_auth import ReauthRequiredError
from .queue_manager import PIPELINE_LOG_DIR, QueueItem

# backoff giữa các lần retry (giây) cho lỗi TẠM THỜI — sau khi hết list này mà vẫn
# fail thì bỏ qua slug, KHÔNG chặn cả batch.
RETRY_BACKOFF_SEC = [30, 60, 120]

# Các pattern lỗi coi là TẠM THỜI (đáng retry): 409 đụng Telegram listener, mạng,
# broken pipe khi đẩy Drive... Lỗi khác (script sai, thiếu file, v.v.) không retry.
TRANSIENT_ERROR_PATTERNS = [
    r"HTTP Error 409",
    r"HTTP Error 5\d\d",  # 5xx (vd 503 Pexels quá tải) -- lỗi phía server, đáng retry
    r"Conflict",
    r"Temporary failure in name resolution",
    r"Broken pipe",
    r"Connection reset",
    r"ConnectionError",
    r"timed out",
    r"Name or service not known",
]

# Marker print bởi pipeline.py khi BẮT ĐẦU mỗi khâu (khác marker "✓" khi xong) —
# dùng để ghi ledger NGAY khi video đang chạy khâu nào, thay vì để trống/"pending"
# suốt lúc đang chạy. Thứ tự quan trọng: marker "ai-render" phải khớp TRƯỚC marker
# render chung vì cả 2 đều bắt đầu bằng "[3/4] Render".
STAGE_START_MARKERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\[1/4\] Ideation\s*▶"), "running-ideation"),
    (re.compile(r"^\[2/4\] Voiceover\s*▶"), "running-voiceover"),
    (re.compile(r"^\[3/4\] Render\s*▶.*\(ai/"), "running-ai-render"),
    (re.compile(r"^\[3/4\] Render\s*▶"), "running-render"),
    (re.compile(r"^\[4/4\] Publish\s*▶"), "running-publish"),
]


def _cli():
    """Import trễ module batch_cli — xem queue_manager._cli() cho lý do."""
    from . import batch_cli

    return batch_cli


def detect_stage_marker(line: str) -> str | None:
    """Khớp 1 dòng stdout của pipeline con với marker bắt-đầu-khâu — None nếu không khớp."""
    for pattern, stage in STAGE_START_MARKERS:
        if pattern.search(line):
            return stage
    return None


def is_transient_error(output: str) -> bool:
    """True nếu output chứa dấu hiệu lỗi tạm thời (đáng retry)."""
    return any(re.search(pattern, output) for pattern in TRANSIENT_ERROR_PATTERNS)


def build_env(item: QueueItem) -> dict:
    """Env bắt buộc cho mỗi lần chạy pipeline — TELEGRAM_APPROVAL=false để tránh
    đụng getUpdates với listener daemon (nguyên nhân lỗi 409 thực tế đã gặp)."""
    env = os.environ.copy()
    env.update(
        {
            "TELEGRAM_APPROVAL": "false",
            "RENDER_PROVIDER": "ai",
            "ORIENTATION": "landscape",
            "DRY_RUN": "false",
            "YOUTUBE_PUBLISH_AT": item.publish_at,
        }
    )
    return env


def log_path_for(slug: str, log_dir: Path = PIPELINE_LOG_DIR) -> Path:
    """File log của 1 slug — để `ytb batch logs <slug>` tail được khi đang chạy."""
    return log_dir / f"{slug}.log"


def run_pipeline_once(
    item: QueueItem, script_path: Path | None = None, ledger_path: Path | None = None
) -> subprocess.CompletedProcess:
    """Chạy `python -m ytb_pipeline scripts/<slug>.json` 1 lần, đồng bộ (blocking).

    Stream stdout/stderr ra console NGAY (không chờ tới khi xong) và đồng thời
    ghi vào assets/batch_logs/<slug>.log, để `ytb batch logs <slug> --follow`
    tail được từ terminal khác trong lúc lệnh này còn đang chạy.

    Ghi ledger NGAY khi bắt đầu (stage "running-ideation") và mỗi lần stdout của
    pipeline con báo sang khâu mới (running-voiceover/running-ai-render/
    running-publish) — để `ytb batch status`/`ledger` luôn phản ánh đúng video
    đang ở khâu nào, thay vì không có dòng nào (trông như "pending") suốt lúc
    đang chạy thật.

    Nếu nhận SIGTERM/SIGINT giữa lúc chạy (`ytb batch stop`), tiến trình con bị
    kill ngay và ledger ghi stage hiện tại với status "stopped" (KHÔNG "done"/
    "ok") — để lần `run`/`retry` kế tiếp tự chọn lại ĐÚNG video này (xem
    `done_slugs`/`next_pending`), thay vì coi như đã xong hoặc nhảy qua video kế.
    """
    cli = _cli()
    script_path = script_path or (cli.ROOT / "scripts" / f"{item.slug}.json")
    log_path = cli.log_path_for(item.slug)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cli.update_ledger(
        item.slug, "", "running-ideation", "running", "Tự động: bắt đầu chạy pipeline", ledger_path=ledger_path
    )

    proc = cli.subprocess.Popen(
        [sys.executable, "-m", "ytb_pipeline", str(script_path)],
        cwd=cli.ROOT,
        env=cli.build_env(item),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,  # leader process group riêng -> killpg dọn sạch cả cây con (F5 worker, ffmpeg)
    )
    cli._current_proc = proc
    lines: list[str] = []
    last_stage = "running-ideation"
    try:
        with log_path.open("w", encoding="utf-8", buffering=1) as f:
            for line in proc.stdout:  # type: ignore[union-attr]
                print(line, end="")
                f.write(line)
                lines.append(line)
                stage = cli.detect_stage_marker(line)
                if stage and stage != last_stage:
                    cli.update_ledger(item.slug, "", stage, "running", "Tự động: đang chạy", ledger_path=ledger_path)
                    last_stage = stage
        proc.wait()
    finally:
        cli._current_proc = None

    if cli._stop_requested:
        cli.update_ledger(
            item.slug, "", last_stage, "stopped",
            "Dừng graceful theo yêu cầu user (ytb batch stop) — chạy lại run/retry sẽ tự tiếp tục đúng video này.",
            ledger_path=ledger_path,
        )
    return subprocess.CompletedProcess(args=proc.args, returncode=proc.returncode, stdout="".join(lines), stderr="")


def run_with_retry(
    item: QueueItem,
    backoff: list[int] | None = None,
    sleep_fn=time.sleep,
    run_fn=None,
    ledger_path: Path | None = None,
) -> tuple[bool, str]:
    """Chạy pipeline cho 1 video; tự retry nếu lỗi tạm thời, tối đa len(backoff) lần.

    Lỗi không tạm thời -> dừng ngay, không retry. Cả 2 trường hợp thất bại cuối
    cùng đều gọi emit_warning() (Telegram + log) trước khi trả về False.

    Dừng GRACEFUL (`ytb batch stop`, cờ `_stop_requested`) không tính là lỗi:
    trả về False ngay, KHÔNG retry, KHÔNG emit_warning — `run_pipeline_once`
    đã ghi ledger status "stopped" rồi, không cần cảnh báo thêm.
    """
    cli = _cli()
    backoff = backoff if backoff is not None else RETRY_BACKOFF_SEC
    run_fn = run_fn if run_fn is not None else cli.run_pipeline_once
    attempt = 0
    last_output = ""
    while True:
        result = run_fn(item, ledger_path=ledger_path)
        last_output = (result.stdout or "") + (result.stderr or "")
        if cli._stop_requested:
            return False, last_output
        if result.returncode == 0:
            return True, last_output

        if not cli.is_transient_error(last_output):
            cli.emit_warning(
                f"Video '{item.slug}' lỗi KHÔNG retry (không phải lỗi tạm thời) — "
                f"bỏ qua, chuyển video kế tiếp. Đuôi log:\n{last_output[-1500:]}"
            )
            return False, last_output

        if attempt >= len(backoff):
            cli.emit_warning(
                f"Video '{item.slug}' lỗi tạm thời nhưng đã retry hết {len(backoff)} lần vẫn fail — "
                f"bỏ qua, chuyển video kế tiếp. Đuôi log:\n{last_output[-1500:]}"
            )
            return False, last_output

        wait = backoff[attempt]
        print(f"  ⏳ Lỗi tạm thời (lần {attempt + 1}/{len(backoff)}), retry sau {wait}s...")
        sleep_fn(wait)
        attempt += 1


def extract_claimed_video_id(output: str) -> str | None:
    """Lấy youtube_id mà pipeline TỰ KHAI BÁO trong stdout — KHÔNG đáng tin, chỉ
    dùng để biết ID cần đem đi xác minh thật qua API."""
    m = re.search(r"youtu\.be/([\w-]{6,})", output)
    return m.group(1) if m else None


def verify_youtube_video(video_id: str) -> dict:
    """Xác minh THẬT qua YouTube Data API — không tin stdout của pipeline.

    Bài học từ thực tế: video #2 batch này pipeline tự báo ID sai (không tồn
    tại); chỉ video().list() qua API mới cho biết ID/privacy/publishAt thật.
    """
    from ..publish.youtube_auth import get_youtube_client

    youtube = get_youtube_client()
    resp = youtube.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return {"exists": False}
    snippet = items[0]["snippet"]
    status = items[0]["status"]
    return {
        "exists": True,
        "title": snippet.get("title"),
        "privacy_status": status.get("privacyStatus"),
        "publish_at": status.get("publishAt"),
    }


def check_schedule_drift(verified_publish_at: str | None, expected_publish_at: str) -> bool:
    """True nếu publishAt thật (từ API) lệch so với kế hoạch (auto_state.json).

    Chỉ phát hiện + cảnh báo — KHÔNG tự sửa lịch publish thật trên YouTube.
    """
    if not verified_publish_at:
        return False
    actual = datetime.fromisoformat(verified_publish_at.replace("Z", "+00:00"))
    expected = datetime.fromisoformat(expected_publish_at)
    return actual != expected


def process_next(queue_path: Path | None = None, ledger_path: Path | None = None) -> bool:
    """Chạy đúng 1 video kế tiếp trong queue: pipeline -> verify YouTube -> ledger.

    Trả True nếu đã xử lý 1 video (thành công hoặc thất bại đã ghi nhận),
    False nếu queue đã hết (không còn video pending) — caller dừng vòng lặp.
    """
    cli = _cli()
    queue = cli.load_queue(queue_path)
    item = cli.next_pending(queue, cli.done_slugs(ledger_path))
    if item is None:
        print("✓ Queue đã hết — không còn video pending.")
        return False

    print(f"▶ Chạy video '{item.slug}' (day {item.day}, publish_at={item.publish_at})")
    ok, output = cli.run_with_retry(item, ledger_path=ledger_path)

    if cli._stop_requested:
        # run_pipeline_once đã ghi ledger status "stopped" cho slug này rồi —
        # không ghi đè thành "error", chỉ báo caller (cmd_run) dừng vòng lặp.
        return False

    if not ok:
        failed_stage = cli.last_stage_for_slug(item.slug, ledger_path).removeprefix("running-") or "ideation"
        cli.update_ledger(
            item.slug, "", failed_stage, "error",
            "Tự động: thất bại, xem assets/batch_cli_warnings.log",
            ledger_path=ledger_path,
        )
        return True

    video_id = cli.extract_claimed_video_id(output)
    if video_id is None:
        cli.emit_warning(
            f"Video '{item.slug}' chạy XONG (exit 0) nhưng không tìm thấy youtu.be/<id> "
            f"trong stdout để xác minh — cần Claude kiểm tra log thủ công."
        )
        cli.update_ledger(
            item.slug, "", "publish", "error",
            "Pipeline exit 0 nhưng không có youtube_id trong stdout",
            ledger_path=ledger_path,
        )
        return True

    try:
        verified = cli.verify_youtube_video(video_id)
    except ReauthRequiredError as exc:
        # youtube_auth đã tự bắn Telegram cảnh báo -- ở đây chỉ cần ghi ledger +
        # dừng video này lại (không retry vô hạn), để batch tiếp tục slug khác.
        cli.update_ledger(
            item.slug, "", "publish", "error",
            f"Không xác minh được qua API -- cần `ytb auth`: {exc}",
            ledger_path=ledger_path,
        )
        return True
    if not verified.get("exists"):
        cli.emit_warning(
            f"Video '{item.slug}' — pipeline tự báo ID {video_id} nhưng YouTube API "
            f"KHÔNG xác nhận video này tồn tại. Cần Claude kiểm tra lại."
        )
        cli.update_ledger(
            item.slug, "", "publish", "error",
            f"youtube_id {video_id} không xác minh được qua API",
            ledger_path=ledger_path,
        )
        return True

    if cli.check_schedule_drift(verified.get("publish_at"), item.publish_at):
        cli.emit_warning(
            f"Video '{item.slug}' (https://youtu.be/{video_id}) lệch lịch publish: "
            f"thật={verified.get('publish_at')} vs kế hoạch={item.publish_at} trong auto_state.json. "
            f"KHÔNG tự sửa lịch — cần Claude xác nhận với user."
        )

    cli.update_ledger(
        item.slug,
        verified.get("title", ""),
        "done",
        "ok",
        f"https://youtu.be/{video_id} — verified qua YouTube API "
        f"(privacy={verified.get('privacy_status')}, publishAt={verified.get('publish_at')}).",
        ledger_path=ledger_path,
    )
    print(f"✓ Video '{item.slug}' done — https://youtu.be/{video_id}")
    return True
