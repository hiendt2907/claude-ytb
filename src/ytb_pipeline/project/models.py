"""Project Model — schema cho `project.json`.

`Project` thay cho `assets/auto_state.json` ad-hoc: mỗi project có 1 file
`project.json` chứa trạng thái từng `WorkflowNode` (ideation/voiceover/render/
publish), cho phép resume chính xác theo node thay vì scan log rải rác.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    SCRIPTED = "scripted"
    APPROVED = "approved"
    RENDERING = "rendering"
    RENDERED = "rendered"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    FAILED = "failed"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class WorkflowNode:
    """Trạng thái 1 node trong workflow (1 khâu: ideation/voiceover/render/publish)."""

    node_id: str
    stage: str  # "ideation" | "voiceover" | "render" | "publish"
    status: NodeStatus = NodeStatus.PENDING
    output_ref: str | None = None  # path hoặc identifier của output
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    retry_count: int = 0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "stage": self.stage,
            "status": self.status.value,
            "output_ref": self.output_ref,
            "output_data": self.output_data,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowNode":
        return cls(
            node_id=d["node_id"],
            stage=d["stage"],
            status=NodeStatus(d.get("status", NodeStatus.PENDING.value)),
            output_ref=d.get("output_ref"),
            output_data=d.get("output_data", {}),
            error=d.get("error"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            retry_count=d.get("retry_count", 0),
        )


@dataclass(frozen=True)
class Project:
    """Trạng thái toàn bộ 1 project — persisted thành `project.json`."""

    project_id: str  # slug, vd "hieu-ung-zeigarnik"
    status: ProjectStatus = ProjectStatus.DRAFT
    script_path: str | None = None
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "status": self.status.value,
            "script_path": self.script_path,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        nodes = {
            node_id: WorkflowNode.from_dict(node_dict)
            for node_id, node_dict in d.get("nodes", {}).items()
        }
        return cls(
            project_id=d["project_id"],
            status=ProjectStatus(d.get("status", ProjectStatus.DRAFT.value)),
            script_path=d.get("script_path"),
            nodes=nodes,
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def with_node(self, node: WorkflowNode) -> "Project":
        """Trả Project mới với node được thêm/thay thế, updated_at refresh."""
        new_nodes = dict(self.nodes)
        new_nodes[node.node_id] = node
        return replace(self, nodes=new_nodes, updated_at=_now_iso())
