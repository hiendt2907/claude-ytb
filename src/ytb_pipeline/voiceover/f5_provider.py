"""Provider TTS local: F5-TTS fine-tune tiếng Việt (hynt/F5-TTS-Vietnamese-ViVoice).

Chạy trong venv riêng `.venv-tts` (Python 3.12) vì F5-TTS + torch chưa hỗ trợ
Python 3.14 của pipeline chính. Pipeline gọi sang đây qua subprocess CLI.

F5 là mô hình voice-clone zero-shot: cần 1 clip giọng mẫu (~6-10s) + transcript.
Giọng đọc của video = giọng trong `F5_REF_AUDIO`.

Bản ViVoice train 1000h; `config.json` đóng vai file vocab. Chạy trên MPS
(GPU Apple Silicon) ~10s/đoạn; CPU ~29s/đoạn.
"""

import json
import os
import re
import subprocess
import tempfile
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
F5_BATCH_WORKER = ROOT / "scripts" / "f5_batch_worker.py"

# F5-TTS trên MPS segfault (code -11/-6) với text quá dài. Chia nhỏ theo câu để an toàn.
F5_MAX_CHARS = 300

F5_PYTHON = ROOT / ".venv-tts" / "bin" / "python"
F5_CLI = ROOT / ".venv-tts" / "bin" / "f5-tts_infer-cli"
F5_CKPT = ROOT / "models" / "vivoice" / "model_last.pt"
F5_VOCAB = ROOT / "models" / "vivoice" / "config.json"
F5_MODEL_ARCH = "F5TTS_Base"  # kiến trúc nền của bản fine-tune Việt
F5_DEVICE = "mps"  # GPU Apple Silicon; đổi "cpu" nếu máy khác

F5_REF_AUDIO = ROOT / "assets" / "ref" / "narrator.wav"
F5_REF_TEXT_FILE = ROOT / "assets" / "ref" / "narrator.txt"


def _split_text(text: str, max_chars: int = F5_MAX_CHARS) -> list[str]:
    """Chia text dài thành các cụm ≤ max_chars, cắt ở ranh giới câu (. ! ? …).

    Câu đơn lẻ vẫn quá dài thì cắt thêm ở dấu phẩy. Không bao giờ vượt max_chars
    trừ khi một mệnh đề không có dấu ngắt nào.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # tách thành câu, GIỮ dấu kết câu
    sentences = re.findall(r"[^.!?…]+[.!?…]*\s*", text)
    pieces: list[str] = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= max_chars:
            pieces.append(sent)
        else:  # câu quá dài → cắt tiếp ở dấu phẩy
            buf = ""
            for clause in re.split(r"(?<=,)\s*", sent):
                if buf and len(buf) + len(clause) + 1 > max_chars:
                    pieces.append(buf.strip())
                    buf = clause
                else:
                    buf = f"{buf} {clause}".strip()
            if buf:
                pieces.append(buf.strip())

    # gộp các cụm nhỏ liền kề lại cho ít lần infer hơn (vẫn ≤ max_chars)
    chunks: list[str] = []
    for p in pieces:
        if chunks and len(chunks[-1]) + len(p) + 1 <= max_chars:
            chunks[-1] = f"{chunks[-1]} {p}"
        else:
            chunks.append(p)
    return chunks or [text]


def _f5_once(text: str, ref_text: str, out_path: Path) -> None:
    """Một lần infer F5-TTS cho 1 cụm text ngắn → ghi ra out_path."""
    cmd = [
        str(F5_CLI),
        "--model", F5_MODEL_ARCH,
        "--ckpt_file", str(F5_CKPT),
        "--vocab_file", str(F5_VOCAB),
        "--ref_audio", str(F5_REF_AUDIO),
        "--ref_text", ref_text,
        "--gen_text", text,
        "--output_dir", str(out_path.parent),
        "--output_file", out_path.name,
        "--device", F5_DEVICE,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"F5-TTS lỗi (code {result.returncode}):\n{result.stderr[-2000:]}"
        )


def _concat_wavs(parts: list[Path], out_path: Path) -> None:
    """Ghép nhiều wav thành 1 (re-encode pcm cho an toàn) bằng ffmpeg."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
        list_path = Path(f.name)
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c:a", "pcm_s16le", str(out_path)],
            capture_output=True, text=True,
        )
        if res.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"ffmpeg concat lỗi:\n{res.stderr[-1000:]}")
    finally:
        list_path.unlink(missing_ok=True)


