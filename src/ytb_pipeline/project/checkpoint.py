"""CheckpointManager — persist + resume `WorkflowNode` state qua `project.json`.

Atomic write: ghi vào `.tmp` rồi `rename` — tránh corrupt file khi crash giữa
lúc viết (vd OOM-kill, power loss).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .models import NodeStatus, Project, WorkflowNode


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointManager:
    """Đọc/viết trạng thái Project, đánh dấu node running/done/failed."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)

    def _path(self, project_id: str) -> Path:
        return self.project_dir / project_id / "project.json"

    def load(self, project_id: str) -> Project | None:
        """Đọc project từ `<project_dir>/<project_id>/project.json`. None nếu chưa có."""
        path = self._path(project_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Project.from_dict(data)

    def save(self, project: Project) -> None:
        """Atomic write (viết file tạm rồi rename) vào project.json."""
        path = self._path(project.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.rename(path)

    def mark_running(self, project: Project, node_id: str) -> Project:
        """Trả Project mới với node status=RUNNING, started_at=now."""
        existing = project.nodes.get(node_id)
        stage = existing.stage if existing else node_id
        node = replace(
            existing if existing else WorkflowNode(node_id=node_id, stage=stage),
            status=NodeStatus.RUNNING,
            started_at=_now_iso(),
            error=None,
        )
        return project.with_node(node)

    def mark_done(
        self,
        project: Project,
        node_id: str,
        output_ref: str,
        output_data: dict | None = None,
    ) -> Project:
        """Trả Project mới với node status=DONE, completed_at=now, output_ref set."""
        existing = project.nodes.get(node_id)
        stage = existing.stage if existing else node_id
        node = replace(
            existing if existing else WorkflowNode(node_id=node_id, stage=stage),
            status=NodeStatus.DONE,
            output_ref=output_ref,
            output_data=output_data or {},
            completed_at=_now_iso(),
            error=None,
        )
        return project.with_node(node)

    def mark_failed(self, project: Project, node_id: str, error: str) -> Project:
        """Trả Project mới với node status=FAILED, error set, retry_count+1."""
        existing = project.nodes.get(node_id)
        stage = existing.stage if existing else node_id
        retry_count = existing.retry_count + 1 if existing else 1
        node = replace(
            existing if existing else WorkflowNode(node_id=node_id, stage=stage),
            status=NodeStatus.FAILED,
            error=error,
            retry_count=retry_count,
        )
        return project.with_node(node)

    def is_done(self, project: Project, node_id: str) -> bool:
        """True nếu node tồn tại và status=DONE."""
        node = project.nodes.get(node_id)
        return node is not None and node.status == NodeStatus.DONE

    def get_output(self, project: Project, node_id: str) -> str | None:
        """Trả output_ref cho 1 node DONE (None nếu chưa done/không tồn tại)."""
        node = project.nodes.get(node_id)
        if node is None:
            return None
        return node.output_ref

    def get_output_data(self, project: Project, node_id: str) -> dict:
        """Trả output_data cho 1 node DONE, hoặc dict rỗng nếu chưa có."""
        node = project.nodes.get(node_id)
        if node is None:
            return {}
        return dict(node.output_data or {})
