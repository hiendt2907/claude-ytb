"""Prompt templates cho `ytb batch start` — tách khỏi ideation_cmd.py.

Prompt là versioned artifact (xem CLAUDE.md mục Prompt Standards): mọi thay đổi
prompt ở đây diff được qua git, không rải string trong logic gọi provider.
"""

from __future__ import annotations

import json

from ..ideation.generator import CHARS_PER_MIN, SHORT_MAX_MINUTES, SHORT_MIN_MINUTES

SHORT_TARGET_CHARS = int(CHARS_PER_MIN * 1.0)
SHORT_MIN_CHARS = int(CHARS_PER_MIN * SHORT_MIN_MINUTES) + 60
SHORT_MAX_CHARS = int(CHARS_PER_MIN * SHORT_MAX_MINUTES) - 60


def build_resume_prompt(remaining: int, type_of_vid: str, type_of_rules: str, existing_slugs: list[str]) -> str:
    """Prompt resume — nói rõ đã có bao nhiêu, cần thêm bao nhiêu, KHÔNG viết lại cũ."""
    vid_label = "Video dài (ngang, 10-30 phút)" if type_of_vid == "long" else "Short (dọc, 1-2 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh (đọc memory dự án + ledger)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    slugs_str = "\n".join(f"  - {s}" for s in existing_slugs)
    return (
        f"RESUME IDEATION — tiếp tục batch bị dừng giữa chừng.\n\n"
        f"Các slug SAU ĐÂY đã có script + đã đăng ký trong auto_state.json, "
        f"TUYỆT ĐỐI KHÔNG viết lại hay đăng ký lại:\n{slugs_str}\n\n"
        f"Cần viết THÊM {remaining} video loại \"{vid_label}\" — dùng skill youtube-ideation, "
        f"tuân thủ ĐẦY ĐỦ .claude/skills/youtube-ideation/video-quality-rules.md "
        f"(cổng verify mục 0, luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` đọc "
        "auto_state.json để biết đã có bao nhiêu và chỉ viết phần còn thiếu.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish. Khi đủ "
        f"{remaining} video MỚI đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video mới)."
    )


def build_start_prompt(num_of_vid: int, type_of_vid: str, type_of_rules: str) -> str:
    """Dựng prompt giao việc SÁNG TẠO (ideation + viết kịch bản) cho LLM.

    Đây là phần KHÔNG mô phỏng được bằng code thường — cần LLM chọn chủ đề
    (chống trùng ledger), viết narration, tự chấm cổng compliance. Sau khi LLM
    viết xong scripts/*.json + đăng ký vào auto_state.json, `ytb batch run --loop`
    mới tiếp quản phần sản xuất máy-móc (không cần LLM nữa).
    """
    vid_label = "Video dài (ngang, 10-30 phút)" if type_of_vid == "long" else "Short (dọc, 1-2 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh hiện tại (đọc memory dự án + ledger để biết ngách)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    return (
        f"Làm phần SÁNG TẠO (ideation + viết kịch bản) cho {num_of_vid} video loại "
        f"\"{vid_label}\" — dùng skill youtube-ideation, tuân thủ ĐẦY ĐỦ "
        f".claude/skills/youtube-ideation/video-quality-rules.md (cổng verify mục 0, "
        f"luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` sẽ đọc "
        "auto_state.json để biết đã có bao nhiêu script và KHÔNG viết lại — "
        "chỉ hoạt động đúng nếu mỗi video được ghi ngay sau khi xong.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish — đó là việc của "
        "`ytb batch run --loop` chạy bằng tay sau, không cần LLM. Khi đủ "
        f"{num_of_vid} video đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video)."
    )


def ledger_topics(ledger_text: str) -> list[str]:
    """Cột 'Tiêu đề' từ text ledger.md — dùng làm blacklist chủ đề đã làm."""
    topics: list[str] = []
    for line in ledger_text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [part.strip() for part in line.strip("|").split("|")]
        if len(cols) >= 3 and cols[2] and cols[2].lower() != "tiêu đề":
            topics.append(cols[2])
    return topics