def synthesize_f5(text: str, out_path: Path) -> None:
    """Sinh 1 đoạn audio (.wav) bằng F5-TTS Việt; tự chia nhỏ text dài. Raise nếu lỗi."""
    _require(F5_CLI, "F5-TTS CLI (chạy: .venv-tts/bin/pip install f5-tts)")
    _require(F5_CKPT, "checkpoint model_last.pt")
    _require(F5_VOCAB, "vocab.txt")
    _require(F5_REF_AUDIO, "giọng tham chiếu narrator.wav")
    _require(F5_REF_TEXT_FILE, "transcript narrator.txt")

    ref_text = F5_REF_TEXT_FILE.read_text(encoding="utf-8").strip()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = _split_text(text)
    if len(chunks) == 1:
        _f5_once(chunks[0], ref_text, out_path)
        return

    parts: list[Path] = []
    try:
        for i, chunk in enumerate(chunks):
            part = out_path.with_name(f"{out_path.stem}.part{i:02d}.wav")
            _f5_once(chunk, ref_text, part)
            parts.append(part)
        _concat_wavs(parts, out_path)
    finally:
        for p in parts:
            p.unlink(missing_ok=True)


def run_batch(jobs: list[dict]) -> None:
    """Sinh NHIỀU đoạn trong MỘT process F5 — nạp model 1 lần cho cả tập.

    `jobs`: list các dict {"text": str, "out": str(.wav)}. Gọi worker thường trú
    trong `.venv-tts`; stream tiến độ ra stdout. Raise nếu worker lỗi.

    Đây là đường nhanh thay cho việc gọi `synthesize_f5` từng cụm (mỗi lần nạp
    lại checkpoint 5.4GB). Giữ nguyên chunking 300 ký tự bên trong worker.
    """
    _require(F5_PYTHON, "Python .venv-tts")
    _require(F5_BATCH_WORKER, "worker batch f5")
    _require(F5_CKPT, "checkpoint model_last.pt")
    _require(F5_VOCAB, "vocab/config.json")
    _require(F5_REF_AUDIO, "giọng tham chiếu narrator.wav")
    _require(F5_REF_TEXT_FILE, "transcript narrator.txt")

    if not jobs:
        return

    ref_text = F5_REF_TEXT_FILE.read_text(encoding="utf-8").strip()
    manifest = {
        "model": F5_MODEL_ARCH,
        "ckpt": str(F5_CKPT),
        "vocab": str(F5_VOCAB),
        "device": F5_DEVICE,
        "ref_audio": str(F5_REF_AUDIO),
        "ref_text": ref_text,
        "max_chars": F5_MAX_CHARS,
        "jobs": jobs,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
        manifest_path = Path(f.name)

    # PYTHONHASHSEED hợp lệ để tiến trình con của torch không "Fatal Python error".
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    try:
        proc = subprocess.Popen(
            [str(F5_PYTHON), str(F5_BATCH_WORKER), str(manifest_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        )
        tail: deque[str] = deque(maxlen=80)
        for line in proc.stdout:  # stream tiến độ từng job
            line = line.rstrip()
            tail.append(line)
            if line.startswith("JOB ") or line.startswith("[f5-batch]"):
                print(f"    {line}", flush=True)
        code = proc.wait()
        if code != 0:
            details = "\n".join(tail)
            raise RuntimeError(f"F5 batch worker lỗi (code {code}):\n{details}")
    finally:
        manifest_path.unlink(missing_ok=True)


def _require(path: Path, what: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Thiếu {what}: {path}")
