"""Health checks cho batch_cli — `ytb batch doctor`.

Xem docstring đầu queue_manager.py về việc đọc hằng số/hàm có thể patch qua
`_cli()` tại thời điểm gọi.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..publish.youtube_auth import DRIVE_SCOPES, YOUTUBE_SCOPES, ReauthRequiredError


def _cli():
    from . import batch_cli

    return batch_cli


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
    cli = _cli()
    text = cli.LEDGER_PATH.read_text(encoding="utf-8")
    recent: list[tuple[str, str]] = []  # (slug, video_id)
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 6 or cols[0] in ("Ngày", "---") or cols[0].startswith("---"):
            continue
        slug, stage, status, note = cols[1], cols[3], cols[4], cols[5]
        if stage == "done" and status == "ok":
            video_id = cli.extract_claimed_video_id(note)
            if video_id:
                recent.append((slug, video_id))
    recent = recent[-limit:]
    if not recent:
        return f"Đối chiếu {limit} video done gần nhất", True, "chưa có video done nào để đối chiếu"

    problems = []
    for slug, video_id in recent:
        try:
            verified = cli.verify_youtube_video(video_id)
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
    cli = _cli()
    checks: list[tuple[str, bool, str]] = []

    queue: list = []
    done: set[str] = set()
    try:
        queue = cli.load_queue()
        checks.append(("auto_state.json", True, f"{len(queue)} video trong queue"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("auto_state.json", False, str(exc)))

    try:
        done = cli.done_slugs()
        checks.append(("ledger.md", True, f"{len(done)} slug đã done"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("ledger.md", False, str(exc)))

    has_telegram = bool(cli.settings.telegram_bot_token and cli.settings.telegram_chat_id)
    checks.append((
        "Telegram config",
        has_telegram,
        "đã set" if has_telegram else "thiếu TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID trong .env",
    ))

    checks.append(cli._check_oauth_token("YouTube OAuth token", cli.settings.youtube_token_file, YOUTUBE_SCOPES))
    checks.append(cli._check_oauth_token("Drive OAuth token", cli.settings.drive_token_file, DRIVE_SCOPES))

    pid_running = cli.PID_PATH.exists() and cli._pid_alive(int(cli.PID_PATH.read_text(encoding="utf-8").strip()))
    checks.append((
        "Tiến trình batch run/retry",
        True,  # chỉ thông tin, không phải lỗi
        f"đang chạy (PID {cli.PID_PATH.read_text(encoding='utf-8').strip()})" if pid_running else "không có tiến trình nào đang chạy",
    ))

    checks.append(cli._check_recent_published())

    missing_scripts = [
        item.slug
        for item in queue
        if item.slug not in done and not (cli.ROOT / "scripts" / f"{item.slug}.json").exists()
    ]
    checks.append((
        "Script JSON cho video pending",
        not missing_scripts,
        "đủ" if not missing_scripts else f"thiếu file cho: {', '.join(missing_scripts)}",
    ))

    return checks


def run_local_doctor_checks() -> list[tuple[str, bool, str]]:
    """Check local-first AI stack readiness with actionable failures."""
    cli = _cli()
    checks: list[tuple[str, bool, str]] = []

    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        checks.append((binary, bool(path), path or f"thiếu `{binary}` — cài bằng `brew install ffmpeg`"))

    try:
        from ..providers.registry import get_image_provider, get_llm_provider, get_video_provider, get_voice_provider

        llm = get_llm_provider(cli.settings.llm_provider)
        checks.append((
            "Ollama local LLM",
            llm.is_available(),
            f"{llm.model_name()} tại {cli.settings.ollama_url}"
            if llm.is_available()
            else f"Ollama không sẵn sàng — chạy `ollama serve` và `ollama pull {cli.settings.ollama_model}`",
        ))

        image = get_image_provider(cli.settings.image_provider)
        image_status = (
            image.availability_status()
            if hasattr(image, "availability_status")
            else (image.is_available(), f"provider={image.name}" if image.is_available() else "provider unavailable")
        )
        image_label = "ComfyUI Flux image" if image.name == "flux" else "Local image provider"
        checks.append((
            image_label,
            image_status[0],
            image_status[1],
        ))

        voice = get_voice_provider(cli.settings.tts_provider)
        checks.append((
            "Vietnamese TTS provider",
            voice.is_available(),
            f"provider={voice.name}"
            if voice.is_available()
            else f"provider `{voice.name}` chưa sẵn sàng — kiểm tra model/command TTS local",
        ))

        video = get_video_provider(cli.settings.video_provider)
        video_status = (
            video.availability_status()
            if hasattr(video, "availability_status")
            else (video.is_available(), f"provider={video.name}" if video.is_available() else "provider unavailable")
        )
        checks.append((
            "Pexels footage provider",
            cli.settings.broll_strategy == "pexels" and video_status[0],
            video_status[1] if cli.settings.broll_strategy == "pexels"
            else "BROLL_STRATEGY phải là pexels để render footage thật",
        ))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Provider registry", False, str(exc)))

    for path in (cli.settings.assets_dir, cli.settings.output_dir, cli.settings.manual_publish_dir):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            checks.append((f"Directory {path}", True, "writable"))
        except OSError as exc:
            checks.append((f"Directory {path}", False, str(exc)))

    try:
        usage = shutil.disk_usage(cli.ROOT)
        free_gb = usage.free / (1024 ** 3)
        checks.append(("Disk space", free_gb >= 10, f"{free_gb:.1f} GB free"))
    except OSError as exc:
        checks.append(("Disk space", False, str(exc)))

    return checks


def cmd_doctor(args: argparse.Namespace) -> None:
    cli = _cli()
    checks = cli.run_local_doctor_checks() if getattr(args, "local", False) else cli.run_doctor_checks()
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
        cli.telegram.send_message(f"🩺 ytb doctor ({len(failed)} lỗi):\n{body}" if failed else "🩺 ytb doctor: tất cả OK")
    if failed:
        sys.exit(1)
