"""Khâu 2 — Voiceover (TTS).

Hai provider, chọn qua settings.tts_provider:
  - "edge" : edge-tts online, miễn phí, không cần key (mặc định).
  - "f5"   : F5-TTS local tiếng Việt (voice-clone), chạy trong .venv-tts.
"""

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

import edge_tts

from ..config.settings import settings
from ..pkg.models import Script, Segment, Voiceover

AUDIO_DIR = Path("assets/audio")

SENTENCE_PUNCT = ".!?…"
CLAUSE_PUNCT = ",;:"


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    comma_sec: float
    sentence_sec: float
    segment_sec: float
    edge_rate: str = "+0%"
    edge_pitch: str = "+0Hz"
    f5_tempo: float = 1.0


# F5 post-processing must match Edge's effective rate.  The values below are
# the Edge percentage converted to a tempo multiplier: +100% -> 2.00x, +96%
# -> 1.96x, etc.  This keeps character-based timing consistent across TTS
# providers.
VOICE_NEUTRAL = VoiceProfile("neutral", 0.20, 0.32, 0.28, edge_rate="+100%", f5_tempo=2.00)
VOICE_ENTERTAINMENT = VoiceProfile(
    "entertainment",
    comma_sec=0.06,
    sentence_sec=0.14,
    segment_sec=0.08,
    edge_rate="+116%",
    edge_pitch="+8Hz",
    f5_tempo=2.16,
)
VOICE_KNOWLEDGE = VoiceProfile(
    "knowledge",
    comma_sec=0.24,
    sentence_sec=0.46,
    segment_sec=0.34,
    edge_rate="+96%",
    edge_pitch="-2Hz",
    f5_tempo=1.96,
)
VOICE_INSPIRING = VoiceProfile(
    "inspiring",
    comma_sec=0.28,
    sentence_sec=0.52,
    segment_sec=0.42,
    edge_rate="+88%",
    edge_pitch="-1Hz",
    f5_tempo=1.88,
)

_ENTERTAINMENT_HINTS = (
    "giải trí", "giai tri", "người que", "nguoi que", "stickman", "hài",
    "hai", "meme", "viral", "kéo view", "keo view", "vui nhộn", "vui nhon",
)
_KNOWLEDGE_HINTS = (
    "kiến thức", "kien thuc", "giáo dục", "giao duc", "tâm lý", "tam ly",
    "phát triển bản thân", "phat trien ban than", "khoa học", "khoa hoc",
    "lịch sử", "lich su", "tài chính", "tai chinh", "sức khỏe", "suc khoe",
)
_STAGE_DIRECTION_PATTERNS = (
    r"\bCú hình tiếp theo\s*:\s*",
    r"\bBeat sau\s*:\s*",
    r"\bChốt cảnh\s*:\s*",
    r"\bChốt\s*\.\s*",
)


