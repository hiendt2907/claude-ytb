"""CLI gọi tay để sản xuất tiếp batch sau khi kịch bản đã viết xong — không cần Claude.

Mô phỏng lại đúng việc Claude làm tay trong session: đọc queue từ
assets/auto_state.json, bỏ qua slug đã done trong data/ledger.md, chạy
pipeline với env đúng (đặc biệt TELEGRAM_APPROVAL=false để khỏi đụng listener
daemon -> lỗi 409), tự retry lỗi tạm thời, xác minh video thật qua YouTube
Data API (không tin stdout), và bắn MỌI cảnh báo về Telegram + ghi log để
đưa cho Claude fix sau.

Gọi tắt qua `ytb batch <lệnh>` (xem bin/ytb) hoặc:
    python -m ytb_pipeline.orchestrator.batch_cli <lệnh>

Xem `ytb batch <lệnh> --help` để biết chi tiết + ví dụ từng lệnh.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..claude_cli import build_claude_cmd
from ..config.settings import settings
from ..notify import telegram
from ..publish.youtube_auth import DRIVE_SCOPES, YOUTUBE_SCOPES, ReauthRequiredError

TOP_LEVEL_EPILOG = """\
Các lệnh:
  start    Gọi Claude làm phần SÁNG TẠO (ideation + viết kịch bản N video)
  status   Xem video nào done/pending trong queue
  run      Chạy video kế tiếp (mặc định 1 video, --loop để chạy hết queue)
  retry    Chạy lại tay 1 slug cụ thể (vd sau khi đã sửa lỗi)
  verify   Xác minh 1 youtube_id có thật trên YouTube, không tin stdout
  logs     Xem log của 1 video / --warnings / --current (video đang chạy)
  ledger   Xem nhanh N dòng cuối của data/ledger.md
  queue    In toàn bộ queue dạng JSON (để script/jq xử lý tiếp)
  ps       Xem slug + PID + thời gian của tiến trình đang chạy
  reset    Đưa 1 slug đã done về pending (chạy lại từ đầu)
  cancel   Huỷ 1 slug khỏi queue vĩnh viễn (không sản xuất nữa)
  stop     Dừng GRACEFUL `run`/`retry` đang chạy — resume đúng video đó sau
  doctor   Kiểm tra môi trường trước khi chạy batch (config, token, script)
  auth     Đăng nhập lại OAuth (mở browser) cho YouTube + Drive

Quy trình thường dùng:
  ytb batch start -n 5 --type-of-vid long   # Claude viết 5 kịch bản (tốn token)
  ytb doctor                # kiểm tra môi trường trước (shortcut top-level)
  ytb batch status          # xem còn video nào pending
  ytb batch run             # chạy 1 video, lặp lại lệnh này cho video kế
  ytb batch run --loop      # hoặc chạy hết queue luôn, không cần lặp tay
  ytb batch logs --current  # terminal khác — theo dõi log video đang chạy
  ytb batch ps              # xem slug + thời gian đang chạy
  ytb batch stop            # dừng ngay, an toàn — resume lại sau

`start` là bước duy nhất CẦN Claude (sáng tạo) — mọi lệnh khác chạy thuần CLI,
không tốn token, không phụ thuộc Claude còn hạn mức hay không.

