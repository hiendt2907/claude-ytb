"""Candidate bị QA loại phải được nhớ SANG LẦN CHẠY SAU.

Trong một lần chạy, `ideation_cmd` đã ghi mỗi candidate bị loại vào
`generated_summaries` dưới dạng "REJECTED — do not reuse | ..." nên lượt sinh
kế tiếp không lặp lại nó. Nhưng lần chạy MỚI dựng lại lịch sử từ `ledger.md`,
và bản bị loại — dù đã được lưu xuống `assets/script_revisions/failed_ideation/`
— không ai đọc lại. Thư mục đó chỉ được ghi vào.

Vì sao điều đó nghiêm trọng, đo được 2026-09-02 21:35: gateway xKiro CACHE
request giống hệt.

    lần 1: 14.20s  sha=bf49062e7cc86756
    lần 2:  0.43s  sha=bf49062e7cc86756
    lần 3:  0.27s  sha=bf49062e7cc86756

Nên prompt không đổi nghĩa là kịch bản không đổi, byte-for-byte. Ba lượt "thử
lại" sau một lần loại đã hỏng y hệt nhau trong 2-3 giây, cùng section được
sửa, cùng câu vi phạm. Một vòng lặp không đổi được đầu vào thì không phải vòng
lặp — nó là một lần chạy được phát lại.

Đọc lại kho đã loại vừa làm prompt khác đi thật, vừa đúng về nghĩa: thứ vừa bị
biên tập loại là đúng thứ không nên viết lại.
"""

from __future__ import annotations

import json


def _write_archive(directory, slug: str, title: str, topic: str, profile: str = "ban-so-6"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}_20260902_120000_000000.json"
    path.write_text(
        json.dumps(
            {"slug": slug, "title": title, "topic": topic, "profile_id": profile},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_rejected_candidates_come_back_as_do_not_reuse_entries(tmp_path):
    from ytb_pipeline.orchestrator.ideation_cmd import rejected_candidate_history

    archive = tmp_path / "failed_ideation"
    _write_archive(archive, "sang-som-o-ban-so-6", "Sáng Sớm Ở Bàn Số 6", "Chờ một xác nhận")

    history = rejected_candidate_history(archive, profile_id="ban-so-6")

    assert len(history) == 1
    entry = history[0]
    # Đúng dạng engine đã dùng trong-tiến-trình, để cả hai đường vào cùng một
    # danh sách và prompt không phải biết chúng đến từ đâu.
    assert entry.startswith("REJECTED — do not reuse |")
    assert "sang-som-o-ban-so-6" in entry
    assert "Sáng Sớm Ở Bàn Số 6" in entry
    assert "Chờ một xác nhận" in entry


def test_only_the_profile_being_generated_is_recalled(tmp_path):
    """Một profile khác bị loại không nói gì về profile này, và nhồi vào prompt
    chỉ làm loãng ngữ cảnh."""
    from ytb_pipeline.orchestrator.ideation_cmd import rejected_candidate_history

    archive = tmp_path / "failed_ideation"
    _write_archive(archive, "cua-ban-so-6", "Của Bàn Số 6", "A", profile="ban-so-6")
    _write_archive(archive, "cua-profile-khac", "Của Profile Khác", "B", profile="one-cup-cafe-6h")

    history = rejected_candidate_history(archive, profile_id="ban-so-6")

    assert len(history) == 1
    assert "cua-ban-so-6" in history[0]


def test_the_recall_is_bounded(tmp_path):
    """171 bản đã loại nằm trên đĩa lúc viết test này. Nhồi hết vào prompt sẽ
    đẩy chính brief ra rìa ngữ cảnh; lấy các bản mới nhất là đủ."""
    from ytb_pipeline.orchestrator.ideation_cmd import (
        MAX_RECALLED_REJECTIONS,
        rejected_candidate_history,
    )

    archive = tmp_path / "failed_ideation"
    archive.mkdir(parents=True, exist_ok=True)
    for index in range(MAX_RECALLED_REJECTIONS + 7):
        path = archive / f"slug-{index:03d}_2026090{index % 9}_120000_000000.json"
        path.write_text(
            json.dumps({"slug": f"slug-{index:03d}", "title": f"T{index}",
                        "topic": "x", "profile_id": "ban-so-6"}, ensure_ascii=False),
            encoding="utf-8",
        )

    history = rejected_candidate_history(archive, profile_id="ban-so-6")

    assert len(history) == MAX_RECALLED_REJECTIONS
    assert MAX_RECALLED_REJECTIONS <= 20


def test_a_missing_or_unreadable_archive_is_not_fatal(tmp_path):
    """Kho này là gợi ý, không phải nguồn sự thật. Thiếu hoặc hỏng thì lượt
    sinh vẫn phải chạy — chỉ là mất một lớp chống lặp."""
    from ytb_pipeline.orchestrator.ideation_cmd import rejected_candidate_history

    assert rejected_candidate_history(tmp_path / "khong-ton-tai", profile_id="ban-so-6") == []

    archive = tmp_path / "failed_ideation"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "hong_20260902_120000_000000.json").write_text("{ khong phai json", encoding="utf-8")
    (archive / "tot_20260902_120001_000000.json").write_text(
        json.dumps({"slug": "tot", "title": "T", "topic": "x", "profile_id": "ban-so-6"}),
        encoding="utf-8",
    )

    history = rejected_candidate_history(archive, profile_id="ban-so-6")
    assert len(history) == 1
    assert "tot" in history[0]