def local_script_prompt(
    index: int,
    total: int,
    type_of_vid: str,
    type_of_rules: str,
    ledger_text: str,
    generated_summaries: list[str] | None = None,
    analytics_feedback: list[str] | None = None,
) -> str:
    """Prompt sinh 1 script JSON qua local/structured LLM (khác luồng Claude skill)."""
    target = (
        '"video_type": "long", "target_minutes": 10-12 and 20-30 rich sections'
        if type_of_vid == "long"
        else '"video_type": "short", no target_minutes and enough narration for a 1-2 minute Short'
    )
    generated_summaries = generated_summaries or []
    analytics_feedback = analytics_feedback or []
    topic = (
        "Pick a non-duplicate topic from the channel niche."
        if type_of_rules == "auto"
        else (
            "User idea is the primary constraint. Build this script around the exact idea, "
            f"without drifting to another topic: {type_of_rules}"
        )
    )
    blocked_titles = "\n".join(f"- {title}" for title in ledger_topics(ledger_text)[-40:])
    generated = "\n".join(f"- {item}" for item in generated_summaries) or "- none yet"
    feedback = "\n".join(f"- {item}" for item in analytics_feedback) or "- no mature data yet"
    custom_rules = "" if type_of_rules == "auto" else (
        "\nCustom idea rules:\n"
        "- The user's idea overrides the default channel niche and old ledger topics.\n"
        "- Use the ledger ONLY as a blacklist of topics/titles to avoid, not as inspiration.\n"
        "- Current channel scope is sharing/knowledge, not entertainment. Do NOT write comedy, "
        "comedy, punchline structure, or gag narration for this channel.\n"
        "- Write a clear Vietnamese knowledge short: concrete everyday example, mechanism, "
        "application step, and grounded Pexels queries for real stock footage.\n"
    )
    return (
        "You are writing a Vietnamese YouTube script JSON for a local-first pipeline.\n"
        f"Video {index}/{total}. Type: {type_of_vid}. Requirement: {topic}\n"
        f"Length contract: {target}.\n"
        "This must be a NEW concept inside the current batch. Do not reuse any slug, title, "
        "topic, scene setup, or punchline already listed below.\n"
        f"{custom_rules}\n"
        "Already generated in this batch:\n"
        f"{generated}\n\n"
        "Analytics decisions from mature previous videos: \n"
        f"{feedback}\n"
        "Do not repeat formats labelled drop_format; for revise_hook/revise_value, change the named component.\n\n"
        "Blocked historical titles/topics:\n"
        f"{blocked_titles or '- none'}\n\n"
        "Return ONLY one JSON object with keys: slug, topic, title, description, tags, "
        "video_type, voice_profile, sections, compliance. video_type is only long or short. "
        "voice_profile is knowledge or inspiring. Each section needs time_goal, voiceover, "
        "visual_intent, pexels_query, caption, hook, transition, payoff, emphasis. "
        "Keep legacy narration equal to voiceover and broll equal to pexels_query for compatibility.\n"
        "compliance.passed must be true and include community/copyright/accuracy/"
        "advertiser/coppa/notes."
    )


def repair_prompt(payload: dict, qa_output: dict | None, validation_error: str | None) -> str:
    """Prompt yêu cầu LLM sửa script JSON không qua validation/QA."""
    issues = {
        "validation_error": validation_error,
        "qa": qa_output or {},
    }
    return (
        "Repair this Vietnamese YouTube script JSON for the local-first pipeline.\n"
        "Return ONLY the full corrected JSON object. Do not add markdown.\n"
        "Preserve the topic and core story unless a listed violation requires a narrow fix.\n"
        f"For Shorts without target_minutes, total narration MUST be {SHORT_MIN_CHARS}-{SHORT_MAX_CHARS} "
        "Vietnamese characters. Do not overshoot. Do not add greetings. If the script is too short, "
        "write the missing narration from scratch so every added sentence remains specific to the declared "
        "title and topic; never reuse generic examples, mechanisms, or application steps from another video.\n"
        "Current channel scope is sharing/knowledge, not entertainment. Remove comedy, "
        "punchline, and gag narration if present. Keep a concrete "
        "everyday example, mechanism, application step, and real-stock-footage Pexels queries.\n"
        "If QA reports concrete_example, the repaired narration MUST contain one sentence "
        "starting exactly with 'Ví dụ cụ thể:' and state all four parts: bối cảnh, "
        "hành động, hậu quả, and cách áp dụng. Do not hide the example only in visual fields.\n"
        "Required schema: slug, topic, title, description, tags, video_type, voice_profile, "
        "sections, compliance. video_type is only short or long. voice_profile is knowledge "
        "or inspiring. Each section needs time_goal, voiceover, visual_intent, pexels_query, "
        "caption, hook, transition, payoff, emphasis. Also include legacy narration=voiceover "
        "and broll=pexels_query. compliance.passed must be true.\n\n"
        f"Issues:\n{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
        f"Current JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