Mọi cảnh báo (lỗi sau khi retry hết lượt, hoặc lỗi không-retry) đều được gửi
Telegram NGAY và ghi vào assets/batch_cli_warnings.log — dùng
`ytb batch logs --warnings` để xem lại và đưa cho Claude fix.
"""

ROOT = Path(__file__).resolve().parents[3]
AUTO_STATE_PATH = ROOT / "assets" / "auto_state.json"
LEDGER_PATH = ROOT / "data" / "ledger.md"
WARN_LOG_PATH = ROOT / "assets" / "batch_cli_warnings.log"
PIPELINE_LOG_DIR = ROOT / "assets" / "batch_logs"
PID_PATH = ROOT / "assets" / "batch_cli.pid"

# Subcommand nào ghi pid file (để `stop` tìm đúng process cần SIGTERM) — chỉ
# những lệnh chạy lâu, lồng subprocess pipeline con (run/retry). `start` (gọi
# Claude) và các lệnh đọc-only khác không cần.
PID_TRACKED_COMMANDS = {"run", "retry"}

# Tiến trình `python -m ytb_pipeline <script>` đang chạy lồng bên trong (nếu
# có) — signal handler forward SIGTERM xuống đây để không bỏ orphan, và cờ
# báo cho run_with_retry/process_next/cmd_run biết là dừng CHỦ ĐỘNG (không
# phải lỗi) để không retry/không ghi cảnh báo trùng.
_current_proc: subprocess.Popen | None = None
_stop_requested = False

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


def detect_stage_marker(line: str) -> str | None:
    """Khớp 1 dòng stdout của pipeline con với marker bắt-đầu-khâu — None nếu không khớp."""
    for pattern, stage in STAGE_START_MARKERS:
        if pattern.search(line):
            return stage
    return None


def _handle_stop_signal(signum, frame) -> None:  # noqa: ANN001 — chữ ký bắt buộc của signal.signal
    """Bắt SIGTERM/SIGINT: đặt cờ dừng + kill NGAY tiến trình pipeline con (nếu có).

    Không có bước này, tiến trình con `python -m ytb_pipeline <script>` (render/
    upload) sẽ thành orphan khi process cha bị kill — đã xảy ra thật với `/stop`
    qua Telegram (proc.terminate() ở listener.py chỉ kill được batch_cli.py,
    không propagate xuống cây con vì không cùng process group).
    """
    global _stop_requested
    _stop_requested = True
    if _current_proc is not None and _current_proc.poll() is None:
        # killpg (không phải .terminate()) — `_current_proc` được spawn với
        # start_new_session=True nên là leader của 1 process group riêng, gồm cả
        # cháu sâu hơn 1 cấp như worker F5-TTS (.venv-tts/bin/python
        # scripts/f5_batch_worker.py) và ffmpeg do compose_ai.py gọi. .terminate()
        # chỉ kill đúng PID này, để lại các tiến trình cháu chạy mồ côi.
        try:
            os.killpg(_current_proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def check_not_already_running() -> None:
    """Chặn `run`/`retry` chồng lên 1 tiến trình cũ chưa thoát -- 2 process đua nhau
    ghi cùng file audio/render gây hỏng dữ liệu (đã xảy ra thật, xem ledger 23/06)."""
    if not PID_PATH.exists():
        return
    old_pid_text = PID_PATH.read_text(encoding="utf-8").strip()
    if old_pid_text and _pid_alive(int(old_pid_text)):
        raise SystemExit(
            f"✗ Đã có `ytb batch run`/`retry` đang chạy (PID {old_pid_text}). "
            "Dùng `ytb batch stop` để dừng graceful trước, hoặc đợi nó xong."
        )
    PID_PATH.unlink(missing_ok=True)  # pid file cũ, tiến trình đã chết -- dọn rồi chạy tiếp


def write_pid_file() -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file() -> None:
    """Chỉ xoá pid file nếu nó vẫn còn ghi đúng PID của tiến trình hiện tại --
    nếu không (1 tiến trình khác đã ghi đè đè lên), giữ nguyên, tránh xoá nhầm
    "dấu vết đang chạy" của tiến trình kia (xem check_not_already_running)."""
    try:
        if PID_PATH.read_text(encoding="utf-8").strip() != str(os.getpid()):
            return
    except FileNotFoundError:
        return
    PID_PATH.unlink(missing_ok=True)


@dataclass(frozen=True)
class QueueItem:
    day: int
    slug: str
    publish_at: str
    shorts_status: str


def load_queue(auto_state_path: Path | None = None, batch_key: str | None = None) -> list[QueueItem]:
    """Đọc queue (đã sort theo day) từ batch mới nhất trong auto_state.json."""
    auto_state_path = auto_state_path if auto_state_path is not None else AUTO_STATE_PATH
    data = json.loads(Path(auto_state_path).read_text(encoding="utf-8"))
    if batch_key is None:
        batch_keys = [k for k in data if k.startswith("shorts_funnel_batch_")]
        if not batch_keys:
            raise KeyError("Không tìm thấy key shorts_funnel_batch_* nào trong auto_state.json")
        batch_key = sorted(batch_keys)[-1]
    long_videos = data[batch_key]["long_videos"]
    items = [QueueItem(v["day"], v["slug"], v["publish_at"], v["shorts_status"]) for v in long_videos]
    return sorted(items, key=lambda i: i.day)


def done_slugs(ledger_path: Path | None = None) -> set[str]:
    """Lấy tập slug đã `stage=done` + `status=ok` trong ledger — bỏ qua khi chọn video kế tiếp.

    Dùng ROW CUỐI CÙNG của mỗi slug để quyết định trạng thái (không phải ANY row).
    Nhờ đó `ytb batch reset` chỉ cần append thêm 1 row stage=reset để "un-done" 1 slug.
    """
    ledger_path = ledger_path if ledger_path is not None else LEDGER_PATH
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
    ledger_path = ledger_path if ledger_path is not None else LEDGER_PATH
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


def emit_warning(message: str, *, log_path: Path | None = None) -> None:
    """Điểm gọi DUY NHẤT cho mọi cảnh báo: luôn ghi log VÀ gửi Telegram cùng lúc.

    Áp dụng cho cả 2 trường hợp người dùng yêu cầu: cảnh báo phát sinh sau khi
    đã retry hết lượt, và cảnh báo cho lỗi không-retry. Không tách 2 đường khác
    nhau để tránh quên 1 trong 2 kênh.
    """
    log_path = log_path if log_path is not None else WARN_LOG_PATH
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        telegram.send_message(f"⚠ {message}")
    except Exception as exc:  # noqa: BLE001 — cảnh báo gửi Telegram lỗi vẫn phải có trong log
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] (Gửi Telegram cho cảnh báo trên bị lỗi: {exc})\n")


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


def current_running_slug() -> str | None:
    """Slug đang được pipeline xử lý ngay lúc này — None nếu không có batch run đang chạy.

    Tìm bằng cách: xác nhận PID còn sống → lấy log file được ghi gần nhất trong
    PIPELINE_LOG_DIR (vì run_pipeline_once đang stream stdout vào đó).
    """
    if not PID_PATH.exists():
        return None
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        return None
    if not _pid_alive(pid):
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
    script_path = script_path or (ROOT / "scripts" / f"{item.slug}.json")
    log_path = log_path_for(item.slug)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    update_ledger(item.slug, "", "running-ideation", "running", "Tự động: bắt đầu chạy pipeline", ledger_path=ledger_path)

    global _current_proc
    proc = subprocess.Popen(
        [sys.executable, "-m", "ytb_pipeline", str(script_path)],
        cwd=ROOT,
        env=build_env(item),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,  # leader process group riêng -> killpg dọn sạch cả cây con (F5 worker, ffmpeg)
    )
    _current_proc = proc
    lines: list[str] = []
    last_stage = "running-ideation"
    try:
        with log_path.open("w", encoding="utf-8", buffering=1) as f:
            for line in proc.stdout:  # type: ignore[union-attr]
                print(line, end="")
                f.write(line)
                lines.append(line)
                stage = detect_stage_marker(line)
                if stage and stage != last_stage:
                    update_ledger(item.slug, "", stage, "running", "Tự động: đang chạy", ledger_path=ledger_path)
                    last_stage = stage
        proc.wait()
    finally:
        _current_proc = None

    if _stop_requested:
        update_ledger(
            item.slug, "", last_stage, "stopped",
            "Dừng graceful theo yêu cầu user (ytb batch stop) — chạy lại run/retry sẽ tự tiếp tục đúng video này.",
            ledger_path=ledger_path,
        )
    return subprocess.CompletedProcess(args=proc.args, returncode=proc.returncode, stdout="".join(lines), stderr="")


def run_with_retry(
    item: QueueItem,
    backoff: list[int] = RETRY_BACKOFF_SEC,
    sleep_fn=time.sleep,
    run_fn=run_pipeline_once,
    ledger_path: Path | None = None,
) -> tuple[bool, str]:
    """Chạy pipeline cho 1 video; tự retry nếu lỗi tạm thời, tối đa len(backoff) lần.

    Lỗi không tạm thời -> dừng ngay, không retry. Cả 2 trường hợp thất bại cuối
    cùng đều gọi emit_warning() (Telegram + log) trước khi trả về False.

    Dừng GRACEFUL (`ytb batch stop`, cờ `_stop_requested`) không tính là lỗi:
    trả về False ngay, KHÔNG retry, KHÔNG emit_warning — `run_pipeline_once`
    đã ghi ledger status "stopped" rồi, không cần cảnh báo thêm.
    """
    attempt = 0
    last_output = ""
    while True:
        result = run_fn(item, ledger_path=ledger_path)
        last_output = (result.stdout or "") + (result.stderr or "")
        if _stop_requested:
            return False, last_output
        if result.returncode == 0:
            return True, last_output

        if not is_transient_error(last_output):
            emit_warning(
                f"Video '{item.slug}' lỗi KHÔNG retry (không phải lỗi tạm thời) — "
                f"bỏ qua, chuyển video kế tiếp. Đuôi log:\n{last_output[-1500:]}"
            )
            return False, last_output

        if attempt >= len(backoff):
            emit_warning(
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


def update_ledger(
    slug: str,
    title: str,
    stage: str,
    status: str,
    note: str,
    ledger_path: Path | None = None,
) -> None:
    """Append 1 dòng mới vào ledger (quy ước: ghi NGAY sau mỗi khâu, atomic, append-only)."""
    ledger_path = ledger_path if ledger_path is not None else LEDGER_PATH
    today = datetime.now().strftime("%Y-%m-%d")
    line = f"| {today} | {slug} | {title} | {stage} | {status} | {note} |\n"
    with Path(ledger_path).open("a", encoding="utf-8") as f:
        f.write(line)


def process_next(queue_path: Path | None = None, ledger_path: Path | None = None) -> bool:
    """Chạy đúng 1 video kế tiếp trong queue: pipeline -> verify YouTube -> ledger.

    Trả True nếu đã xử lý 1 video (thành công hoặc thất bại đã ghi nhận),
    False nếu queue đã hết (không còn video pending) — caller dừng vòng lặp.
    """
    queue = load_queue(queue_path)
    item = next_pending(queue, done_slugs(ledger_path))
    if item is None:
        print("✓ Queue đã hết — không còn video pending.")
        return False

    print(f"▶ Chạy video '{item.slug}' (day {item.day}, publish_at={item.publish_at})")
    ok, output = run_with_retry(item, ledger_path=ledger_path)

    if _stop_requested:
        # run_pipeline_once đã ghi ledger status "stopped" cho slug này rồi —
        # không ghi đè thành "error", chỉ báo caller (cmd_run) dừng vòng lặp.
        return False

    if not ok:
        failed_stage = last_stage_for_slug(item.slug, ledger_path).removeprefix("running-") or "ideation"
        update_ledger(
            item.slug, "", failed_stage, "error",
            "Tự động: thất bại, xem assets/batch_cli_warnings.log",
            ledger_path=ledger_path,
        )
        return True

    video_id = extract_claimed_video_id(output)
    if video_id is None:
        emit_warning(
            f"Video '{item.slug}' chạy XONG (exit 0) nhưng không tìm thấy youtu.be/<id> "
            f"trong stdout để xác minh — cần Claude kiểm tra log thủ công."
        )
        update_ledger(
            item.slug, "", "publish", "error",
            "Pipeline exit 0 nhưng không có youtube_id trong stdout",
            ledger_path=ledger_path,
        )
        return True

    try:
        verified = verify_youtube_video(video_id)
    except ReauthRequiredError as exc:
        # youtube_auth đã tự bắn Telegram cảnh báo -- ở đây chỉ cần ghi ledger +
        # dừng video này lại (không retry vô hạn), để batch tiếp tục slug khác.
        update_ledger(
            item.slug, "", "publish", "error",
            f"Không xác minh được qua API -- cần `ytb auth`: {exc}",
            ledger_path=ledger_path,
        )
        return True
    if not verified.get("exists"):
        emit_warning(
            f"Video '{item.slug}' — pipeline tự báo ID {video_id} nhưng YouTube API "
            f"KHÔNG xác nhận video này tồn tại. Cần Claude kiểm tra lại."
        )
        update_ledger(
            item.slug, "", "publish", "error",
            f"youtube_id {video_id} không xác minh được qua API",
            ledger_path=ledger_path,
        )
        return True

    if check_schedule_drift(verified.get("publish_at"), item.publish_at):
        emit_warning(
            f"Video '{item.slug}' (https://youtu.be/{video_id}) lệch lịch publish: "
            f"thật={verified.get('publish_at')} vs kế hoạch={item.publish_at} trong auto_state.json. "
            f"KHÔNG tự sửa lịch — cần Claude xác nhận với user."
        )

    update_ledger(
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


def _build_start_prompt(num_of_vid: int, type_of_vid: str, type_of_rules: str) -> str:
    """Dựng prompt giao việc SÁNG TẠO (ideation + viết kịch bản) cho Claude.

    Đây là phần KHÔNG mô phỏng được bằng code thường — cần Claude chọn chủ đề
    (chống trùng ledger), viết narration, tự chấm cổng compliance. Sau khi Claude
    viết xong scripts/*.json + đăng ký vào auto_state.json, `ytb batch run --loop`
    mới tiếp quản phần sản xuất máy-móc (không cần Claude nữa).
    """
    vid_label = "Video dài (ngang, 10-30 phút)" if type_of_vid == "long" else "Short (dọc, 1-2 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh hiện tại (đọc memory dự án + ledger để biết ngách)."
        if type_of_rules == "auto"
        else f"Chủ đề/định hướng: {type_of_rules}"
    )
    return (
        f"Làm phần SÁNG TẠO (ideation + viết kịch bản) cho {num_of_vid} video loại "
        f"\"{vid_label}\" — dùng skill youtube-ideation, tuân thủ ĐẦY ĐỦ "
        f".claude/skills/youtube-ideation/video-quality-rules.md (cổng verify mục 0, "
        f"luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done). Mỗi video: viết scripts/<slug>.json đầy đủ kèm "
        "khối compliance.passed=true, RỒI đăng ký 1 item vào assets/auto_state.json "
        "(mảng items, đúng schema slug/topic/orientation/render_provider/dry_run/"
        "publish_at/stage=\"ideation\"/status=\"ok\"/updated) và ghi 1 dòng vào "
        "data/ledger.md.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish — đó là việc của "
        "`ytb batch run --loop` chạy bằng tay sau, không cần Claude. Khi đủ "
        f"{num_of_vid} video đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video)."
    )


def cmd_start(args: argparse.Namespace) -> None:
    prompt = _build_start_prompt(args.num_of_vid, args.type_of_vid, args.type_of_rules)
    cmd = build_claude_cmd(prompt)
    print(f"▶️  Gọi Claude sáng tạo {args.num_of_vid} video ({args.type_of_vid})... "
          f"có thể mất nhiều phút, không có output real-time (claude -p chỉ trả "
          f"kết quả cuối).")
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"✗ Không tìm thấy `{settings.claude_bin}`. Đặt CLAUDE_BIN trong .env.")
        sys.exit(1)
    output = (result.stdout or "").strip()
    if output:
        print(output)
    if result.returncode != 0:
        emit_warning(f"ytb batch start lỗi (code {result.returncode}): {(result.stderr or '')[-500:]}")
        sys.exit(1)
    print("\n✓ Xong phần sáng tạo — chạy `ytb batch status` để xem queue, rồi "
          "`ytb batch run --loop` để sản xuất.")


def cmd_status(args: argparse.Namespace) -> None:
    queue = load_queue()
    done = done_slugs()
    for item in queue:
        mark = "✓ done" if item.slug in done else "… pending"
        print(f"day {item.day:>2}  {mark:<10}  {item.slug}  (publish_at={item.publish_at})")


def cmd_run(args: argparse.Namespace) -> None:
    while True:
        processed = process_next()
        if _stop_requested:
            print(
                "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại "
                "`ytb batch run`/`run --loop` để tiếp tục đúng video đang dở."
            )
            break
        if not processed or not args.loop:
            break


def cmd_verify(args: argparse.Namespace) -> None:
    result = verify_youtube_video(args.youtube_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_retry(args: argparse.Namespace) -> None:
    queue = load_queue()
    item = next((i for i in queue if i.slug == args.slug), None)
    if item is None:
        print(f"Không tìm thấy slug '{args.slug}' trong queue.")
        return
    ok, _output = run_with_retry(item)
    if _stop_requested:
        print(
            "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại lệnh "
            "retry này (hoặc `ytb batch run`) để tiếp tục đúng video."
        )
        return
    print("✓ Thành công" if ok else "✗ Thất bại — xem assets/batch_cli_warnings.log")


def cmd_stop(args: argparse.Namespace) -> None:
    if not PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy (không thấy assets/batch_cli.pid).")
        return
    pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Process {pid} đã không còn chạy (pid file cũ) — dọn pid file.")
        PID_PATH.unlink(missing_ok=True)  # đã xác nhận chết hẳn -- xoá vô điều kiện
        return
    print(
        f"✓ Đã gửi lệnh dừng graceful tới process {pid}. Tiến trình con (render/upload) sẽ bị "
        "kill an toàn ngay, ledger ghi nhận stage hiện tại với status 'stopped'. Chạy lại "
        "`ytb batch run --loop` (hoặc `ytb batch retry <slug>`) để tiếp tục ĐÚNG video này."
    )


def cmd_ps(args: argparse.Namespace) -> None:
    if not PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    if not _pid_alive(pid):
        print(f"Không có tiến trình nào đang chạy (pid file cũ PID {pid} — tiến trình đã chết).")
        PID_PATH.unlink(missing_ok=True)
        return
    elapsed_sec = int((datetime.now() - datetime.fromtimestamp(PID_PATH.stat().st_ctime)).total_seconds())
    elapsed = f"{elapsed_sec // 60}m {elapsed_sec % 60}s"
    slug = current_running_slug()
    if slug:
        print(f"▶ đang chạy: {slug}")
        print(f"  PID: {pid}  |  thời gian: {elapsed}")
        print(f"  xem log: ytb batch logs {slug} -f")
    else:
        print(f"▶ batch đang chạy (PID {pid}, {elapsed}) — chưa có log file (có thể đang ở bước start/khởi tạo).")


def cmd_reset(args: argparse.Namespace) -> None:
    queue = load_queue()
    if not any(i.slug == args.slug for i in queue):
        print(f"✗ '{args.slug}' không có trong queue (auto_state.json) — không thể reset.")
        return
    running = current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước.")
        return
    update_ledger(args.slug, "", "reset", "reset", "Reset thủ công về pending qua `ytb batch reset`")
    print(f"✓ Đã reset '{args.slug}' về pending — sẽ được `ytb batch run` nhặt ở lượt kế tiếp.")


def cmd_cancel(args: argparse.Namespace) -> None:
    running = current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước rồi cancel.")
        return
    data = json.loads(AUTO_STATE_PATH.read_text(encoding="utf-8"))
    batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
    if not batch_keys:
        print("✗ Không tìm thấy batch nào trong auto_state.json.")
        return
    bk = batch_keys[-1]
    videos = data[bk]["long_videos"]
    filtered = [v for v in videos if v["slug"] != args.slug]
    if len(filtered) == len(videos):
        print(f"✗ Không tìm thấy slug '{args.slug}' trong queue (batch {bk}).")
        return
    data[bk]["long_videos"] = filtered
    AUTO_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    update_ledger(args.slug, "", "cancel", "cancelled", "Huỷ thủ công qua `ytb batch cancel`")
    print(f"✓ Đã huỷ '{args.slug}' khỏi queue — ghi ledger (stage=cancel, status=cancelled).")


def cmd_logs(args: argparse.Namespace) -> None:
    if getattr(args, "current", False):
        slug = current_running_slug()
        if not slug:
            print("Không có tiến trình nào đang chạy.")
            return
        args.slug = slug
        args.follow = True
    path = WARN_LOG_PATH if args.warnings else log_path_for(args.slug)
    if args.follow:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        subprocess.run(["tail", "-f", str(path)])
        return
    text = tail_text(path, args.tail)
    print(text or f"(trống — chưa có log tại {path})")


def cmd_ledger(args: argparse.Namespace) -> None:
    print(tail_text(LEDGER_PATH, args.tail))


def cmd_queue(args: argparse.Namespace) -> None:
    queue = load_queue()
    done = done_slugs()
    rows = [
        {
            "day": item.day,
            "slug": item.slug,
            "publish_at": item.publish_at,
            "status": "done" if item.slug in done else "pending",
        }
        for item in queue
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def _check_oauth_token(label: str, token_file: str, scopes: list[str]) -> tuple[str, bool, str]:
    """Thử nạp/refresh token THẬT (không mở browser) -- chỉ vậy mới biết token còn
    sống hay đã bị Google revoke, khác với check `token_path.exists()` cũ (file
    có thể tồn tại nhưng refresh token đã chết)."""
    from ..publish.youtube_auth import _load_or_authorize

    try:
        _load_or_authorize(token_file, scopes, allow_interactive=False)
    except ReauthRequiredError:
        return label, False, "token hết hạn/bị revoke — chạy `ytb auth` để đăng nhập lại"
    except FileNotFoundError as exc:
        return label, False, str(exc)
    return label, True, "hợp lệ"


def _check_recent_published(limit: int = 3) -> tuple[str, bool, str]:
    """Đối chiếu N video `done`/`ok` gần nhất trong ledger với YouTube API thật --
    bắt trường hợp ledger nói "done" nhưng video thực ra không còn/không đúng."""
    text = LEDGER_PATH.read_text(encoding="utf-8")
    recent: list[tuple[str, str]] = []  # (slug, video_id)
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 6 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        slug, stage, status, note = cols[1], cols[3], cols[4], cols[5]
        if stage == "done" and status == "ok":
            video_id = extract_claimed_video_id(note)
            if video_id:
                recent.append((slug, video_id))
    recent = recent[-limit:]
    if not recent:
        return f"Đối chiếu {limit} video done gần nhất", True, "chưa có video done nào để đối chiếu"

    problems = []
    for slug, video_id in recent:
        try:
            verified = verify_youtube_video(video_id)
        except ReauthRequiredError as exc:
            problems.append(f"{slug}: {exc}")
            continue
        if not verified.get("exists"):
            problems.append(f"{slug}: youtu.be/{video_id} không còn tồn tại trên YouTube")

    ok = not problems
    detail = "khớp YouTube API" if ok else "; ".join(problems)
    return f"Đối chiếu {len(recent)} video done gần nhất", ok, detail


def run_doctor_checks() -> list[tuple[str, bool, str]]:
    """Sanity-check môi trường trước khi chạy batch tay — không sửa gì, chỉ báo."""
    checks: list[tuple[str, bool, str]] = []

    queue: list[QueueItem] = []
    done: set[str] = set()
    try:
        queue = load_queue()
        checks.append(("auto_state.json", True, f"{len(queue)} video trong queue"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("auto_state.json", False, str(exc)))

    try:
        done = done_slugs()
        checks.append(("ledger.md", True, f"{len(done)} slug đã done"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("ledger.md", False, str(exc)))

    has_telegram = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    checks.append((
        "Telegram config",
        has_telegram,
        "đã set" if has_telegram else "thiếu TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID trong .env",
    ))

    checks.append(_check_oauth_token("YouTube OAuth token", settings.youtube_token_file, YOUTUBE_SCOPES))
    checks.append(_check_oauth_token("Drive OAuth token", settings.drive_token_file, DRIVE_SCOPES))

    pid_running = PID_PATH.exists() and _pid_alive(int(PID_PATH.read_text(encoding="utf-8").strip()))
    checks.append((
        "Tiến trình batch run/retry",
        True,  # chỉ thông tin, không phải lỗi
        f"đang chạy (PID {PID_PATH.read_text(encoding='utf-8').strip()})" if pid_running else "không có tiến trình nào đang chạy",
    ))

    checks.append(_check_recent_published())

    missing_scripts = [
        item.slug
        for item in queue
        if item.slug not in done and not (ROOT / "scripts" / f"{item.slug}.json").exists()
    ]
    checks.append((
        "Script JSON cho video pending",
        not missing_scripts,
        "đủ" if not missing_scripts else f"thiếu file cho: {', '.join(missing_scripts)}",
    ))

    return checks


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = run_doctor_checks()
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"{mark} {name}: {detail}")
    failed = [(name, detail) for name, ok, detail in checks if not ok]
    if args.notify:
        # --notify dành cho chạy theo lịch (cron/launchd) -- không có ai ngồi đọc
        # stdout, nên bắn Telegram thay. Chạy tay không cần (đỡ spam).
        body = (
            "\n".join(f"✗ {name}: {detail}" for name, detail in failed)
            if failed
            else "tất cả OK"
        )
        telegram.send_message(f"🩺 ytb doctor ({len(failed)} lỗi):\n{body}" if failed else "🩺 ytb doctor: tất cả OK")
    if failed:
        sys.exit(1)


def cmd_auth(args: argparse.Namespace) -> None:
    """Đăng nhập lại tương tác (mở browser) cho cả YouTube + Drive — chạy TAY khi
    `ytb doctor` báo token hết hạn, hoặc sau khi đổi publishing status trên Cloud Console."""
    from ..publish.youtube_auth import get_drive_client, get_youtube_client

    print("▶ Đăng nhập YouTube (brand channel)...")
    get_youtube_client(allow_interactive=True)
    print("✓ YouTube OK.")
    print("▶ Đăng nhập Drive (tài khoản cá nhân)...")
    get_drive_client(allow_interactive=True)
    print("✓ Drive OK.")
    print("\n✓ Token đã lưu — chạy `ytb batch doctor` để xác nhận.")


def _sub(sub, name: str, *, help: str, description: str, epilog: str = ""):
    """Tạo 1 subparser với help (dòng ngắn cho list lệnh) + description/epilog
    chi tiết (hiện khi gõ `ytb batch <lệnh> --help`)."""
    return sub.add_parser(
        name,
        help=help,
        description=description,
        epilog=epilog or None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ytb batch",
        description=__doc__,
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = _sub(
        sub, "start",
        help="Gọi Claude làm phần SÁNG TẠO (ideation + viết N kịch bản)",
        description="Chạy 1 phiên `claude -p` (TỐN TOKEN, mất nhiều phút, không có "
        "output real-time) yêu cầu Claude: chọn chủ đề (chống trùng data/ledger.md), "
        "viết kịch bản đầy đủ cho N video vào scripts/<slug>.json, và đăng ký từng "
        "video vào assets/auto_state.json để `ytb batch run --loop` sản xuất tiếp — "
        "KHÔNG render/publish/voiceover trong lệnh này.\n\n"
        "Đây là lệnh DUY NHẤT trong `ytb batch` cần Claude; mọi lệnh khác (run/retry/"
        "status...) chạy thuần CLI, không phụ thuộc Claude còn hạn mức hay không.",
        epilog="Ví dụ:\n"
        "  ytb batch start --num-of-vid 5 --type-of-vid long --type-of-rules auto\n"
        "  ytb batch start -n 3 --type-of-vid short\n"
        "  ytb batch start -n 1 --type-of-vid long --type-of-rules \"chủ đề về trì hoãn\"\n",
    )
    p_start.add_argument("--num-of-vid", "-n", type=int, required=True, help="Số video cần viết kịch bản")
    p_start.add_argument(
        "--type-of-vid", choices=["long", "short"], default="long",
        help="long = video dài ngang 10-30 phút, short = dọc 1-2 phút (mặc định long)",
    )
    p_start.add_argument(
        "--type-of-rules", default="auto",
        help="'auto' = Claude tự chọn chủ đề theo ngách kênh; hoặc 1 chuỗi mô tả "
        "chủ đề/định hướng cụ thể (mặc định auto)",
    )
    p_start.set_defaults(func=cmd_start)

    _sub(
        sub, "status",
        help="Xem video nào done/pending trong queue",
        description="In từng video trong queue (assets/auto_state.json) kèm trạng thái "
        "done/pending — done = đã có dòng `stage=done, status=ok` trong data/ledger.md.",
        epilog="Ví dụ:\n  ytb batch status\n",
    ).set_defaults(func=cmd_status)

    p_run = _sub(
        sub, "run",
        help="Chạy video kế tiếp (--loop để chạy hết queue)",
        description="Chạy pipeline cho video PENDING đầu tiên trong queue: ideation -> "
        "voiceover -> render -> publish, rồi xác minh video thật qua YouTube Data API "
        "(không tin stdout) và ghi 1 dòng mới vào ledger.\n\n"
        "Tự retry lỗi tạm thời (409 Conflict, mất mạng, timeout) với backoff 30/60/120s. "
        "Lỗi khác (script sai, thiếu file...) bỏ qua ngay, KHÔNG retry. Mọi thất bại cuối "
        "cùng đều bắn cảnh báo Telegram + ghi assets/batch_cli_warnings.log.\n\n"
        "Mặc định chỉ chạy ĐÚNG 1 video rồi dừng (an toàn để theo dõi); dùng --loop nếu "
        "muốn chạy liên tục cho tới khi queue hết video pending.",
        epilog="Ví dụ:\n"
        "  ytb batch run            # chạy 1 video kế tiếp rồi dừng\n"
        "  ytb batch run --loop     # chạy hết các video pending còn lại\n",
    )
    p_run.add_argument("--loop", action="store_true", help="Chạy hết queue, không chỉ 1 video")
    p_run.set_defaults(func=cmd_run)

    p_verify = _sub(
        sub, "verify",
        help="Xác minh 1 youtube_id có thật qua API (không tin stdout)",
        description="Gọi YouTube Data API videos().list() để lấy trạng thái THẬT của 1 "
        "video (title, privacyStatus, publishAt). Dùng khi nghi ngờ pipeline tự báo sai ID "
        "trong stdout (đã từng gặp thật trong batch này).",
        epilog="Ví dụ:\n  ytb batch verify b917RPp2o7o\n",
    )
    p_verify.add_argument("youtube_id", help="ID video trên YouTube (phần sau youtu.be/)")
    p_verify.set_defaults(func=cmd_verify)

    p_retry = _sub(
        sub, "retry",
        help="Chạy lại tay 1 slug cụ thể trong queue",
        description="Chạy lại pipeline cho 1 slug bất kỳ trong queue (không cần là video "
        "pending đầu tiên) — dùng khi đã tự sửa lỗi và muốn retry ngay video đó, không "
        "đợi đến lượt theo thứ tự day. KHÔNG verify YouTube hay ghi ledger (dùng `run` "
        "cho luồng đầy đủ).",
        epilog="Ví dụ:\n"
        "  ytb batch retry thien-kien-xac-nhan-vi-sao-nao-chi-thay-dieu-ban-muon-thay\n",
    )
    p_retry.add_argument("slug", help="Slug video (khớp với auto_state.json)")
    p_retry.set_defaults(func=cmd_retry)

    p_logs = _sub(
        sub, "logs",
        help="Xem log của 1 video, hoặc log cảnh báo (--warnings)",
        description="In N dòng cuối của log pipeline cho 1 slug "
        "(assets/batch_logs/<slug>.log, được ghi LIVE trong lúc `run`/`retry` đang chạy), "
        "hoặc log cảnh báo chung (--warnings, tức assets/batch_cli_warnings.log) — chính "
        "log này nên đưa cho Claude khi cần fix lỗi.",
        epilog="Ví dụ:\n"
        "  ytb batch logs ne-mat-mat-vi-sao-mat-100k-dau-hon-niem-vui-duoc-100k\n"
        "  ytb batch logs ne-mat-mat-... --tail 200\n"
        "  ytb batch logs ne-mat-mat-... --follow   # tail -f trực tiếp, Ctrl+C để thoát\n"
        "  ytb batch logs --warnings                # log cảnh báo (đưa cho Claude fix)\n",
    )
    p_logs.add_argument("slug", nargs="?", help="Slug cần xem log (bỏ qua nếu dùng --warnings hoặc --current)")
    p_logs.add_argument(
        "--warnings", action="store_true",
        help="Xem assets/batch_cli_warnings.log (mọi cảnh báo retry-hết-lượt/không-retry) thay vì log pipeline",
    )
    p_logs.add_argument(
        "--current", action="store_true",
        help="Tail -f log của video đang chạy ngay lúc này (không cần biết slug)",
    )
    p_logs.add_argument("--tail", type=int, default=50, help="Số dòng cuối (mặc định 50)")
    p_logs.add_argument("--follow", "-f", action="store_true", help="Tail -f trực tiếp (Ctrl+C để thoát)")
    p_logs.set_defaults(func=cmd_logs)

    p_ledger = _sub(
        sub, "ledger",
        help="Xem nhanh N dòng cuối của data/ledger.md",
        description="In N dòng cuối của data/ledger.md (mặc định 20) — tiện hơn `tail` tay "
        "vì luôn đúng đường dẫn, dùng để kiểm tra nhanh video vừa publish đã ghi ledger "
        "đúng chưa.",
        epilog="Ví dụ:\n  ytb batch ledger\n  ytb batch ledger --tail 50\n",
    )
    p_ledger.add_argument("--tail", type=int, default=20, help="Số dòng cuối (mặc định 20)")
    p_ledger.set_defaults(func=cmd_ledger)

    _sub(
        sub, "queue",
        help="In toàn bộ queue dạng JSON (cho script/jq)",
        description="In toàn bộ queue (day, slug, publish_at, status done/pending) dạng "
        "JSON ra stdout — để pipe qua `jq` hoặc script khác, khác với `status` (chỉ in "
        "người-đọc-được).",
        epilog="Ví dụ:\n"
        "  ytb batch queue | jq '.[] | select(.status==\"pending\")'\n",
    ).set_defaults(func=cmd_queue)

    _sub(
        sub, "ps",
        help="Xem slug + PID + thời gian của tiến trình đang chạy",
        description="In tên slug, PID, và thời gian đã chạy của `ytb batch run`/`retry` "
        "hiện tại — tiện khi nghe fan laptop chạy mạnh hoặc nhận Telegram notification "
        "mà không nhớ đang render video nào.",
        epilog="Ví dụ:\n  ytb batch ps\n",
    ).set_defaults(func=cmd_ps)

    p_reset = _sub(
        sub, "reset",
        help="Đưa 1 slug đã done về pending (chạy lại từ đầu)",
        description="Đánh dấu 1 slug đã `done` thành pending bằng cách append 1 dòng "
        "stage=reset vào ledger — `run` sẽ nhặt lại ở lượt kế tiếp. Dùng khi muốn "
        "render lại 1 video đã upload (vd thumbnail sai, audio lỗi) mà không xoá khỏi queue.",
        epilog="Ví dụ:\n  ytb batch reset ne-mat-mat-vi-sao-mat-100k-dau-hon-niem-vui-duoc-100k\n",
    )
    p_reset.add_argument("slug", help="Slug cần reset về pending")
    p_reset.set_defaults(func=cmd_reset)

    p_cancel = _sub(
        sub, "cancel",
        help="Huỷ 1 slug khỏi queue vĩnh viễn (không sản xuất nữa)",
        description="Xoá slug khỏi long_videos trong auto_state.json và ghi ledger "
        "stage=cancel. Dùng khi topic đã lỗi thời hoặc không muốn sản xuất nữa — "
        "khác reset (reset giữ trong queue, cancel xoá hẳn). Không thể cancel slug "
        "đang chạy; dùng `stop` trước.",
        epilog="Ví dụ:\n  ytb batch cancel hieu-ung-spotlight-vi-sao-ban-nghi-ai-cung-nhin-minh\n",
    )
    p_cancel.add_argument("slug", help="Slug cần huỷ")
    p_cancel.set_defaults(func=cmd_cancel)

    _sub(
        sub, "stop",
        help="Dừng GRACEFUL `run`/`retry` đang chạy — resume đúng video đó sau",
        description="Gửi SIGTERM tới process `ytb batch run`/`retry` đang chạy (đọc PID từ "
        "assets/batch_cli.pid). Dừng NGAY (kill cả tiến trình con render/upload, không để "
        "orphan), nhưng AN TOÀN cho resume: ledger ghi stage hiện tại với status 'stopped' "
        "(không phải 'done'), nên lệnh `run`/`retry` kế tiếp tự chọn lại ĐÚNG video đang dở, "
        "không nhảy qua video kế hay coi như đã xong.\n\n"
        "Chạy ở 1 terminal/Telegram khác trong lúc `run --loop` đang chạy ở nơi khác.",
        epilog="Ví dụ:\n  ytb batch stop\n",
    ).set_defaults(func=cmd_stop)

    p_doctor = _sub(
        sub, "doctor",
        help="Kiểm tra môi trường trước khi chạy batch",
        description="Kiểm tra (không sửa gì, không mở browser) môi trường: đọc được "
        "auto_state.json/ledger.md, cấu hình Telegram, token OAuth YouTube + Drive còn "
        "REFRESH ĐƯỢC THẬT (không chỉ tồn tại file), tiến trình run/retry hiện tại, đối "
        "chiếu vài video 'done' gần nhất với YouTube API thật, và đủ file scripts/<slug>.json "
        "cho video pending. Trả exit code 1 nếu có mục fail — tiện gọi trước `run --loop` "
        "hoặc đặt lịch (cron/launchd) với `--notify` để tự báo Telegram khi có lỗi.",
        epilog="Ví dụ:\n  ytb batch doctor\n  ytb batch doctor --notify   # dùng trong cron\n"
        "  ytb batch doctor && ytb batch run --loop\n",
    )
    p_doctor.add_argument(
        "--notify", action="store_true",
        help="Bắn kết quả qua Telegram (dùng khi chạy theo lịch, không có ai đọc stdout)",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    _sub(
        sub, "auth",
        help="Đăng nhập lại OAuth (mở browser) cho YouTube + Drive",
        description="Mở browser đăng nhập lại tương tác cho cả 2 token (YouTube brand "
        "channel + Drive cá nhân) và lưu vào secrets/. Chạy TAY khi `ytb doctor` báo token "
        "hết hạn/bị revoke, hoặc lần đầu sau khi đổi publishing status OAuth client trên "
        "Google Cloud Console.",
        epilog="Ví dụ:\n  ytb batch auth\n",
    ).set_defaults(func=cmd_auth)

    args = parser.parse_args(argv)
    if args.command == "logs" and not args.warnings and not args.slug and not getattr(args, "current", False):
        parser.error("logs cần 1 slug, hoặc dùng --warnings / --current")

    try:
        if args.command in PID_TRACKED_COMMANDS:
            check_not_already_running()
            _install_signal_handlers()
            write_pid_file()
            try:
                args.func(args)
            finally:
                remove_pid_file()
        else:
            args.func(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
