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
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..publish.youtube_auth import ReauthRequiredError
from ..content_profiles import load_content_profile, profile_environment
from .queue_manager import PIPELINE_LOG_DIR, QueueItem
from .recovery_contract import RecoveryPlan, recovery_for_failure
from .recovery_report import write_recovery_report

# backoff giữa các lần retry (giây) cho lỗi TẠM THỜI — sau khi hết list này mà vẫn
# fail thì bỏ qua slug, KHÔNG chặn cả batch.
RETRY_BACKOFF_SEC = [30, 60, 120]
# `videos.list` chỉ đọc metadata, nên không được phép giữ một worker batch vô
# hạn như upload/render. Hạ timeout transport xuống 20s cho riêng call verify;
# upload vẫn dùng timeout mặc định dài hơn trong publish/uploader.py.
YOUTUBE_VERIFY_TIMEOUT_SEC = 20

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
    r"NoAudioReceived",
    r"No audio was received",
]

# Marker print bởi pipeline.py khi BẮT ĐẦU mỗi khâu (khác marker "✓" khi xong) —
# dùng để ghi ledger NGAY khi video đang chạy khâu nào, thay vì để trống/"pending"
# suốt lúc đang chạy. Thứ tự quan trọng: marker "ai-render" phải khớp TRƯỚC marker
# render chung vì cả 2 đều bắt đầu bằng "[3/4] Render".
STAGE_START_MARKERS: list[tuple[re.Pattern, str]] = [
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
    return recovery_for_output(output).retryable


def recovery_for_output(output: str) -> RecoveryPlan:
    """Infer the latest stage from pipeline output and return the recovery plan."""
    stage = "unknown"
    for line in output.splitlines():
        marker = detect_stage_marker(line)
        if marker:
            stage = marker
    return recovery_for_failure(stage, output)


def write_failure_recovery_report(item: QueueItem, output: str) -> Path | None:
    """Persist a sanitized recovery observation without changing batch state.

    Reporting itself must never mask the pipeline failure: monitor evidence is
    useful, but a read/write error in its JSON directory cannot grant a retry.
    """
    cli = _cli()
    try:
        return write_recovery_report(
            cli.ROOT / "assets" / "quality_reports" / "recovery",
            slug=item.slug,
            failure_output=output,
            log_path=cli.log_path_for(item.slug),
        )
    except OSError:
        return None


def build_env(item: QueueItem, *, publish: bool = False) -> dict:
    """Env bắt buộc cho mỗi lần chạy pipeline — TELEGRAM_APPROVAL=false để tránh
    đụng getUpdates với listener daemon (nguyên nhân lỗi 409 thực tế đã gặp)."""
    env = os.environ.copy()
    profile = load_content_profile(item.profile_id or None)
    env.update(profile_environment(profile))
    env.update(
        {
            "TELEGRAM_APPROVAL": "false",
            "ALLOW_CLOUD_PROVIDERS": "true",
            "E2E_TEST": "false",
            "ORIENTATION": item.orientation,
            "DRY_RUN": "false" if publish else "true",
            "YOUTUBE_PUBLISH_AT": item.publish_at,
        }
    )
    return env


def validate_queue_profile_binding(item: QueueItem, script_path: Path) -> None:
    """Fail before subprocess when queue and explicit script profiles diverge."""
    try:
        raw = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Không đọc được script để kiểm profile: {script_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Script phải là JSON object: {script_path}")
    script_profile_id = str(raw.get("profile_id") or "").strip()
    if not script_profile_id:
        return  # Legacy script compatibility; input gate applies global contract.
    script_profile_version = str(raw.get("profile_version") or "").strip()
    if not item.profile_version:
        raise ValueError(
            f"Queue item '{item.slug}' thiếu profile_version cho profile explicit."
        )
    if (item.profile_id, item.profile_version) != (
        script_profile_id,
        script_profile_version,
    ):
        raise ValueError(
            f"Queue/script profile mismatch cho '{item.slug}': "
            f"queue={item.profile_id}@{item.profile_version}, "
            f"script={script_profile_id}@{script_profile_version}."
        )


def log_path_for(slug: str, log_dir: Path = PIPELINE_LOG_DIR) -> Path:
    """File log của 1 slug — để `ytb batch logs <slug>` tail được khi đang chạy."""
    return log_dir / f"{slug}.log"


def run_pipeline_once(
    item: QueueItem,
    script_path: Path | None = None,
    ledger_path: Path | None = None,
    worker_id: int | str | None = None,
    *,
    through: str = "publish",
    publish: bool = False,
    f5_daemon_socket: Path | None = None,
    initial_stage: str = "starting-voiceover",
) -> subprocess.CompletedProcess:
    """Chạy `python -m ytb_pipeline scripts/<slug>.json` 1 lần, đồng bộ (blocking).

    Stream stdout/stderr ra console NGAY (không chờ tới khi xong) và đồng thời
    ghi vào assets/batch_logs/<slug>.log, để `ytb batch logs <slug> --follow`
    tail được từ terminal khác trong lúc lệnh này còn đang chạy.

    Ghi ledger NGAY khi bắt đầu (stage "starting-voiceover") và mỗi lần stdout của
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
    validate_queue_profile_binding(item, script_path)
    log_path = cli.log_path_for(item.slug)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cli.update_ledger(item.slug, "", initial_stage, "running", "Tự động: chuẩn bị pipeline", ledger_path=ledger_path)
    if worker_id is not None:
        cli.update_worker_state(worker_id, slug=item.slug, stage=initial_stage)

    env = cli.build_env(item, publish=publish)
    if f5_daemon_socket is not None:
        env["F5_DAEMON_SOCKET"] = str(f5_daemon_socket)

    proc = cli.subprocess.Popen(
        [sys.executable, "-m", "ytb_pipeline", "--through", through, str(script_path)],
        cwd=cli.ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,  # leader process group riêng -> killpg dọn sạch cả cây con (F5 worker, ffmpeg)
    )
    cli._current_proc = proc
    cli._current_procs[item.slug] = proc
    lines: list[str] = []
    last_stage = initial_stage
    try:
        with log_path.open("w", encoding="utf-8", buffering=1) as f:
            for line in proc.stdout:  # type: ignore[union-attr]
                print(line, end="")
                f.write(line)
                lines.append(line)
                stage = cli.detect_stage_marker(line)
                if stage and stage != last_stage:
                    cli.update_ledger(item.slug, "", stage, "running", "Tự động: đang chạy", ledger_path=ledger_path)
                    if worker_id is not None:
                        cli.update_worker_state(worker_id, slug=item.slug, stage=stage)
                    last_stage = stage
        proc.wait()
    finally:
        cli._current_procs.pop(item.slug, None)
        cli._current_proc = None

    if cli._stop_requested:
        cli.update_ledger(
            item.slug, "", last_stage, "stopped",
            "Dừng graceful theo yêu cầu user (ytb batch stop) — chạy lại run/retry sẽ tự tiếp tục đúng video này.",
            ledger_path=ledger_path,
        )
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="stopped")
    return subprocess.CompletedProcess(args=proc.args, returncode=proc.returncode, stdout="".join(lines), stderr="")


# Số lần liên tiếp CÙNG recovery code (không tính reset bởi 1 lần thành công)
# trước khi gửi thêm 1 cảnh báo escalation riêng biệt, khác với emit_warning
# thường mỗi lần fail. Mục đích: --loop chạy vô tiếp qua nhiều video lỗi cùng
# 1 nguyên nhân hệ thống (vd calibration sai) trong nhiều giờ không ai để ý —
# xem data/ledger.md 2026-07-22 (6 lỗi voiceover liên tiếp cùng lớp nguyên nhân).
RECOVERY_ESCALATION_THRESHOLD = 3


def _track_recovery_failure(plan: RecoveryPlan) -> int:
    """Tăng streak của `plan.code`, trả về streak hiện tại sau khi tăng."""
    cli = _cli()
    streak = cli._recovery_code_streak
    streak[plan.code] = streak.get(plan.code, 0) + 1
    return streak[plan.code]


def _reset_recovery_streaks() -> None:
    """Gọi khi 1 video chạy thành công — escalation chỉ đếm lỗi LIÊN TIẾP."""
    _cli()._recovery_code_streak.clear()


def _maybe_escalate_recovery_streak(plan: RecoveryPlan, streak: int, item: QueueItem) -> None:
    """Gửi 1 cảnh báo escalation RIÊNG khi cùng mã lỗi lặp liên tiếp đủ ngưỡng.

    Khác `emit_warning` thường (gửi mỗi lần fail) — đây là tín hiệu "đây gần như
    chắc chắn là lỗi hệ thống, không phải lỗi 1 video", để Sếp biết cần dừng
    `--loop` kiểm tra thay vì để nó tự chạy hết queue lỗi.
    """
    if streak < RECOVERY_ESCALATION_THRESHOLD:
        return
    cli = _cli()
    cli.emit_warning(
        f"🚨 ESCALATION: mã lỗi [{plan.code}] đã lặp lại {streak} lần liên tiếp trong phiên "
        f"--loop này (lần gần nhất: '{item.slug}'). Đây nhiều khả năng là lỗi hệ thống "
        "(vd calibration/prompt sai chung cho cả lớp nội dung), không phải lỗi riêng 1 video — "
        "cân nhắc dừng loop (`ytb batch stop`) và kiểm tra trước khi để nó tiếp tục đốt compute."
    )


def run_with_retry(
    item: QueueItem,
    backoff: list[int] | None = None,
    sleep_fn=time.sleep,
    run_fn=None,
    ledger_path: Path | None = None,
    worker_id: int | str | None = None,
) -> tuple[bool, str]:
    """Chạy pipeline cho 1 video; tự retry nếu lỗi tạm thời, tối đa len(backoff) lần.

    Lỗi không tạm thời -> dừng ngay, không retry. Cả 2 trường hợp thất bại cuối
    cùng đều gọi emit_warning() (Telegram + log) trước khi trả về False, và đếm
    streak để escalate riêng nếu cùng mã lỗi lặp lại nhiều lần liên tiếp (xem
    `_maybe_escalate_recovery_streak`).

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
        result = run_fn(item, ledger_path=ledger_path, worker_id=worker_id)
        last_output = (result.stdout or "") + (result.stderr or "")
        if cli._stop_requested:
            return False, last_output
        if result.returncode == 0:
            cli._reset_recovery_streaks()
            return True, last_output

        plan = cli.recovery_for_output(last_output)
        if not plan.retryable:
            report = cli.write_failure_recovery_report(item, last_output)
            streak = cli._track_recovery_failure(plan)
            cli.emit_warning(
                f"Video '{item.slug}' dừng an toàn [{plan.code}]: {plan.action}. "
                f"KHÔNG retry tự động; report={report or 'không ghi được'}. "
                f"Xem log trước khi can thiệp. Đuôi log:\n{last_output[-1500:]}"
            )
            cli._maybe_escalate_recovery_streak(plan, streak, item)
            return False, last_output

        allowed_retries = min(len(backoff), plan.max_attempts)
        if attempt >= allowed_retries:
            report = cli.write_failure_recovery_report(item, last_output)
            streak = cli._track_recovery_failure(plan)
            cli.emit_warning(
                f"Video '{item.slug}' [{plan.code}] đã retry hết {allowed_retries} lần — "
                f"{plan.action}. report={report or 'không ghi được'}. Đuôi log:\n{last_output[-1500:]}"
            )
            cli._maybe_escalate_recovery_streak(plan, streak, item)
            return False, last_output

        wait = backoff[attempt]
        print(f"  ⏳ [{plan.code}] retry an toàn (lần {attempt + 1}/{allowed_retries}) sau {wait}s...")
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
    # googleapiclient bọc httplib2.Http trong AuthorizedHttp. Nếu một socket cũ
    # rơi vào CLOSE_WAIT, timeout ngắn này biến nó thành lỗi có thể ghi nhận thay
    # vì giữ worker batch mãi mãi. Fake client trong test/implementation khác
    # không nhất thiết có cấu trúc nội bộ này, nên giữ call verify tương thích.
    transport = getattr(getattr(youtube, "_http", None), "http", None)
    if transport is not None and hasattr(transport, "timeout"):
        transport.timeout = YOUTUBE_VERIFY_TIMEOUT_SEC
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


def _persist_published_auto_state(
    item: QueueItem,
    video_id: str,
    *,
    batch_key: str | None = None,
    auto_state_path: Path | None = None,
) -> None:
    """Persist the verified YouTube identity back into the originating queue item."""
    cli = _cli()
    path = Path(auto_state_path) if auto_state_path is not None else Path(cli.AUTO_STATE_PATH)
    with cli.locked_json_update(path) as data:
        keys = [batch_key] if batch_key is not None else list(data)
        matches: list[dict] = []
        for key in keys:
            batch = data.get(key)
            if not isinstance(batch, dict):
                continue
            for group in ("short_videos", "long_videos"):
                for video in batch.get(group, []):
                    if isinstance(video, dict) and video.get("slug") == item.slug:
                        matches.append(video)
        if len(matches) != 1:
            raise ValueError(
                f"Không thể cập nhật publish state cho '{item.slug}': "
                f"tìm thấy {len(matches)} queue item."
            )
        matches[0].update({
            "shorts_status": "published",
            "youtube_id": video_id,
            "youtube_url": f"https://youtu.be/{video_id}",
        })


def finalize_published_item(
    item: QueueItem,
    output: str,
    *,
    ledger_path: Path | None = None,
    worker_id: int | str | None = None,
    position: int | None = None,
    total: int | None = None,
    batch_key: str | None = None,
    auto_state_path: Path | None = None,
) -> bool:
    """Verify a successful publish and persist its final ledger state.

    Both the legacy full-pipeline worker and the render/upload consumer use this
    single completion path.  A voiceover producer must never call it: audio is
    not a published video yet.
    """
    cli = _cli()
    queue = cli.load_queue(batch_key=batch_key)
    done = cli.done_slugs(ledger_path)
    failed = cli.failed_slugs(ledger_path)
    position = position if position is not None else sum(1 for q in queue if q.slug in done or q.slug in failed) + 1
    total = total if total is not None else len(queue)
    video_id = cli.extract_claimed_video_id(output)
    if video_id is None:
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error="missing youtube_id")
        cli.emit_warning(
            f"Video '{item.slug}' chạy XONG (exit 0) nhưng không tìm thấy youtu.be/<id> "
            "trong stdout để xác minh — cần Claude kiểm tra log thủ công."
        )
        cli.update_ledger(item.slug, "", "publish", "error", "Pipeline exit 0 nhưng không có youtube_id trong stdout", ledger_path=ledger_path)
        return False

    try:
        verified = cli.verify_youtube_video(video_id)
    except ReauthRequiredError as exc:
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error=str(exc))
        cli.update_ledger(item.slug, "", "publish", "error", f"Không xác minh được qua API -- cần `ytb auth`: {exc}", ledger_path=ledger_path)
        return False
    except Exception as exc:  # noqa: BLE001 -- API verify cannot kill a consumer
        message = (
            f"Video '{item.slug}' đã upload https://youtu.be/{video_id} nhưng không xác minh được qua YouTube API: {exc}. "
            "Bỏ qua để worker chạy video kế tiếp; cần kiểm tra lại bằng `ytb batch verify` trước khi retry video này."
        )
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error=str(exc))
        cli.emit_warning(message)
        cli.update_ledger(item.slug, "", "publish", "error", f"Đã upload https://youtu.be/{video_id} nhưng verify API lỗi: {exc}", ledger_path=ledger_path)
        return False
    if not verified.get("exists"):
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error="youtube_id not verified")
        cli.emit_warning(f"Video '{item.slug}' — pipeline tự báo ID {video_id} nhưng YouTube API KHÔNG xác nhận video này tồn tại. Cần Claude kiểm tra lại.")
        cli.update_ledger(item.slug, "", "publish", "error", f"youtube_id {video_id} không xác minh được qua API", ledger_path=ledger_path)
        return False

    if cli.check_schedule_drift(verified.get("publish_at"), item.publish_at):
        cli.emit_warning(
            f"Video '{item.slug}' (https://youtu.be/{video_id}) lệch lịch publish: thật={verified.get('publish_at')} "
            f"vs kế hoạch={item.publish_at} trong auto_state.json. KHÔNG tự sửa lịch — cần Claude xác nhận với user."
        )
    try:
        _persist_published_auto_state(
            item, video_id, batch_key=batch_key, auto_state_path=auto_state_path
        )
    except Exception as exc:  # noqa: BLE001 -- verified ledger is the anti-duplicate authority
        # The upload cannot be rolled back.  Losing the done ledger row here
        # would make the next batch run upload a duplicate, whereas auto_state
        # is recoverable observability/resume data.
        cli.emit_warning(
            f"Video '{item.slug}' đã được YouTube API xác minh https://youtu.be/{video_id} "
            f"nhưng không cập nhật được auto_state: {exc}. "
            "Vẫn ghi ledger done|ok để chặn publish trùng; cần reconcile state thủ công."
        )
    cli.update_ledger(
        item.slug, verified.get("title", ""), "done", "ok",
        f"https://youtu.be/{video_id} — verified qua YouTube API (privacy={verified.get('privacy_status')}, publishAt={verified.get('publish_at')}).",
        ledger_path=ledger_path,
    )
    print(f"✓ Video '{item.slug}' done — https://youtu.be/{video_id}")
    cli.notify_progress(
        f"✅ [{position}/{total}] '{item.slug}' đã lên YouTube: https://youtu.be/{video_id}\n"
        f"privacy={verified.get('privacy_status')}, publishAt={verified.get('publish_at')}"
    )
    if worker_id is not None:
        cli.update_worker_state(worker_id, slug=item.slug, stage="done")
    return True


