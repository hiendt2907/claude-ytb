"""Local Vietnamese TTS adapters backed by an installed command-line runner.

The pipeline should not import heavyweight TTS frameworks at module import time.
These providers fail fast unless the user points them at a local executable via
VIENEU_TTS_CMD or VIXTTS_CMD. The command may contain ``{text}`` and ``{out}``
placeholders; otherwise the text and output path are appended as positional args.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from ...config.settings import settings
from ...pkg.models import Script, Segment, Voiceover
from ...voiceover.tts import _concat_audio, _probe_duration, _slugify, _to_mp3
from ..errors import ProviderUnavailableError


class _CommandVoiceProvider:
    name = "local-command"
    env_attr = ""

    def _command_template(self) -> str:
        return str(getattr(settings, self.env_attr, "") or "")

    def is_available(self) -> bool:
        template = self._command_template()
        if not template:
            return False
        binary = shlex.split(template)[0]
        return shutil.which(binary) is not None or Path(binary).exists()

    async def synthesise(self, script: Script, output_dir: Path) -> Voiceover:
        if not self.is_available():
            raise ProviderUnavailableError(
                f"{self.name} chưa khả dụng — cấu hình {self.env_attr.upper()} trỏ tới runner TTS local."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(script.title)
        voiced: list[Segment] = []
        for index, seg in enumerate(script.segments):
            seg_path = output_dir / f"{slug}_{index:02d}.mp3"
            if not seg_path.exists():
                raw = seg_path.with_suffix(f".{self.name}.wav")
                self._run(seg.narration, raw)
                _to_mp3(raw, seg_path)
                raw.unlink(missing_ok=True)
            voiced.append(replace(seg, audio_path=seg_path, duration_sec=_probe_duration(seg_path)))

        combined = output_dir / f"{slug}.mp3"
        _concat_audio([s.audio_path for s in voiced if s.audio_path], combined)
        enriched = replace(script, segments=tuple(voiced))
        return replace(
            Voiceover(**vars(enriched)),
            audio_path=combined,
            duration_sec=sum(s.duration_sec for s in voiced),
        )

    def _run(self, text: str, out: Path) -> None:
        template = self._command_template()
        parts = shlex.split(template)
        if any("{text}" in part or "{out}" in part for part in parts):
            cmd = [part.replace("{text}", text).replace("{out}", str(out)) for part in parts]
        else:
            cmd = [*parts, text, str(out)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)


class VieNeuVoiceProvider(_CommandVoiceProvider):
    name = "vieneu"
    env_attr = "vieneu_tts_cmd"


class ViXTTSVoiceProvider(_CommandVoiceProvider):
    name = "vixtts"
    env_attr = "vixtts_cmd"
