"""Voiceover — sinh giọng đọc edge-tts cho `content.models.Script`, ghép thành 1 voice track.

Port rút gọn từ claude-ytb/voiceover/tts.py cho content.models.Script (không có
caption/broll/topic). Trả thêm per-segment audio_path/duration_sec để
assembler/duration.py (mode "voice_silence") đồng bộ độ dài cảnh với clip Pexels.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import edge_tts

from .models import Script

SENTENCE_PUNCT = ".!?…"
CLAUSE_PUNCT = ",;:"

DEFAULT_VOICE = os.environ.get("EDGE_VOICE", "vi-VN-NamMinhNeural")
DEFAULT_RATE = os.environ.get("EDGE_RATE", "+100%")
DEFAULT_PITCH = os.environ.get("EDGE_PITCH", "+0Hz")

EDGE_MAX_WORKERS = 4
# assembler/duration.py (VoiceSilenceDurationStrategy) mặc định coi khoảng
# lặng >= 0.3s là 1 ranh giới cảnh — COMMA/SENTENCE_PAUSE_SEC phải nằm RÕ RÀNG
# dưới ngưỡng đó (để pause trong câu không bị hiểu nhầm là ranh giới cảnh),
# còn SEGMENT_PAUSE_SEC (giữa 2 đoạn = 2 cảnh) phải RÕ RÀNG trên ngưỡng.
COMMA_PAUSE_SEC = 0.12
SENTENCE_PAUSE_SEC = 0.15
SEGMENT_PAUSE_SEC = 0.6
TTS_MAX_RETRIES = 3
TTS_RETRY_DELAY = 2.0


@dataclass(frozen=True)
class VoicedSegment:
    narration: str
    visual_keywords: tuple[str, ...]
    audio_path: Path
    duration_sec: float


@dataclass(frozen=True)
class Voiceover:
    title: str
    segments: tuple[VoicedSegment, ...]
    audio_path: Path
    duration_sec: float


def synthesize(script: Script, output_dir: Path, *, slug: str | None = None) -> Voiceover:
    """Sinh audio cho từng segment (song song), ghép thành 1 file voice duy nhất."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slug or _slugify(script.title)

    voiced = _synth_all_parallel(script, slug, output_dir)

    combined = output_dir / f"{slug}_voice.mp3"
    _concat_audio([s.audio_path for s in voiced], combined)
    total = sum(s.duration_sec for s in voiced)

    return Voiceover(title=script.title, segments=tuple(voiced), audio_path=combined, duration_sec=total)


def _synth_all_parallel(script: Script, slug: str, output_dir: Path) -> list[VoicedSegment]:
    """Sinh audio segment SONG SONG; resume bỏ qua segment đã có audio hợp lệ.

    Thứ tự kết quả trả về luôn khớp thứ tự segment gốc.
    """
    pending: list[tuple[int, object, Path]] = []
    voiced: list[VoicedSegment | None] = [None] * len(script.segments)

    for i, seg in enumerate(script.segments):
        seg_path = _segment_audio_path(output_dir, slug, i)
        dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
        if dur > 0:
            voiced[i] = VoicedSegment(seg.narration, seg.visual_keywords, seg_path, dur)
        else:
            pending.append((i, seg, seg_path))

    last_index = len(script.segments) - 1

    def _work(item: tuple[int, object, Path]) -> tuple[int, VoicedSegment]:
        i, seg, seg_path = item
        # Đoạn CUỐI không chèn khoảng lặng cuối — nếu có, ghép audio sẽ tạo ra
        # N+1 khoảng lặng cho N đoạn, khiến assembler/duration.py
        # (VoiceSilenceDurationStrategy) đếm lệch 1 so với số cảnh.
        _synth_segment(seg.narration, seg_path, trailing_pause=i != last_index)
        dur = _probe_duration(seg_path)
        return i, VoicedSegment(seg.narration, seg.visual_keywords, seg_path, dur)

    if pending:
        with ThreadPoolExecutor(max_workers=EDGE_MAX_WORKERS) as pool:
            for i, done_seg in pool.map(_work, pending):
                voiced[i] = done_seg

    return [v for v in voiced if v is not None]


