"""Định nghĩa argparse cho `ytb batch` — tách khỏi batch_cli.py để file đó gọn
hơn. Help/description/epilog text giữ nguyên 100% so với bản gốc.
"""

from __future__ import annotations

import argparse

TOP_LEVEL_EPILOG = """\
Các lệnh:
  start    Gọi LLM làm phần SÁNG TẠO (ideation + viết kịch bản N video)
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
  benchmark-local  Benchmark local AI stack và ghi JSON report

Quy trình thường dùng:
  ytb batch start -n 5 --type-of-vid long   # local LLM viết 5 kịch bản
  ytb doctor                # kiểm tra môi trường trước (shortcut top-level)
  ytb batch status          # xem còn video nào pending
  ytb batch run             # chạy 1 video, lặp lại lệnh này cho video kế
  ytb batch run --loop      # hoặc chạy hết queue luôn, không cần lặp tay
  ytb batch logs --current  # terminal khác — theo dõi log video đang chạy
  ytb batch ps              # xem slug + thời gian đang chạy
  ytb batch stop            # dừng ngay, an toàn — resume lại sau

`start` là bước duy nhất CẦN LLM (sáng tạo) — mọi lệnh khác chạy thuần CLI,
không phụ thuộc cloud LLM còn hạn mức hay không.

Mọi cảnh báo (lỗi sau khi retry hết lượt, hoặc lỗi không-retry) đều được gửi
Telegram NGAY và ghi vào assets/batch_cli_warnings.log — dùng
`ytb batch logs --warnings` để xem lại và đưa cho Claude fix.
"""


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


