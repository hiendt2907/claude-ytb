"""Đăng ký các VoiceProvider vào voice_registry khi module này được import."""

from ..registry import voice_registry
from .edge_provider import EdgeVoiceProvider
from .f5_provider import F5VoiceProvider
from .local_command_provider import VieNeuVoiceProvider, ViXTTSVoiceProvider

voice_registry.register("edge", EdgeVoiceProvider)
voice_registry.register("f5", F5VoiceProvider)
voice_registry.register("vieneu", VieNeuVoiceProvider)
voice_registry.register("vixtts", ViXTTSVoiceProvider)

__all__ = ["EdgeVoiceProvider", "F5VoiceProvider", "VieNeuVoiceProvider", "ViXTTSVoiceProvider"]
