"""Ledger — lịch sử chủ đề đã tạo, chống Claude lặp lại ý tưởng cũ.

Rút gọn từ claude-ytb/ideation/series.py (slugify + dedup_topics), bỏ phần
lên lịch series 30 ngày (không cần cho video-render — mỗi lần chỉ tạo 1 kịch
bản). Lưu dạng JSON list (không phải markdown table như claude-ytb) vì đơn
giản hơn để đọc/ghi lại bằng code, không cần con người đọc trực tiếp.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import load_content_settings


@dataclass(frozen=True)
class LedgerEntry:
    slug: str
    title: str
    created_at: str


def slugify(text: str) -> str:
    """Chuẩn hoá tiêu đề -> slug ascii: bỏ dấu tiếng Việt, hạ thường, nối '-'."""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def _ledger_path() -> Path:
    return Path(load_content_settings().ledger_path)


def load_ledger(path: Path | None = None) -> list[LedgerEntry]:
    """Đọc ledger từ đĩa; trả [] nếu chưa từng tạo file (lần chạy đầu)."""
    path = path or _ledger_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [LedgerEntry(**item) for item in data]


def is_duplicate(title: str, ledger: list[LedgerEntry]) -> bool:
    """True nếu slug của `title` đã có trong ledger."""
    slug = slugify(title)
    return bool(slug) and any(entry.slug == slug for entry in ledger)


def filter_new_topics(topics: list[str], ledger: list[LedgerEntry]) -> list[str]:
    """Loại chủ đề mà slug đã có trong ledger — lưới AN TOÀN cấp slug (không
    phải chống trùng ngữ nghĩa, việc đó vẫn do Claude phán đoán khi tự chọn).
    Giữ thứ tự, loại trùng nội bộ danh sách luôn."""
    seen: set[str] = set()
    existing = {entry.slug for entry in ledger}
    kept: list[str] = []
    for topic in topics:
        slug = slugify(topic)
        if slug and slug not in seen and slug not in existing:
            seen.add(slug)
            kept.append(topic)
    return kept


def append_ledger(title: str, created_at: str, path: Path | None = None) -> LedgerEntry:
    """Ghi thêm 1 chủ đề mới vào ledger, atomic (qua file .tmp + replace)."""
    path = path or _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load_ledger(path)
    entry = LedgerEntry(slug=slugify(title), title=title, created_at=created_at)
    entries.append(entry)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return entry
