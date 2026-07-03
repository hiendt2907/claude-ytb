"""Adapter — bọc `voiceover/f5_provider.py` (F5-TTS local, .venv-tts) thành
VoiceProvider.

QUAN TRỌNG: F5-TTS/torch chỉ tồn tại trong `.venv-tts`, KHÔNG import ở module
level (nặng + có thể thiếu trong venv chính). Mọi import F5 nằm trong method,
và `is_available()` chỉ kiểm tra sự tồn tại của binary/checkpoint (path-based),
không import torch/F5-TTS.
"""

from pathlib import Path

from ...pkg.models import Script, Voiceover


class F5VoiceProvider:
    name = "f5"

    async def synthesise(self, script: Script, output_dir: Path) -> Voiceover:
        # tts.synthesize() tự dispatch sang F5 dựa trên settings.tts_provider —
        # giữ nguyên đường nhanh "_synth_all_f5" (nạp model 1 lần/cả tập).
        from ...voiceover.tts import synthesize

        return synthesize(script)

    def is_available(self) -> bool:
        from ...voiceover.f5_provider import F5_CKPT, F5_CLI, F5_PYTHON

        return F5_PYTHON.exists() and F5_CLI.exists() and F5_CKPT.exists()
