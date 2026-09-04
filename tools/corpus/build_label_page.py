"""Emit the human-labelling page for the golden corpus.

The open question is not "how good is this script" — the owner already answered
that for the series as a whole. It is whether the 91% rejection rate on
ban-so-6 Longs (52 of 57) is the gate protecting quality or the gate blocking
it. So the page asks one thing per script: was this rejection right, or wrong?

That is one click per entry instead of five scores, and it produces exactly the
disagreement data Step 5 and Step 7 need. Rubric rejections sort first because
`editorial_review` causes 22 of the 52.

An earlier round asked for five-dimension scores across 20 scripts, of which
only 5 were the format under refactor and every rejection shown was a Short for
a Long-only series. That sample is the reason `stratify` now buckets on
video_type too.

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

TARGET = 12
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


def select(
    entries: list[dict[str, Any]],
    target: int = TARGET,
    *,
    profile_id: str = "",
    video_type: str = "",
    rejected_only: bool = False,
) -> list[dict[str, Any]]:
    """Pick what is worth a person's time.

    The first round asked about 20 scripts of which only 5 were the format
    actually being refactored, and every rejection shown was a Short for a
    Long-only series. Narrowing to one profile and one format costs the reader
    far less and answers the question that is actually open.
    """
    pool = [
        e for e in entries
        if (not profile_id or e["profile_id"] == profile_id)
        and (not video_type or e["video_type"] == video_type)
        and (not rejected_only or not e["machine_verdict"]["passed"])
    ]

    def sort_key(entry: dict[str, Any]) -> tuple[int, str]:
        # Rubric rejections first: that gate causes 22 of 52 Long rejections,
        # so a disagreement there is worth more than one anywhere else.
        rules = entry["machine_verdict"].get("violated_rules") or []
        return (0 if "editorial_review" in rules else 1, entry["entry_id"])

    return sorted(pool, key=sort_key)[:target]


def build() -> str:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    picked = select(
        corpus["entries"],
        profile_id="ban-so-6",
        video_type="long",
        rejected_only=True,
    )

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
