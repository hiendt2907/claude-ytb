"""Nối các clip segment bằng xfade (mượt) + whoosh SFX ở ranh giới đánh dấu.

Thay cho concat `-c copy` cứng: mỗi ranh giới crossfade ~0.4s cho mượt; ranh giới
có `transition=True` (vd vấn đề->giải pháp) còn được trộn thêm một tiếng whoosh
tổng hợp (không cần asset ngoài — sinh bằng ffmpeg lavfi, cache lại).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

XFADE_SEC = 0.4
SFX_DIR = Path("assets/sfx")
WHOOSH = SFX_DIR / "whoosh.wav"


def whoosh_sfx() -> Path:
    """Đường dẫn tới whoosh.wav (sinh + cache lần đầu bằng noise sweep)."""
    if WHOOSH.exists() and WHOOSH.stat().st_size > 0:
        return WHOOSH
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:a=0.9",
         "-af", "highpass=f=250,lowpass=f=5000,"
                "afade=t=in:d=0.25,afade=t=out:st=0.25:d=0.3,volume=0.6",
         "-ar", "44100", "-ac", "2", str(WHOOSH)],
        capture_output=True, check=True,
    )
    return WHOOSH


def concat_with_transitions(clips: list[Path], whoosh_before: list[bool],
                            out: Path, *, xfade: float = XFADE_SEC) -> None:
    """Nối `clips` bằng xfade chuỗi; whoosh_before[k]=True -> whoosh tại ranh giới k.

    whoosh_before có cùng độ dài với clips; phần tử 0 bị bỏ qua (không có ranh
    giới trước clip đầu).
    """
    if len(clips) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(out)],
                       capture_output=True, check=True)
        return

    durs = [_duration(c) for c in clips]
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]

    # Chuẩn hoá audio mọi clip về 44.1kHz stereo (narration TTS có thể ≠ rate này)
    # để acrossfade không lỗi mismatch.
    apre = [f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo[na{k}]"
            for k in range(len(clips))]

    # Tính offset xfade chuỗi + thời điểm ranh giới (để đặt whoosh).
    vchain, achain = [], []
    boundary_t: list[float] = []
    running = durs[0]
    vlabel, alabel = "0:v", "na0"
    for k in range(1, len(clips)):
        off = running - xfade
        boundary_t.append(off)
        vout, aout = f"v{k}", f"a{k}"
        vchain.append(
            f"[{vlabel}][{k}:v]xfade=transition=fade:duration={xfade}:offset={off:.3f}[{vout}]"
        )
        achain.append(f"[{alabel}][na{k}]acrossfade=d={xfade}[{aout}]")
        vlabel, alabel = vout, aout
        running += durs[k] - xfade

    filt = apre + vchain + achain
    # Trộn whoosh tại các ranh giới đánh dấu.
    whoosh_idx = [k for k in range(1, len(clips)) if whoosh_before[k]]
    if whoosh_idx:
        sfx = whoosh_sfx()
        sfx_input_base = len(clips)
        for j, k in enumerate(whoosh_idx):
            inputs += ["-i", str(sfx)]
        amix_labels = [f"[{alabel}]"]
        for j, k in enumerate(whoosh_idx):
            delay_ms = int(max(0.0, boundary_t[k - 1]) * 1000)
            wlabel = f"w{j}"
            filt.append(
                f"[{sfx_input_base + j}:a]adelay={delay_ms}|{delay_ms}[{wlabel}]"
            )
            amix_labels.append(f"[{wlabel}]")
        filt.append(
            "".join(amix_labels)
            + f"amix=inputs={len(amix_labels)}:duration=first:normalize=0[aout]"
        )
        alabel = "aout"

    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
         "-map", f"[{vlabel}]", "-map", f"[{alabel}]",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         str(out)],
        capture_output=True, check=True,
    )


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())
