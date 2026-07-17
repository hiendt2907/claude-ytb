"""Queue/ledger operations cho batch_cli — đọc queue từ auto_state.json, đọc/ghi
data/ledger.md, cảnh báo Telegram + log.

Lưu ý quan trọng: các hằng số đường dẫn (AUTO_STATE_PATH, LEDGER_PATH, ...) định
nghĩa ở đây là nguồn gốc, nhưng test patch chúng qua `batch_cli.<TÊN>` (vd.
`monkeypatch.setattr(cli, "LEDGER_PATH", ...)`). Để patch đó có hiệu lực dù hàm
nằm ở module nào, mọi hàm đọc hằng số theo path mutable (LEDGER_PATH/
AUTO_STATE_PATH/WARN_LOG_PATH/PID_PATH/ROOT) phải đọc qua `_cli()` (module
batch_cli đã import đầy đủ) tại THỜI ĐIỂM GỌI, không đọc biến module-level tĩnh
của riêng file này.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..notify import telegram
from .state_io import locked_append_text

ROOT = Path(__file__).resolve().parents[3]
AUTO_STATE_PATH = ROOT / "assets" / "auto_state.json"
LEDGER_PATH = ROOT / "data" / "ledger.md"
WARN_LOG_PATH = ROOT / "assets" / "batch_cli_warnings.log"
PIPELINE_LOG_DIR = ROOT / "assets" / "batch_logs"
PID_PATH = ROOT / "assets" / "batch_cli.pid"


def _cli():
    """Module batch_cli — import trễ (tránh circular import lúc load), dùng để
    đọc giá trị HẰNG SỐ ĐÃ-CÓ-THỂ-BỊ-PATCH (xem docstring module)."""
    from . import batch_cli

    return batch_cli


@dataclass(frozen=True)
class QueueItem:
    day: int
    slug: str
    publish_at: str
    shorts_status: str
    orientation: str = "landscape"
    series: str = ""
    content_pillar: str = ""
    core_mechanism: str = ""
    audience_problem: str = ""
    long_form_slug: str = ""
    playlist: str = ""
    cta_target: str = ""
    dry_run: bool = False


def load_queue(auto_state_path: Path | None = None, batch_key: str | None = None) -> list[QueueItem]:
    """Đọc queue (đã sort theo day) từ batch mới nhất trong auto_state.json."""
    auto_state_path = auto_state_path if auto_state_path is not None else _cli().AUTO_STATE_PATH
    data = json.loads(Path(auto_state_path).read_text(encoding="utf-8"))
    if batch_key is None:
        batch_keys = [k for k in data if k.startswith("shorts_funnel_batch_")]
        if not batch_keys:
            raise KeyError("Không tìm thấy key shorts_funnel_batch_* nào trong auto_state.json")
        batch_key = sorted(batch_keys)[-1]
    batch = data[batch_key]
    videos = list(batch.get("long_videos", [])) + list(batch.get("short_videos", []))
    items = [
        QueueItem(
            int(v["day"]),
            v["slug"],
            v.get("publish_at", ""),
            v.get("shorts_status", v.get("status", "queued")),
            v.get("orientation", "landscape"),
            v.get("series", ""),
            v.get("content_pillar", ""),
            v.get("core_mechanism", ""),
            v.get("audience_problem", ""),
            v.get("long_form_slug", ""),
            v.get("playlist", ""),
            v.get("cta_target", ""),
            bool(v.get("dry_run", False)),
        )
        for v in videos
    ]
    return sorted(items, key=lambda i: i.day)


def done_slugs(ledger_path: Path | None = None) -> set[str]:
    """Lấy tập slug đã `stage=done` + `status=ok` trong ledger — bỏ qua khi chọn video kế tiếp.

    Dùng ROW CUỐI CÙNG của mỗi slug để quyết định trạng thái (không phải ANY row).
    Nhờ đó `ytb batch reset` chỉ cần append thêm 1 row stage=reset để "un-done" 1 slug.
    """
    ledger_path = ledger_path if ledger_path is not None else _cli().LEDGER_PATH
    text = Path(ledger_path).read_text(encoding="utf-8")
    slug_last: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        slug, stage, status = cols[1], cols[3], cols[4]
        slug_last[slug] = (stage, status)
    return {s for s, (stage, status) in slug_last.items() if stage == "done" and status == "ok"}


def failed_slugs(ledger_path: Path | None = None) -> set[str]:
    """Lấy slug có dòng cuối là lỗi terminal để batch loop bỏ qua.

    Lỗi vẫn có thể chạy lại có chủ đích qua `ytb batch retry <slug>` hoặc sau
    `ytb batch reset <slug>`. Không để `--loop` lặp vô hạn cùng một script hỏng.
    """
    ledger_path = ledger_path if ledger_path is not None else _cli().LEDGER_PATH
    text = Path(ledger_path).read_text(encoding="utf-8")
    slug_last: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        slug, stage, status = cols[1], cols[3], cols[4]
        slug_last[slug] = (stage, status)
    return {s for s, (_stage, status) in slug_last.items() if status == "error"}


def next_pending(queue: list[QueueItem], done: set[str]) -> QueueItem | None:
    """Video đầu tiên trong queue (theo day) chưa `done` — None nếu hết việc."""
    for item in queue:
        if item.slug not in done:
            return item
    return None


def last_stage_for_slug(slug: str, ledger_path: Path | None = None) -> str:
    """Stage của dòng ledger MỚI NHẤT ghi cho slug này — "" nếu chưa có dòng nào.

    Dùng để biết video dừng ở khâu nào thật (voiceover/ai-render/publish...) khi
    pipeline lỗi, thay vì đoán/hardcode 1 stage cố định.
    """
    ledger_path = ledger_path if ledger_path is not None else _cli().LEDGER_PATH
    text = Path(ledger_path).read_text(encoding="utf-8")
    stage = ""
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        if cols[1] == slug:
            stage = cols[3]
    return stage


def update_ledger(
    slug: str,
    title: str,
    stage: str,
    status: str,
    note: str,
    ledger_path: Path | None = None,
) -> None:
    """Append 1 dòng mới vào ledger (quy ước: ghi NGAY sau mỗi khâu, atomic, append-only)."""
    ledger_path = ledger_path if ledger_path is not None else _cli().LEDGER_PATH
    today = datetime.now().strftime("%Y-%m-%d")
    line = f"| {today} | {slug} | {title} | {stage} | {status} | {note} |\n"
    locked_append_text(Path(ledger_path), line)


def mark_needs_review(slug: str, reason: str, auto_state_path: Path | None = None) -> None:
    """Persist terminal review state so an unsafe publish is never retried blindly."""
    from .state_io import locked_json_update

    path = auto_state_path if auto_state_path is not None else _cli().AUTO_STATE_PATH
    with locked_json_update(Path(path)) as data:
        for batch in data.values():
            if not isinstance(batch, dict):
                continue
            for key in ("short_videos", "long_videos"):
                for item in batch.get(key, []) or []:
                    if isinstance(item, dict) and item.get("slug") == slug:
                        item.update({"status": "needs_review", "shorts_status": "needs_review", "review_reason": reason})


def emit_warning(message: str, *, log_path: Path | None = None) -> None:
    """Điểm gọi DUY NHẤT cho mọi cảnh báo: luôn ghi log VÀ gửi Telegram cùng lúc.

    Áp dụng cho cả 2 trường hợp người dùng yêu cầu: cảnh báo phát sinh sau khi
    đã retry hết lượt, và cảnh báo cho lỗi không-retry. Không tách 2 đường khác
    nhau để tránh quên 1 trong 2 kênh.
    """
    log_path = log_path if log_path is not None else _cli().WARN_LOG_PATH
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        _cli().telegram.send_message(f"⚠ {message}")
    except Exception as exc:  # noqa: BLE001 — cảnh báo gửi Telegram lỗi vẫn phải có trong log
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] (Gửi Telegram cho cảnh báo trên bị lỗi: {exc})\n")


def notify_progress(message: str) -> None:
    """Bắn Telegram tiến độ batch (best-effort, KHÔNG raise).

    Khác `emit_warning`: đây là tin TIẾN ĐỘ bình thường (video bắt đầu/xong),
    không ghi warning log. Tắt bằng TELEGRAM_PROGRESS=false; thiếu token/lỗi
    mạng chỉ bỏ qua — không bao giờ làm hỏng batch run.
    """
    from ..config.settings import settings

    if not settings.telegram_progress:
        return
    try:
        _cli().telegram.send_message(message)
    except Exception:  # noqa: BLE001 — tiến độ là best-effort, lỗi gửi không được chặn batch
        pass


def current_running_slug() -> str | None:
    """Slug đang được pipeline xử lý ngay lúc này — None nếu không có batch run đang chạy.

    Tìm bằng cách: xác nhận PID còn sống → lấy log file được ghi gần nhất trong
    PIPELINE_LOG_DIR (vì run_pipeline_once đang stream stdout vào đó).
    """
    cli = _cli()
    if not cli.PID_PATH.exists():
        return None
    try:
        pid = int(cli.PID_PATH.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        return None
    if not cli._pid_alive(pid):
        return None
    log_files = list(PIPELINE_LOG_DIR.glob("*.log"))
    if not log_files:
        return None
    return max(log_files, key=lambda p: p.stat().st_mtime).stem


def tail_text(path: Path, n: int = 50) -> str:
    """N dòng cuối của 1 file log — rỗng nếu file chưa tồn tại."""
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-n:])
