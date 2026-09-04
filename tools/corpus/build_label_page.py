"""Emit the human-labelling page for the golden corpus.

The corpus records what the MACHINE decided. Calibration needs what a person
decides, scored without seeing the machine first — so this page shows the
transcript alone, takes the five dimension scores, and only then reveals the
recorded verdict for comparison.

Selection favours entries whose LLM rubric scores survived the hash join: those
give a direct human-vs-rubric pair on the same text. The rest fill in from the
stratified corpus so both profiles and both outcomes are represented.

    PYTHONPATH=src .venv/bin/python tools/corpus/build_label_page.py --write
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "assets" / "golden_corpus" / "editorial.json"
TEMPLATE = Path(__file__).resolve().parent / "label_page.html"
OUT = ROOT / "assets" / "golden_corpus" / "label_page.html"

TARGET = 20
_PLACEHOLDER = "/*__CORPUS_DATA__*/null"

_DIMENSION_HELP = {
    "causal_coherence": "Chuyện có nhân quả thật không, hay chỉ là các cảnh xếp cạnh nhau?",
    "human_truth": "Người trong truyện cư xử như người thật, hay như minh hoạ cho một luận điểm?",
    "role_fidelity": "Mỗi người nói đúng vai mình — chủ quán không hoá thành nhà trị liệu?",
    "spoken_naturalness": "Đọc thành tiếng một hơi được không, hay là văn viết đeo vào miệng người?",
    "useful_restraint": "Có kìm được việc rút đạo lý hộ người xem không?",
}


def _sections_of(source: str) -> list[dict[str, str]]:
    path = ROOT / source
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    out: list[dict[str, str]] = []
    for section in payload.get("sections", []):
        if not isinstance(section, dict):
            continue
        voiceover = str(section.get("voiceover") or "").strip()
        if not voiceover:
            continue
        out.append(
            {
                "speaker": str(section.get("speaker_id") or "narrator"),
                "purpose": str(section.get("purpose") or ""),
                "voiceover": voiceover,
            }
        )
    return out


def select(entries: list[dict[str, Any]], target: int = TARGET) -> list[dict[str, Any]]:
    """Rubric-joined entries first; then a spread across profile and outcome."""
    def has_rubric(entry: dict[str, Any]) -> bool:
        return bool(entry["machine_verdict"].get("dimension_scores"))

    chosen = [e for e in entries if has_rubric(e)]
    chosen_ids = {e["entry_id"] for e in chosen}

    remaining = [e for e in entries if e["entry_id"] not in chosen_ids]
    # Round-robin the buckets so filling up cannot skew the set toward whichever
    # bucket happens to be largest.
    buckets: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for entry in remaining:
        key = (entry["profile_id"], bool(entry["machine_verdict"]["passed"]))
        buckets.setdefault(key, []).append(entry)
    order = sorted(buckets)
    index = 0
    while len(chosen) < target and any(buckets[k] for k in order):
        bucket = buckets[order[index % len(order)]]
        if bucket:
            chosen.append(bucket.pop(0))
        index += 1
    return chosen[:target]


def build() -> str:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    picked = select(corpus["entries"])

    items = []
    for entry in picked:
        sections = _sections_of(entry["source"])
        if not sections:
            continue
        items.append(
            {
                "id": entry["entry_id"],
                "title": entry["title"],
                "profile": entry["profile_id"],
                "videoType": entry["video_type"],
                "sectionCount": entry["section_count"],
                "totalChars": entry["total_chars"],
                "sections": sections,
                "machine": entry["machine_verdict"],
            }
        )

    data = {
        "dimensions": [
            {"key": key, "help": _DIMENSION_HELP[key]} for key in corpus["dimensions"]
        ],
        "items": items,
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    if _PLACEHOLDER not in template:
        raise SystemExit(f"Template thiếu placeholder {_PLACEHOLDER!r}.")
    return template.replace(
        _PLACEHOLDER, json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    html = build()
    count = html.count('"sections"')
    print(f"kich thuoc: {len(html) / 1024:.0f} KB · so kich ban: {count}")
    if args.write:
        OUT.write_text(html, encoding="utf-8")
        print(f"da ghi: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
