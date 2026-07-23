"""CLI: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"

Kịch bản do Claude viết tay sẵn dưới scripts/*.json — lệnh này nạp/tạo
`project.json` checkpoint rồi chạy WorkflowGraph 4 node (ideation ->
voiceover -> render -> publish). Chạy lại cùng kịch bản = resume: node đã
DONE được skip, node stale (file mất, dry-run cũ) tự reset về pending.
"""

import argparse
import asyncio

from .config.settings import settings
from .ideation.approval import ScriptRevisionRequested
from .pipeline import load_or_create_project, publish_summary, run_project
from .project.checkpoint import CheckpointManager
from .project.workflow import WorkflowError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script_source", help="Đường dẫn/slug kịch bản đã được batch start approve")
    parser.add_argument("--through", choices=("voiceover", "render", "publish"), default="publish")
    args = parser.parse_args()
    checkpoint = CheckpointManager(settings.projects_dir)
    project = load_or_create_project(args.script_source, checkpoint)
    try:
        final = asyncio.run(run_project(project, checkpoint, through=args.through))
    except WorkflowError as exc:
        if isinstance(exc.__cause__, ScriptRevisionRequested):
            print(f"⏸  Dừng: user yêu cầu sửa kịch bản — {exc.__cause__.instruction}", file=sys.stderr)
            return 2
        raise
    uploaded, url = publish_summary(final, checkpoint)
    print(f"Xong stage={args.through}: uploaded={uploaded} url={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