def _segment_audio_path(output_dir: Path, slug: str, index: int) -> Path:
    return output_dir / f"{slug}_{index:02d}.mp3"


def _prepare_narration(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).strip()


def _split_for_pacing(text: str) -> list[tuple[str, float]]:
    """Chia narration thành cụm đọc + khoảng lặng (giây) chèn SAU mỗi cụm."""
    text = text.strip()
    if not text:
        return []

    parts = re.findall(rf"[^{SENTENCE_PUNCT}{CLAUSE_PUNCT}]+[{SENTENCE_PUNCT}{CLAUSE_PUNCT}]*", text)
    out: list[tuple[str, float]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        last = part[-1]
        if last in SENTENCE_PUNCT:
            pause = SENTENCE_PAUSE_SEC
        elif last in CLAUSE_PUNCT:
            pause = COMMA_PAUSE_SEC
        else:
            pause = 0.0
        out.append((part, pause))

    if out:
        out[-1] = (out[-1][0], 0.0)
    return out


def _synth_segment(text: str, out_mp3: Path, *, trailing_pause: bool = True) -> None:
    text = _prepare_narration(text)
    pieces = _split_for_pacing(text) or [(text, 0.0)]

    parts: list[Path] = []
    tmp: list[Path] = []
    for i, (piece, pause) in enumerate(pieces):
        raw = out_mp3.with_name(f"{out_mp3.stem}.p{i:02d}.mp3")
        _synth_raw(piece, raw)
        parts.append(raw)
        tmp.append(raw)
        if pause > 0:
            sil = out_mp3.with_name(f"{out_mp3.stem}.s{i:02d}.mp3")
            _silence_mp3(pause, sil)
            parts.append(sil)
            tmp.append(sil)

    if trailing_pause and SEGMENT_PAUSE_SEC > 0:
        sil = out_mp3.with_name(f"{out_mp3.stem}.send.mp3")
        _silence_mp3(SEGMENT_PAUSE_SEC, sil)
        parts.append(sil)
        tmp.append(sil)

    _concat_audio(parts, out_mp3)
    for p in tmp:
        p.unlink(missing_ok=True)


def _synth_raw(text: str, out_mp3: Path) -> None:
    raw = out_mp3.with_suffix(".edge.mp3")
    asyncio.run(_tts(text, raw))
    _to_mp3(raw, out_mp3)
    raw.unlink(missing_ok=True)


async def _tts(text: str, out: Path) -> None:
    """Gọi edge-tts; retry khi rớt mạng (NoAudioReceived) — lỗi transient hay gặp."""
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(text, DEFAULT_VOICE, rate=DEFAULT_RATE, pitch=DEFAULT_PITCH)
            await communicate.save(str(out))
            return
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == TTS_MAX_RETRIES:
                raise
            await asyncio.sleep(TTS_RETRY_DELAY)


def _silence_mp3(seconds: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out)],
        capture_output=True, check=True,
    )


_SILENCEREMOVE = "silenceremove=start_periods=1:start_threshold=-30dB:start_silence=0.05:detection=peak,areverse,silenceremove=start_periods=1:start_threshold=-30dB:start_silence=0.05:detection=peak,areverse"


def _to_mp3(src: Path, dst: Path) -> None:
    """Chuẩn hoá về mp3 + CẮT SẠCH khoảng lặng đầu/cuối do edge-tts tự chèn.

    edge-tts luôn để lại vài trăm ms im lặng ở đầu/cuối mỗi audio — nếu không
    cắt, khoảng lặng này cộng dồn với `SEGMENT_PAUSE_SEC` sẽ làm
    `assembler/duration.py` (VoiceSilenceDurationStrategy) đếm sai số đoạn so
    với số cảnh (đã gặp thật khi test: 3 đoạn phát hiện được cho 2 cảnh).
    """
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-af", _SILENCEREMOVE,
         "-ar", "44100", "-ac", "2", "-b:a", "192k", str(dst)],
        capture_output=True, check=True,
    )


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _probe_duration_or_zero(path: Path) -> float:
    try:
        return _probe_duration(path)
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return 0.0


def _concat_audio(parts: list[Path], out: Path) -> None:
    listfile = out.with_suffix(".txt")
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(out)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "video"
