#!/usr/bin/env python3
"""Verify + học phiên âm 1 từ Anh/brand cho F5-TTS, bằng round-trip ASR.

Vòng lặp: sinh thử audio cho từng candidate phiên âm bằng F5-TTS (giọng đã
clone của project) -> chạy whisper-cli (model medium, tiếng Việt) ASR lại ->
so khớp text ASR với candidate. Candidate nào TTS đọc rõ thì ASR sẽ nghe ra
GẦN ĐÚNG candidate đó (vì candidate đã là tiếng Việt thuần) — độ khớp cao =
phát âm rõ, không méo/nuốt. Candidate thắng được LƯU VĨNH VIỄN vào
assets/ref/pronunciation_overrides.json — các lần dùng `voice` sau tự áp dụng
qua `pronunciation.normalize_for_speech()`, không cần verify lại.

Dùng:
    python3 scripts/verify_pronunciation.py PLUFIT
        # tự sinh 1 candidate bằng engine quy tắc rồi verify

    python3 scripts/verify_pronunciation.py PLUFIT "Plu-phít" "Pờ-lu-phít"
        # tự thêm các candidate này vào danh sách thử (ưu tiên hơn engine)

Yêu cầu: whisper-cli (`brew install whisper-cpp`) + model
~/whisper-models/ggml-medium.bin (tải bằng tay 1 lần, xem README whisper.cpp).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ytb_pipeline.voiceover.f5_provider import synthesize_f5  # noqa: E402
from ytb_pipeline.voiceover.pronunciation import (  # noqa: E402
    save_override,
    similarity,
    transliterate_english,
)

WHISPER_MODEL = Path.home() / "whisper-models" / "ggml-medium.bin"
WHISPER_BIN = "whisper-cli"
PASS_THRESHOLD = 0.8
RUNS_PER_CANDIDATE = 2  # F5 có stochastic — lặp lại để tránh ăn may 1 lần

# Câu dẫn cố định để cắt bỏ trước khi so khớp — "Đây là" có thể bị ASR nghe
# nhầm thành biến thể khác ("Bấy là"...), KHÔNG liên quan tới candidate đang
# test, nên loại khỏi phần so khớp để khỏi làm méo điểm.
_CARRIER_WORDS = 2  # "đây/bấy là" = 2 từ đầu


def log(msg: str) -> None:
    print(f"[verify_pronunciation] {msg}")


def asr_transcribe(wav_path: Path) -> str:
    result = subprocess.run(
        [WHISPER_BIN, "-m", str(WHISPER_MODEL), "-f", str(wav_path),
         "-l", "vi", "--no-timestamps"],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _tail_after_carrier(text: str) -> str:
    """Cắt bỏ N từ đầu (câu dẫn "đây là"/biến thể ASR nghe nhầm) — chỉ so khớp
    phần ASR nghe ra TƯƠNG ỨNG với candidate, không lẫn lỗi của câu dẫn."""
    words = text.split()
    return " ".join(words[_CARRIER_WORDS:]) if len(words) > _CARRIER_WORDS else text


def try_candidate(candidate: str, tmp_dir: Path) -> tuple[str, float]:
    """Sinh + ASR lại candidate RUNS_PER_CANDIDATE lần, lấy điểm khớp THẤP NHẤT
    (worst-case) — 1 lần ăn may không đủ, phải đọc rõ ổn định mới qua được."""
    phrase = f"Đây là {candidate}."
    scores = []
    last_asr = ""
    for run in range(RUNS_PER_CANDIDATE):
        wav_path = tmp_dir / f"candidate_{run}.wav"
        log(f"Sinh thử ({run + 1}/{RUNS_PER_CANDIDATE}): \"{phrase}\"")
        synthesize_f5(phrase, wav_path)
        asr_text = asr_transcribe(wav_path)
        last_asr = asr_text
        score = similarity(_tail_after_carrier(asr_text), candidate)
        log(f"  ASR nghe ra: \"{asr_text}\" -> phần so khớp: "
            f"\"{_tail_after_carrier(asr_text)}\" (khớp {score:.0%})")
        scores.append(score)
    worst = min(scores)
    log(f"Điểm thấp nhất trong {RUNS_PER_CANDIDATE} lần: {worst:.0%}")
    return last_asr, worst


def main() -> None:
    if len(sys.argv) < 2:
        print("Dùng: python3 verify_pronunciation.py <từ> [candidate1] [candidate2] ...",
              file=sys.stderr)
        sys.exit(1)

    term = sys.argv[1]
    candidates = sys.argv[2:] or []
    auto_candidate = transliterate_english(term)
    if auto_candidate.lower() not in [c.lower() for c in candidates]:
        candidates.append(auto_candidate)
    log(f"Candidates cho '{term}': {candidates}")

    best_candidate, best_score = None, -1.0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for candidate in candidates:
            _, score = try_candidate(candidate, tmp_dir)
            if score > best_score:
                best_candidate, best_score = candidate, score

    print()
    if best_score >= PASS_THRESHOLD:
        save_override(term, best_candidate)
        log(f"ĐẠT — lưu '{term}' -> '{best_candidate}' (khớp {best_score:.0%}) "
            f"vào pronunciation_overrides.json. Áp dụng tự động từ giờ.")
    else:
        log(f"KHÔNG candidate nào đạt ngưỡng {PASS_THRESHOLD:.0%} "
            f"(tốt nhất: '{best_candidate}' @ {best_score:.0%}). "
            f"Thử thêm candidate khác: python3 verify_pronunciation.py "
            f"\"{term}\" \"<candidate mới>\"")
        sys.exit(1)


if __name__ == "__main__":
    main()
