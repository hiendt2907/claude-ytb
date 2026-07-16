"""WorkflowGraph — DAG executor đơn giản, không phụ thuộc ngoài (no networkx).

Thay cho pipeline tuần tự cứng 4 khâu: mỗi `NodeDef` khai báo `deps` (node_id
phải DONE trước), executor topo-sort rồi chạy theo thứ tự, skip node đã DONE
trong checkpoint (resume), và dừng + raise `WorkflowError` khi 1 node fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from .checkpoint import CheckpointManager
from .models import Project, ProjectStatus


@dataclass(frozen=True)
class NodeDef:
    """Khai báo 1 node trong workflow: id, stage, hàm thực thi (async), deps."""

    node_id: str
    stage: str
    fn: Callable[..., Awaitable[str | tuple[str, dict[str, Any]]]]  # nhận project, trả output_ref hoặc (ref, data)
    deps: list[str] = field(default_factory=list)  # node_id phải DONE trước


class WorkflowError(Exception):
    """Raise khi 1 node trong workflow fail — mang node_id + lỗi gốc."""

    def __init__(self, node_id: str, error: str) -> None:
        self.node_id = node_id
        self.error = error
        super().__init__(f"Node '{node_id}' failed: {error}")


class WorkflowGraph:
    """DAG executor: chạy node PENDING theo thứ tự topo, tôn trọng checkpoint."""

    def __init__(self, nodes: list[NodeDef], checkpoint: CheckpointManager) -> None:
        self.nodes = {node.node_id: node for node in nodes}
        self.checkpoint = checkpoint

    def _topo_sort(self) -> list[str]:
        """Trả thứ tự topo các node_id (Kahn's algorithm). Raise nếu có cycle."""
        in_degree: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        dependents: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}

        for node_id, node in self.nodes.items():
            for dep in node.deps:
                if dep not in self.nodes:
                    raise ValueError(f"Node '{node_id}' depends on unknown node '{dep}'")
                in_degree[node_id] += 1
                dependents[dep].append(node_id)

        queue = sorted([node_id for node_id, deg in in_degree.items() if deg == 0])
        order: list[str] = []

        while queue:
            queue.sort()
            current = queue.pop(0)
            order.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self.nodes):
            raise ValueError("Cycle detected in workflow graph")

        return order

    def _ready_nodes(self, project: Project) -> list[str]:
        """Node_id đang PENDING (chưa DONE) và mọi dep đã DONE."""
        ready = []
        for node_id in self._topo_sort():
            if self.checkpoint.is_done(project, node_id):
                continue
            node = self.nodes[node_id]
            if all(self.checkpoint.is_done(project, dep) for dep in node.deps):
                ready.append(node_id)
        return ready

    async def execute(self, project: Project) -> Project:
        """Chạy mọi node PENDING theo thứ tự topo, skip node đã DONE.

        Khi 1 node fail: đánh dấu FAILED, lưu checkpoint, raise WorkflowError
        kèm node_id + lỗi gốc.
        """
        current = project
        for node_id in self._topo_sort():
            if self.checkpoint.is_done(current, node_id):
                continue

            node = self.nodes[node_id]
            current = self.checkpoint.mark_running(current, node_id)
            self.checkpoint.save(current)

            try:
                output = await node.fn(current)
            except Exception as exc:  # noqa: BLE001
                current = self.checkpoint.mark_failed(current, node_id, str(exc))
                self.checkpoint.save(current)
                raise WorkflowError(node_id, str(exc)) from exc

            output_ref, output_data = _normalize_node_output(output)
            current = self.checkpoint.mark_done(current, node_id, output_ref, output_data)
            self.checkpoint.save(current)

        if "publish" in self.nodes and all(
            self.checkpoint.is_done(current, node_id) for node_id in self.nodes
        ):
            current = replace(current, status=ProjectStatus.PUBLISHED)
            self.checkpoint.save(current)

        return current


def _normalize_node_output(output: str | tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if isinstance(output, tuple):
        ref, data = output
        return ref, data
    return output, {}
