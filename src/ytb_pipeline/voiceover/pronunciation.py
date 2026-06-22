"""Chuẩn hoá phát âm cho TTS tiếng Việt.

edge-tts/F5-TTS giọng tiếng Việt đọc thuật ngữ Anh/brand theo luật chữ Việt -> sai
hoặc méo hoàn toàn (vd "PLUFIT" -> vô nghĩa). Module này thay thế các từ Anh/kỹ
thuật/brand bằng phiên âm tiếng Việt CHỈ trong chuỗi đẩy vào TTS. Caption/title
trên màn hình vẫn giữ nguyên chữ gốc — đây là yêu cầu cố định (brand muốn hiện
đúng tên gốc), KHÔNG phải lỗi cần "sửa kịch bản".

Hai lớp dữ liệu:
1. `PRONUNCIATION` — dict tay, thuật ngữ dev phổ biến đã biết chắc đọc đúng.
2. `OVERRIDES_FILE` (assets/ref/pronunciation_overrides.json) — học dần qua
   `scripts/verify_pronunciation.py`: mỗi từ mới (brand, thuật ngữ y tế/mỹ phẩm...)
   được thử phát âm bằng engine `transliterate_english()` dưới đây, verify lại
   bằng ASR (whisper), rồi LƯU VĨNH VIỄN vào đây khi đã xác nhận đọc rõ — không
   cần sửa code, không cần đoán lại từ đầu cho các lần dùng sau.

`transliterate_english()` là engine quy tắc: phiên âm một từ Anh CHƯA từng gặp
thành phiên âm tiếng Việt theo các quy tắc tương ứng âm phổ biến (kiểu báo chí
Việt phiên "Facebook" -> "Phây-búc", "format" -> "phoóc-mát"). Đây CHỈ là gợi ý
ban đầu — không có gì đảm bảo TTS đọc đúng như mong đợi cho tới khi qua
`verify_pronunciation.py` (sinh thử + ASR round-trip) xác nhận.

Khoá dict là chữ thường; so khớp theo ranh giới từ, không phân biệt hoa thường.
Cụm nhiều từ (vd "fork bomb") được thay trước token đơn để khỏi vỡ.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

# Phiên âm Việt cho thuật ngữ dev phổ biến. Mở rộng tự do khi gặp từ mới.
PRONUNCIATION: dict[str, str] = {
    # hệ điều hành / nền tảng
    "linux": "Li-nức",
    "ubuntu": "U-bun-tu",
    "windows": "Quin-đâu",
    "macos": "Mác Ô Ét",
    # vai trò / khái niệm
    "sysadmin": "sít-át-min",
    "admin": "át-min",
    "devops": "đép-ốp",
    "developer": "đi-ve-lốp-pơ",
    "server": "sơ-vơ",
    "client": "clai-ừn",
    "terminal": "tơ-mi-nồ",
    "shell": "sheo",
    "script": "scríp",
    # lệnh / công cụ hay đọc sai
    "fork bomb": "phọt bom",
    "fork": "phọt",
    "format": "phoóc-mát",
    "tool": "tu",
    "file": "phai",
    "folder": "phâu-đờ",
    "root": "rút",
    "backup": "bách-cấp",
    "deploy": "đi-ploi",
    "commit": "cờ-mít",
    # ký hiệu / lệnh chữ cái dễ nuốt
    "dd": "đi-đi",
    "ssh": "ét ét ách",
    "sql": "ét-queo",
    "api": "ây-pi-ai",
    "url": "u-rồ",
    "ram": "ram",
    "cpu": "xi-pi-iu",
}

OVERRIDES_FILE = (
    Path(__file__).resolve().parents[3] / "assets" / "ref" / "pronunciation_overrides.json"
)


def _load_overrides() -> dict[str, str]:
    if not OVERRIDES_FILE.exists():
        return {}
    return json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))


def save_override(term: str, pronunciation: str) -> None:
    """Lưu vĩnh viễn 1 mapping đã verify qua ASR — gọi từ verify_pronunciation.py."""
    overrides = _load_overrides()
    overrides[term.lower()] = pronunciation
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def _build_patterns() -> list[tuple[re.Pattern, str]]:
    merged = {**PRONUNCIATION, **_load_overrides()}
    ordered = sorted(merged.items(), key=lambda kv: -len(kv[0]))
    return [
        (re.compile(rf"(?<![\w-])({re.escape(term)})(?![\w-])", re.IGNORECASE), say)
        for term, say in ordered
    ]


def normalize_for_speech(text: str) -> str:
    """Trả về chuỗi đã phiên âm thuật ngữ Anh/brand sang tiếng Việt cho TTS.

    Nạp lại overrides mỗi lần gọi (rẻ — file nhỏ) để học từ mới không cần restart.
    """
    for pattern, say in _build_patterns():
        text = pattern.sub(say, text)
    return text


# ---------------------------------------------------------------------------
# Engine quy tắc: phiên âm từ Anh CHƯA biết -> gợi ý phiên âm tiếng Việt.
# Chỉ là GỢI Ý — phải qua verify_pronunciation.py xác nhận trước khi tin dùng.
# ---------------------------------------------------------------------------

_VOWELS = set("aeiouy")

# Khớp dài nhất trước. Nguyên tắc: ánh xạ theo ÂM (TTS tiếng Việt sẽ đọc ra),
# không phải copy chữ viết.
_VOWEL_DIGRAPHS: list[tuple[str, str]] = [
    ("igh", "ai"), ("augh", "a"), ("ough", "âu"),
    ("are", "e"), ("ire", "ai"), ("ore", "o"), ("ure", "iu"),
    ("ee", "i"), ("ea", "i"), ("oo", "u"), ("ou", "ao"), ("ow", "âu"),
    ("oy", "oi"), ("oi", "oi"), ("ay", "ây"), ("ai", "ai"),
    ("au", "ô"), ("aw", "ô"), ("ey", "ây"), ("ei", "ây"), ("ie", "i"), ("ue", "iu"),
    ("er", "ơ"), ("or", "ơ"), ("ir", "ơ"), ("ur", "ơ"), ("ar", "a"),
    ("a", "a"), ("e", "e"), ("i", "i"), ("o", "o"), ("u", "u"), ("y", "i"),
]

_CONSONANT_DIGRAPHS: list[tuple[str, str]] = [
    ("tch", "ch"), ("dge", "giơ"),
    ("th", "th"), ("ph", "ph"), ("ch", "ch"), ("sh", "s"), ("wh", "qu"),
    ("ck", "c"), ("qu", "qu"), ("ng", "ng"), ("nk", "nh"), ("ny", "nh"),
    ("x", "x"), ("z", "d"), ("j", "gi"), ("w", "qu"), ("v", "v"), ("f", "ph"),
    ("c", "c"), ("g", "g"), ("q", "c"),
]

# Phụ âm cuối tiếng Việt hợp lệ — âm cuối Anh không nằm trong tập này bị bỏ
# (Vietnamese chỉ có 8 phụ âm cuối: p t c m n ng nh ch).
_VALID_CODA = {"p", "t", "c", "m", "n", "ng", "nh", "ch"}
_CODA_VOICING = {"b": "p", "d": "t", "g": "c", "s": "t", "k": "c"}


def _syllabify(word: str) -> list[str]:
    """Tách theo nhóm nguyên âm (nucleus): phụ âm giữa 2 nguyên âm ưu tiên làm
    onset của âm tiết SAU (âm tiết mở) — cụm 2+ phụ âm thì 1 phụ âm cuối ở lại
    làm coda âm tiết trước, còn lại làm onset âm tiết sau.
    """
    spans = []  # (start, end) của từng nhóm nguyên âm liên tiếp
    i, n = 0, len(word)
    while i < n:
        if word[i] in _VOWELS:
            j = i
            while j < n and word[j] in _VOWELS:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    if not spans:
        return [word]

    syllables: list[str] = []
    prev_end = 0
    for idx, (vs, ve) in enumerate(spans):
        consonants = word[prev_end:vs]
        if idx == 0 or len(consonants) <= 1:
            onset = consonants
        else:
            onset = consonants[-1:]
            syllables[-1] += consonants[:-1]  # cụm thừa ở lại làm coda âm tiết trước
        syllables.append(onset + word[vs:ve])
        prev_end = ve
    syllables[-1] += word[prev_end:]  # phụ âm cuối từ thuộc về âm tiết cuối
    return syllables


def _map_chunk(chunk: str, table: list[tuple[str, str]]) -> tuple[str, str]:
    """Bóc phần đầu chunk khớp 1 mục trong table (dài nhất trước); trả (âm, phần còn lại)."""
    for pattern, sound in table:
        if chunk.startswith(pattern):
            return sound, chunk[len(pattern):]
    return "", chunk


def _map_syllable(syll: str) -> str:
    onset = ""
    rest = syll
    # onset: phụ âm đầu (nếu có) trước nguyên âm đầu tiên
    vowel_idx = next((i for i, c in enumerate(rest) if c in _VOWELS), len(rest))
    consonant_part, vowel_and_after = rest[:vowel_idx], rest[vowel_idx:]
    while consonant_part:
        sound, consonant_part = _map_chunk(consonant_part, _CONSONANT_DIGRAPHS)
        if not sound:  # ký tự lạ không khớp gì — giữ nguyên để khỏi mất âm
            sound, consonant_part = consonant_part[0], consonant_part[1:]
        onset += sound

    nucleus = ""
    coda = ""
    remaining = vowel_and_after
    matched_vowel = False
    for pattern, sound in _VOWEL_DIGRAPHS:
        if remaining.startswith(pattern):
            nucleus = sound
            remaining = remaining[len(pattern):]
            matched_vowel = True
            break
    if not matched_vowel and remaining:
        nucleus = remaining[0]
        remaining = remaining[1:]

    # phần còn lại sau nguyên âm = coda (phụ âm cuối âm tiết) — chỉ lấy phụ âm
    # ĐẦU TIÊN khớp 1 trong 8 coda hợp lệ tiếng Việt, phần dư bỏ (loanword
    # tiếng Việt luôn đơn giản hoá cụm phụ âm cuối, vd "format" -> "phoóc-mát").
    coda = ""
    for cand in sorted(_VALID_CODA, key=len, reverse=True):
        if remaining.startswith(cand):
            coda = cand
            break
    if not coda and remaining:
        voiced = _CODA_VOICING.get(remaining[0], remaining[0])
        if voiced in _VALID_CODA:
            coda = voiced

    return onset + nucleus + coda


def transliterate_english(word: str) -> str:
    """Gợi ý phiên âm tiếng Việt cho 1 từ Anh CHƯA có trong dict.

    CHỈ là gợi ý ban đầu (heuristic theo âm tiết) — dùng làm input cho
    `scripts/verify_pronunciation.py`, KHÔNG dùng trực tiếp vào TTS khi chưa
    verify qua ASR round-trip.
    """
    word = word.strip().lower()
    if not word:
        return word
    syllables = _syllabify(word)
    mapped = [_map_syllable(s) for s in syllables]
    mapped = [m for m in mapped if m]
    result = "-".join(mapped) if mapped else word
    return result[:1].upper() + result[1:]


def similarity(a: str, b: str) -> float:
    """Độ giống 0..1 giữa 2 chuỗi (dùng so ASR output với candidate phiên âm)."""
    norm = lambda s: re.sub(r"[^\w\s]", "", s.lower()).strip()
    return SequenceMatcher(None, norm(a), norm(b)).ratio()