def synthesize(script: Script) -> Voiceover:
    """Sinh audio cho từng segment, đo duration, ghép thành 1 file mp3.

    Trả Voiceover làm giàu từ script (replace) — không mutate bản gốc.
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(script.title)
    profile = _voice_profile(script)

    # F5 local: nạp model 1 lần, sinh CẢ TẬP trong 1 process (đường nhanh).
    if settings.tts_provider == "f5":
        voiced = _synth_all_f5(script, slug, profile)
    else:
        voiced = _synth_all_edge_parallel(script, slug, profile)

    combined = AUDIO_DIR / f"{slug}_{profile.name}.mp3"
    _concat_audio([s.audio_path for s in voiced], combined)
    total = sum(s.duration_sec for s in voiced)

    enriched = replace(script, segments=tuple(voiced))
    return replace(
        Voiceover(**vars(enriched)),
        audio_path=combined,
        duration_sec=total,
    )


def _synth_all_edge_parallel(script: Script, slug: str, profile: VoiceProfile) -> list[Segment]:
    """Sinh audio edge-tts cho mọi segment SONG SONG (mỗi segment đã tự cắt cụm
    nhỏ qua `_split_for_pacing`, độc lập file — an toàn chạy đa luồng vì mỗi
    segment ghi ra `seg_path` riêng, không tranh chấp).

    Số worker qua `settings.edge_tts_workers` (đặt 1 nếu edge-tts rate-limit;
    lỗi NoAudioReceived đã có retry riêng trong `_tts`).

    Segment đã có audio hợp lệ từ lần chạy trước (resume) được bỏ qua, không
    gọi lại edge-tts. Thứ tự kết quả trả về LUÔN khớp thứ tự segment gốc.
    """
    from concurrent.futures import ThreadPoolExecutor

    pending: list[tuple[int, Segment, Path]] = []
    voiced: list[Segment | None] = [None] * len(script.segments)

    for i, seg in enumerate(script.segments):
        seg_path = _segment_audio_path(slug, profile, i)
        dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
        if dur > 0:
            voiced[i] = replace(seg, audio_path=seg_path, duration_sec=dur)
        else:
            pending.append((i, seg, seg_path))

    def _work(item: tuple[int, Segment, Path]) -> tuple[int, Segment]:
        i, seg, seg_path = item
        _synth_segment(_prepare_narration(seg.narration), script.voice, seg_path, profile)
        dur = _probe_duration(seg_path)
        return i, replace(seg, audio_path=seg_path, duration_sec=dur)

    if pending:
        workers = max(1, settings.edge_tts_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, done_seg in pool.map(_work, pending):
                voiced[i] = done_seg

    return [v for v in voiced if v is not None]


def _synth_all_f5(script: Script, slug: str, profile: VoiceProfile) -> list[Segment]:
    """Đường nhanh cho F5: gom mọi cụm của CẢ TẬP → worker nạp model 1 lần → ghép.

    Giữ NGUYÊN nhịp ngắt nghỉ như edge (cùng `_split_for_pacing` + chèn im lặng),
    chỉ khác: model nạp 1 lần thay vì cold-start mỗi cụm.
    """
    cached: list[Segment] = []
    for i, seg in enumerate(script.segments):
        seg_path = _segment_audio_path(slug, profile, i)
        dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
        if dur <= 0:
            cached = []
            break
        cached.append(replace(seg, audio_path=seg_path, duration_sec=dur))
    if cached and len(cached) == len(script.segments):
        return cached

    from .f5_provider import run_batch

    # Pha 1 — dựng danh sách cụm/segment + job toàn tập (mỗi cụm 1 wav).
    seg_pieces: list[list[tuple[str, float, Path]]] = []
    jobs: list[dict] = []
    for i, seg in enumerate(script.segments):
        narration = _prepare_narration(seg.narration)
        pieces = _split_for_pacing(narration, profile.comma_sec, profile.sentence_sec) \
            or [(narration, 0.0)]
        items: list[tuple[str, float, Path]] = []
        for j, (piece, pause) in enumerate(pieces):
            wav = AUDIO_DIR / f"{slug}_{profile.name}_{i:02d}.p{j:02d}.f5.wav"
            jobs.append({"text": piece, "out": str(wav)})
            items.append((piece, pause, wav))
        seg_pieces.append(items)

    # Pha 2 — sinh tất cả wav trong 1 lần nạp model.
    run_batch(jobs)

    # Pha 3 — ghép từng segment: wav→mp3 + chèn im lặng + nối.
    voiced: list[Segment] = []
    for i, seg in enumerate(script.segments):
        seg_path = _segment_audio_path(slug, profile, i)
        parts: list[Path] = []
        tmp: list[Path] = []
        for j, (_piece, pause, wav) in enumerate(seg_pieces[i]):
            raw = seg_path.with_name(f"{seg_path.stem}.p{j:02d}.mp3")
            _to_mp3(wav, raw, tempo=profile.f5_tempo)
            wav.unlink(missing_ok=True)
            parts.append(raw)
            tmp.append(raw)
            if pause > 0:
                sil = seg_path.with_name(f"{seg_path.stem}.s{j:02d}.mp3")
                _silence_mp3(pause, sil)
                parts.append(sil)
                tmp.append(sil)
        if profile.segment_sec > 0:
            sil = seg_path.with_name(f"{seg_path.stem}.send.mp3")
            _silence_mp3(profile.segment_sec, sil)
            parts.append(sil)
            tmp.append(sil)
        _concat_audio(parts, seg_path)
        for p in tmp:
            p.unlink(missing_ok=True)
        dur = _probe_duration(seg_path)
        voiced.append(replace(seg, audio_path=seg_path, duration_sec=dur))
    return voiced


def _segment_audio_path(slug: str, profile: VoiceProfile, index: int) -> Path:
    # Changing F5 tempo must not resume a segment rendered at an older speed.
    # Edge has its own remote rate setting and keeps its existing cache key.
    f5_cache_key = f"_f5x{profile.f5_tempo:.2f}" if settings.tts_provider == "f5" else ""
    return AUDIO_DIR / f"{slug}_{profile.name}{f5_cache_key}_{index:02d}.mp3"


def _edge_rate_pct(edge_rate: str) -> int:
    """Parse edge-tts rate string (vd "+100%", "-4%") thành số nguyên % có dấu."""
    return int(edge_rate.strip().rstrip("%"))


def _voice_profile(script: Script) -> VoiceProfile:
    """Pick TTS pacing by content intent, not one news-reader voice for everything."""
    declared = getattr(script, "voice_profile", "")
    if declared == "inspiring":
        return VOICE_INSPIRING
    if declared == "knowledge":
        return VOICE_KNOWLEDGE
    haystack = " ".join([
        script.topic,
        script.title,
        script.description,
        " ".join(script.tags),
        " ".join(seg.caption for seg in script.segments),
        " ".join(seg.narration for seg in script.segments),
        " ".join(seg.broll for seg in script.segments),
    ]).lower()
    if any(hint in haystack for hint in _ENTERTAINMENT_HINTS):
        return VOICE_ENTERTAINMENT
    if any(hint in haystack for hint in _KNOWLEDGE_HINTS):
        return VOICE_KNOWLEDGE
    return VOICE_NEUTRAL


def _prepare_narration(text: str) -> str:
    """Remove leaked visual/stage directions before TTS reads them out loud."""
    cleaned = text.strip()
    for pattern in _STAGE_DIRECTION_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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


def _synth_segment(text: str, voice: str, out_mp3: Path, profile: VoiceProfile | None = None) -> None:
    """Tổng hợp 1 segment với nhịp ngắt nghỉ: synth từng cụm + chèn khoảng lặng,
    rồi nối lại. Khoảng lặng cuối = pause giữa segment (để video đỡ đọc một lèo)."""
    profile = profile or VOICE_NEUTRAL

    text = _prepare_narration(text)
    pieces = _split_for_pacing(text, profile.comma_sec, profile.sentence_sec) or [(text.strip(), 0.0)]

    parts: list[Path] = []
    tmp: list[Path] = []
    for i, (piece, pause) in enumerate(pieces):
        raw = out_mp3.with_name(f"{out_mp3.stem}.p{i:02d}.mp3")
        _synth_raw(piece, voice, raw, profile)
        parts.append(raw)
        tmp.append(raw)
        if pause > 0:
            sil = out_mp3.with_name(f"{out_mp3.stem}.s{i:02d}.mp3")
            _silence_mp3(pause, sil)
            parts.append(sil)
            tmp.append(sil)

    if profile.segment_sec > 0:
        sil = out_mp3.with_name(f"{out_mp3.stem}.send.mp3")
        _silence_mp3(profile.segment_sec, sil)
        parts.append(sil)
        tmp.append(sil)

    _concat_audio(parts, out_mp3)
    for p in tmp:
        p.unlink(missing_ok=True)


def _synth_raw(text: str, voice: str, out_mp3: Path, profile: VoiceProfile | None = None) -> None:
    """Dispatch theo provider; CHUẨN HOÁ về mp3 44100/stereo/192k để concat copy an toàn."""
    if settings.tts_provider == "f5":
        from .f5_provider import synthesize_f5

        wav = out_mp3.with_suffix(".f5.wav")
        synthesize_f5(text, wav)
        _to_mp3(wav, out_mp3, tempo=(profile or VOICE_NEUTRAL).f5_tempo)
        wav.unlink(missing_ok=True)
    else:
        raw = out_mp3.with_suffix(".edge.mp3")
        asyncio.run(_tts(text, voice, raw, profile or VOICE_NEUTRAL))
        _to_mp3(raw, out_mp3)
        raw.unlink(missing_ok=True)


def _silence_mp3(seconds: float, out: Path) -> None:
    """Sinh 1 đoạn im lặng mp3 cùng định dạng (44100/stereo/192k) với giọng đọc."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out)],
        capture_output=True, check=True,
    )


