#!/usr/bin/env python3
"""Worker F5-TTS batch — NẠP MODEL 1 LẦN, sinh toàn bộ đoạn của 1 tập.

Chạy trong `.venv-tts` (Python 3.12). Pipeline chính gọi sang đây MỘT lần/tập
qua subprocess, thay vì cold-start CLI cho từng cụm (mỗi cold-start nạp lại
checkpoint 5.4GB -> cực chậm). Đây là cách rút voiceover từ ~60-80' xuống vài phút.

Giao tiếp qua 1 file manifest JSON:
  {
    "model": "F5TTS_Base", "ckpt": "...", "vocab": "...", "device": "mps",
    "ref_audio": "...", "ref_text": "...", "max_chars": 300,
    "jobs": [{"text": "...", "out": "/abs/path.wav"}, ...]
  }

In ra mỗi job 1 dòng `JOB i/n ok <out>` (flush) để pipeline cha theo dõi tiến độ.
Thoát code != 0 nếu bất kỳ job nào lỗi.

Resume: nếu `out` đã tồn tại và là wav hợp lệ (vd lần trước bị `ytb batch stop` dừng
giữa batch), job được bỏ qua (`JOB i/n skip (đã có) <out>`) — cho phép chạy lại
đúng từ job bị dừng, không render lại từ đầu.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# F5/Torch may create Python helper processes after this daemon has started.
# Set the seed in the worker environment itself (not only in Popen's env) so
# every helper inherits a value CPython accepts during pre-initialization.
os.environ["PYTHONHASHSEED"] = "0"

# CPython only accepts values in [0, 2**32 - 1] for PYTHONHASHSEED.  F5-TTS
# otherwise generates a random value up to sys.maxsize on every inference and
# exports it to this process environment, which can make later Python helpers
# abort during interpreter startup on 64-bit macOS.
_PYTHON_HASH_SEED_MAX = (2**32) - 1


def _inference_seed(manifest: dict) -> int:
    """Return the validated deterministic seed used for every F5 inference."""
    raw_seed = manifest.get("inference_seed", 0)
    if isinstance(raw_seed, bool):
        raise ValueError("inference_seed phải là số nguyên không âm")
    try:
        seed = int(raw_seed)
    except (TypeError, ValueError) as exc:
        raise ValueError("inference_seed phải là số nguyên") from exc
    if not 0 <= seed <= _PYTHON_HASH_SEED_MAX:
        raise ValueError(f"inference_seed phải nằm trong 0..{_PYTHON_HASH_SEED_MAX}")
    return seed


def _validate_daemon_request_speed(request: dict, manifest: dict) -> None:
    """Reject daemon jobs calibrated for a different acoustic speed."""
    if "inference_speed" not in request:
        raise ValueError("Daemon request thiếu inference_speed.")
    requested = _inference_speed(request)
    expected = _inference_speed(manifest)
    if requested != expected:
        raise ValueError(
            f"Daemon inference_speed không khớp: request={requested:.2f}, daemon={expected:.2f}."
        )


def _is_valid_wav(path: Path) -> bool:
    """True nếu `path` là wav đọc được và có frame — chặn file dở dang do bị kill giữa lúc ghi."""
    try:
        with wave.open(str(path), "rb") as f:
            return f.getnframes() > 0
    except (wave.Error, EOFError, OSError):
        return False


def _split_text(text: str, max_chars: int) -> list[str]:
    """Chia text dài thành cụm ≤ max_chars, cắt ở ranh giới câu rồi tới dấu phẩy.

    GIỮ Y HỆT logic f5_provider._split_text — F5 trên MPS segfault với text quá dài.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    sentences = re.findall(r"[^.!?…]+[.!?…]*\s*", text)
    pieces: list[str] = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= max_chars:
            pieces.append(sent)
        else:
            buf = ""
            for clause in re.split(r"(?<=,)\s*", sent):
                if buf and len(buf) + len(clause) + 1 > max_chars:
                    pieces.append(buf.strip())
                    buf = clause
                else:
                    buf = f"{buf} {clause}".strip()
            if buf:
                pieces.append(buf.strip())
    return pieces or [text]


