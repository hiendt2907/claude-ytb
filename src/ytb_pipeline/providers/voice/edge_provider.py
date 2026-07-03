"""Adapter — bọc `voiceover/tts.py` (edge-tts) thành VoiceProvider.

KHÔNG viết lại logic; chỉ delegate sang `synthesize()` hiện có. `output_dir`
nhận để khớp Protocol nhưng tts.py tự quản lý AUDIO_DIR riêng — giữ nguyên
hành vi gốc.
"""

from pathlib import Path

from ...pkg.models import Script, Voiceover


class EdgeVoiceProvider:
    name = "edge"

    async def synthesise(self, script: Script, output_dir: Path) -> Voiceover:
        from ...voiceover.tts import synthesize

        return synthesize(script)

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False
