"""Khâu 2 — Voiceover (TTS).

Hai provider, chọn qua settings.tts_provider:
  - "edge" : edge-tts online, miễn phí, không cần key (mặc định).
  - "f5"   : F5-TTS local tiếng Việt (voice-clone), chạy trong .venv-tts.
"""

import asyncio
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

import edge_tts

from ..config.settings import settings
from ..content_contract import contract_for
from ..pkg.models import Script, Segment, Voiceover
from .pronunciation import normalize_for_speech

AUDIO_DIR = Path("assets/audio")
VOICE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "voice_profiles.json"

SENTENCE_PUNCT = ".!?…"
CLAUSE_PUNCT = ",;:"
# F5's acoustic model already produces natural Vietnamese pacing.  Applying
# ``atempo`` near 2x made the transcript gate recover only ~1% of a Long and
# is unpleasant for people too.  Keep post-processing within a small, audible
# range; contrast comes from pauses/pitch, not time-warping the voice.
MAX_F5_TEMPO = 1.18
# F5 has substantial per-inference overhead.  Sending every comma clause as a
# separate request makes a three-minute script fan out into dozens of tiny jobs
# (including two-character fragments), which is slow and harms prosody.
F5_MIN_INFERENCE_CHARS = 160


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    comma_sec: float
    sentence_sec: float
    segment_sec: float
    edge_rate: str = "+0%"
    edge_pitch: str = "+0Hz"
    f5_tempo: float = 1.0
    pitch_semitones: float = 0.0
    gain_db: float = 0.0
    pause_before: float = 0.0
    pause_after: float = 0.0


def _load_voice_config() -> dict:
    config = json.loads(VOICE_CONFIG_PATH.read_text(encoding="utf-8"))
    for name, values in config.get("profiles", {}).items():
        tempo = float(values.get("f5_tempo", 1.0))
        if not 0.95 <= tempo <= MAX_F5_TEMPO:
            raise ValueError(
                f"Voice profile {name!r} has unsafe F5 tempo {tempo}; "
                f"must be 0.95-{MAX_F5_TEMPO}."
            )
    return config


