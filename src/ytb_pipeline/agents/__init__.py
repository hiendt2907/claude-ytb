"""Phase 5 — Agent system. Auto-đăng ký 5 agent vào `agent_registry` khi import."""

from .base import Agent, AgentResult, AgentStatus
from .registry import AgentRegistry, agent_registry
from .research_agent import ResearchAgent
from .seo_agent import SEOAgent
from .story_architect_agent import StoryArchitectAgent
from .qa_agent import QAAgent
from .voice_director_agent import VoiceDirectorAgent

agent_registry.register(ResearchAgent())
agent_registry.register(StoryArchitectAgent())
agent_registry.register(VoiceDirectorAgent())
agent_registry.register(SEOAgent())
agent_registry.register(QAAgent())

__all__ = [
    "Agent",
    "AgentResult",
    "AgentStatus",
    "AgentRegistry",
    "agent_registry",
    "ResearchAgent",
    "StoryArchitectAgent",
    "VoiceDirectorAgent",
    "SEOAgent",
    "QAAgent",
]
