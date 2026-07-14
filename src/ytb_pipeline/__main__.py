"""CLI: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"

Kịch bản do Claude viết tay sẵn dưới scripts/*.json — lệnh này nạp/tạo
`project.json` checkpoint rồi chạy WorkflowGraph 4 node (ideation ->
voiceover -> render -> publish). Chạy lại cùng kịch bản = resume: node đã
DONE được skip, node stale (file mất, dry-run cũ) tự reset về pending.
"""

import asyncio
import sys

from .config.settings import settings
from .ideation.approval import ScriptRevisionRequested
from .pipeline import load_or_create_project, publish_summary, run_project
from .project.checkpoint import CheckpointManager
from .project.workflow import WorkflowError


def main() -> int:
    if len(sys.argv) < 2:
        print('Cách dùng: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"', file=sys.stderr)
        return 1
    checkpoint = CheckpointManager(settings.projects_dir)
    project = load_or_create_project(sys.argv[1], checkpoint)
    try:
        final = asyncio.run(run_project(project, checkpoint))
    except WorkflowError as exc:
        if isinstance(exc.__cause__, ScriptRevisionRequested):
            print(f"⏸  Dừng: user yêu cầu sửa kịch bản — {exc.__cause__.instruction}", file=sys.stderr)
            return 2
        raise
    uploaded, url = publish_summary(final, checkpoint)
    print(f"Xong: uploaded={uploaded} url={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
