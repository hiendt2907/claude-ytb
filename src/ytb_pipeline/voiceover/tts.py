"""Khâu 2 — Voiceover (TTS).

Hai provider, chọn qua settings.tts_provider:
  - "edge" : edge-tts online, miễn phí, không cần key (mặc định).
  - "f5"   : F5-TTS local tiếng Việt (voice-clone), chạy trong .venv-tts.
"""

import asyncio
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import edge_tts

from ..config.settings import settings
from ..pkg.models import Script, Segment, Voiceover

AUDIO_DIR = Path("assets/audio")

SENTENCE_PUNCT = ".!?…"
CLAUSE_PUNCT = ",;:"


def synthesize(script: Script) -> Voiceover:
    """Sinh audio cho từng segment, đo duration, ghép thành 1 file mp3.

    Trả Voiceover làm giàu từ script (replace) — không mutate bản gốc.
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(script.title)

    # F5 local: nạp model 1 lần, sinh CẢ TẬP trong 1 process (đường nhanh).
    if settings.tts_provider == "f5":
        voiced = _synth_all_f5(script, slug)
    else:
        voiced = []
        for i, seg in enumerate(script.segments):
            seg_path = AUDIO_DIR / f"{slug}_{i:02d}.mp3"
            # Resume: segment đã có audio hợp lệ từ lần chạy trước (bị dừng giữa
            # voiceover) -> bỏ qua, không gọi lại edge-tts cho segment này.
            dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
            if dur <= 0:
                _synth_segment(seg.narration, script.voice, seg_path)
                dur = _probe_duration(seg_path)
            voiced.append(replace(seg, audio_path=seg_path, duration_sec=dur))

    combined = AUDIO_DIR / f"{slug}.mp3"
    _concat_audio([s.audio_path for s in voiced], combined)
    total = sum(s.duration_sec for s in voiced)

    enriched = replace(script, segments=tuple(voiced))
    return replace(
        Voiceover(**vars(enriched)),
        audio_path=combined,
        duration_sec=total,
    )


def _synth_all_f5(script: Script, slug: str) -> list[Segment]:
    """Đường nhanh cho F5: gom mọi cụm của CẢ TẬP → worker nạp model 1 lần → ghép.

    Giữ NGUYÊN nhịp ngắt nghỉ như edge (cùng `_split_for_pacing` + chèn im lặng),
    chỉ khác: model nạp 1 lần thay vì cold-start mỗi cụm.
    """
    from .f5_provider import run_batch

    comma = settings.pause_comma_ms / 1000
    sentence = settings.pause_sentence_ms / 1000
    seg_pause = settings.pause_segment_ms / 1000

    # Pha 1 — dựng danh sách cụm/segment + job toàn tập (mỗi cụm 1 wav).
    seg_pieces: list[list[tuple[str, float, Path]]] = []
    jobs: list[dict] = []
    for i, seg in enumerate(script.segments):
        pieces = _split_for_pacing(seg.narration, comma, sentence) \
            or [(seg.narration.strip(), 0.0)]
        items: list[tuple[str, float, Path]] = []
        for j, (piece, pause) in enumerate(pieces):
            wav = AUDIO_DIR / f"{slug}_{i:02d}.p{j:02d}.f5.wav"
            jobs.append({"text": piece, "out": str(wav)})
            items.append((piece, pause, wav))
        seg_pieces.append(items)

    # Pha 2 — sinh tất cả wav trong 1 lần nạp model.
    run_batch(jobs)

    # Pha 3 — ghép từng segment: wav→mp3 + chèn im lặng + nối.
    voiced: list[Segment] = []
    for i, seg in enumerate(script.segments):
        seg_path = AUDIO_DIR / f"{slug}_{i:02d}.mp3"
        parts: list[Path] = []
        tmp: list[Path] = []
        for j, (_piece, pause, wav) in enumerate(seg_pieces[i]):
            raw = seg_path.with_name(f"{seg_path.stem}.p{j:02d}.mp3")
            _to_mp3(wav, raw)
            wav.unlink(missing_ok=True)
            parts.append(raw)
            tmp.append(raw)
            if pause > 0:
                sil = seg_path.with_name(f"{seg_path.stem}.s{j:02d}.mp3")
                _silence_mp3(pause, sil)
                parts.append(sil)
                tmp.append(sil)
        if seg_pause > 0:
            sil = seg_path.with_name(f"{seg_path.stem}.send.mp3")
            _silence_mp3(seg_pause, sil)
            parts.append(sil)
            tmp.append(sil)
        _concat_audio(parts, seg_path)
        for p in tmp:
            p.unlink(missing_ok=True)
        dur = _probe_duration(seg_path)
        voiced.append(replace(seg, audio_path=seg_path, duration_sec=dur))
    return voiced


def _split_for_pacing(text: str, comma_sec: float,
                      sentence_sec: float) -> list[tuple[str, float]]:
    """Chia narration thành các cụm đọc + khoảng lặng (giây) chèn SAU mỗi cụm.

    Cụm kết bằng `. ! ? …` → nghỉ dài; kết bằng `, ; :` → nghỉ ngắn. Cụm CUỐI
    của segment đặt nghỉ 0 (khoảng cách giữa segment do mức segment xử lý riêng).
    Hàm thuần — không phụ thuộc provider, dễ test.
    """
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
            pause = sentence_sec
        elif last in CLAUSE_PUNCT:
            pause = comma_sec
        else:
            pause = 0.0
        out.append((part, pause))

    if out:
        out[-1] = (out[-1][0], 0.0)  # cụm cuối: nghỉ ở mức segment, không ở đây
    return out


def _synth_segment(text: str, voice: str, out_mp3: Path) -> None:
    """Tổng hợp 1 segment với nhịp ngắt nghỉ: synth từng cụm + chèn khoảng lặng,
    rồi nối lại. Khoảng lặng cuối = pause giữa segment (để video đỡ đọc một lèo)."""
    comma = settings.pause_comma_ms / 1000
    sentence = settings.pause_sentence_ms / 1000
    seg_pause = settings.pause_segment_ms / 1000

    pieces = _split_for_pacing(text, comma, sentence) or [(text.strip(), 0.0)]

    parts: list[Path] = []
    tmp: list[Path] = []
    for i, (piece, pause) in enumerate(pieces):
        raw = out_mp3.with_name(f"{out_mp3.stem}.p{i:02d}.mp3")
        _synth_raw(piece, voice, raw)
        parts.append(raw)
        tmp.append(raw)
        if pause > 0:
            sil = out_mp3.with_name(f"{out_mp3.stem}.s{i:02d}.mp3")
            _silence_mp3(pause, sil)
            parts.append(sil)
            tmp.append(sil)

    if seg_pause > 0:
        sil = out_mp3.with_name(f"{out_mp3.stem}.send.mp3")
        _silence_mp3(seg_pause, sil)
        parts.append(sil)
        tmp.append(sil)

    _concat_audio(parts, out_mp3)
    for p in tmp:
        p.unlink(missing_ok=True)


def _synth_raw(text: str, voice: str, out_mp3: Path) -> None:
    """Dispatch theo provider; CHUẨN HOÁ về mp3 44100/stereo/192k để concat copy an toàn."""
    if settings.tts_provider == "f5":
        from .f5_provider import synthesize_f5

        wav = out_mp3.with_suffix(".f5.wav")
        synthesize_f5(text, wav)
        _to_mp3(wav, out_mp3)
        wav.unlink(missing_ok=True)
    else:
        raw = out_mp3.with_suffix(".edge.mp3")
        asyncio.run(_tts(text, voice, raw))
        _to_mp3(raw, out_mp3)
        raw.unlink(missing_ok=True)


def _silence_mp3(seconds: float, out: Path) -> None:
    """Sinh 1 đoạn im lặng mp3 cùng định dạng (44100/stereo/192k) với giọng đọc."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out)],
        capture_output=True, check=True,
    )


def _to_mp3(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "44100", "-ac", "2",
         "-b:a", "192k", str(dst)],
        capture_output=True, check=True,
    )


TTS_MAX_RETRIES = 3
TTS_RETRY_DELAY = 2.0  # giây


async def _tts(text: str, voice: str, out: Path) -> None:
    """Gọi edge-tts; retry khi rớt mạng (NoAudioReceived) — lỗi transient hay gặp."""
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(out))
            return
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == TTS_MAX_RETRIES:
                raise
            await asyncio.sleep(TTS_RETRY_DELAY)


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _probe_duration_or_zero(path: Path) -> float:
    """Như `_probe_duration` nhưng trả 0.0 nếu file dở dang/hỏng (vd bị kill giữa lúc ghi)."""
    try:
        return _probe_duration(path)
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return 0.0


def _concat_audio(parts: list[Path], out: Path) -> None:
    listfile = out.with_suffix(".txt")
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def _slugify(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "video"
