"""Orchestrator: nối 4 khâu thành pipeline tuần tự.

Ideation = nạp kịch bản Claude viết sẵn (scripts/*.json). Mỗi khâu sau là hàm
thuần nhận model trước, trả model làm giàu thêm qua replace().
"""

from .ideation.generator import load_script
from .ideation.approval import gate
from .voiceover.tts import synthesize
from .render.compose import render_video
from .render.compose_ai import render_video_ai
from .publish.uploader import publish
from .config.settings import settings
from .pkg.models import PublishResult


def run(script_source: str) -> PublishResult:
    """Chạy pipeline từ 1 kịch bản Claude đã viết sẵn (scripts/*.json)."""
    script = load_script(script_source)
    print(f"[1/4] Ideation  ✓  {script.title} ({len(script.segments)} đoạn)")
    script = gate(script)  # cổng duyệt Telegram (bỏ qua nếu TELEGRAM_APPROVAL=false)
    print("[2/4] Voiceover ▶  đang tạo audio...")
    voiceover = synthesize(script)
    print(f"[2/4] Voiceover ✓  {voiceover.audio_path}  ({voiceover.duration_sec:.1f}s)")
    renderer = render_video_ai if settings.render_provider == "ai" else render_video
    print(f"[3/4] Render    ▶  đang dựng video ({settings.render_provider}/{settings.orientation})...")
    video = renderer(voiceover)
    print(f"[3/4] Render    ✓  ({settings.render_provider}/{settings.orientation}) {video.video_path}")
    print("[4/4] Publish   ▶  đang upload...")
    result = publish(video)
    print(f"[4/4] Publish   ✓  uploaded={result.uploaded}")

    # Sau khi upload thật, MOVE video lên Drive (xoá local). Lỗi Drive không hỏng pipeline
    # và KHÔNG xoá local (move chỉ chạy khi Drive nhận file thành công).
    if result.uploaded and settings.drive_backup:
        from .publish.drive import backup_to_drive
        try:
            backup_to_drive(result.video_path, move=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ Đưa lên Drive thất bại (giữ bản local): {exc}")

    return result
