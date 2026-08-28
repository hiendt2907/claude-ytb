"""CLI: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"

Kịch bản do Claude viết tay sẵn dưới scripts/*.json — lệnh này nạp/tạo
`project.json` checkpoint rồi chạy WorkflowGraph. Chạy lại cùng kịch bản =
resume: node đã DONE được skip, node stale tự reset về pending. Kết quả CLI
luôn in một ``PIPELINE_STATE`` rõ ràng để operator phân biệt success, review,
abandonment và infrastructure failure.
"""

import argparse
import asyncio
import sys

from .config.settings import settings
from .ideation.approval import ScriptRevisionRequested
from .pipeline import load_or_create_project, publish_summary, run_project
from .project.checkpoint import CheckpointManager
from .project.workflow import WorkflowError
from .render.visual_review import ReviewRequiredError, VisualAbandonedError


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
        if isinstance(exc.__cause__, ReviewRequiredError):
            print(
                f"PIPELINE_STATE=REVIEW_REQUIRED node={exc.node_id} "
                f"{exc.__cause__}",
                file=sys.stderr,
            )
            return 3
        if isinstance(exc.__cause__, VisualAbandonedError):
            print(
                f"PIPELINE_STATE=ABANDONED node={exc.node_id} {exc.__cause__}",
                file=sys.stderr,
            )
            return 4
        print(
            f"PIPELINE_STATE=INFRASTRUCTURE_FAILED node={exc.node_id} "
            f"error={exc.error}",
            file=sys.stderr,
        )
        return 1
    uploaded, url = publish_summary(final, checkpoint)
    print(
        f"PIPELINE_STATE=SUCCESS stage={args.through} "
        f"uploaded={uploaded} url={url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
