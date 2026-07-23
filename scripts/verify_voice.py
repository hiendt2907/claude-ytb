#!/usr/bin/env python3
"""Local voice QA: transcript hook + audio metrics + waveform/spectrogram."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np


def _wav(path: Path) -> tuple[np.ndarray, int]:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path),
                        "-ac", "1", "-ar", "16000", str(target)], check=True)
        with wave.open(str(target), "rb") as f:
            return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768, f.getframerate()


def _pitch(samples: np.ndarray, rate: int) -> float | None:
    values: list[float] = []
    frame = int(rate * 0.04)
    for start in range(0, len(samples) - frame, frame // 2):
        x = samples[start:start + frame]
        if np.sqrt(np.mean(x * x)) < 0.01:
            continue
        x = x - np.mean(x)
        corr = np.correlate(x, x, mode="full")[len(x)-1:]
        lo, hi = max(1, int(rate / 350)), int(rate / 70)
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] > corr[0] * 0.25:
            values.append(rate / lag)
    return round(float(np.median(values)), 2) if values else None


def _render_graphics(audio: Path, out_dir: Path, stem: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    waveform = out_dir / f"{stem}.waveform.png"
    spectrum = out_dir / f"{stem}.spectrogram.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-filter_complex",
                    "showwavespic=s=1600x360:colors=DodgerBlue", str(waveform)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-lavfi",
                    "showspectrumpic=s=1600x600:legend=disabled", str(spectrum)], check=True)
    return {"waveform": str(waveform), "spectrogram": str(spectrum)}


def verify(audio: Path, out_dir: Path, expected_text: str = "") -> dict:
    samples, rate = _wav(audio)
    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    result = {
        "audio": str(audio),
        "duration_sec": round(len(samples) / rate, 3),
        "sample_rate": rate,
        "rms_db": round(20 * np.log10(max(rms, 1e-9)), 2),
        "peak_db": round(20 * np.log10(max(peak, 1e-9)), 2),
        "clipping_samples": int(np.sum(np.abs(samples) >= 0.999)),
        "median_pitch_hz": _pitch(samples, rate),
        "expected_text": expected_text,
        "transcription": {"status": "not_configured", "note": "Cài whisper.cpp hoặc openai-whisper để bật WER."},
    }
    result["graphics"] = _render_graphics(audio, out_dir, audio.stem)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("assets/voice_reports"))
    parser.add_argument("--expected-text", default="")
    args = parser.parse_args()
    report = verify(args.audio, args.out_dir, args.expected_text)
    target = args.out_dir / f"{args.audio.stem}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