def process_next(
    queue_path: Path | None = None, ledger_path: Path | None = None, *,
    worker_id: int | None = None, through: str = "publish", batch_key: str | None = None,
    completed_render_slugs: set[str] | None = None,
    publish: bool = False,
) -> bool:
    """Chạy đúng 1 video kế tiếp trong queue: pipeline -> verify YouTube -> ledger.

    Trả True nếu đã xử lý 1 video (thành công hoặc thất bại đã ghi nhận),
    False nếu queue đã hết (không còn video pending) — caller dừng vòng lặp.
    """
    cli = _cli()
    with cli._queue_claim_lock:
        queue = cli.load_queue(queue_path, batch_key=batch_key)
        done = cli.done_slugs(ledger_path)
        failed = cli.failed_slugs(ledger_path)
        excluded = done | failed | cli._claimed_slugs | (completed_render_slugs or set())
        pending = [candidate for candidate in queue if candidate.slug not in excluded]
        blocked_shorts = [
            candidate for candidate in pending
            if candidate.long_form_slug and candidate.long_form_slug not in done
        ]
        item = next(
            (
                candidate for candidate in pending
                if not candidate.long_form_slug or candidate.long_form_slug in done
            ),
            None,
        )
        if item is None:
            if blocked_shorts:
                destinations = ", ".join(
                    f"{candidate.slug}→{candidate.long_form_slug}"
                    for candidate in blocked_shorts
                )
                print(f"⏸ Short đang chờ Long hoàn tất publish/API verify: {destinations}")
                return False
            print("✓ Queue đã hết — không còn video pending.")
            return False
        cli._claimed_slugs.add(item.slug)

    try:
        preflight = cli.preflight_script(cli.ROOT / "scripts" / f"{item.slug}.json")
        if not preflight.passed:
            detail = "; ".join(f"[{failure.code}] {failure.message}" for failure in preflight.failures)
            cli.update_ledger(item.slug, "", "preflight", "error", detail, ledger_path=ledger_path)
            if worker_id is not None:
                cli.update_worker_state(worker_id, slug=item.slug, stage="preflight-error", last_error=detail[-500:])
            return True
        if worker_id is not None:
            cli.update_worker_state(worker_id, slug=item.slug, stage="starting-voiceover")
        position = sum(1 for q in queue if q.slug in done or q.slug in failed) + 1
        print(f"▶ Chạy video '{item.slug}' (day {item.day}, publish_at={item.publish_at})")
        cli.notify_progress(
            f"🎬 [{position}/{len(queue)}] Bắt đầu '{item.slug}' (publish_at={item.publish_at})"
        )
        ok, output = cli.run_with_retry(
            item, ledger_path=ledger_path, worker_id=worker_id,
            run_fn=lambda queued, **kwargs: cli.run_pipeline_once(
                queued, through=through, publish=publish, **kwargs
            ),
        )

        if cli._stop_requested:
            # run_pipeline_once đã ghi ledger status "stopped" cho slug này rồi —
            # không ghi đè thành "error", chỉ báo caller (cmd_run) dừng vòng lặp.
            return False

        if not ok:
            if worker_id is not None:
                cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error=output[-500:])
            failed_stage = cli.last_stage_for_slug(item.slug, ledger_path).removeprefix("running-") or "voiceover"
            cli.update_ledger(
                item.slug, "", failed_stage, "error",
                "Tự động: thất bại, xem assets/batch_cli_warnings.log",
                ledger_path=ledger_path,
            )
            return True

        if through == "render" or not publish:
            if completed_render_slugs is not None:
                completed_render_slugs.add(item.slug)
            cli.update_ledger(
                item.slug, "", "render" if through == "render" else "publish-prep", "ok",
                "Batch dry-run: render/publish-prep completed; uploaded=false.",
                ledger_path=ledger_path,
            )
            if worker_id is not None:
                cli.update_worker_state(worker_id, slug=item.slug, stage="done")
            return True

        finalize_published_item(
            item, output, ledger_path=ledger_path, worker_id=worker_id,
            position=position, total=len(queue), batch_key=batch_key,
            auto_state_path=queue_path,
        )
        return True
    finally:
        with cli._queue_claim_lock:
            cli._claimed_slugs.discard(item.slug)
