"""AgentRegistry — đăng ký + tra cứu agent theo tên (mirror ProviderRegistry).

Pipeline/orchestrator gọi `agent_registry.get("research")` thay vì biết cụ thể
class nào đang chạy — cho phép thay/độn agent độc lập, dễ test.
"""

from __future__ import annotations

from .base import Agent


class AgentRegistry:
    """Registry tên -> instance agent."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(
                f"Không có agent tên '{name}'. Các agent khả dụng: {self.available()}"
            ) from exc

    def available(self) -> list[str]:
        return sorted(self._agents.keys())


agent_registry = AgentRegistry()
