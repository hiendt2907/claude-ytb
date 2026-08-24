"""xKiro's OpenAI-compatible text-to-speech adapter.

Each script segment is requested independently so pipeline checkpoints can
resume safely.  xKiro returns MP3 bytes; the existing FFmpeg helpers keep the
audio contract identical to the F5 and Edge providers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from ...config.settings import settings
from ...content_contract import contract_for
from ...pkg.models import Script, Segment, Voiceover
from ...voiceover.tts import (
    _concat_audio,
    _pad_audio,
    _prepare_narration,
    _probe_duration,
    _segment_profile,
    _silence_mp3,
    _slugify,
    _split_for_pacing,
    _to_mp3,
    _voice_profile,
)
from ..errors import ProviderUnavailableError


class XkiroVoiceProvider:
    """Synthesize Vietnamese narration through xKiro's speech endpoint."""

    name = "xkiro"

    def is_available(self) -> bool:
        return bool(settings.xkiro_api_key.strip())

    async def synthesise(self, script: Script, output_dir: Path) -> Voiceover:
        if not self.is_available():
            raise ProviderUnavailableError(
                "xKiro chưa khả dụng — cấu hình XKIRO_API_KEY trong .env."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        slug = self._artifact_slug(script)
        default_profile = _voice_profile(script)
        voiced: list[Segment] = []
        for index, segment in enumerate(script.segments):
            profile = _segment_profile(segment, default_profile, index, len(script.segments))
            segment_path = self._segment_path(script, segment, index, output_dir, profile=profile)
            duration = self._existing_duration(segment_path)
            if duration <= 0:
                await self._synthesise_segment(segment.narration, profile, segment_path, index)
                duration = _probe_duration(segment_path)
            voiced.append(
                replace(segment, audio_path=segment_path, duration_sec=duration)
            )

        total = sum(segment.duration_sec for segment in voiced)
        lower, _ = contract_for(script.video_type).audio_runtime_bounds_sec(
            segment_count=len(voiced)
        )
        if total < lower and lower - total <= 2.0:
            gap = lower - total
            last = voiced[-1]
            if last.audio_path is None:
                raise ValueError("Không thể pad runtime: segment cuối thiếu audio_path.")
            _pad_audio(last.audio_path, gap)
            voiced[-1] = replace(last, duration_sec=last.duration_sec + gap)
            total = lower

        combined = output_dir / f"{slug}_xkiro.mp3"
        _concat_audio([segment.audio_path for segment in voiced if segment.audio_path], combined)
        enriched = replace(script, segments=tuple(voiced))
        return replace(
            Voiceover(**vars(enriched)),
            audio_path=combined,
            duration_sec=total,
        )

    def _segment_path(
        self,
        script: Script,
        segment: Segment,
        index: int,
        output_dir: Path,
        *,
        profile=None,
    ) -> Path:
        profile = profile or _segment_profile(
            segment, _voice_profile(script), index, len(script.segments)
        )
        prepared = _prepare_narration(segment.narration)
        cache_key = json.dumps(
            {
                "provider": self.name,
                "endpoint": settings.xkiro_tts_url,
                "model": settings.xkiro_model,
                "voice": settings.xkiro_voice,
                "text": prepared,
                "profile": vars(profile),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:12]
        return output_dir / f"{self._artifact_slug(script)}_xkiro_{index:02d}_{digest}.mp3"

    @staticmethod
    def _artifact_slug(script: Script) -> str:
        """Prefer the pipeline's stable project slug over an editable title."""
        return _slugify(script.project_id or script.title)

    @staticmethod
    def _existing_duration(path: Path) -> float:
        if not path.exists():
            return 0.0
        try:
            return _probe_duration(path)
        except (subprocess.CalledProcessError, KeyError, ValueError):
            return 0.0

    async def _synthesise_segment(self, narration: str, profile, output: Path, index: int) -> None:
        prepared = _prepare_narration(narration)
        pieces = _split_for_pacing(prepared, profile.comma_sec, profile.sentence_sec)
        if not pieces:
            raise ValueError(f"Segment {index + 1} không có narration để xKiro đọc.")

        parts: list[Path] = []
        temporary: list[Path] = []
        try:
            if profile.pause_before > 0:
                before = output.with_name(f"{output.stem}.before.mp3")
                _silence_mp3(profile.pause_before, before)
                parts.append(before)
                temporary.append(before)
            for piece_index, (text, pause) in enumerate(pieces):
                fetched = output.with_name(f"{output.stem}.p{piece_index:02d}.raw.mp3")
                normalized = output.with_name(f"{output.stem}.p{piece_index:02d}.mp3")
                audio = await asyncio.to_thread(self._request_audio, text)
                if not audio:
                    raise RuntimeError(f"xKiro trả audio rỗng cho segment {index + 1}.")
                fetched.write_bytes(audio)
                temporary.append(fetched)
                # xKiro trả mp3 24kHz mono; chuẩn hoá về 44100/stereo/192k như
                # F5/Edge để concat demuxer không đổi sample rate giữa chừng
                # (mismatch từng làm ffmpeg/libmp3lame abort ở loudnorm).
                _to_mp3(fetched, normalized)
                parts.append(normalized)
                temporary.append(normalized)
                if pause > 0:
                    silence = output.with_name(f"{output.stem}.s{piece_index:02d}.mp3")
                    _silence_mp3(pause, silence)
                    parts.append(silence)
                    temporary.append(silence)
            for suffix, seconds in (("after", profile.pause_after), ("end", profile.segment_sec)):
                if seconds > 0:
                    silence = output.with_name(f"{output.stem}.{suffix}.mp3")
                    _silence_mp3(seconds, silence)
                    parts.append(silence)
                    temporary.append(silence)
            _concat_audio(parts, output)
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)

    def _request_audio(self, text: str) -> bytes:
        payload = json.dumps(
            {
                "model": settings.xkiro_model,
                "input": text,
                "voice": settings.xkiro_voice,
                "response_format": "mp3",
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            settings.xkiro_tts_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.xkiro_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ytb-pipeline/1.0 (+https://xkiro.com)",
            },
            method="POST",
        )
        retries = settings.xkiro_max_retries
        for attempt in range(retries):
            try:
                with urllib_request.urlopen(request, timeout=settings.xkiro_timeout_sec) as response:
                    return response.read()
            except urllib_error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == retries - 1:
                    raise RuntimeError(f"xKiro TTS trả HTTP {exc.code}.") from exc
            except (TimeoutError, urllib_error.URLError) as exc:
                if attempt == retries - 1:
                    raise RuntimeError("Không kết nối được xKiro TTS.") from exc
            time.sleep(2**attempt)
        raise RuntimeError("xKiro TTS không trả audio sau các lần thử lại.")