def _to_mp3(src: Path, dst: Path, *, tempo: float = 1.0) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    # TTS providers commonly add encoder/trailing silence to every short
    # phrase.  Because `_synth_segment` concatenates many phrases, that
    # provider padding can dominate short scripts and trip the audio QA gate.
    # Trim only silence at each provider file boundary; intentional pauses are
    # generated separately by `_silence_mp3` and therefore remain intact.
    filters = [
        "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB:"
        "stop_periods=1:stop_duration=0.12:stop_threshold=-50dB"
    ]
    if abs(tempo - 1.0) > 0.001:
        filters.append(f"atempo={tempo:.3f}")
    cmd += ["-filter:a", ",".join(filters)]
    cmd += ["-ar", "44100", "-ac", "2", "-b:a", "192k", str(dst)]
    subprocess.run(cmd, capture_output=True, check=True)


TTS_MAX_RETRIES = 3
TTS_RETRY_DELAY = 2.0  # giây


async def _tts(text: str, voice: str, out: Path, profile: VoiceProfile | None = None) -> None:
    """Gọi edge-tts; retry khi rớt mạng (NoAudioReceived) — lỗi transient hay gặp."""
    profile = profile or VOICE_NEUTRAL
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        try:
            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=profile.edge_rate,
                pitch=profile.edge_pitch,
            )
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
