"""JobStore singleton dùng chung giữa `app.py` và `content_routes.py`.

Tách riêng để tránh circular import: `content_routes.py` cần cùng 1 `store`
với `app.py` để `/api/jobs/{id}` poll đúng job render mà content pipeline
khởi chạy, nhưng `app.py` lại include router của `content_routes.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ytb_pipeline.webui.jobs import JobStore


def _job_store_dir() -> Path | None:
    configured = os.environ.get("VIDEO_RENDER_JOB_STORE_DIR")
    if configured:
        return Path(configured).expanduser()
    if "pytest" in sys.modules:
        return None
    return Path.home() / ".video_render" / "jobs"


store = JobStore(persistence_dir=_job_store_dir())