_VOICE_CONFIG = _load_voice_config()
VOICE_PROFILES = {
    name: VoiceProfile(name=name, **values)
    for name, values in _VOICE_CONFIG["profiles"].items()
}
VOICE_NEUTRAL = VOICE_PROFILES["neutral"]
VOICE_ENTERTAINMENT = VOICE_PROFILES["entertainment"]
VOICE_KNOWLEDGE = VOICE_PROFILES["knowledge"]
VOICE_INSPIRING = VOICE_PROFILES["inspiring"]
VOICE_SERIOUS = VOICE_PROFILES["serious"]
VOICE_HOOK = VOICE_PROFILES["hook"]
VOICE_CURIOUS = VOICE_PROFILES["curious"]
VOICE_CONCLUSION = VOICE_PROFILES["conclusion"]
_ROUTING = _VOICE_CONFIG["routing"]
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
    slug = _artifact_slug(script)
    profile = _voice_profile(script)

    # F5 local: nạp model 1 lần, sinh CẢ TẬP trong 1 process (đường nhanh).
    if settings.tts_provider == "f5":
        voiced = _synth_all_f5(script, slug, profile)
    else:
        voiced = _synth_all_edge_parallel(script, slug, profile)

    total = sum(s.duration_sec for s in voiced)
    # Provider timing can undershoot the audio contract by a fraction of a
    # second even when the script budget is valid. Heal only a tiny boundary
    # gap with silence; never hide a substantive runtime defect.
    lower, _ = contract_for(script.video_type).audio_runtime_bounds_sec(
        segment_count=len(voiced)
    )
    if total < lower and lower - total <= 2.0:
        gap = lower - total
        # Renderers compose the individual segment files, not only the merged
        # audio.  Pad the last segment before merging so voiceover, render, and
        # final-video timelines stay in the same contract.
        last = voiced[-1]
        if last.audio_path is None:
            raise ValueError("Không thể pad runtime: segment cuối thiếu audio_path.")
        _pad_audio(last.audio_path, gap)
        voiced[-1] = replace(last, duration_sec=last.duration_sec + gap)
        total = lower

    combined = AUDIO_DIR / f"{slug}_{profile.name}.mp3"
    _concat_audio([s.audio_path for s in voiced], combined)

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

    pending: list[tuple[int, Segment, Path, VoiceProfile]] = []
    voiced: list[Segment | None] = [None] * len(script.segments)

    for i, seg in enumerate(script.segments):
        segment_profile = _segment_profile(seg, profile, i, len(script.segments))
        seg_path = _segment_audio_path(slug, segment_profile, i, narration=seg.narration, voice=script.voice)
        dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
        if dur > 0:
            voiced[i] = replace(seg, audio_path=seg_path, duration_sec=dur)
        else:
            pending.append((i, seg, seg_path, segment_profile))

    def _work(item: tuple[int, Segment, Path, VoiceProfile]) -> tuple[int, Segment]:
        i, seg, seg_path, segment_profile = item
        _synth_segment(_prepare_narration(seg.narration), script.voice, seg_path, segment_profile)
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
        segment_profile = _segment_profile(seg, profile, i, len(script.segments))
        seg_path = _segment_audio_path(slug, segment_profile, i, narration=seg.narration, voice=script.voice)
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
    segment_profiles: list[VoiceProfile] = []
    jobs: list[dict] = []
    for i, seg in enumerate(script.segments):
        segment_profile = _segment_profile(seg, profile, i, len(script.segments))
        segment_profiles.append(segment_profile)
        narration = _prepare_narration(seg.narration)
        pacing_pieces = _split_for_pacing(
            narration, segment_profile.comma_sec, segment_profile.sentence_sec
        ) or [(narration, 0.0)]
        # Unlike Edge TTS, F5 must not infer each comma clause independently.
        # Preserve text and the pause at each grouped boundary while sending
        # sufficiently substantial utterances to the acoustic model.
        pieces = _coalesce_f5_pieces(pacing_pieces)
        items: list[tuple[str, float, Path]] = []
        for j, (piece, pause) in enumerate(pieces):
            wav = _f5_piece_audio_path(AUDIO_DIR, slug, profile.name, i, j, piece)
            jobs.append({"text": piece, "out": str(wav)})
            items.append((piece, pause, wav))
        seg_pieces.append(items)

    # Pha 2 — sinh tất cả wav trong 1 lần nạp model.
    run_batch(jobs)

    # Pha 3 — ghép từng segment: wav→mp3 + chèn im lặng + nối.
    voiced: list[Segment] = []
    for i, seg in enumerate(script.segments):
        segment_profile = segment_profiles[i]
        seg_path = _segment_audio_path(slug, segment_profile, i, narration=seg.narration, voice=script.voice)
        parts: list[Path] = []
        tmp: list[Path] = []
        for j, (_piece, pause, wav) in enumerate(seg_pieces[i]):
            raw = seg_path.with_name(f"{seg_path.stem}.p{j:02d}.mp3")
            _to_mp3(wav, raw, profile=segment_profiles[i])
            wav.unlink(missing_ok=True)
            parts.append(raw)
            tmp.append(raw)
            if pause > 0:
                sil = seg_path.with_name(f"{seg_path.stem}.s{j:02d}.mp3")
                _silence_mp3(pause, sil)
                parts.append(sil)
                tmp.append(sil)
        if segment_profile.pause_before > 0:
            sil = seg_path.with_name(f"{seg_path.stem}.s-before.mp3")
            _silence_mp3(segment_profile.pause_before, sil)
            parts.insert(0, sil)
            tmp.append(sil)
        if segment_profile.pause_after > 0:
            sil = seg_path.with_name(f"{seg_path.stem}.s-after.mp3")
            _silence_mp3(segment_profile.pause_after, sil)
            parts.append(sil)
            tmp.append(sil)
        if segment_profile.segment_sec > 0:
            sil = seg_path.with_name(f"{seg_path.stem}.send.mp3")
            _silence_mp3(segment_profile.segment_sec, sil)
            parts.append(sil)
            tmp.append(sil)
        _concat_audio(parts, seg_path)
        for p in tmp:
            p.unlink(missing_ok=True)
        dur = _probe_duration(seg_path)
        voiced.append(replace(seg, audio_path=seg_path, duration_sec=dur))
    return voiced