def build_parser(*, doc: str | None, cmd_funcs: dict) -> argparse.ArgumentParser:
    """Dựng toàn bộ argparse cho `ytb batch` — `cmd_funcs` map tên lệnh ->
    callback `cmd_*` tương ứng (tiêm từ batch_cli.py để tránh import vòng)."""
    parser = argparse.ArgumentParser(
        prog="ytb batch",
        description=doc,
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = _sub(
        sub, "start",
        help="Sinh phần SÁNG TẠO (ideation + viết N kịch bản)",
        description="Mặc định dùng local LLM provider (Ollama/Qwen) để chọn chủ đề "
        "(chống trùng data/ledger.md), viết kịch bản đầy đủ cho N video vào "
        "scripts/<slug>.json, và đăng ký từng video vào assets/auto_state.json. "
        "Dùng --cloud nếu muốn gọi Claude legacy.\n\n"
        "Luồng legacy chạy 1 phiên `claude -p` (TỐN TOKEN, mất nhiều phút, không có "
        "output real-time) yêu cầu Claude: chọn chủ đề (chống trùng data/ledger.md), "
        "viết kịch bản đầy đủ cho N video vào scripts/<slug>.json, và đăng ký từng "
        "video vào assets/auto_state.json để `ytb batch run --loop` sản xuất tiếp — "
        "KHÔNG render/publish/voiceover trong lệnh này.\n\n"
        "Đây là lệnh DUY NHẤT trong `ytb batch` cần LLM; mọi lệnh khác (run/retry/"
        "status...) chạy thuần CLI, không phụ thuộc cloud LLM còn hạn mức hay không.",
        epilog="Ví dụ:\n"
        "  ytb batch start --num-of-vid 5 --type-of-vid long --type-of-rules auto\n"
        "  ytb batch start -n 3 --type-of-vid short\n"
        "  ytb batch start -n 3 --type-of-vid short --idea \"cơ chế trì hoãn\"\n"
        "  ytb batch start -n 10 --type-of-vid short --idea \"cơ chế xấu hổ\" --clear-ledger\n"
        "  ytb batch start --ask\n"
        "  ytb batch start -n 1 --type-of-vid long --type-of-rules \"chủ đề về trì hoãn\"\n",
    )
    p_start.add_argument("--num-of-vid", "-n", type=int, default=None, help="Số video cần viết kịch bản (hỏi interactive nếu bỏ qua)")
    p_start.add_argument(
        "--type-of-vid", choices=["long", "short"], default="long",
        help="long = video dài ngang 10-30 phút, short = dọc 1-2 phút (mặc định long)",
    )
    p_start.add_argument(
        "--type-of-rules", default="auto",
        help="'auto' = LLM tự chọn chủ đề theo ngách kênh; hoặc 1 chuỗi mô tả "
        "chủ đề/định hướng cụ thể (mặc định auto)",
    )
    p_start.add_argument(
        "--idea",
        dest="type_of_rules",
        help="Alias dễ nhớ của --type-of-rules: ý tưởng/chủ đề/định hướng muốn đưa cho LLM",
    )
    p_start.add_argument(
        "--ask",
        action="store_true",
        default=False,
        help="Luôn hỏi tương tác số video, loại video, và ý tưởng trước khi chạy",
    )
    p_start.add_argument(
        "--clear-ledger",
        action="store_true",
        default=False,
        help="Backup rồi reset data/ledger.md trước khi sinh ý tưởng mới; dùng khi muốn batch bám sát idea mới",
    )
    p_start.add_argument(
        "--resume", action="store_true", default=False,
        help="Tiếp tục batch bị dừng: đếm script đã có, chỉ yêu cầu LLM viết thêm phần còn thiếu",
    )
    p_start.add_argument(
        "--local", action="store_true", default=False,
        help="Explicit dùng local LLM provider cho ideation; đây là mặc định, thêm để tương thích acceptance command",
    )
    p_start.add_argument(
        "--cloud", action="store_true", default=False,
        help="Opt-in dùng Claude CLI legacy cho ideation; mặc định dùng local LLM provider",
    )
    p_start.set_defaults(func=cmd_funcs["start"])

    _sub(
        sub, "status",
        help="Xem video nào done/pending trong queue",
        description="In từng video trong queue (assets/auto_state.json) kèm trạng thái "
        "done/pending — done = đã có dòng `stage=done, status=ok` trong data/ledger.md.",
        epilog="Ví dụ:\n  ytb batch status\n",
    ).set_defaults(func=cmd_funcs["status"])

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
    p_run.set_defaults(func=cmd_funcs["run"])

    p_verify = _sub(
        sub, "verify",
        help="Xác minh 1 youtube_id có thật qua API (không tin stdout)",
        description="Gọi YouTube Data API videos().list() để lấy trạng thái THẬT của 1 "
        "video (title, privacyStatus, publishAt). Dùng khi nghi ngờ pipeline tự báo sai ID "
        "trong stdout (đã từng gặp thật trong batch này).",
        epilog="Ví dụ:\n  ytb batch verify b917RPp2o7o\n",
    )
    p_verify.add_argument("youtube_id", help="ID video trên YouTube (phần sau youtu.be/)")
    p_verify.set_defaults(func=cmd_funcs["verify"])

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
    p_retry.set_defaults(func=cmd_funcs["retry"])

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
    p_logs.set_defaults(func=cmd_funcs["logs"])

    p_ledger = _sub(
        sub, "ledger",
        help="Xem nhanh N dòng cuối của data/ledger.md",
        description="In N dòng cuối của data/ledger.md (mặc định 20) — tiện hơn `tail` tay "
        "vì luôn đúng đường dẫn, dùng để kiểm tra nhanh video vừa publish đã ghi ledger "
        "đúng chưa.",
        epilog="Ví dụ:\n  ytb batch ledger\n  ytb batch ledger --tail 50\n",
    )
    p_ledger.add_argument("--tail", type=int, default=20, help="Số dòng cuối (mặc định 20)")
    p_ledger.set_defaults(func=cmd_funcs["ledger"])

    _sub(
        sub, "queue",
        help="In toàn bộ queue dạng JSON (cho script/jq)",
        description="In toàn bộ queue (day, slug, publish_at, status done/pending) dạng "
        "JSON ra stdout — để pipe qua `jq` hoặc script khác, khác với `status` (chỉ in "
        "người-đọc-được).",
        epilog="Ví dụ:\n"
        "  ytb batch queue | jq '.[] | select(.status==\"pending\")'\n",
    ).set_defaults(func=cmd_funcs["queue"])

    _sub(
        sub, "ps",
        help="Xem slug + PID + thời gian của tiến trình đang chạy",
        description="In tên slug, PID, và thời gian đã chạy của `ytb batch run`/`retry` "
        "hiện tại — tiện khi nghe fan laptop chạy mạnh hoặc nhận Telegram notification "
        "mà không nhớ đang render video nào.",
        epilog="Ví dụ:\n  ytb batch ps\n",
    ).set_defaults(func=cmd_funcs["ps"])

    p_reset = _sub(
        sub, "reset",
        help="Đưa 1 slug đã done về pending (chạy lại từ đầu)",
        description="Đánh dấu 1 slug đã `done` thành pending bằng cách append 1 dòng "
        "stage=reset vào ledger — `run` sẽ nhặt lại ở lượt kế tiếp. Dùng khi muốn "
        "render lại 1 video đã upload (vd thumbnail sai, audio lỗi) mà không xoá khỏi queue.",
        epilog="Ví dụ:\n  ytb batch reset ne-mat-mat-vi-sao-mat-100k-dau-hon-niem-vui-duoc-100k\n",
    )
    p_reset.add_argument("slug", help="Slug cần reset về pending")
    p_reset.set_defaults(func=cmd_funcs["reset"])

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
    p_cancel.set_defaults(func=cmd_funcs["cancel"])

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
    ).set_defaults(func=cmd_funcs["stop"])

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
    p_doctor.add_argument(
        "--local", action="store_true",
        help="Kiểm tra local-first AI stack: Ollama, ComfyUI/Flux, TTS local, Wan/LTX, ffmpeg",
    )
    p_doctor.set_defaults(func=cmd_funcs["doctor"])

    _sub(
        sub, "auth",
        help="Đăng nhập lại OAuth (mở browser) cho YouTube + Drive",
        description="Mở browser đăng nhập lại tương tác cho cả 2 token (YouTube brand "
        "channel + Drive cá nhân) và lưu vào secrets/. Chạy TAY khi `ytb doctor` báo token "
        "hết hạn/bị revoke, hoặc lần đầu sau khi đổi publishing status OAuth client trên "
        "Google Cloud Console.",
        epilog="Ví dụ:\n  ytb batch auth\n",
    ).set_defaults(func=cmd_funcs["auth"])

    p_benchmark = _sub(
        sub, "benchmark-local",
        help="Benchmark local AI stack và ghi JSON report",
        description="Chạy benchmark lặp lại được cho local-first stack: một lượt "
        "LLM, một đoạn TTS tiếng Việt, một ảnh Flux, và một clip video local 5s "
        "(nếu provider khả dụng). Mỗi mục lỗi độc lập và được ghi vào report thay "
        "vì làm hỏng toàn bộ benchmark.",
        epilog="Ví dụ:\n  ytb batch benchmark-local\n"
        "  ytb batch benchmark-local --output assets/benchmarks/m4-local.json\n",
    )
    p_benchmark.add_argument(
        "--output",
        default="assets/benchmarks/local_benchmark.json",
        help="Đường dẫn JSON report benchmark (mặc định assets/benchmarks/local_benchmark.json)",
    )
    p_benchmark.set_defaults(func=cmd_funcs["benchmark-local"])

    return parser