def _concat_wavs(parts: list[Path], out: Path) -> None:
    """Nối nhiều wav thành 1 (pcm an toàn) bằng ffmpeg hệ thống."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
        list_path = Path(f.name)
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c:a", "pcm_s16le", str(out)],
            capture_output=True, text=True,
        )
        if res.returncode != 0 or not out.exists():
            raise RuntimeError(f"ffmpeg concat lỗi:\n{res.stderr[-1000:]}")
    finally:
        list_path.unlink(missing_ok=True)


def _load_tts(manifest: dict):
    """Load the model once; a daemon keeps this object resident across videos."""
    from f5_tts.api import F5TTS

    print(f"[f5-batch] nạp model {manifest['model']} ({manifest['device']})…", flush=True)
    tts = F5TTS(
        model=manifest["model"],
        ckpt_file=manifest["ckpt"],
        vocab_file=manifest["vocab"],
        device=manifest["device"],
    )
    print("[f5-batch] model sẵn sàng", flush=True)
    return tts


def _run_jobs(tts, manifest: dict, emit=print) -> int:
    jobs = manifest["jobs"]
    max_chars = int(manifest.get("max_chars", 300))
    ref_audio = manifest["ref_audio"]
    ref_text = manifest["ref_text"]
    inference_seed = _inference_seed(manifest)

    emit(f"[f5-batch] nhận {len(jobs)} job", flush=True)

    n = len(jobs)
    for i, job in enumerate(jobs, 1):
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)

        # Resume: job này đã render xong ở lần chạy trước (bị dừng giữa batch) ->
        # bỏ qua, không nạp lại model/render lại — đây là điểm mấu chốt để resume
        # đúng ngay job bị dừng (vd job 200/250) chứ không chạy lại từ job 1.
        if out.exists() and _is_valid_wav(out):
            emit(f"JOB {i}/{n} skip (đã có) {out}", flush=True)
            continue

        chunks = _split_text(job["text"], max_chars)

        if len(chunks) <= 1:
            tts.infer(ref_file=ref_audio, ref_text=ref_text,
                      gen_text=chunks[0] if chunks else job["text"],
                      file_wave=str(out), remove_silence=False,
                      seed=inference_seed)
        else:
            parts: list[Path] = []
            try:
                for k, chunk in enumerate(chunks):
                    part = out.with_name(f"{out.stem}.c{k:02d}.wav")
                    tts.infer(ref_file=ref_audio, ref_text=ref_text,
                              gen_text=chunk, file_wave=str(part),
                              remove_silence=False, seed=inference_seed)
                    parts.append(part)
                _concat_wavs(parts, out)
            finally:
                for p in parts:
                    p.unlink(missing_ok=True)

        if not out.exists():
            emit(f"[f5-batch] LỖI job {i}/{n}: không tạo được {out}", flush=True)
            return 1
        emit(f"JOB {i}/{n} ok {out}", flush=True)

    emit("[f5-batch] xong toàn bộ", flush=True)
    return 0


def _serve(socket_path: Path, manifest: dict) -> int:
    """Serve one job list at a time while retaining the loaded model."""
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(4)
    try:
        tts = _load_tts(manifest)
        while True:
            conn, _ = server.accept()
            with conn, conn.makefile("rwb") as stream:
                request = json.loads(stream.readline())
                if request.get("command") == "shutdown":
                    stream.write(b'{"event":"done"}\n')
                    stream.flush()
                    return 0

                def emit(line: str, **_ignored) -> None:
                    stream.write(json.dumps({"event": "progress", "line": line}, ensure_ascii=False).encode("utf-8") + b"\n")
                    stream.flush()

                try:
                    _validate_daemon_request_speed(request, manifest)
                    code = _run_jobs(tts, {**manifest, "jobs": request["jobs"]}, emit=emit)
                    if code:
                        stream.write(json.dumps({"event": "error", "detail": f"job worker exit {code}"}).encode("utf-8") + b"\n")
                    else:
                        stream.write(b'{"event":"done"}\n')
                    stream.flush()
                except Exception as exc:  # noqa: BLE001 -- return daemon errors to the requesting lane
                    stream.write(json.dumps({"event": "error", "detail": str(exc)}, ensure_ascii=False).encode("utf-8") + b"\n")
                    stream.flush()
    finally:
        server.close()
        socket_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.serve:
        return _serve(args.serve, manifest)
    return _run_jobs(_load_tts(manifest), manifest)


if __name__ == "__main__":
    sys.exit(main())