def _segment_audio_path(
    slug: str,
    profile: VoiceProfile,
    index: int,
    *,
    narration: str,
    voice: str,
) -> Path:
    """Return a content-addressed audio-cache path for every TTS provider."""
    from .f5_provider import F5_DEVICE, F5_INFERENCE_SPEED

    payload = {
        "narration": _prepare_narration(narration),
        "voice": voice,
        "provider": settings.tts_provider,
        "model": getattr(settings, "xkiro_model", "") if settings.tts_provider == "xkiro" else "",
        "profile": vars(profile),
        "edge_rate_override": settings.edge_tts_rate_override,
        "f5_device": F5_DEVICE,
        "f5_speed": F5_INFERENCE_SPEED,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    if settings.tts_provider == "edge":
        rate = settings.edge_tts_rate_override or profile.edge_rate
        rate_label = f"edge{'p' if _edge_rate_pct(rate) >= 0 else 'm'}{abs(_edge_rate_pct(rate))}"
    elif settings.tts_provider == "f5":
        rate_label = f"f5x{profile.f5_tempo:.2f}s{F5_INFERENCE_SPEED:.3f}"
    else:
        rate_label = settings.tts_provider
    return AUDIO_DIR / f"{slug}_{profile.name}_{index:02d}_{rate_label}_{digest}.mp3"


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
    if any(hint in haystack for hint in _ROUTING["entertainment_hints"]):
        return VOICE_ENTERTAINMENT
    if any(hint in haystack for hint in _ROUTING["knowledge_hints"]):
        return VOICE_KNOWLEDGE
    return VOICE_NEUTRAL


def _auto_voice_style(segment: Segment, index: int, total: int) -> str:
    """Choose a restrained performance style from script semantics."""
    text = f"{segment.narration} {segment.caption}".lower()
    for rule in _ROUTING["rules"]:
        condition = rule["when"]
        hints = _ROUTING.get(rule.get("hints_key", ""), [])
        if condition == "hook_or_first" and (segment.hook or index == 0):
            return rule["profile"]
        if condition == "danger_or_hint" and (segment.danger or any(k in text for k in hints)):
            return rule["profile"]
        if condition == "last_or_hint" and (index == total - 1 or any(k in text for k in hints)):
            return rule["profile"]
        if condition == "question_or_hint" and ("?" in text or any(k in text for k in hints)):
            return rule["profile"]
    return ""


def _segment_profile(segment: Segment, default: VoiceProfile,
                     index: int = 0, total: int = 1) -> VoiceProfile:
    """Resolve and validate per-segment performance without mutating segment."""
    explicit = segment.voice_style.strip().lower() if segment.voice_style else ""
    name = explicit or _auto_voice_style(segment, index, total) or default.name
    try:
        base = VOICE_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"voice_style không hợp lệ: {segment.voice_style!r}") from exc
    tempo = base.f5_tempo if segment.voice_tempo is None else float(segment.voice_tempo)
    pitch = base.pitch_semitones if segment.voice_pitch is None else float(segment.voice_pitch)
    gain = base.gain_db if segment.voice_gain is None else float(segment.voice_gain)
    if segment.voice_tempo is not None and not 0.88 <= tempo <= 1.12:
        raise ValueError("voice_tempo phải nằm trong khoảng 0.88–1.12")
    if segment.voice_pitch is not None and not -2.0 <= pitch <= 2.0:
        raise ValueError("voice_pitch phải nằm trong khoảng -2–2 semitone")
    if segment.voice_gain is not None and not -3.0 <= gain <= 3.0:
        raise ValueError("voice_gain phải nằm trong khoảng -3–3 dB")
    before = base.pause_before if segment.voice_pause_before is None else float(segment.voice_pause_before)
    after = base.pause_after if segment.voice_pause_after is None else float(segment.voice_pause_after)
    if before < 0 or after < 0 or before > 2 or after > 2:
        raise ValueError("voice_pause phải nằm trong khoảng 0–2 giây")
    return replace(base, f5_tempo=tempo, pitch_semitones=pitch, gain_db=gain,
                   pause_before=before, pause_after=after)


def _prepare_narration(text: str) -> str:
    """Clean stage directions AND fix pronunciation before TTS reads the line.

    `pronunciation.normalize_for_speech` shipped with a table, a learnable
    override file and no caller: 103 statements at 0% coverage. Nothing stood
    between a written word and the voice, so an English term was read as
    English and a name the voice does not recognise was spelled out letter by
    letter — the published Gate-1 videos say "mờ i nờ hờ" for "Minh", and no
    supported lever existed to correct it.
    """
    cleaned = text.strip()
    for pattern in _STAGE_DIRECTION_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return normalize_for_speech(cleaned)


# "Đọc được" = có ít nhất một chữ cái hoặc chữ số; dấu câu đơn thuần thì không.
_SPEAKABLE_RE = re.compile(r"[^\W_]", re.UNICODE)


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

    out = _merge_unspeakable_pieces(out)
    if out:
        out[-1] = (out[-1][0], 0.0)  # cụm cuối: nghỉ ở mức segment, không ở đây
    return out


def _merge_unspeakable_pieces(pieces: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Gộp cụm không có chữ nào vào cụm liền trước, giữ khoảng nghỉ dài hơn.

    Dấu đóng ngoặc kép không nằm trong bảng dấu ngắt, nên `“...”.` bị tách thành
    một cụm riêng chỉ gồm `”.` — không có gì để đọc. xKiro trả HTTP 400 cho một
    input như vậy và cả segment hỏng, dù kịch bản hoàn toàn hợp lệ. Đây là lý do
    lỗi chỉ xuất hiện ở vài kịch bản có ngoặc kép chứ không phải mọi kịch bản.

    Gộp thay vì bỏ để không mất khoảng nghỉ mà dấu câu đó biểu thị.
    """
    merged: list[tuple[str, float]] = []
    for text, pause in pieces:
        if _SPEAKABLE_RE.search(text) or not merged:
            merged.append((text, pause))
            continue
        previous_text, previous_pause = merged[-1]
        merged[-1] = (f"{previous_text}{text}", max(previous_pause, pause))
    # Cụm đầu tiên cũng có thể không đọc được; khi đó gộp xuôi vào cụm kế.
    if merged and not _SPEAKABLE_RE.search(merged[0][0]):
        if len(merged) == 1:
            return []
        head_text, head_pause = merged[0]
        next_text, next_pause = merged[1]
        merged[1] = (f"{head_text}{next_text}", max(head_pause, next_pause))
        merged.pop(0)
    return merged


def _coalesce_f5_pieces(
    pieces: list[tuple[str, float]], *, min_chars: int = F5_MIN_INFERENCE_CHARS,
    max_chars: int = 300,
) -> list[tuple[str, float]]:
    """Group pacing clauses into efficient, bounded F5 inference requests.

    F5 retains punctuation within a grouped utterance, so its native prosody
    handles internal commas/sentences.  Only the pause belonging to the final
    clause of a group is inserted externally.  The function is deterministic,
    keeps every word, and never exceeds the provider's text limit.
    """
    if min_chars <= 0 or max_chars < min_chars:
        raise ValueError("F5 coalescing requires 0 < min_chars <= max_chars.")

    grouped: list[tuple[str, float]] = []
    current_text = ""
    current_pause = 0.0
    for text, pause in pieces:
        text = text.strip()
        if not text:
            continue
        candidate = f"{current_text} {text}".strip() if current_text else text
        if current_text and len(candidate) > max_chars:
            grouped.append((current_text, current_pause))
            current_text, current_pause = text, pause
        else:
            current_text, current_pause = candidate, pause
        if len(current_text) >= min_chars:
            grouped.append((current_text, current_pause))
            current_text, current_pause = "", 0.0
    if current_text:
        grouped.append((current_text, current_pause))
    if grouped:
        grouped[-1] = (grouped[-1][0], 0.0)
    return grouped


def _f5_piece_audio_path(
    audio_dir: Path, slug: str, profile_name: str, segment_index: int,
    piece_index: int, text: str, *, inference_speed: float | None = None,
    inference_device: str | None = None,
) -> Path:
    """Return a resumable F5 cache path bound to text, calibration, and backend."""
    if inference_speed is None or inference_device is None:
        from .f5_provider import F5_DEVICE, F5_INFERENCE_SPEED
        if inference_device is None:
            inference_device = F5_DEVICE
        if inference_speed is None:
            inference_speed = F5_INFERENCE_SPEED
    digest_input = f"{inference_device}\\0{float(inference_speed):.3f}\\0{text}".encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()[:12]
    return audio_dir / (
        f"{slug}_{profile_name}_{segment_index:02d}.p{piece_index:02d}.{digest}.f5.wav"
    )


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

    if profile.pause_before > 0:
        sil = out_mp3.with_name(f"{out_mp3.stem}.s-before.mp3")
        _silence_mp3(profile.pause_before, sil)
        parts.insert(0, sil)
        tmp.append(sil)
    if profile.pause_after > 0:
        sil = out_mp3.with_name(f"{out_mp3.stem}.s-after.mp3")
        _silence_mp3(profile.pause_after, sil)
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


def _to_mp3(src: Path, dst: Path, *, tempo: float = 1.0,
            profile: VoiceProfile | None = None) -> None:
    if profile is not None:
        tempo = profile.f5_tempo
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
    if profile is not None and abs(profile.pitch_semitones) > 0.001:
        # Homebrew's ffmpeg often lacks rubberband.  Resample + inverse atempo
        # changes pitch while preserving duration and works with stock ffmpeg.
        ratio = 2 ** (profile.pitch_semitones / 12)
        filters.extend([
            f"asetrate=44100*{ratio:.6f}",
            "aresample=44100",
            f"atempo={1 / ratio:.6f}",
        ])
    if profile is not None and abs(profile.gain_db) > 0.001:
        filters.append(f"volume={profile.gain_db:.3f}dB")
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
                rate=settings.edge_tts_rate_override or profile.edge_rate,
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
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2",
         "-b:a", "192k", str(out)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def _pad_audio(path: Path, seconds: float) -> None:
    padded = path.with_suffix(".padded.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-f", "lavfi", "-t", f"{seconds:.3f}",
         "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex",
         "[0:a][1:a]concat=n=2:v=0:a=1", "-ar", "44100", "-ac", "2",
         "-b:a", "192k", str(padded)],
        capture_output=True, check=True,
    )
    padded.replace(path)


def _slugify(text: str) -> str:
    import re
    import unicodedata

    # NFKD does not decompose Vietnamese Đ/đ, so map them before ASCII folding.
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "video"


def _artifact_slug(script: Script) -> str:
    """Prefer the immutable queue/project slug over an editable title."""
    return _slugify(script.project_id or script.title)
